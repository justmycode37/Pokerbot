#!/usr/bin/env python3
"""Convert saved, public Triton PokerHandV2 payloads to replayed Ivey decisions.

This tool only reads local JSON/JSONL captures. It never fetches source data,
fits or scores a policy, admits rows, or changes a frozen split. Every output
row remains pending independent source and conversion review.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pokerbot import ivey
from pokerbot.corpus import validate_rows
from scripts.acquisition_pot_eligibility import PrefixPotError, inspect_prefix_pot

HERO_UUID = "3970ce21-3d14-4bdc-97ca-98df8220d040"
GRAPHQL_URL = "https://prod-public-serverless.triton-poker.com/graphql"
SOURCE_PREFIX = "triton:"
FORCED_DEAD = {"ante", "small_ante", "big_ante"}
FORCED_LIVE = {"small_blind", "big_blind", "straddle"}
BETTING = {"raise", "call", "bet", "all_in", "check", "fold"}
KNOWN_ACTIONS = FORCED_DEAD | FORCED_LIVE | BETTING
STREETS = ("pre_flop", "flop", "turn", "river")


class RejectHand(ValueError):
    """A source hand is incomplete, unsupported, or inconsistent."""


def _is_int(value: Any) -> bool:
    return type(value) is int


def _chips(value: Any, label: str, *, positive: bool = False) -> int:
    if not _is_int(value) or value < (1 if positive else 0):
        raise RejectHand(f"invalid_{label}")
    return value


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hand_id(hand: dict[str, Any]) -> str:
    value = hand.get("handId")
    if not isinstance(value, str) or not value.strip():
        raise RejectHand("missing_hand_uuid")
    value = value.strip()
    try:
        uuid.UUID(value)
    except ValueError as exc:
        raise RejectHand("invalid_hand_uuid") from exc
    return value


def _find_hands(value: Any, inherited_session: str | None = None) -> Iterable[tuple[dict[str, Any], str | None]]:
    """Yield each PokerHandV2 object once, carrying a tournament-level group."""
    if isinstance(value, dict):
        session = inherited_session
        tournament = value.get("tournament")
        if isinstance(tournament, dict) and isinstance(tournament.get("uuid"), str):
            session = f"triton:tournament:{tournament['uuid']}"
        if "handId" in value and "rounds" in value and "players" in value:
            yield value, session
            return
        for child in value.values():
            yield from _find_hands(child, session)
    elif isinstance(value, list):
        for child in value:
            yield from _find_hands(child, inherited_session)


def _read_input(path: Path) -> tuple[list[tuple[dict[str, Any], str | None]], str]:
    """Read one saved JSON or JSONL file without a network fallback."""
    raw = path.read_bytes()
    if path.suffix.lower() == ".jsonl":
        hands: list[tuple[dict[str, Any], str | None]] = []
        try:
            for number, line in enumerate(raw.decode("utf-8-sig").splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    hands.extend(_find_hands(json.loads(line)))
                except (json.JSONDecodeError, UnicodeError) as exc:
                    raise ValueError(f"invalid_jsonl_line_{number}") from exc
        except UnicodeError as exc:
            raise ValueError("invalid_utf8") from exc
    else:
        try:
            hands = list(_find_hands(json.loads(raw.decode("utf-8-sig"))))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ValueError("invalid_json_document") from exc
    return hands, _sha256(raw)


def _source_provenance(path: Path, capture_sha256: str,
                       hand_id: str) -> dict[str, Any]:
    """Read an adjacent saved request sidecar, without inferring missing facts."""
    sidecar_paths = [candidate for candidate in (
        path.with_suffix(".request.json"),
        path.with_name(path.stem + "-request.json"),
    ) if candidate.is_file()]
    if len(sidecar_paths) > 1:
        contents = [candidate.read_bytes() for candidate in sidecar_paths]
        if any(content != contents[0] for content in contents[1:]):
            raise RejectHand("ambiguous_source_request_sidecars")
    metadata: dict[str, Any] = {
        "source_capture_path": str(path),
        "source_capture_sha256": capture_sha256,
        "source_request_path": None,
        "source_request_sha256": None,
        "source_request_operation_name": None,
        "source_request_variables": None,
        "source_request_query": None,
        "source_query_sha256": None,
        "source_request_episode_id": None,
    }
    if not sidecar_paths:
        return metadata

    request_path = sidecar_paths[0]
    request_bytes = request_path.read_bytes()
    try:
        request = json.loads(request_bytes.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RejectHand("invalid_source_request_sidecar") from exc
    if not isinstance(request, dict):
        raise RejectHand("invalid_source_request_sidecar")
    variables = request.get("variables")
    if (isinstance(variables, dict) and "handId" in variables
            and variables["handId"] is not None):
        if variables["handId"] != hand_id:
            raise RejectHand("source_request_hand_uuid_mismatch")
    query = request.get("query")
    query_sha256 = _sha256(query.encode("utf-8")) if isinstance(query, str) else None
    metadata.update({
        "source_request_path": str(request_path),
        "source_request_sha256": _sha256(request_bytes),
        "source_request_operation_name": request.get("operationName"),
        "source_request_variables": variables,
        "source_request_query": query,
        "source_query_sha256": query_sha256,
        "source_request_episode_id": (variables.get("episodeId")
                                       if isinstance(variables, dict) else None),
    })
    return metadata


def _card(value: Any) -> str:
    if not isinstance(value, str) or not value.startswith("CARD_"):
        raise RejectHand("unsupported_card_encoding")
    code = value[5:]
    if len(code) != 2:
        raise RejectHand("invalid_card_code")
    try:
        return ivey.normalize_card(code)
    except (TypeError, ValueError) as exc:
        raise RejectHand("invalid_card_code") from exc


def _required_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RejectHand(f"missing_or_invalid_{label}")
    return value


def _prepare(hand: dict[str, Any], session_hint: str | None) -> dict[str, Any]:
    """Validate source facts and prepare exact ordered participants/actions."""
    hand_id = _hand_id(hand)
    if hand.get("pokerVariant") != "texas":
        raise RejectHand("unsupported_or_non_texas_variant")
    if hand.get("noOfRuns") != 1:
        raise RejectHand("unsupported_or_missing_runout_count")

    capacity = _chips(hand.get("noOfSeats"), "physical_capacity", positive=True)
    blind_level = _required_object(hand.get("blindLevel"), "blind_level")
    small_level = _chips(blind_level.get("smallBlind"), "small_blind", positive=True)
    big_level = _chips(blind_level.get("bigBlind"), "big_blind", positive=True)
    # Archived hands may omit the optional denomination metadata. Replay uses
    # the explicit blinds and action increments, never minChip; retain unknown
    # metadata without inventing a denomination or rejecting an exact prefix.
    min_chip = blind_level.get("minChip")
    if min_chip is not None:
        min_chip = _chips(min_chip, "min_chip", positive=True)
    if big_level < small_level:
        raise RejectHand("invalid_blind_level")

    raw_players = hand.get("players")
    if not isinstance(raw_players, list) or not 2 <= len(raw_players) <= 9:
        raise RejectHand("unsupported_actual_player_count")
    if len(raw_players) > capacity:
        raise RejectHand("actual_players_exceed_physical_capacity")
    players_by_id: dict[str, dict[str, Any]] = {}
    seat_owner: dict[int, str] = {}
    for row in raw_players:
        if not isinstance(row, dict):
            raise RejectHand("invalid_player_record")
        user_id = row.get("userId")
        if not isinstance(user_id, str) or not user_id:
            raise RejectHand("missing_player_uuid")
        if user_id in players_by_id:
            raise RejectHand("duplicate_player_uuid")
        seat = _chips(row.get("seatNo"), "seat_number", positive=True)
        if seat > capacity or seat in seat_owner:
            raise RejectHand("invalid_or_duplicate_physical_seat")
        _chips(row.get("startChips"), "starting_stack")
        _chips(row.get("endChips"), "ending_stack")
        user = row.get("user")
        if not isinstance(user, dict):
            raise RejectHand("missing_player_user")
        nested_uuid = user.get("uuid")
        if nested_uuid is not None and nested_uuid != user_id:
            raise RejectHand("player_uuid_mismatch")
        players_by_id[user_id] = row
        seat_owner[seat] = user_id

    heroes = [key for key, row in players_by_id.items()
              if key == HERO_UUID or (row.get("user") or {}).get("uuid") == HERO_UUID]
    if len(heroes) != 1:
        raise RejectHand("ivey_uuid_not_uniquely_identified")
    hero_id = heroes[0]
    hero_cards_source = players_by_id[hero_id].get("pocketCards")
    hero_cards_known = (isinstance(hero_cards_source, list)
                        and len(hero_cards_source) == 2
                        and all(hero_cards_source))
    hero_betting_actions = sum(
        action.get("userId") == hero_id and action.get("type") in BETTING
        for round_row in hand.get("rounds", []) if isinstance(round_row, dict)
        for action in round_row.get("actions", []) if isinstance(action, dict))
    if len(raw_players) > 8 and hero_cards_known and hero_betting_actions:
        raise RejectHand("model_observation_player_count_exceeds_eight")

    raw_rounds = hand.get("rounds")
    if not isinstance(raw_rounds, list) or not raw_rounds or len(raw_rounds) > 4:
        raise RejectHand("missing_or_invalid_rounds")
    round_names: list[str] = []
    source_actions: list[tuple[str, dict[str, Any], int, int]] = []
    previous_timestamp: int | None = None
    for round_index, round_row in enumerate(raw_rounds):
        if not isinstance(round_row, dict):
            raise RejectHand("invalid_round_record")
        name = round_row.get("name")
        if not isinstance(name, str):
            raise RejectHand("missing_round_name")
        normalized = name.lower().replace("preflop", "pre_flop")
        if normalized not in STREETS or normalized in round_names:
            raise RejectHand("unsupported_or_duplicate_round")
        if normalized != STREETS[round_index]:
            raise RejectHand("nonsequential_rounds")
        round_names.append(normalized)
        if normalized == "flop":
            reveal_times = round_row.get("communityCardTimestamps")
            if (not isinstance(reveal_times, list) or len(reveal_times) != 3
                    or any(not _is_int(value) or value < 0 for value in reveal_times)):
                raise RejectHand("missing_or_invalid_flop_reveal_timestamps")
            # Entries follow card positions, not necessarily reveal order.
            # The whole flop becomes visible only after its last reveal;
            # keep the original card/timestamp pairing and action cutoff.
            board_ready_at = max(reveal_times)
        elif normalized in {"turn", "river"}:
            board_ready_at = round_row.get("communityCardTimestamp")
            if not _is_int(board_ready_at) or board_ready_at < 0:
                raise RejectHand("missing_or_invalid_board_reveal_timestamp")
        else:
            board_ready_at = None
        if board_ready_at is not None:
            if previous_timestamp is not None and board_ready_at < previous_timestamp:
                raise RejectHand("board_timestamp_conflicts_with_source_order")
            previous_timestamp = board_ready_at
        actions = round_row.get("actions")
        if not isinstance(actions, list):
            raise RejectHand("missing_or_invalid_action_list")
        if actions and board_ready_at is not None:
            first_action_time = actions[0].get("timestamp") if isinstance(actions[0], dict) else None
            if not _is_int(first_action_time) or first_action_time < board_ready_at:
                raise RejectHand("action_precedes_public_board_reveal")
        for action_index, action in enumerate(actions):
            if not isinstance(action, dict):
                raise RejectHand("invalid_action_record")
            kind = action.get("type")
            actor = action.get("userId")
            if kind not in KNOWN_ACTIONS:
                raise RejectHand("unknown_action_type")
            if actor not in players_by_id:
                raise RejectHand("unknown_action_actor")
            timestamp = action.get("timestamp")
            if not _is_int(timestamp) or timestamp < 0:
                raise RejectHand("missing_or_invalid_action_timestamp")
            if previous_timestamp is not None and timestamp < previous_timestamp:
                raise RejectHand("action_timestamp_order_conflicts_with_source_order")
            previous_timestamp = timestamp
            if kind in FORCED_DEAD | FORCED_LIVE | {"raise", "call", "bet", "all_in"}:
                amount = _chips(action.get("amount"), "action_amount")
                if amount <= 0:
                    raise RejectHand("nonpositive_chip_action")
            else:
                if "amount" in action:
                    raise RejectHand("unexpected_amount_on_check_or_fold")
                amount = 0
            source_actions.append((normalized, action, round_index, action_index))

    # Preserve source list order (including tied timestamps); never sort the
    # labels by timestamp because the UI's <= timestamp view includes the
    # current action itself.
    forced_rows: list[tuple[str, str, int]] = []
    betting_started = False
    for street, action, _, _ in source_actions:
        kind, actor = action["type"], action["userId"]
        if kind in FORCED_DEAD | FORCED_LIVE:
            if street != "pre_flop" or betting_started:
                raise RejectHand("forced_bet_outside_preflop_prefix")
            forced_rows.append((kind, actor, action["amount"]))
        else:
            betting_started = True
    live_forced = [(kind, actor, amount) for kind, actor, amount in forced_rows
                   if kind in FORCED_LIVE]
    smalls = [actor for kind, actor, _ in live_forced if kind == "small_blind"]
    bigs = [actor for kind, actor, _ in live_forced if kind == "big_blind"]
    if len(smalls) != 1 or len(bigs) != 1 or smalls[0] == bigs[0]:
        raise RejectHand("explicit_small_and_big_blind_actors_required")
    sb_id, bb_id = smalls[0], bigs[0]

    # Keep PokerKit's frozen seat convention. In heads-up its indices are
    # [BB, BTN], so the small blind/button must be dealt at index 1. For larger
    # tables index 0 remains the small blind and occupied seats proceed clockwise.
    sb_seat = players_by_id[sb_id]["seatNo"]
    if len(raw_players) == 2:
        ordered_rows = [players_by_id[bb_id], players_by_id[sb_id]]
    else:
        ordered_rows = sorted(raw_players,
                              key=lambda row: (row["seatNo"] - sb_seat) % capacity)
    ordered_ids = [row["userId"] for row in ordered_rows]
    if len(ordered_ids) > 2 and (ordered_ids[0] != sb_id or ordered_ids[1] != bb_id):
        raise RejectHand("blind_actors_conflict_with_physical_seat_order")
    dealer = _chips(hand.get("dealerSeatNo"), "dealer_seat", positive=True)
    if dealer > capacity:
        raise RejectHand("dealer_outside_physical_capacity")
    dealer_id = seat_owner.get(dealer)
    if dealer_id is not None and len(ordered_ids) > 2 and ordered_ids[-1] != dealer_id:
        raise RejectHand("dealer_order_conflicts_with_explicit_blinds")
    if len(ordered_ids) == 2 and dealer != sb_seat:
        raise RejectHand("heads_up_button_conflicts_with_explicit_blinds")

    player_index = {user_id: index for index, user_id in enumerate(ordered_ids)}
    starting = [_chips(players_by_id[user_id]["startChips"], "starting_stack")
                for user_id in ordered_ids]
    ending = [_chips(players_by_id[user_id]["endChips"], "ending_stack")
              for user_id in ordered_ids]
    antes = [0] * len(ordered_ids)
    blinds = [0] * len(ordered_ids)
    blind_action_order = []
    for kind, actor, amount in forced_rows:
        index = player_index[actor]
        if kind in FORCED_DEAD:
            antes[index] += amount
        else:
            if blinds[index] != 0:
                raise RejectHand("multiple_live_forced_bets_by_one_actor")
            blinds[index] = amount
            blind_action_order.append((kind, index))
    expected_live = [("small_blind", player_index[sb_id]),
                     ("big_blind", player_index[bb_id])]
    expected_live.extend(("straddle", index) for index in range(2, len(ordered_ids))
                         if any(kind == "straddle" and player_index[actor] == index
                                for kind, actor, _ in forced_rows))
    if blind_action_order != expected_live:
        raise RejectHand("unsupported_live_forced_bet_order")
    if (blinds[player_index[sb_id]] > small_level
            or blinds[player_index[bb_id]] > big_level):
        raise RejectHand("forced_blind_exceeds_declared_level")
    for index, amount in enumerate(antes):
        if amount + blinds[index] > starting[index]:
            raise RejectHand("forced_bets_exceed_starting_stack")
    # PokerKit's two-player raw ante/blind tuples are in posting order
    # (SB/button, BB), while its player indices are [BB, BTN]. Keep the source
    # actor amounts paired with that engine convention at state creation.
    if len(ordered_ids) == 2:
        engine_antes = [antes[player_index[sb_id]], antes[player_index[bb_id]]]
        engine_blinds = [blinds[player_index[sb_id]], blinds[player_index[bb_id]]]
    else:
        engine_antes = antes
        engine_blinds = blinds

    # Terminal accounting is a guard, not an observation feature. It catches
    # truncated or malformed histories while retaining one-player return pots.
    totals_by_actor: Counter[str] = Counter()
    for _, action, _, _ in source_actions:
        if action["type"] in FORCED_DEAD | FORCED_LIVE | {"raise", "call", "bet", "all_in"}:
            totals_by_actor[action["userId"]] += action["amount"]
    raw_pots = hand.get("pots")
    if not isinstance(raw_pots, list) or not raw_pots:
        raise RejectHand("missing_terminal_pots")
    pot_contributions: Counter[str] = Counter()
    payouts: Counter[str] = Counter()
    pot_total = 0
    for pot in raw_pots:
        if not isinstance(pot, dict):
            raise RejectHand("invalid_terminal_pot")
        total = _chips(pot.get("totalAmount"), "pot_total")
        players = pot.get("potPlayers")
        high = _required_object(pot.get("hi"), "high_pot")
        side_players = high.get("sidePlayers")
        if not isinstance(players, list) or not isinstance(side_players, list):
            raise RejectHand("missing_terminal_pot_players")
        contribution_this_pot: Counter[str] = Counter()
        for entry in players:
            if not isinstance(entry, dict) or entry.get("userId") not in players_by_id:
                raise RejectHand("unknown_terminal_pot_player")
            contribution = _chips(entry.get("amount"), "pot_contribution")
            contribution_this_pot[entry["userId"]] += contribution
            pot_contributions[entry["userId"]] += contribution
        if sum(contribution_this_pot.values()) != total:
            raise RejectHand("pot_contributions_do_not_sum_to_total")
        if _chips(high.get("totalAmount"), "high_pot_total") != total:
            raise RejectHand("unsupported_non_high_or_split_pot")
        side_this_pot: Counter[str] = Counter()
        for entry in side_players:
            if not isinstance(entry, dict) or entry.get("userId") not in players_by_id:
                raise RejectHand("unknown_terminal_pot_winner")
            user_id = entry["userId"]
            amount = _chips(entry.get("amount"), "side_pot_contribution")
            win_amount = _chips(entry.get("winAmount"), "pot_award")
            if type(entry.get("isWinner")) is not bool:
                raise RejectHand("missing_terminal_winner_flag")
            side_this_pot[user_id] += amount
            payouts[user_id] += win_amount
        if side_this_pot != contribution_this_pot:
            raise RejectHand("high_pot_attribution_mismatch")
        # Single-participant pots carry uncalled returns and count in payouts.
        if sum(_chips(entry.get("winAmount"), "pot_award") for entry in side_players) != total:
            raise RejectHand("terminal_pot_awards_do_not_sum_to_total")
        pot_total += total
    if pot_contributions != totals_by_actor:
        raise RejectHand("terminal_pot_contributions_mismatch_action_payments")
    if pot_total != sum(totals_by_actor.values()):
        raise RejectHand("terminal_pot_total_mismatch_action_payments")
    for user_id, row in players_by_id.items():
        derived = row["startChips"] - totals_by_actor[user_id] + payouts[user_id]
        if derived != row["endChips"]:
            raise RejectHand("terminal_stack_does_not_reconcile")
    if sum(starting) != sum(ending):
        raise RejectHand("total_chips_change_across_hand")

    # Verify every incremental action against an explicit chip ledger before
    # asking PokerKit to validate ordering and legality.
    stacks = {user_id: players_by_id[user_id]["startChips"] for user_id in ordered_ids}
    street_bets = {user_id: 0 for user_id in ordered_ids}
    max_bet = 0
    for kind, actor, amount in forced_rows:
        stacks[actor] -= amount
        if kind in FORCED_LIVE:
            street_bets[actor] += amount
            max_bet = max(max_bet, street_bets[actor])
    street = "pre_flop"
    for action_street, action, _, _ in source_actions:
        kind, actor = action["type"], action["userId"]
        if kind in FORCED_DEAD | FORCED_LIVE:
            continue
        if action_street != street:
            street = action_street
            street_bets = {user_id: 0 for user_id in ordered_ids}
            max_bet = 0
        amount = action.get("amount", 0)
        remaining = stacks[actor]
        due = max_bet - street_bets[actor]
        if kind == "check" and due != 0:
            raise RejectHand("check_faces_live_wager")
        if kind == "call" and amount != min(due, remaining):
            raise RejectHand("call_amount_differs_from_additional_price")
        if kind == "all_in" and amount != remaining:
            raise RejectHand("all_in_does_not_exhaust_remaining_stack")
        if kind == "bet" and max_bet != 0:
            raise RejectHand("bet_faces_existing_wager")
        if kind == "raise" and street_bets[actor] + amount <= max_bet:
            raise RejectHand("raise_does_not_increase_live_wager")
        if amount > remaining:
            raise RejectHand("action_exceeds_remaining_stack")
        if kind in {"raise", "bet", "all_in"}:
            target = street_bets[actor] + amount
            if target > max_bet:
                max_bet = target
        if amount:
            stacks[actor] -= amount
            street_bets[actor] += amount
    for user_id, row in players_by_id.items():
        if stacks[user_id] != row["endChips"] - payouts[user_id]:
            raise RejectHand("remaining_stack_before_payout_does_not_reconcile")

    # Explicit action actors, not capacity, establish the actual occupied
    # order. No imaginary seats are ever appended.
    hero_cards_raw = players_by_id[hero_id].get("pocketCards")
    hero_cards: list[str] | None = None
    if isinstance(hero_cards_raw, list) and len(hero_cards_raw) == 2 and all(hero_cards_raw):
        hero_cards = [_card(card) for card in hero_cards_raw]
        if len(set(hero_cards)) != 2:
            raise RejectHand("duplicate_hero_hole_card")
    elif hero_cards_raw not in (None, []):
        raise RejectHand("invalid_hero_hole_cards")

    rounds_for_phh = []
    seen_board: set[str] = set(hero_cards or [])
    for round_row, name in zip(raw_rounds, round_names):
        if name == "pre_flop":
            board: list[str] = []
        elif name == "flop":
            cards = round_row.get("communityCards")
            if not isinstance(cards, list) or len(cards) != 3:
                raise RejectHand("missing_or_invalid_flop_cards")
            board = [_card(card) for card in cards]
        elif name in {"turn", "river"}:
            card = round_row.get("communityCard")
            board = [_card(card)]
        else:
            raise RejectHand("unsupported_board_round")
        for card in board:
            if card in seen_board:
                raise RejectHand("duplicate_public_or_hero_card")
            seen_board.add(card)
        rounds_for_phh.append((name, board, round_row["actions"]))
    if len(round_names) > 1 and round_names[1:] != list(STREETS[1:len(round_names)]):
        raise RejectHand("nonsequential_board_rounds")

    session = session_hint
    if not session:
        session = f"triton:tournament:{hand.get('tournamentId')}" if isinstance(hand.get("tournamentId"), str) else None
    if not session:
        raise RejectHand("event_or_tournament_session_id_required")

    return {
        "hand_id": hand_id,
        "hero_id": hero_id,
        "hero_cards": hero_cards,
        "capacity": capacity,
        "min_chip": min_chip,
        "big_blind": big_level,
        "small_blind": small_level,
        "players_by_id": players_by_id,
        "ordered_ids": ordered_ids,
        "starting": starting,
        "antes": engine_antes,
        "blinds": engine_blinds,
        "rounds": rounds_for_phh,
        "session_id": session,
        "source_payload_sha256": _sha256(_canonical_json(hand)),
        "raw_action_count": len(source_actions),
        "ivey_action_count": sum(action["userId"] == hero_id and action["type"] in BETTING
                                  for _, action, _, _ in source_actions),
    }


def _source_decision_positions(hand: dict[str, Any], hero_id: str
                               ) -> list[tuple[int, int, int]]:
    """Return original (round, action) positions and their legacy flat ordinals."""
    result: list[tuple[int, int, int]] = []
    seen_positions: set[tuple[int, int]] = set()
    flat = 0
    for round_index, round_row in enumerate(hand["rounds"]):
        for action_index, action in enumerate(round_row["actions"]):
            if action["userId"] == hero_id and action["type"] in BETTING:
                position = (round_index, action_index)
                if position in seen_positions:
                    raise RejectHand("duplicate_source_decision_position")
                seen_positions.add(position)
                result.append((round_index, action_index, flat))
            flat += 1
    flat_ordinals = [position[2] for position in result]
    if flat_ordinals != sorted(set(flat_ordinals)):
        raise RejectHand("source_decision_positions_not_bijective")
    return result


def _strict_replay(hand: dict[str, Any], prepared: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Replay the ordered public prefix in PokerKit and capture Ivey states."""
    from pokerkit import Automation, Mode, NoLimitTexasHoldem
    from pokerbot.simulation import _observation, _positions

    ids = prepared["ordered_ids"]
    player_index = {user_id: index for index, user_id in enumerate(ids)}
    hero_index = player_index[prepared["hero_id"]]
    count = len(ids)
    automations = tuple(getattr(Automation, name) for name in (
        "ANTE_POSTING", "BET_COLLECTION", "BLIND_OR_STRADDLE_POSTING",
        "RUNOUT_COUNT_SELECTION", "HAND_KILLING", "CHIPS_PUSHING", "CHIPS_PULLING"))
    state = NoLimitTexasHoldem.create_state(
        automations, False, prepared["antes"], prepared["blinds"],
        prepared["big_blind"], prepared["starting"], count, mode=Mode.CASH_GAME)
    positions = _positions(count)
    history: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    hero_actions = 0
    action_count = 0
    mucked_unknown_showdowns = 0
    hand_key = f"{SOURCE_PREFIX}{prepared['hand_id']}"

    # Deal only Ivey's private cards. Every opponent remains unknown, even if
    # the completed source payload later reveals their cards.
    for index, user_id in enumerate(ids):
        cards = ("".join(prepared["hero_cards"] or []) if user_id == prepared["hero_id"]
                 else "????")
        state.deal_hole(cards or "????", index)

    for street_name, board, source_rows in prepared["rounds"]:
        if street_name != "pre_flop":
            # PokerKit asks the remaining showdown players to show or muck
            # before running out cards after an all-in. Muck instead of ever
            # introducing opponent private cards into this replay.
            while state.showdown_indices:
                state.show_or_muck_hole_cards(False, state.showdown_index)
                mucked_unknown_showdowns += 1
            if state.can_burn_card():
                state.burn_card("??")
            cards = "".join(board)
            if not cards or not state.can_deal_board(cards):
                raise RejectHand("engine_board_prefix_not_ready")
            state.deal_board(cards)

        for action in source_rows:
            kind, actor_id = action["type"], action["userId"]
            if kind in FORCED_DEAD | FORCED_LIVE:
                # create_state posted only the amounts and actors taken from
                # explicit forced-action records above.
                continue
            actor = player_index[actor_id]
            if state.actor_index != actor:
                raise RejectHand("engine_action_order_mismatch")
            before = state.bets[actor]
            due = state.checking_or_calling_amount or 0
            amount = action.get("amount", 0)
            current_max = max(state.bets)
            target = before + amount
            decision_action = kind
            if kind == "all_in" and target <= current_max:
                decision_action = "call"
            elif kind in {"raise", "bet", "all_in"}:
                decision_action = "raise"

            hero_actions += actor_id == prepared["hero_id"]
            if actor_id == prepared["hero_id"] and prepared["hero_cards"] is not None:
                observation = _observation(
                    state, hero_index, positions, 0, hero_actions - 1, history)
                observation["hand_id"] = hand_key
                observation["seed"] = 0
                expected: dict[str, Any] = {"action": decision_action}
                if decision_action == "raise":
                    expected["amount"] = target
                if not ivey._legal_prediction(expected, observation):
                    raise RejectHand("source_action_is_not_legal_in_engine_state")
                rows.append({
                    "state": observation,
                    "expected": expected,
                    "hand_id": hand_key,
                    "canonical_hand_id": hand_key,
                    "source": f"{GRAPHQL_URL}?sourceHandId={prepared['hand_id']}",
                    "session_id": prepared["session_id"],
                    "source_payload_sha256": prepared["source_payload_sha256"],
                    "source_validation": "engine_replayed",
                    "admission_status": "pending_independent_source_and_conversion_review",
                    "evidence_tier": "acquired_history_pending_independent_source_review",
                    "source_action_count": prepared["raw_action_count"],
                    "source_physical_capacity": prepared["capacity"],
                    "source_actual_player_count": count,
                })

            if kind == "fold":
                state.fold()
                history_action = "fold"
                logged_target = before
            elif kind == "check":
                if due != 0:
                    raise RejectHand("engine_check_faces_live_wager")
                state.check_or_call()
                history_action = "check"
                logged_target = before
            elif kind == "call" or (kind == "all_in" and target <= current_max):
                expected_added = min(due, state.stacks[actor])
                if amount != expected_added:
                    raise RejectHand("engine_call_amount_differs_from_source_increment")
                state.check_or_call()
                history_action = "call"
                logged_target = before + amount
            elif kind in {"raise", "bet", "all_in"}:
                if amount > state.stacks[actor]:
                    raise RejectHand("engine_action_exceeds_remaining_stack")
                state.complete_bet_or_raise_to(target)
                history_action = "raise"
                logged_target = target
            else:
                raise RejectHand("unknown_engine_action")

            if history_action != "fold":
                street_index = state.street_index
                # An action can close a street and advance PokerKit immediately;
                # retain the source street from the board/action loop instead.
                street_label = {"pre_flop": "preflop", "flop": "flop",
                                "turn": "turn", "river": "river"}[street_name]
                history.append({
                    "street": street_label,
                    "player": f"p{actor}",
                    "position": positions[actor],
                    "action": history_action,
                    "amount": logged_target,
                    "added": max(0, logged_target - before),
                })
            else:
                history.append({
                    "street": {"pre_flop": "preflop", "flop": "flop",
                               "turn": "turn", "river": "river"}[street_name],
                    "player": f"p{actor}", "position": positions[actor],
                    "action": "fold", "amount": before, "added": 0,
                })
            action_count += 1

    if state.actor_index is not None:
        raise RejectHand("source_action_prefix_ends_before_betting_round_closed")
    if hero_actions != prepared["ivey_action_count"]:
        raise RejectHand("engine_hero_action_count_mismatch")
    return rows, {
        "engine": "PokerKit NoLimitTexasHoldem",
        "source_actions_replayed": action_count,
        "hero_actions_replayed": hero_actions,
        "decisions_emitted": len(rows),
        "mucked_hidden_showdown_players": mucked_unknown_showdowns,
        "action_order_and_legal_transitions_verified": True,
    }


def _convert_one(hand: dict[str, Any], session_hint: str | None
                 ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    prepared = _prepare(hand, session_hint)
    decisions, replay = _strict_replay(hand, prepared)
    source_positions = _source_decision_positions(hand, prepared["hero_id"])
    if len(decisions) != len(source_positions) and prepared["hero_cards"] is not None:
        raise RejectHand("strict_replay_decision_count_mismatch")
    if prepared["hero_cards"] is None and decisions:
        raise RejectHand("unknown_hero_cards_exposed")
    # The engine records a state before the current action; labels and all
    # later actions/cards remain outside the state object. Source positions
    # follow original arrays, preserving source order when timestamps tie.
    for decision, (round_index, action_index, ordinal) in zip(decisions, source_positions):
        # Keep the engine's actor/legality checks, then reconcile its prefix
        # with a separate source ledger. Dead antes belong to the common pot,
        # rather than the live contribution tiers used to cap side pots.
        try:
            prefix = inspect_prefix_pot(hand, ordinal, hero_id=prepared["hero_id"])
        except PrefixPotError as exc:
            raise RejectHand(f"source_prefix_pot:{exc}") from exc
        observation = decision["state"]
        if prefix["pot"] != observation["pot"]:
            raise RejectHand("source_prefix_pot_differs_from_engine")
        if prefix["to_call"] != observation["to_call"]:
            raise RejectHand("source_prefix_call_differs_from_engine")
        if prefix["evidence"]["remaining_stacks"][prepared["hero_id"]] != observation["stack"]:
            raise RejectHand("source_prefix_stack_differs_from_engine")
        observation["contestable_pot"] = prefix["contestable_pot"]
        decision["source_prefix_pot_check"] = {
            key: prefix[key] for key in ("pot", "to_call", "contestable_pot", "dead_antes")
        }
        decision["source_decision_id"] = f"triton:{prepared['hand_id']}:action:{ordinal}"
        decision["source_action_index"] = ordinal
        decision["source_round_index"] = round_index
        decision["source_round_action_index"] = action_index
        decision["stable_source_decision_key"] = (
            f"triton:{prepared['hand_id']}:round:{round_index}:action:{action_index}")
    hand_report = {
        "hand_id": f"triton:{prepared['hand_id']}",
        "source_hand_uuid": prepared["hand_id"],
        "source_payload_sha256": prepared["source_payload_sha256"],
        "session_id": prepared["session_id"],
        "actual_players": len(prepared["ordered_ids"]),
        "physical_capacity": prepared["capacity"],
        "ivey_actions": prepared["ivey_action_count"],
        "hero_cards_known": prepared["hero_cards"] is not None,
        "decisions": len(decisions),
        "raw_action_count": prepared["raw_action_count"],
        "replay": replay,
    }
    if prepared["ivey_action_count"] and prepared["hero_cards"] is None:
        hand_report["exclusion"] = "hero_hole_cards_missing_at_decision"
    elif not prepared["ivey_action_count"]:
        hand_report["exclusion"] = "no_ivey_decision"
    return decisions, hand_report

def _input_paths(inputs: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    for input_path in inputs:
        if input_path.is_dir():
            result.extend(path for path in input_path.rglob("*")
                          if path.is_file() and path.suffix.lower() in {".json", ".jsonl"})
        elif input_path.is_file():
            result.append(input_path)
        else:
            raise FileNotFoundError(f"input path not found: {input_path}")
    return sorted(set(path.resolve() for path in result))


def convert(inputs: Iterable[Path], output_path: Path, *, session_id: str | None = None) -> dict[str, Any]:
    paths = _input_paths(inputs)
    if not paths:
        raise ValueError("no JSON or JSONL input files found")
    if output_path.exists():
        raise FileExistsError("output already exists; choose a new run path")
    source_reports: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    raw_hands: list[tuple[dict[str, Any], str | None, Path, str]] = []
    file_hashes: dict[Path, str] = {}
    seen: dict[str, str] = {}
    duplicate_count = 0
    conflict_ids: set[str] = set()
    for path in paths:
        report: dict[str, Any] = {"source_file": str(path), "status": "read"}
        try:
            hands, file_hash = _read_input(path)
            file_hashes[path] = file_hash
            report["source_file_sha256"] = file_hash
            report["hands_found"] = len(hands)
            if not hands:
                report["status"] = "no_hand_records"
            for hand, inherited in hands:
                effective_session = session_id or inherited
                hand_id = _hand_id(hand)
                digest = _sha256(_canonical_json(hand))
                prior = seen.get(hand_id)
                if prior is not None:
                    if prior != digest:
                        conflict_ids.add(hand_id)
                        rejections.append({"source_file": str(path), "source_hand_uuid": hand_id,
                                           "reason": "conflicting_duplicate_hand_uuid"})
                    else:
                        duplicate_count += 1
                    continue
                seen[hand_id] = digest
                raw_hands.append((hand, effective_session, path, digest))
            source_reports.append(report)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            report["status"] = "rejected_input_file"
            report["reason"] = str(exc)
            source_reports.append(report)
            rejections.append(copy.deepcopy(report))

    accepted: list[dict[str, Any]] = []
    hand_reports: list[dict[str, Any]] = []
    replayed_ids: set[str] = set()
    for hand, effective_session, path, digest in raw_hands:
        hand_id = hand.get("handId")
        if hand_id in conflict_ids:
            continue
        try:
            source_provenance = _source_provenance(path, file_hashes[path], hand_id)
        except (OSError, ValueError, TypeError, KeyError, IndexError, RuntimeError) as exc:
            rejections.append({"source_file": str(path), "source_hand_uuid": hand_id,
                               "reason": str(exc)})
            hand_reports.append({"hand_id": f"{SOURCE_PREFIX}{hand_id}",
                                 "source_hand_uuid": hand_id,
                                 "source_file": str(path), "decisions": 0,
                                 "rejection": str(exc)})
            continue
        raw_players = hand.get("players")
        has_ivey = isinstance(raw_players, list) and any(
            isinstance(row, dict) and (row.get("userId") == HERO_UUID
                or (isinstance(row.get("user"), dict)
                    and row["user"].get("uuid") == HERO_UUID))
            for row in raw_players)
        if not has_ivey:
            hand_reports.append({"hand_id": f"{SOURCE_PREFIX}{hand_id}",
                                 "source_hand_uuid": hand_id,
                                 "source_file": str(path),
                                 "source_capture_sha256": source_provenance["source_capture_sha256"],
                                 "source_request_path": source_provenance["source_request_path"],
                                 "source_request_sha256": source_provenance["source_request_sha256"],
                                 "ivey_actions": 0,
                                 "decisions": 0, "exclusion": "phil_ivey_not_in_hand"})
            continue
        try:
            rows, hand_report = _convert_one(hand, effective_session)
            for row in rows:
                row.update(source_provenance)
            accepted.extend(rows)
            replayed_ids.add(hand_id)
            hand_report["source_file"] = str(path)
            hand_report["source_capture_sha256"] = source_provenance["source_capture_sha256"]
            hand_report["source_request_path"] = source_provenance["source_request_path"]
            hand_report["source_request_sha256"] = source_provenance["source_request_sha256"]
            hand_reports.append(hand_report)
        except (OSError, ValueError, TypeError, KeyError, IndexError, RuntimeError) as exc:
            rejection = {"source_file": str(path), "source_hand_uuid": hand_id,
                         "reason": str(exc)}
            rejections.append(rejection)
            hand_reports.append({"hand_id": f"{SOURCE_PREFIX}{hand_id}",
                                 "source_hand_uuid": hand_id,
                                 "source_file": str(path), "decisions": 0,
                                 "rejection": str(exc)})

    # Conflicting source copies invalidate every candidate from that UUID.
    if conflict_ids:
        accepted = [row for row in accepted
                    if row.get("hand_id") not in {f"{SOURCE_PREFIX}{hand_id}" for hand_id in conflict_ids}]
    clean = validate_rows(accepted) if accepted else []
    decisions_per_hand = Counter(row["hand_id"] for row in clean)
    included_hands = len(decisions_per_hand)
    counts = {
        "source_files_seen": len(paths),
        "source_files_rejected": sum(r.get("status") == "rejected_input_file" for r in source_reports),
        "raw_hand_records_found": sum(r.get("hands_found", 0) for r in source_reports),
        "unique_hand_uuids": len(seen) - len(conflict_ids),
        "duplicate_hand_payloads_removed": duplicate_count,
        "conflicting_hand_uuids_excluded": len(conflict_ids),
        "hands_replayed": len(replayed_ids),
        "hands_with_ivey_decisions": included_hands,
        "hands_rejected": sum("rejection" in r for r in hand_reports),
        "ivey_decisions_seen": sum(r.get("ivey_actions", 0) for r in hand_reports),
        "hands_with_ivey_known_cards": sum(
            r.get("hero_cards_known") is True and r.get("ivey_actions", 0) > 0
            for r in hand_reports),
        "hands_with_ivey_unknown_cards": sum(
            r.get("hero_cards_known") is False and r.get("ivey_actions", 0) > 0
            for r in hand_reports),
        "known_card_ivey_decisions": sum(
            r.get("ivey_actions", 0) for r in hand_reports
            if r.get("hero_cards_known") is True),
        "unknown_card_ivey_decisions": sum(
            r.get("ivey_actions", 0) for r in hand_reports
            if r.get("hero_cards_known") is False),
        "validated_candidate_decisions": len(clean),
        "newly_admitted_decisions": 0,
    }
    result = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "validated_candidates_pending_independent_source_and_conversion_review",
        "counts": counts,
        "records": clean,
        "source_reports": source_reports,
        "hand_reports": hand_reports,
        "rejections": rejections,
        "limitations": [
            "Only saved official source JSON/JSONL files are read; no data is fetched.",
            "Replay validity does not establish source transcription accuracy or admission.",
            "No policy is fitted or scored, and no split is created or modified.",
            "One-player uncalled return pots remain part of terminal payout accounting.",
            "Triton noOfSeats is recorded as physical capacity; only listed player records are replayed.",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as output:
        json.dump(result, output, indent=2, sort_keys=True, allow_nan=False)
        output.write("\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path,
                        help="saved JSON/JSONL file(s) or directories containing them")
    parser.add_argument("--output", required=True, type=Path,
                        help="new candidate report path; existing outputs are never overwritten")
    parser.add_argument("--session-id", default=None,
                        help="event/festival grouping ID when the source wrapper has no tournament UUID")
    args = parser.parse_args()
    try:
        result = convert(args.inputs, args.output, session_id=args.session_id)
    except (OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result["counts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
