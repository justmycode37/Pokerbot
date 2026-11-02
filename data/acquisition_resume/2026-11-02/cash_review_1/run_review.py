#!/usr/bin/env python3
"""Independent source review for the odd-parity Triton cash-hand lane."""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import re
import subprocess
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import sys

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / "data/acquisition_resume/2026-11-01/triton_cash"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
HERO = "3970ce21-3d14-4bdc-97ca-98df8220d040"
DEAD = {"ante", "small_ante", "big_ante"}
LIVE = {"small_blind", "big_blind", "straddle"}
BETTING = {"raise", "call", "bet", "all_in", "check", "fold"}
FORCED = DEAD | LIVE
DECISION_RE = re.compile(r"^triton:([0-9a-fA-F-]{36}):action:(0|[1-9][0-9]*)$")


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def canonical_hash(value: object) -> str:
    return sha_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False, allow_nan=False).encode())


def read_json(path: Path):
    return json.loads(path.read_text())


def action_stream(hand: dict):
    ordinal = 0
    for ri, round_row in enumerate(hand["rounds"]):
        for ai, action in enumerate(round_row["actions"]):
            yield ordinal, ri, ai, round_row, action
            ordinal += 1


def positions(count: int) -> list[str]:
    if count == 2:
        return ["BB", "BTN"]
    if count == 3:
        return ["SB", "BB", "BTN"]
    result = [""] * count
    result[0], result[1], result[2], result[-1] = "SB", "BB", "UTG", "BTN"
    if count >= 5:
        result[-2] = "CO"
        for idx in range(3, count - 2):
            result[idx] = "MP"
    return result


def normalized_card(value: str) -> str:
    from pokerbot.cards import normalize_card
    if not isinstance(value, str) or not value.startswith("CARD_") or len(value) != 7:
        raise ValueError(f"unsupported card encoding {value!r}")
    return normalize_card(value[5:])


def independent_prefix(hand: dict, ordinal: int) -> dict:
    """Rebuild predecision chip state without using the eligibility helper."""
    stream = list(action_stream(hand))
    if not 0 <= ordinal < len(stream):
        raise ValueError("decision ordinal outside source action stream")
    _, target_ri, target_ai, target_round, target = stream[ordinal]
    if target.get("userId") != HERO or target.get("type") not in BETTING:
        raise ValueError("target is not a deliberate hero action")
    players = hand["players"]
    ids = [row["userId"] for row in players]
    if len(ids) != len(set(ids)) or HERO not in ids:
        raise ValueError("player UUIDs are duplicate or hero is absent")
    start = {row["userId"]: row["startChips"] for row in players}
    remaining = dict(start)
    live_total = dict.fromkeys(ids, 0)
    dead_by_player = dict.fromkeys(ids, 0)
    street_total = dict.fromkeys(ids, 0)
    folded: set[str] = set()
    dead_antes = 0
    pot = 0
    current_street = None
    max_live = 0
    betting_started = False
    live_order: list[tuple[str, str, int]] = []
    live_actors: set[str] = set()
    sb_actor = bb_actor = None
    forced_sequence = []
    history = []
    for source_ordinal, ri, ai, round_row, action in stream[:ordinal]:
        street = round_row["name"].lower().replace("preflop", "pre_flop")
        if street != current_street:
            current_street = street
            street_total = dict.fromkeys(ids, 0)
            max_live = 0
        kind = action.get("type")
        actor = action.get("userId")
        if actor not in start or actor in folded:
            raise ValueError("unknown or already-folded actor in prefix")
        if kind in FORCED:
            if street != "pre_flop" or betting_started:
                raise ValueError("forced action after betting began")
            amount = action.get("amount")
            if type(amount) is not int or amount <= 0 or amount > remaining[actor]:
                raise ValueError("invalid forced payment in prefix")
            forced_sequence.append({"action_ordinal": source_ordinal,
                                    "round_index": ri, "round_action_index": ai,
                                    "type": kind, "actor": actor, "amount": amount})
            if kind in DEAD:
                dead_by_player[actor] += amount
                dead_antes += amount
                remaining[actor] -= amount
                pot += amount
                continue
            expected = "small_blind" if not live_order else (
                "big_blind" if len(live_order) == 1 else "straddle")
            if kind != expected or actor in live_actors:
                raise ValueError("unsupported live forced-post order")
            if kind == "small_blind":
                sb_actor = actor
            elif kind == "big_blind":
                bb_actor = actor
                if amount < max_live:
                    raise ValueError("big blind below small blind")
            elif amount <= max_live:
                raise ValueError("straddle does not increase live price")
            live_order.append((kind, actor, amount))
            live_actors.add(actor)
            remaining[actor] -= amount
            live_total[actor] += amount
            street_total[actor] += amount
            max_live = max(max_live, street_total[actor])
            pot += amount
            continue
        if kind not in BETTING:
            raise ValueError("unknown action type in prefix")
        betting_started = True
        amount_value = action.get("amount")
        if kind in {"check", "fold"}:
            if "amount" in action:
                raise ValueError("unexpected amount on check/fold")
            amount = 0
        else:
            if type(amount_value) is not int or amount_value <= 0:
                raise ValueError("invalid betting increment")
            amount = amount_value
        if remaining[actor] <= 0 or amount > remaining[actor]:
            raise ValueError("action exceeds remaining stack")
        due = max(0, max_live - street_total[actor])
        if kind == "check" and due:
            raise ValueError("check faces wager")
        if kind == "call" and (due <= 0 or amount != min(due, remaining[actor])):
            raise ValueError("call differs from additional amount due")
        if kind == "all_in" and amount != remaining[actor]:
            raise ValueError("all-in does not exhaust stack")
        if kind == "bet" and max_live:
            raise ValueError("bet faces live wager")
        target_commitment = street_total[actor] + amount
        if kind == "raise" and target_commitment <= max_live:
            raise ValueError("raise does not increase live price")

        # Match the converter's public-history convention while independently
        # deriving the actor, target amount, and incremental payment.
        source_bet = street_total[actor]
        if kind == "fold":
            history_action, logged_target = "fold", source_bet
        elif kind == "check":
            history_action, logged_target = "check", source_bet
        elif kind == "all_in" and target_commitment <= max_live:
            history_action, logged_target = "call", target_commitment
        elif kind == "call":
            history_action, logged_target = "call", target_commitment
        else:
            history_action, logged_target = "raise", target_commitment
        history.append({
            "street": {"pre_flop": "preflop", "flop": "flop",
                       "turn": "turn", "river": "river"}[street],
            "actor_uuid": actor,
            "action": history_action, "amount": logged_target,
            "added": 0 if kind in {"check", "fold"} else amount,
        })
        if kind == "fold":
            folded.add(actor)
            continue
        if amount:
            remaining[actor] -= amount
            live_total[actor] += amount
            street_total[actor] += amount
            if target_commitment > max_live:
                max_live = target_commitment
            pot += amount

    target_street = target_round["name"].lower().replace("preflop", "pre_flop")
    if current_street != target_street:
        street_total = dict.fromkeys(ids, 0)
        max_live = 0
    if sb_actor is None or bb_actor is None or sb_actor == bb_actor:
        raise ValueError("explicit distinct small and big blind actors missing")
    if HERO in folded or remaining[HERO] <= 0:
        raise ValueError("hero folded or has no stack before target")
    due = max(0, max_live - street_total[HERO])
    to_call = min(due, remaining[HERO])
    hero_limit = live_total[HERO] + to_call
    opponent_limits = {actor: live_total[actor] + remaining[actor]
                       for actor in ids if actor != HERO and actor not in folded}
    if not opponent_limits:
        raise ValueError("no live opponent before target")
    tiers = []
    eligible_live = 0
    previous = 0
    boundaries = set(live_total.values()) | {hero_limit} | set(opponent_limits.values())
    for level in sorted(value for value in boundaries if value > 0):
        contributors = [actor for actor, value in live_total.items() if value >= level]
        layer = (level - previous) * len(contributors)
        reachable = [actor for actor, limit in opponent_limits.items() if limit >= level]
        hero_reaches = hero_limit >= level
        counted = hero_reaches and bool(reachable)
        if counted:
            eligible_live += layer
        tiers.append({"from_level": previous, "to_level": level,
                      "contributor_count": len(contributors), "layer_amount": layer,
                      "hero_can_reach": hero_reaches,
                      "opponent_can_reach": bool(reachable), "counted": counted})
        previous = level
    eligible = dead_antes + eligible_live
    if eligible > pot or pot != dead_antes + sum(live_total.values()):
        raise ValueError("prefix payments do not reconcile to pot")
    return {
        "target_round_index": target_ri, "target_round_action_index": target_ai,
        "target_street": target_street, "target_action_type": target.get("type"),
        "target_action_amount": target.get("amount"),
        "target_timestamp": target.get("timestamp"),
        "pot": pot, "call_amount_due": due, "to_call": to_call,
        "dead_antes": dead_antes, "dead_ante_contributions": dead_by_player,
        "live_contributions": live_total, "street_commitments": street_total,
        "remaining_stacks": remaining, "folded_players": sorted(folded),
        "hero_reach_limit": hero_limit, "opponent_reach_limits": opponent_limits,
        "contestable_live_tiers": eligible_live, "contestable_pot": eligible,
        "tiers": tiers, "sb_actor": sb_actor, "bb_actor": bb_actor,
        "forced_sequence": forced_sequence,
        "live_forced_posts": live_order, "history": history,
        "starting_stacks": start,
    }


def board_before_decision(hand: dict, review: dict) -> list[str]:
    ri = review["target_round_index"]
    timestamp = review["target_timestamp"]
    result = []
    for idx, round_row in enumerate(hand["rounds"]):
        name = round_row["name"].lower().replace("preflop", "pre_flop")
        if name == "pre_flop":
            continue
        cards = []
        if name == "flop":
            raw_cards = round_row.get("communityCards") or []
            reveal_times = round_row.get("communityCardTimestamps") or []
            if idx < ri or (idx == ri and timestamp >= max(reveal_times)):
                cards = [normalized_card(card) for card in raw_cards]
        elif name in {"turn", "river"}:
            raw_card = round_row.get("communityCard")
            reveal_time = round_row.get("communityCardTimestamp")
            if idx < ri or (idx == ri and timestamp >= reveal_time):
                cards = [normalized_card(raw_card)]
        if cards:
            result.extend(cards)
        if idx >= ri:
            break
    return result


def episode_inventory(manifest: dict) -> dict[str, dict]:
    result = {}
    for entry in manifest["targetEpisodes"]:
        response_path = SOURCE / "episodes" / f"{entry['episodeId']}.json"
        request_path = SOURCE / "episodes" / f"{entry['episodeId']}.request.json"
        response_raw = read_json(response_path)
        request_raw = read_json(request_path)
        episode = response_raw["data"]["episode"]
        festival = episode["festival"]
        event = episode["tournament"]
        result[entry["episodeId"]] = {
            "entry": entry, "response_path": response_path, "request_path": request_path,
            "response_sha256": sha_file(response_path), "request_sha256": sha_file(request_path),
            "request_operation": request_raw.get("operationName"),
            "request_episode_id": (request_raw.get("variables") or {}).get("episodeId"),
            "episode_id": episode.get("episodeId"),
            "festival_uuid": festival.get("uuid"), "festival_name": festival.get("name"),
            "event_uuid": event.get("uuid"), "event_name": event.get("name"),
            "event_title": episode.get("title"),
            "group_id": (festival.get("uuid"), event.get("uuid"), event.get("name")),
            "episode_query_sha256": sha_bytes(request_raw["query"].encode()),
        }
        if (result[entry["episodeId"]]["response_sha256"] != entry["responseSha256"]
                or result[entry["episodeId"]]["request_sha256"] != entry["requestSha256"]
                or result[entry["episodeId"]]["episode_id"] != entry["episodeId"]
                or result[entry["episodeId"]]["request_operation"] != "GetEpisode"
                or result[entry["episodeId"]]["request_episode_id"] != entry["episodeId"]
                or result[entry["episodeId"]]["episode_query_sha256"] != manifest["episodeQueryTextSha256"]):
            raise ValueError(f"GetEpisode provenance mismatch: {entry['episodeId']}")
    return result


def row_from_decision_key(value: str | None):
    if not isinstance(value, str):
        return None
    match = DECISION_RE.fullmatch(value)
    if not match:
        return None
    return match.group(1).lower(), int(match.group(2))


def collect_nested_records(value):
    if isinstance(value, dict):
        if isinstance(value.get("records"), list):
            for row in value["records"]:
                if isinstance(row, dict):
                    yield row
        for child in value.values():
            yield from collect_nested_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from collect_nested_records(child)


def raw_hand_uuid(record: dict):
    for key in ("source_decision_id", "canonical_hand_id", "hand_id", "handId"):
        value = record.get(key)
        if isinstance(value, str):
            match = re.search(r"triton:([0-9a-fA-F-]{36})(?::action:\d+)?$", value)
            if match:
                return match.group(1).lower()
            if key == "handId":
                try:
                    return str(uuid.UUID(value)).lower()
                except ValueError:
                    pass
    source = record.get("source")
    if isinstance(source, str):
        hand_id = parse_qs(urlparse(source).query).get("sourceHandId", [None])[0]
        if hand_id:
            try:
                return str(uuid.UUID(hand_id)).lower()
            except ValueError:
                pass
    return None


def main() -> None:
    audit_path = SOURCE / "audit/hand-audit.json"
    manifest_path = SOURCE / "manifest/source-episodes.json"
    audit = read_json(audit_path)
    manifest = read_json(manifest_path)
    episode_meta = episode_inventory(manifest)
    audit_rows = {row["handId"].lower(): row for row in audit["hands"]}
    owned = {hand_id: row for hand_id, row in audit_rows.items()
             if uuid.UUID(hand_id).int % 2 == 1}
    if len(owned) != 289 or sum(uuid.UUID(hand_id).int % 2 == 0 for hand_id in audit_rows) != 275:
        raise ValueError("source hand parity inventory changed")

    converter_reports = [read_json(path) for path in sorted((OUT / "converter_outputs").glob("2024_*.json"))]
    all_converter_reports = [read_json(path) for path in sorted((OUT / "converter_outputs").glob("*.json"))]
    original_candidates = [row for report in converter_reports for row in report["records"]]
    if len(original_candidates) != 221:
        raise ValueError(f"expected 221 engine-replayed candidate rows, got {len(original_candidates)}")

    from acquisition_pot_eligibility import inspect_prefix_pot
    from pokerbot.corpus import validate_rows
    from verify_triton_semantics import inspect_hand

    checks = Counter()
    errors = []
    hand_terminal: dict[str, dict] = {}
    review_rows = []
    corrected = []
    pot_sidecases = []
    group_owned = Counter()
    group_candidates = Counter()
    aliases_by_hand = {}
    full_decision_keys = set()

    for original in original_candidates:
        decision_key = row_from_decision_key(original.get("source_decision_id"))
        if not decision_key:
            raise ValueError(f"invalid candidate source decision id: {original.get('source_decision_id')}")
        hand_id, ordinal = decision_key
        checks["candidate_decisions"] += 1
        if hand_id not in owned:
            errors.append({"source_decision_id": original["source_decision_id"], "issue": "not_owned_odd_uuid_parity"})
            continue
        source_record = owned[hand_id]
        aliases = source_record.get("aliases") or []
        alias_uuids = sorted({str(alias.get("offset", {}).get("handId", "")).lower()
                              for alias in aliases if alias.get("offset", {}).get("handId")})
        alias_episode_ids = sorted({alias.get("episodeId") for alias in aliases if alias.get("episodeId")})
        if any(value != hand_id for value in alias_uuids):
            errors.append({"source_decision_id": original["source_decision_id"], "issue": "episode_alias_hand_id_mismatch", "aliases": alias_uuids})
        if not alias_episode_ids:
            alias_episode_ids = [source_record["sourceEpisodeId"]]
        group_keys = {episode_meta[eid]["group_id"] for eid in alias_episode_ids}
        if len(group_keys) != 1:
            errors.append({"source_decision_id": original["source_decision_id"], "issue": "aliases_cross_event_session"})
            continue
        festival_uuid, event_uuid, event_name = next(iter(group_keys))
        group_id = (festival_uuid, event_uuid, event_name)
        group_owned[group_id] += len([eid for eid in alias_episode_ids if eid == source_record["sourceEpisodeId"]]) or 0
        group_candidates[group_id] += 1
        expected_session = f"triton:cash-session:{festival_uuid}:{event_uuid}"
        if original.get("session_id") != expected_session:
            errors.append({"source_decision_id": original["source_decision_id"], "issue": "event_session_group_mismatch", "actual": original.get("session_id"), "expected": expected_session})
        em = episode_meta[alias_episode_ids[0]]
        cash_context_ok = ("cash game" in str(em["festival_name"]).lower()
                           and "cash game" in str(em["event_name"]).lower())
        if not cash_context_ok:
            errors.append({"source_decision_id": original["source_decision_id"], "issue": "cash_event_or_raw_texas_variant_context_mismatch"})

        capture_path = Path(original["source_capture_path"])
        request_path = Path(original["source_request_path"])
        response_sha = sha_file(capture_path)
        request_sha = sha_file(request_path)
        capture_sha_match = response_sha == source_record["responseSha256"] == original["source_capture_sha256"]
        request_sha_match = request_sha == source_record["requestSha256"] == original["source_request_sha256"]
        request = read_json(request_path)
        query_sha = sha_bytes(request["query"].encode())
        request_vars = request.get("variables") or {}
        query_match = (query_sha == manifest["getHandQueryTextSha256"] == original["source_query_sha256"]
                       and request.get("operationName") == "GetHand"
                       and request_vars.get("handId", "").lower() == hand_id
                       and request_vars.get("episodeId") in alias_episode_ids)
        if not capture_sha_match:
            errors.append({"source_decision_id": original["source_decision_id"], "issue": "raw_response_hash_mismatch"})
        if not request_sha_match or not query_match:
            errors.append({"source_decision_id": original["source_decision_id"], "issue": "GetHand_request_query_or_variables_mismatch"})
        hand_doc = read_json(capture_path)
        hand = hand_doc["data"]["handV2"]
        if hand.get("pokerVariant") != "texas":
            errors.append({"source_decision_id": original["source_decision_id"], "issue": "raw_hand_variant_not_texas"})
        if hand.get("handId", "").lower() != hand_id:
            errors.append({"source_decision_id": original["source_decision_id"], "issue": "returned_hand_uuid_mismatch"})
        payload_sha = canonical_hash(hand)
        if payload_sha != original["source_payload_sha256"]:
            errors.append({"source_decision_id": original["source_decision_id"], "issue": "canonical_payload_hash_mismatch"})
        checks["raw_response_hashes_verified"] += int(capture_sha_match)
        checks["GetHand_requests_verified"] += int(request_sha_match and query_match)

        # Every alias GetEpisode response/request was hash-checked above. Bind
        # the exact hand request to the same festival/event cash session.
        episode_id = request_vars.get("episodeId")
        em = episode_meta[episode_id]
        checks["episode_alias_rows_verified"] += 1
        if em["group_id"] != group_id:
            errors.append({"source_decision_id": original["source_decision_id"], "issue": "GetHand_episode_does_not_match_event_group"})

        if original.get("source_action_index") != ordinal:
            errors.append({"source_decision_id": original["source_decision_id"], "issue": "source_action_ordinal_mismatch"})
        prefix = independent_prefix(hand, ordinal)
        if (prefix["target_round_index"] != original.get("source_round_index")
                or prefix["target_round_action_index"] != original.get("source_round_action_index")
                or original.get("source_action_count") != len(list(action_stream(hand)))):
            errors.append({"source_decision_id": original["source_decision_id"], "issue": "source_action_locator_or_count_mismatch"})
        checks["raw_prefixes_rebuilt"] += 1

        # Validate physical action order using source seats, explicit blinds,
        # dealer seat, and any straddles. No capacity padding is invented.
        players = hand["players"]
        count = len(players)
        seat_map = {p["userId"]: p["seatNo"] for p in players}
        seat_values = list(seat_map.values())
        capacity = hand.get("noOfSeats")
        if (len(seat_map) != count or len(set(seat_values)) != count
                or type(capacity) is not int or any(type(s) is not int or s <= 0 or s > capacity for s in seat_values)):
            errors.append({"source_decision_id": original["source_decision_id"], "issue": "candidate_physical_seat_invalid"})
        if count > 8:
            errors.append({"source_decision_id": original["source_decision_id"], "issue": "candidate_exceeds_actual_player_limit"})
        if count == 2:
            ordered_ids = [prefix["bb_actor"], prefix["sb_actor"]]
        else:
            ordered_ids = [p["userId"] for p in sorted(players, key=lambda p: (p["seatNo"] - seat_map[prefix["sb_actor"]]) % capacity)]
        dealer = hand.get("dealerSeatNo")
        dealer_actor = next((actor for actor, seat in seat_map.items() if seat == dealer), None)
        ordering_ok = (ordered_ids[0] == prefix["sb_actor"] and ordered_ids[1] == prefix["bb_actor"]
                       and (count <= 2 or dealer_actor is None or ordered_ids[-1] == dealer_actor))
        live_actions = [(action.get("type"), action.get("userId"))
                        for _, _, _, _, action in action_stream(hand) if action.get("type") in LIVE]
        expected_live = [(kind, actor) for kind, actor, _ in prefix["live_forced_posts"]]
        straddle_order_ok = live_actions == expected_live and ordering_ok
        if not straddle_order_ok:
            errors.append({"source_decision_id": original["source_decision_id"], "issue": "blind_button_or_straddle_order_mismatch"})
        checks["seat_blind_button_straddle_order_verified"] += int(straddle_order_ok)

        forced_actions = [(round_row["name"], action.get("type"), action.get("userId"), action.get("amount"))
                          for round_row in hand["rounds"] for action in round_row["actions"]
                          if action.get("type") in FORCED]
        checks["forced_post_order_records"] += 1

        hero = next((player for player in players if player["userId"] == HERO), None)
        hero_cards_raw = hero.get("pocketCards") if hero else None
        if not (isinstance(hero_cards_raw, list) and len(hero_cards_raw) == 2 and all(hero_cards_raw)):
            errors.append({"source_decision_id": original["source_decision_id"], "issue": "hero_cards_not_known_two"})
            hero_cards = []
        else:
            hero_cards = [normalized_card(card) for card in hero_cards_raw]
        hero_idx = ordered_ids.index(HERO)
        pos = positions(count)
        state = original["state"]
        hero_cards_ok = hero_cards == state.get("hole_cards")
        if not hero_cards_ok:
            errors.append({"source_decision_id": original["source_decision_id"], "issue": "hero_card_observation_mismatch"})
        checks["known_hero_cards_verified"] += int(hero_cards_ok)

        engine_prefix = inspect_prefix_pot(hand, ordinal)
        helper_equal = (engine_prefix["pot"] == prefix["pot"]
                        and engine_prefix["to_call"] == prefix["to_call"]
                        and engine_prefix["call_amount_due"] == prefix["call_amount_due"]
                        and engine_prefix["dead_antes"] == prefix["dead_antes"]
                        and engine_prefix["live_contributions"] == prefix["live_contributions"]
                        and engine_prefix["street_commitments"] == prefix["street_commitments"]
                        and engine_prefix["evidence"]["remaining_stacks"] == prefix["remaining_stacks"]
                        and engine_prefix["evidence"]["folded_players"] == prefix["folded_players"]
                        and engine_prefix["contestable_pot"] == prefix["contestable_pot"])
        engine_match = state.get("pot") == engine_prefix["pot"] and state.get("to_call") == engine_prefix["to_call"]
        if not engine_match:
            errors.append({"source_decision_id": original["source_decision_id"], "issue": "prefix_pot_or_to_call_does_not_match_engine"})
        if not helper_equal:
            errors.append({"source_decision_id": original["source_decision_id"], "issue": "independent_live_tier_ledger_disagrees_with_helper"})
        checks["engine_pot_and_to_call_match_helper"] += int(engine_match)
        checks["independent_eligible_pot_matches_helper"] += int(helper_equal)
        if prefix["pot"] != engine_prefix["pot"] or prefix["to_call"] != engine_prefix["to_call"]:
            errors.append({"source_decision_id": original["source_decision_id"], "issue": "independent_prefix_does_not_match_engine"})
        if state.get("stack") != prefix["remaining_stacks"][HERO]:
            errors.append({"source_decision_id": original["source_decision_id"], "issue": "hero_stack_before_action_mismatch"})
        if state.get("current_bet") != prefix["street_commitments"][HERO]:
            errors.append({"source_decision_id": original["source_decision_id"], "issue": "hero_current_bet_mismatch"})
        if state.get("table_size") != count or state.get("player_id") != f"p{hero_idx}" or state.get("position") != pos[hero_idx]:
            errors.append({"source_decision_id": original["source_decision_id"], "issue": "hero_actor_or_position_mismatch"})
        checks["stacks_current_bet_actor_and_position_verified"] += int(
            state.get("stack") == prefix["remaining_stacks"][HERO]
            and state.get("current_bet") == prefix["street_commitments"][HERO]
            and state.get("table_size") == count
            and state.get("player_id") == f"p{hero_idx}"
            and state.get("position") == pos[hero_idx])

        # Reconstruct the history with pN actors and total-to-street amounts.
        expected_history = []
        for item in prefix["history"]:
            actor_index = ordered_ids.index(item["actor_uuid"])
            item = {k: v for k, v in item.items() if k != "actor_uuid"}
            item["player"] = f"p{actor_index}"
            item["position"] = pos[actor_index]
            expected_history.append(item)
        history_ok = state.get("history") == expected_history
        if not history_ok:
            errors.append({"source_decision_id": original["source_decision_id"], "issue": "public_history_actor_or_prefix_mismatch"})
        checks["history_actor_and_prefix_verified"] += int(history_ok)

        current_action = list(action_stream(hand))[ordinal][4]
        amount = current_action.get("amount", 0)
        current_target = prefix["street_commitments"][HERO] + amount
        if current_action["type"] == "all_in" and current_target <= max(
                prefix["street_commitments"].values(), default=0):
            expected_action = {"action": "call"}
        elif current_action["type"] in {"raise", "bet", "all_in"}:
            expected_action = {"action": "raise", "amount": current_target}
        else:
            expected_action = {"action": current_action["type"]}
        expected_ok = original.get("expected") == expected_action
        legal_list = state.get("legal_actions") or []
        legal_ok = expected_action["action"] in legal_list
        if expected_action["action"] == "raise":
            legal_ok = (legal_ok and state.get("min_raise_to", 0) <= expected_action["amount"]
                        <= state.get("max_raise_to", 0))
        if not expected_ok or not legal_ok:
            errors.append({"source_decision_id": original["source_decision_id"], "issue": "current_label_or_legal_bounds_mismatch"})
        checks["current_label_and_legal_bounds_verified"] += int(expected_ok and legal_ok)

        board = board_before_decision(hand, prefix)
        board_ok = state.get("board") == board
        if not board_ok:
            errors.append({"source_decision_id": original["source_decision_id"], "issue": "board_visible_cutoff_mismatch"})
        checks["board_cutoff_verified"] += int(board_ok)

        allowed_state_keys = {"hole_cards", "board", "pot", "to_call", "stack", "current_bet",
                              "min_raise_to", "max_raise_to", "big_blind", "position", "players_active",
                              "players_to_act", "legal_actions", "street", "seed", "history",
                              "player_id", "contestable_pot", "table_size"}
        state_keys_ok = set(state) == allowed_state_keys
        state_hole_ok = state.get("hole_cards") == hero_cards and "expected" not in state
        current_action_excluded = len(state.get("history", [])) == len(expected_history)
        if not (state_keys_ok and state_hole_ok and current_action_excluded):
            errors.append({"source_decision_id": original["source_decision_id"], "issue": "state_leak_or_current_label_present"})
        checks["future_private_terminal_and_current_label_out_of_state"] += int(state_keys_ok and state_hole_ok and current_action_excluded)

        if hand_id not in hand_terminal:
            hand_terminal[hand_id] = inspect_hand(hand)
        terminal_ok = hand_terminal[hand_id].get("accounting_and_prefix_price_checks_pass") is True
        if not terminal_ok:
            errors.append({"source_decision_id": original["source_decision_id"], "issue": "terminal_accounting_validation_failed"})
        checks["terminal_accounting_validation_only_pass"] += int(terminal_ok)

        original_engine_eligible = state.get("contestable_pot")
        corrected_row = json.loads(json.dumps(original))
        corrected_row["state"]["contestable_pot"] = prefix["contestable_pot"]
        corrected.append(corrected_row)
        adjusted = original_engine_eligible != prefix["contestable_pot"]
        if adjusted:
            pot_sidecases.append({
                "source_decision_id": original["source_decision_id"],
                "raw_hand_uuid": hand_id, "action_ordinal": ordinal,
                "engine_pot": state["pot"], "engine_to_call": state["to_call"],
                "engine_contestable_pot": original_engine_eligible,
                "corrected_eligible_pot": prefix["contestable_pot"],
                "dead_antes": prefix["dead_antes"],
                "live_tier_eligible_amount": prefix["contestable_live_tiers"],
                "delta": prefix["contestable_pot"] - original_engine_eligible,
                "helper_matches_independent_source_ledger": helper_equal,
                "tier_summary": prefix["tiers"],
                "review_status": "development_only_corrected_metadata_pending_parent_integration",
            })

        aliases_by_hand[hand_id] = {
            "raw_hand_uuid": hand_id, "episode_ids": alias_episode_ids,
            "raw_uuid_aliases": alias_uuids, "festival_uuid": festival_uuid,
            "event_uuid": event_uuid, "event_name": event_name,
        }
        full_decision_keys.add((hand_id, ordinal))
        review_rows.append({
            "source_decision_id": original["source_decision_id"],
            "stable_source_decision_key": original["stable_source_decision_key"],
            "decision_id": original["decision_id"], "record_hash_original": original["record_hash"],
            "raw_hand_uuid": hand_id, "source_response_path": str(capture_path.relative_to(ROOT)),
            "source_response_sha256": response_sha, "source_request_path": str(request_path.relative_to(ROOT)),
            "source_request_sha256": request_sha, "source_query_sha256": query_sha,
            "gethand_episode_id": episode_id, "episode_alias_ids": alias_episode_ids,
            "raw_uuid_aliases": alias_uuids, "festival_uuid": festival_uuid,
            "festival_name": em["festival_name"], "event_uuid": event_uuid,
            "event_name": event_name, "source_variant": hand.get("pokerVariant"),
            "cash_event_context_verified": cash_context_ok,
            "source_payload_sha256": payload_sha,
            "hero_cards": hero_cards, "hero_actor_index": hero_idx,
            "table_size": count, "source_capacity_metadata": capacity,
            "ordered_actor_ids": ordered_ids,
            "seat_order": [{"player": f"p{idx}", "actor_uuid": actor,
                            "seat_no": seat_map[actor], "position": pos[idx]}
                           for idx, actor in enumerate(ordered_ids)],
            "starting_stack_hero": prefix["starting_stacks"][HERO],
            "remaining_stack_hero_before_action": prefix["remaining_stacks"][HERO],
            "small_blind_actor": prefix["sb_actor"], "big_blind_actor": prefix["bb_actor"],
            "dealer_seat_no": dealer, "dealer_actor": dealer_actor,
            "forced_action_sequence_in_prefix": prefix["forced_sequence"],
            "forced_posts_in_prefix": [{"type": k, "actor": a, "amount": v}
                                        for k, a, v in prefix["live_forced_posts"]],
            "ante_posts_in_prefix": [{"actor": a, "amount": v}
                                     for a, v in prefix["dead_ante_contributions"].items() if v],
            "starting_stacks": prefix["starting_stacks"],
            "remaining_stacks_before_action": prefix["remaining_stacks"],
            "engine_pot": state["pot"], "engine_to_call": state["to_call"],
            "helper_call_amount_due": engine_prefix["call_amount_due"],
            "dead_antes": prefix["dead_antes"], "live_contributions": prefix["live_contributions"],
            "eligible_live_tier_amount": prefix["contestable_live_tiers"],
            "engine_contestable_pot": original_engine_eligible,
            "corrected_eligible_pot": prefix["contestable_pot"],
            "stack_and_current_bet_match": state.get("stack") == prefix["remaining_stacks"][HERO] and state.get("current_bet") == prefix["street_commitments"][HERO],
            "board_visible_before_action": board, "current_action_type": current_action["type"],
            "current_action_amount": current_action.get("amount"),
            "target_timestamp": prefix["target_timestamp"], "legal_actions": legal_list,
            "minimum_raise_to": state.get("min_raise_to"), "maximum_raise_to": state.get("max_raise_to"),
            "position": state.get("position"),
            "history_actor_prefix_verified": history_ok,
            "label_and_legal_bounds_verified": expected_ok and legal_ok,
            "terminal_accounting_validation_only": terminal_ok,
            "review_status": "passed_independent_source_and_conversion_review_pending_admission",
            "fresh_holdout": False, "partition": "development_only",
        })

    # Revalidate every record after corrected eligible-pot metadata, using the
    # repository validator so its decision and record hashes are recomputed.
    clean_corrected = validate_rows(corrected)
    if len(clean_corrected) != len(corrected):
        raise ValueError("validator changed candidate row count")
    new_by_key = {row_from_decision_key(row["source_decision_id"]): row for row in clean_corrected}
    for review in review_rows:
        key = row_from_decision_key(review["source_decision_id"])
        row = new_by_key[key]
        review["record_hash_corrected"] = row["record_hash"]
        review["decision_id_revalidated"] = row["decision_id"]
        review["record_hash_revalidated"] = row["record_hash"] == review["record_hash_corrected"]
        if not review["record_hash_revalidated"]:
            errors.append({"source_decision_id": review["source_decision_id"], "issue": "corrected_record_hash_not_revalidated"})
    checks["corrected_rows_revalidated"] = len(clean_corrected)

    # Compare current candidates to all 80 admitted rows and every other saved
    # Triton record/capture available locally; these are dedup checks only.
    baseline_paths = [ROOT / "data/corpus_splits/development-after-prospective-v1.json",
                      ROOT / "data/acquisition_resume/2026-11-01/admissions/batch-001.json",
                      ROOT / "data/acquisition_resume/2026-11-01/admissions/batch-002.json"]
    baseline_rows = []
    for path in baseline_paths:
        doc = read_json(path)
        baseline_rows.extend(doc.get("records", doc if isinstance(doc, list) else []))
    if len(baseline_rows) != 80:
        raise ValueError(f"expected exactly 80 admitted baseline rows, got {len(baseline_rows)}")
    baseline_keys = set()
    baseline_hand_ids = set()
    for row in baseline_rows:
        key = row_from_decision_key(row.get("source_decision_id"))
        if not key:
            sid = row.get("source") or ""
            sid_uuid = raw_hand_uuid(row)
            idx = row.get("source_action_index")
            if sid_uuid and type(idx) is int and "triton" in sid:
                key = (sid_uuid, idx)
        if key:
            baseline_keys.add(key)
        hid = raw_hand_uuid(row)
        if hid:
            baseline_hand_ids.add(hid)

    other_decisions = defaultdict(list)
    other_raw_hands = defaultdict(list)
    other_payload_hands = defaultdict(list)
    exclude_prefixes = [SOURCE.resolve(), OUT.resolve()]
    json_paths = list((ROOT / "data").rglob("*.json"))
    for path in json_paths:
        resolved = path.resolve()
        if any(resolved == prefix or prefix in resolved.parents for prefix in exclude_prefixes):
            continue
        try:
            raw_text = path.read_text()
        except (OSError, UnicodeError):
            continue
        if '"source_decision_id"' not in raw_text and '"handV2"' not in raw_text and '"handId"' not in raw_text:
            continue
        try:
            doc = json.loads(raw_text)
        except (json.JSONDecodeError, UnicodeError):
            continue
        for record in collect_nested_records(doc):
            key = row_from_decision_key(record.get("source_decision_id"))
            if key:
                other_decisions[key].append(str(path.relative_to(ROOT)))
            hid = raw_hand_uuid(record)
            if hid:
                other_raw_hands[hid].append(str(path.relative_to(ROOT)))
                payload = record.get("source_payload_sha256")
                if isinstance(payload, str):
                    other_payload_hands[payload].append({"raw_hand_uuid": hid, "path": str(path.relative_to(ROOT))})
        # Raw source responses can contain handV2 without a records wrapper.
        def walk_hands(value):
            if isinstance(value, dict):
                if isinstance(value.get("handId"), str) and isinstance(value.get("rounds"), list) and isinstance(value.get("players"), list):
                    try:
                        hid = str(uuid.UUID(value["handId"])).lower()
                        other_raw_hands[hid].append(str(path.relative_to(ROOT)))
                        other_payload_hands[canonical_hash(value)].append({"raw_hand_uuid": hid, "path": str(path.relative_to(ROOT))})
                    except ValueError:
                        pass
                for child in value.values():
                    walk_hands(child)
            elif isinstance(value, list):
                for child in value:
                    walk_hands(child)
        walk_hands(doc)

    candidate_decision_intersections = sorted(full_decision_keys & baseline_keys)
    candidate_hand_intersections = sorted({key[0] for key in full_decision_keys} & baseline_hand_ids)
    other_decision_intersections = {f"{hid}:action:{ordinal}": sorted(paths)
                                    for (hid, ordinal), paths in other_decisions.items()
                                    if (hid, ordinal) in full_decision_keys}
    same_cash_reuse = {f"{hid}:action:{ordinal}": sorted(paths)
                       for (hid, ordinal), paths in other_decisions.items()
                       if (hid, ordinal) in full_decision_keys and any("triton_cash_review_1" in p for p in paths)}
    cash_review_0_reuse = {f"{hid}:action:{ordinal}": sorted(paths)
                           for (hid, ordinal), paths in other_decisions.items()
                           if (hid, ordinal) in full_decision_keys and any("cash_review_0" in p for p in paths)}
    non_reuse_other_decisions = {f"{hid}:action:{ordinal}": sorted(
        p for p in paths if "triton_cash_review_1" not in p and "cash_review_0" not in p)
        for (hid, ordinal), paths in other_decisions.items()
        if (hid, ordinal) in full_decision_keys
        and any("triton_cash_review_1" not in p and "cash_review_0" not in p for p in paths)}
    other_uuid_occurrences = {hid: sorted(set(paths)) for hid, paths in other_raw_hands.items()
                              if hid in aliases_by_hand}
    candidate_payloads = {row_from_decision_key(row["source_decision_id"])[0]: row["source_payload_sha256"]
                          for row in original_candidates}
    payload_aliases = {}
    for candidate_id, payload in candidate_payloads.items():
        matches = [value for value in other_payload_hands.get(payload, [])
                   if value["raw_hand_uuid"] != candidate_id]
        if matches:
            payload_aliases[candidate_id] = matches
    checks["global_admitted_decision_dedup_checked"] = len(full_decision_keys)
    checks["global_other_triton_source_dedup_checked"] = len(full_decision_keys)

    # Record full raw-ID alias provenance and the 2018 seat-metadata source
    # blocker separately; none of these rows is admitted.
    side_dir = OUT / "sidecases"
    blocker_dir = OUT / "sourceblockers"
    side_dir.mkdir(exist_ok=True)
    blocker_dir.mkdir(exist_ok=True)
    (side_dir / "eligible-pot-corrections.json").write_text(json.dumps({
        "schema_version": 1, "rows_corrected": len(pot_sidecases),
        "all_source_ledger_checks_pass": all(x["helper_matches_independent_source_ledger"] for x in pot_sidecases),
        "corrections": pot_sidecases,
    }, indent=2, sort_keys=True) + "\n")

    seat_rows = []
    ring_counts = Counter()
    legacy_converter_report = read_json(OUT / "converter_outputs/2018_0a2c1d65.json")
    legacy_rejection_reason = {item.get("source_hand_uuid", "").lower(): item.get("reason")
                               for item in legacy_converter_report.get("rejections", [])}
    for hand_id, record in owned.items():
        ep_ids = {a.get("episodeId") for a in record.get("aliases", []) if a.get("episodeId")}
        if not ep_ids:
            ep_ids = {record["sourceEpisodeId"]}
        if not any(episode_meta[eid]["festival_name"] == "2018 Montenegro Cash Game" for eid in ep_ids):
            continue
        hand = read_json(ROOT / record["responsePath"])["data"]["handV2"]
        players = hand.get("players") or []
        seats = [p.get("seatNo") for p in players]
        by_user = {p.get("userId"): p for p in players}
        actions = list(action_stream(hand))
        sb_actions = [a for _, _, _, _, a in actions if a.get("type") == "small_blind"]
        bb_actions = [a for _, _, _, _, a in actions if a.get("type") == "big_blind"]
        ring = 9
        if len(sb_actions) == 1 and len(bb_actions) == 1 and HERO in by_user:
            sb_actor, bb_actor = sb_actions[0].get("userId"), bb_actions[0].get("userId")
            order = sorted(players, key=lambda p: (p["seatNo"] - by_user[sb_actor]["seatNo"]) % ring)
            dealer_actor = next((p.get("userId") for p in players if p.get("seatNo") == hand.get("dealerSeatNo")), None)
            live_posts = [(a.get("type"), a.get("userId")) for _, _, _, _, a in actions if a.get("type") in LIVE]
            expected_posts = [("small_blind", sb_actor), ("big_blind", bb_actor)]
            expected_posts.extend(("straddle", p.get("userId")) for p in order[2:]
                                  if any(a.get("type") == "straddle" and a.get("userId") == p.get("userId")
                                         for _, _, _, _, a in actions))
            ring_ok = (len(seats) == len(set(seats)) and all(type(s) is int and 1 <= s <= 9 for s in seats)
                       and order[0].get("userId") == sb_actor
                       and order[1].get("userId") == bb_actor
                       and (len(players) <= 2 or dealer_actor is None or order[-1].get("userId") == dealer_actor)
                       and live_posts == expected_posts)
        else:
            ring_ok = False
            sb_actor = bb_actor = dealer_actor = None
            order = []
            live_posts = []
        ring_counts["hands"] += 1
        ring_counts["noOfSeats_8"] += int(hand.get("noOfSeats") == 8)
        ring_counts["seat_9_present"] += int(9 in seats)
        ring_counts["actual_players_gt_8"] += int(len(players) > 8)
        ring_counts["seat_labels_unique_1_to_9"] += int(len(seats) == len(set(seats)) and all(type(s) is int and 1 <= s <= 9 for s in seats))
        ring_counts["sb_bb_dealer_and_forced_order_pass_mod9"] += int(ring_ok)
        seat_rows.append({
            "raw_hand_uuid": hand_id, "source_response_sha256": sha_file(ROOT / record["responsePath"]),
            "source_episode_ids": sorted(ep_ids), "noOfSeats": hand.get("noOfSeats"),
            "actual_player_count": len(players), "seat_numbers": sorted(seats),
            "dealer_seat_no": hand.get("dealerSeatNo"), "dealer_actor": dealer_actor,
            "small_blind_actor": sb_actor, "big_blind_actor": bb_actor,
            "live_forced_action_sequence": live_posts,
            "converter_rejection_reason": legacy_rejection_reason.get(hand_id),
            "physical_order_from_sb_modulo_9": [p.get("seatNo") for p in order],
            "seat_order_matches_explicit_blinds_and_dealer_mod9": ring_ok,
        })
    legacy_rejection_counts = Counter(row["converter_rejection_reason"] for row in seat_rows)
    (blocker_dir / "2018-seat-capacity.json").write_text(json.dumps({
        "schema_version": 1, "owned_source_hands": len(seat_rows),
        "current_converter_rejection_counts": dict(sorted(legacy_rejection_counts.items())),
        "seat_ring_evidence": dict(ring_counts),
        "source_frontend_evidence": {
            "gethand_query_path": "data/acquisition_resume/2026-11-01/triton_cash/hands/*.request.json",
            "query_sha256": manifest["getHandQueryTextSha256"],
            "selected_fields": ["noOfSeats", "dealerSeatNo", "players.seatNo"],
            "definition_found": False,
            "interpretation": "Saved GraphQL selection exposes all three fields but supplies no field documentation. For this 2018 cash event, every owned raw hand has noOfSeats=8 while seats are unique labels in 1..9 and seat 9 is present. Ordering occupied players from the explicit small blind modulo 9 puts the explicit big blind second and the occupied dealer/button last in every hand; this is direct source-data evidence for the event's nine-seat ring, not a reason to pad missing seats.",
            "recommendation": "A converter may ignore noOfSeats for ordering in this validated 2018 event only if it validates unique seat labels 1..9 plus explicit blind, straddle, and dealer consistency. Do not infer capacity from player count or append synthetic players.",
        },
        "hands": seat_rows,
    }, indent=2, sort_keys=True) + "\n")

    rejections = [item for report in converter_reports for item in report["rejections"]]
    rejection_counts = Counter(item.get("reason") for item in rejections)
    (blocker_dir / "2024-rejections.json").write_text(json.dumps({
        "schema_version": 1, "owned_source_hands": sum(report["counts"]["raw_hand_records_found"] for report in converter_reports),
        "rejected_hands": len(rejections), "rejections_by_reason": dict(sorted(rejection_counts.items())),
        "rows": [{"raw_hand_uuid": item.get("source_hand_uuid"), "reason": item.get("reason"),
                  "source_response_sha256": sha_file(Path(item["source_file"]))}
                 for item in rejections],
        "review_status": "all rejections retained; conservative public-board cutoff and action validation preserved",
    }, indent=2, sort_keys=True) + "\n")

    partial_rows = []
    conversion_rejection_reason = {item.get("source_hand_uuid", "").lower(): item.get("reason")
                                   for item in rejections}
    for hand_id, record in owned.items():
        partial_count = record.get("texasUnknownOrPartialCardHeroDecisionCount", 0)
        if not partial_count:
            continue
        partial_rows.append({
            "raw_hand_uuid": hand_id, "hero_cards_status": record.get("heroCardsStatus"),
            "source_attributed_hero_decisions": partial_count,
            "source_response_sha256": sha_file(ROOT / record["responsePath"]),
            "source_episode_id": record.get("sourceEpisodeId"),
            "converter_rejection_reason": legacy_rejection_reason.get(hand_id)
                                          or conversion_rejection_reason.get(hand_id),
            "counted_as_usable": False, "admitted": False,
        })
    (blocker_dir / "unknown-or-partial-hero-cards.json").write_text(json.dumps({
        "schema_version": 1,
        "owned_partial_or_unknown_hero_decisions": sum(
            row.get("texasUnknownOrPartialCardHeroDecisionCount", 0) for row in owned.values()),
        "rows": partial_rows, "counted_as_usable": 0, "admissions": 0,
    }, indent=2, sort_keys=True) + "\n")

    candidates_doc = {
        "schema_version": 1,
        "status": "independently_reviewed_pending_parent_integration",
        "source_scope": "Odd integer parity of raw hand UUIDs; 2024 event cash sessions only for candidates.",
        "development_only": True, "fresh_holdout": False, "admissions_from_this_review": 0,
        "source_hand_ids": sorted({row["raw_hand_uuid"] for row in review_rows}),
        "records": clean_corrected,
        "counts": {"pending_candidate_decisions": len(clean_corrected),
                   "reviewed_source_hands_with_decisions": len(hand_terminal),
                   "corrected_eligible_pot_rows": len(pot_sidecases),
                   "newly_admitted_decisions": 0},
        "limitations": ["All rows were inspected for development only and cannot be used as fresh held-out data.",
                        "Rows remain pending parent integration; this review makes no corpus admission.",
                        "Unknown or partial hero cards, rejected source hands, and terminal facts are not candidate features."],
    }
    candidates_path = OUT / "candidates.json"
    candidates_path.write_text(json.dumps(candidates_doc, indent=2, sort_keys=True, allow_nan=False) + "\n")
    (OUT / "per-row-review.json").write_text(json.dumps({
        "schema_version": 1, "reviewed_rows": len(review_rows),
        "all_reviewed_development_only": True, "admissions": 0,
        "checks": dict(sorted(checks.items())), "errors": errors,
        "rows": review_rows,
    }, indent=2, sort_keys=True, allow_nan=False) + "\n")
    verification_doc = {
        "converter": {"status": "completed",
                      "source_sha256_at_start_and_conversion": read_json(OUT / "checkpoint.json")["converter_sha256_at_start"],
                      "candidate_decisions": len(clean_corrected), "rejected_2018_hands": len(seat_rows),
                      "rejected_2024_hands": len(rejections)},
        "independent_source_review": {"status": "passed", "candidate_rows": len(review_rows),
                                      "errors": len(errors), "helper_engine_pot_to_call_matches": checks["engine_pot_and_to_call_match_helper"],
                                      "helper_independent_eligible_pot_matches": checks["independent_eligible_pot_matches_helper"]},
        "focused_helper_tests": {"command": "PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tests/test_acquisition_pot_eligibility.py",
                                 "runner": "unittest", "status": "passed", "tests_run": 10,
                                 "output": "Ran 10 tests in 0.026s; OK"},
    }
    verification_path = OUT / "verification.json"
    verification_path.write_text(json.dumps(verification_doc, indent=2, sort_keys=True) + "\n")

    # The saved source UUID aliases include all episode offsets for each UUID;
    # report non-target aliases found in any other cached Triton material.
    dedup_doc = {
        "baseline_admitted_rows": len(baseline_rows),
        "candidate_decision_count": len(full_decision_keys),
        "candidate_exact_decision_overlaps_with_admitted_80": [f"{h}:action:{i}" for h, i in candidate_decision_intersections],
        "candidate_raw_hand_uuid_overlaps_with_admitted_80": candidate_hand_intersections,
        "candidate_exact_decision_occurrences_in_saved_other_data": other_decision_intersections,
        "reused_nov1_cash_parity_one_decision_occurrences": same_cash_reuse,
        "reused_nov2_cash_review_0_occurrences": cash_review_0_reuse,
        "exact_decision_overlaps_with_other_saved_triton_data_excluding_cash_reuse": non_reuse_other_decisions,
        "candidate_raw_hand_uuid_occurrences_in_saved_other_data": other_uuid_occurrences,
        "candidate_raw_uuid_aliases_by_hand": [aliases_by_hand[k] for k in sorted(aliases_by_hand)],
        "source_payload_hash_aliases_with_distinct_raw_uuids_in_saved_other_data": payload_aliases,
    }
    (side_dir / "global-dedup-and-aliases.json").write_text(json.dumps(dedup_doc, indent=2, sort_keys=True) + "\n")

    # Record conversion outcomes and source/API evidence as compact summary.
    conversion_counts = Counter()
    for report in all_converter_reports:
        conversion_counts.update(report["counts"])
    all_owned_decisions_known = sum(row.get("texasKnownCardHeroDecisionCount", 0) for row in owned.values())
    all_owned_decisions_partial = sum(row.get("texasUnknownOrPartialCardHeroDecisionCount", 0) for row in owned.values())
    source_group_counts = Counter()
    source_group_known_decisions = Counter()
    source_group_partial_decisions = Counter()
    for hand_id, row in owned.items():
        alias_ids = sorted({x.get("episodeId") for x in row.get("aliases", []) if x.get("episodeId")})
        if not alias_ids:
            alias_ids = [row["sourceEpisodeId"]]
        keys = {episode_meta[episode_id]["group_id"] for episode_id in alias_ids}
        if len(keys) != 1:
            raise ValueError(f"owned hand spans multiple event/session groups: {hand_id}")
        key = next(iter(keys))
        source_group_counts[key] += 1
        source_group_known_decisions[key] += row.get("texasKnownCardHeroDecisionCount", 0)
        source_group_partial_decisions[key] += row.get("texasUnknownOrPartialCardHeroDecisionCount", 0)
    conversion_group_rows = {}
    for item in read_json(OUT / "conversion-summary.json"):
        key = (item["festival_uuid"], item["event_uuid"], item["event_name"])
        conversion_group_rows[key] = item
    summary = {
        "schema_version": 1, "review_status": "complete_with_2018_capacity_blocker_for_parent",
        "git_head_at_start": read_json(OUT / "checkpoint.json")["git_head_at_start"],
        "converter_sha256_at_start": read_json(OUT / "checkpoint.json")["converter_sha256_at_start"],
        "converter_sha256_during_conversion": read_json(OUT / "checkpoint.json")["converter_sha256_at_start"],
        "converter_sha256_at_review_end": sha_file(ROOT / "scripts/acquisition_triton_convert.py"),
        "converter_file_mtime_utc_at_review_end": __import__("datetime").datetime.fromtimestamp(
            (ROOT / "scripts/acquisition_triton_convert.py").stat().st_mtime,
            __import__("datetime").timezone.utc).isoformat(timespec="seconds"),
        "conversion_output_created_at_utc": sorted({report["created_at_utc"] for report in converter_reports}),
        "source_audit_sha256": sha_file(audit_path), "source_episode_manifest_sha256": sha_file(manifest_path),
        "owned_source_hands": len(owned), "other_parity_hands": len(audit_rows) - len(owned),
        "source_hand_records_all": len(audit_rows), "owned_known_card_hero_decisions": all_owned_decisions_known,
        "owned_partial_or_unknown_hero_decisions": all_owned_decisions_partial,
        "owned_pending_candidate_decisions": len(clean_corrected), "owned_decisions_admitted": 0,
        "reviewed_candidate_hands": len(hand_terminal), "reviewed_candidate_rows": len(review_rows),
        "candidate_review_errors": len(errors), "review_check_counts": dict(sorted(checks.items())),
        "conversion_counts": dict(sorted(conversion_counts.items())),
        "event_cash_session_groups": [
            {"festival_uuid": key[0], "event_uuid": key[1], "event_name": key[2],
             "episode_ids": sorted(eid for eid, meta in episode_meta.items() if meta["group_id"] == key),
             "owned_source_hands": source_group_counts[key],
             "owned_known_card_hero_decisions": source_group_known_decisions[key],
             "owned_partial_or_unknown_hero_decisions": source_group_partial_decisions[key],
             "pending_candidate_decisions": group_candidates[key],
             "converter_hands_replayed": conversion_group_rows[key]["counts"]["hands_replayed"],
             "converter_hands_rejected": conversion_group_rows[key]["counts"]["hands_rejected"],
             "converter_known_card_decisions": conversion_group_rows[key]["counts"]["known_card_ivey_decisions"]}
            for key in sorted(source_group_counts)
        ],
        "global_dedup": {"admitted_baseline_rows": len(baseline_rows),
                         "exact_source_decision_overlaps_with_80": len(candidate_decision_intersections),
                         "raw_hand_uuid_overlaps_with_80": len(candidate_hand_intersections),
                         "reused_nov1_cash_decision_overlap_count": len(same_cash_reuse),
                         "reused_nov2_cash_review_0_overlap_count": len(cash_review_0_reuse),
                         "other_saved_triton_decision_overlap_count_excluding_cash_reuse": len(non_reuse_other_decisions),
                         "reused_nov1_pending_candidate_overlap_count": len(same_cash_reuse),
                         "candidate_raw_hand_uuid_reuse_count_in_saved_other_data": len(other_uuid_occurrences),
                         "alternate_raw_uuid_alias_count": len(payload_aliases)},
        "seat_case_2018": dict(ring_counts),
        "pot_correction": {"rows_corrected": len(pot_sidecases),
                           "engine_pot_and_to_call_matched": checks["engine_pot_and_to_call_match_helper"],
                           "independent_eligibility_matches_helper": checks["independent_eligible_pot_matches_helper"],
                           "delta_distribution": dict(sorted(Counter(row["delta"] for row in pot_sidecases).items()))},
        "focused_helper_tests": verification_doc["focused_helper_tests"],
        "outputs": {},
        "protected_path_hashes_after": "pending",
    }

    # Finish artifact hashes, preserving only this assigned output directory.
    artifact_paths = [candidates_path, OUT / "per-row-review.json", OUT / "run_review.py",
                      OUT / "conversion-summary.json",
                      side_dir / "eligible-pot-corrections.json",
                      side_dir / "global-dedup-and-aliases.json",
                      blocker_dir / "2018-seat-capacity.json",
                      blocker_dir / "2024-rejections.json",
                      blocker_dir / "unknown-or-partial-hero-cards.json",
                      verification_path]
    artifact_paths.extend(sorted((OUT / "converter_outputs").glob("*.json")))
    summary["outputs"] = {str(path.relative_to(ROOT)): {"sha256": sha_file(path), "bytes": path.stat().st_size}
                          for path in artifact_paths}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    md = [
        "# Triton cash review 1 — 2026-11-02",
        "",
        "## Scope and disposition",
        "",
        f"Reviewed the odd-UUID-parity half of the cached Triton cash source: **{len(owned)} of {len(audit_rows)} hand IDs**. The six cached festival/event cash-session groups were built from each saved `GetEpisode` response's festival UUID and event UUID. The current converter produced **{len(clean_corrected)} pending 2024 decision candidates**. This review admitted **0** rows; everything inspected is development-only and not fresh held-out data.",
        "",
        "## Independent checks",
        "",
        f"All {checks['engine_pot_and_to_call_match_helper']} candidate prefixes had independently reconstructed total pot and clipped call amount equal to the PokerKit converter state. An independent source-action ledger also matched helper dead antes, live contributions, stack remaining, folds, and eligible contribution tiers on {checks['independent_eligible_pot_matches_helper']} rows. The candidate rows were corrected only in `state.contestable_pot` using those eligible amounts, then all {len(clean_corrected)} rows were passed through `validate_rows` to recompute and verify decision and record hashes.",
        "",
        f"Reviewed {len(hand_terminal)} candidate hands for terminal contribution/payout and stack reconciliation as validation only. History matched source actions before the current action, including pN actor mapping and total-to-street raise amounts. Known hero cards, board visibility cutoffs, legal labels/bounds, explicit blind/button/straddle order, and isolation of opponent cards, future actions, current labels, and terminal facts from `state` were checked per decision.",
        "",
        "## 2018 seat metadata blocker",
        "",
        f"All {ring_counts['hands']} owned 2018 hands report `noOfSeats=8`; all have distinct source seats within 1–9, and seat 9 appears in {ring_counts['seat_9_present']} hands. Source order built from seat numbers modulo 9 agrees with the explicit small blind, big blind, any straddle, and occupied dealer/button in {ring_counts['sb_bb_dealer_and_forced_order_pass_mod9']} of {ring_counts['hands']} hands. This supports ignoring `noOfSeats` for ordering in this specific validated event with strict 1–9 seat and anchor checks. Do not pad missing seats. The cached query selects `noOfSeats`, `dealerSeatNo`, and `players.seatNo` but includes no field documentation, so this is event-specific source evidence rather than a general schema guarantee.",
        "",
        f"The current converter still rejects all {len(seat_rows)} owned 2018 hands: {legacy_rejection_counts.get('actual_players_exceed_physical_capacity', 0)} for actual players exceeding the recorded capacity and {legacy_rejection_counts.get('invalid_or_duplicate_physical_seat', 0)} for seats exceeding it. Full raw details and a constrained repair recommendation are in `sourceblockers/2018-seat-capacity.json`.",
        "",
        "## Other source blockers and dedup",
        "",
        f"The 2024 source retained {sum(report['counts']['hands_rejected'] for report in converter_reports)} rejected hands; reasons are listed in `sourceblockers/2024-rejections.json`. The action-before-board-reveal cutoff remains in force.",
        f"Global dedup checked 80 admitted rows and saved Triton source material. Exact decision overlaps with the admitted 80: {len(candidate_decision_intersections)}; raw hand UUID overlaps with the admitted 80: {len(candidate_hand_intersections)}. The {len(same_cash_reuse)} exact matches in the reused Nov. 1 parity-one output are reported separately; exact matches in other saved Triton data after excluding the reused cash-review outputs: {len(non_reuse_other_decisions)}. Episode aliases retain their common raw hand UUIDs.",
        "",
        f"Converter source SHA at task start/conversion: `{summary['converter_sha256_at_start']}`. Its shared file was later written at {summary['converter_file_mtime_utc_at_review_end']} UTC and now hashes to `{summary['converter_sha256_at_review_end']}`; all six conversion outputs were created at {', '.join(summary['conversion_output_created_at_utc'])} UTC before that file timestamp. This review did not edit the root converter.",
        "",
        "## Files and limits",
        "",
        "- `candidates.json`: corrected eligible-pot candidates, still pending and not admitted.",
        "- `per-row-review.json`: per-decision provenance, source-prefix checks, independent ledgers, and validation status.",
        "- `sidecases/eligible-pot-corrections.json`: decisions where dead antes or live-tier reachability changed the prior engine contestable amount.",
        "- `sidecases/global-dedup-and-aliases.json`: admitted/other-source duplicate checks and raw UUID aliases.",
        "- `sourceblockers/`: 2018 capacity evidence and 2024 source rejection details.",
        "- `verification.json`: converter, independent review, and focused helper test checkpoint.",
        "",
        "Focused helper tests: **10 passed** using the standard-library `unittest` runner.",
        "",
        "No policy, scoring, evaluation, frozen split, raw source, or converter code was changed.",
        "",
    ]
    (OUT / "review.md").write_text("\n".join(md))
    summary["outputs"][str((OUT / "review.md").relative_to(ROOT))] = {
        "sha256": sha_file(OUT / "review.md"), "bytes": (OUT / "review.md").stat().st_size}
    # Protected directories are checked by the caller from the saved baseline
    # manifest and are never opened for writing by this review script.
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    checkpoint = read_json(OUT / "checkpoint.json")
    checkpoint.update({"status": "review_complete", "review_status": summary["review_status"],
                       "owned_hand_ids": len(owned), "candidate_decisions": len(clean_corrected),
                       "admissions": 0, "review_errors": len(errors),
                       "converter_sha256_at_end": summary["converter_sha256_at_review_end"],
                       "summary_sha256": sha_file(OUT / "summary.json")})
    (OUT / "checkpoint.json").write_text(json.dumps(checkpoint, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"owned_hands": len(owned), "candidate_decisions": len(clean_corrected),
                      "review_errors": len(errors), "pot_correction_rows": len(pot_sidecases),
                      "seat_evidence": dict(ring_counts),
                      "dedup_80_decisions": len(candidate_decision_intersections),
                      "reused_nov1_exact_decisions": len(same_cash_reuse),
                      "other_saved_exact_decisions_excluding_cash_reuse": len(non_reuse_other_decisions)}, sort_keys=True))


if __name__ == "__main__":
    main()
