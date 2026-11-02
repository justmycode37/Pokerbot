#!/usr/bin/env python3
"""Replay local Full Tilt forum captures into review-only Ivey decisions.

The source JSONL is never edited and no network access is used. Full Tilt
histories are parsed by the pinned PokerKit parser, then replayed by the same
strict PHH path used by the Ivey evaluator. Only source-shown Ivey hole cards
are moved to the pre-deal event; unknown opponent cards and future board cards
remain in their original later events.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import re
import shutil
import sys
import tempfile
import tomllib
import warnings
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pokerbot import ivey
from pokerbot.cards import normalize_card
from pokerbot.corpus import validate_rows

DEFAULT_INPUT = ROOT / "data/acquisition_sprint_1h/online_forum/records.jsonl"
DEFAULT_BASELINE = ROOT / "data/corpus_splits/development-after-prospective-v1.json"
DEFAULT_OUTPUT = ROOT / "data/acquisition_resume/2026-11-01/forum_conversion"
PARSER_WARNING = "The field 'time_zone_abbreviation' is an unexpected field and should probably be prefixed with an underscore character '_'."
HERO_NAME = "Phil Ivey"
CONVERTER_VERSION = 1


class RejectHand(ValueError):
    """A captured history is incomplete, unsupported, or inconsistent."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha_text(value: str) -> str:
    return _sha256(value.encode("utf-8"))


def _read_records(path: Path) -> tuple[list[dict[str, Any]], str, bytes]:
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    records = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid_jsonl_line_{line_number}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"jsonl_record_{line_number}_is_not_an_object")
        records.append(record)
    return records, _sha256(raw), raw


def _exact_fulltilt_id(record: dict[str, Any]) -> str | None:
    text = record.get("raw_source_text")
    if not isinstance(text, str):
        return None
    match = re.search(r"(?im)^Full Tilt Poker Game #(\d+)\s*:", text)
    return match.group(1) if match else None


def _source_url(record: dict[str, Any]) -> str:
    source = record.get("source")
    url = source.get("url") if isinstance(source, dict) else None
    if not isinstance(url, str) or not url.startswith(("https://", "http://")):
        raise RejectHand("public_source_url_missing")
    return url


def _has_source_card_conflict(record: dict[str, Any]) -> bool:
    classification = record.get("classification")
    if not isinstance(classification, dict):
        return False
    return ("conflict" in str(classification.get("card_consistency", "")).casefold()
            or classification.get("candidate_eligible") is False)


def _known_hero_cards(record: dict[str, Any]) -> list[str] | None:
    value = record.get("hero_hole_cards")
    if not isinstance(value, list) or len(value) != 2:
        return None
    try:
        cards = [normalize_card(card) for card in value]
    except (TypeError, ValueError):
        return None
    return cards if len(set(cards)) == 2 else None


def _parse_source_history(text: str):
    if re.search(r"\bCap\b|\bposts?\s+(?:the\s+)?ante\b", text, re.I):
        raise RejectHand("cap_or_ante_format_unsupported")
    from pokerkit import HandHistory

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        histories = list(HandHistory.from_full_tilt_poker(
            text.rstrip() + "\n\n\n",
            parse_value=lambda value: Decimal(value.replace(",", "")),
            error_status=True))
        if len(histories) == 1:
            # PokerKit 0.7.7 preserves this source timezone annotation as a
            # user-defined PHH field. It is not used in observations.
            histories[0].dumps()
    unexpected = [str(item.message) for item in caught if str(item.message) != PARSER_WARNING]
    if unexpected:
        raise RejectHand("unexpected_fulltilt_parser_warning")
    if not histories:
        raise RejectHand("no_complete_fulltilt_history_parsed")
    if len(histories) != 1:
        raise RejectHand("multiple_histories_in_one_source_record")
    return histories[0], len(caught)


def _phh_document(history) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        encoded = history.dumps()
    if any(str(item.message) != PARSER_WARNING for item in caught):
        raise RejectHand("unexpected_fulltilt_serializer_warning")
    try:
        document = tomllib.loads(encoded, parse_float=Decimal)
    except tomllib.TOMLDecodeError as exc:
        raise RejectHand("pokerkit_output_invalid_phh") from exc
    normalizations = [{
        "operation": "pokerkit_full_tilt_to_phh",
        "details": "Parsed the untouched source history with PokerKit 0.7.7; source text is retained verbatim.",
    }]
    if caught:
        normalizations.append({
            "operation": "retain_but_ignore_source_timezone_annotation",
            "field": "time_zone_abbreviation",
            "parser_warning": PARSER_WARNING,
            "details": "Original ET annotation remains in raw source evidence and is not part of the replay observation.",
        })
    return document, encoded, normalizations


def _inject_source_shown_hero_cards(document: dict[str, Any], cards: list[str] | None) -> list[dict[str, Any]]:
    if cards is None:
        return []
    players = document.get("players")
    actions = document.get("actions")
    if not isinstance(players, list) or not isinstance(actions, list):
        raise RejectHand("missing_players_or_actions")
    heroes = [index for index, name in enumerate(players) if isinstance(name, str)
              and name.strip().casefold() == HERO_NAME.casefold()]
    if len(heroes) != 1:
        raise RejectHand("hero_not_uniquely_identified_in_parsed_history")
    hero_index = heroes[0]
    hero_actor = hero_index + 1
    shown = []
    other_shown_cards: list[str] = []
    board_cards: list[str] = []
    for action in actions:
        if not isinstance(action, str):
            raise RejectHand("invalid_parsed_action")
        pieces = action.split()
        if len(pieces) == 3 and pieces[:2] == ["d", "db"]:
            code_string = pieces[2]
            if len(code_string) % 2:
                raise RejectHand("malformed_parsed_board_cards")
            try:
                board_cards.extend(normalize_card(code_string[offset:offset + 2])
                                   for offset in range(0, len(code_string), 2))
            except ValueError as exc:
                raise RejectHand("invalid_parsed_board_card") from exc
        if len(pieces) == 3 and pieces[1] == "sm":
            match = re.fullmatch(r"p([1-9]\d*)", pieces[0])
            if not match:
                raise RejectHand("invalid_showdown_actor")
            packed = pieces[2]
            if packed == "????":
                # Full Tilt represents a mucked unknown hand as ???? in PHH.
                # It remains unknown and is never substituted into a state.
                continue
            if len(packed) % 2:
                raise RejectHand("malformed_shown_hole_cards")
            try:
                exposed = [normalize_card(packed[offset:offset + 2])
                           for offset in range(0, len(packed), 2)]
            except ValueError as exc:
                raise RejectHand("invalid_shown_hole_card") from exc
            if int(match.group(1)) == hero_actor:
                shown.append(exposed)
            else:
                other_shown_cards.extend(exposed)
    if len(shown) != 1 or len(shown[0]) != 2:
        raise RejectHand("source_shown_hero_cards_not_uniquely_parsed")
    if set(shown[0]) != set(cards):
        raise RejectHand("structured_hero_cards_conflict_with_source_show")
    exposed_all = cards + other_shown_cards + board_cards
    if len(set(exposed_all)) != len(exposed_all):
        raise RejectHand("source_card_conflict_in_hero_opponent_or_board_cards")

    deal = f"d dh p{hero_actor} ????"
    locations = [index for index, action in enumerate(actions) if action == deal]
    if len(locations) != 1:
        raise RejectHand("hero_unknown_hole_card_deal_not_unique")
    original = actions[locations[0]]
    actions[locations[0]] = f"d dh p{hero_actor} {''.join(shown[0])}"
    return [{
        "operation": "normalize_source_shown_hero_cards_to_private_deal",
        "action_index": locations[0],
        "from": original,
        "to": actions[locations[0]],
        "source_basis": "the exact hero show cards in the raw Full Tilt text, cross-checked against hero_hole_cards",
        "details": "Opponent show cards and board cards stay at their original action positions.",
    }]


def _terminal_replay_and_pot(document: dict[str, Any], raw_text: str) -> dict[str, Any]:
    """Run the same strict PokerKit transitions and audit reported terminal money."""
    from pokerkit import Automation, Mode, NoLimitTexasHoldem, parse_action

    if document.get("variant") != "NT":
        raise RejectHand("not_no_limit_holdem")
    names, actions = document.get("players"), document.get("actions")
    if not isinstance(names, list) or not 2 <= len(names) <= 8:
        raise RejectHand("missing_or_unsupported_player_list")
    if not isinstance(actions, list) or any(not isinstance(action, str) for action in actions):
        raise RejectHand("missing_or_invalid_action_list")
    pot_match = re.search(
        r"(?im)^Total pot\s+\$?([\d,]+(?:\.\d+)?)\s*\|\s*Rake\s+\$?([\d,]+(?:\.\d+)?)\s*$",
        raw_text)
    if not pot_match:
        raise RejectHand("source_terminal_total_pot_or_rake_missing")
    try:
        source_pot = Decimal(pot_match.group(1).replace(",", ""))
        source_rake = Decimal(pot_match.group(2).replace(",", ""))
    except InvalidOperation as exc:
        raise RejectHand("invalid_source_terminal_pot_or_rake") from exc
    if not source_pot.is_finite() or not source_rake.is_finite() or min(source_pot, source_rake) < 0:
        raise RejectHand("invalid_source_terminal_pot_or_rake")

    summary = raw_text.split("*** SUMMARY ***", 1)
    award_values: list[Decimal] = []
    if len(summary) == 2:
        award_values = [Decimal(award.replace(",", "")) for award in re.findall(
            r"\b(?:collected|won)\s*\(\$([\d,]+(?:\.\d+)?)\)", summary[1], re.I)]
    if not award_values:
        # Some Full Tilt summaries list only losing seats; use the explicit
        # winner amount before SUMMARY when there is no machine-readable award.
        award_values = [Decimal(award.replace(",", "")) for award in re.findall(
            r"\bwin[s]?\s+the pot\s*\(\$([\d,]+(?:\.\d+)?)\)", summary[0], re.I)]
    unmatched_returns = [Decimal(amount.replace(",", "")) for amount in re.findall(
        r"(?im)^Uncalled bet(?: of)?\s+\$?([\d,]+(?:\.\d+)?)\s+returned\b", raw_text)]

    scaled, replay_scale = ivey._scale_chips(document)
    terminal_amounts = [source_pot, source_rake, *award_values, *unmatched_returns]
    terminal_precision = max(0, max(-amount.as_tuple().exponent for amount in terminal_amounts))
    if terminal_precision > 6:
        raise RejectHand("terminal_money_precision_exceeds_six_decimal_places")
    money_scale = max(replay_scale, 10 ** terminal_precision)
    scale_factor = money_scale // replay_scale
    if money_scale % replay_scale:
        raise RejectHand("terminal_money_not_exact_at_replay_chip_scale")
    if any(len(scaled[key]) != len(names) for key in
           ("starting_stacks", "antes", "blinds_or_straddles")):
        raise RejectHand("player_field_length_mismatch")
    automations = tuple(getattr(Automation, name) for name in (
        "ANTE_POSTING", "BET_COLLECTION", "BLIND_OR_STRADDLE_POSTING",
        "RUNOUT_COUNT_SELECTION", "HAND_KILLING", "CHIPS_PUSHING", "CHIPS_PULLING"))
    state = NoLimitTexasHoldem.create_state(
        automations, bool(scaled.get("ante_trimming_status", False)), scaled["antes"],
        scaled["blinds_or_straddles"], scaled["min_bet"], scaled["starting_stacks"],
        len(names), mode=Mode.CASH_GAME)
    terminal_action = None
    chips_before_terminal = None
    for encoded in scaled["actions"]:
        was_active = bool(state.status)
        stacks_before_action = list(state.stacks)
        if state.can_burn_card():
            state.burn_card("??")
        try:
            parse_action(state, encoded)
        except (ValueError, TypeError, IndexError) as exc:
            raise RejectHand("strict_replay_transition_failed") from exc
        if was_active and not state.status:
            terminal_action = encoded
            chips_before_terminal = stacks_before_action
    if state.status:
        raise RejectHand("strict_replay_did_not_reach_terminal_state")
    if chips_before_terminal is None or terminal_action is None:
        raise RejectHand("strict_replay_terminal_transition_missing")
    if sum(state.stacks) != sum(scaled["starting_stacks"]):
        raise RejectHand("strict_replay_terminal_chip_conservation_failed")

    # Before the terminal fold, PokerKit has not yet applied a source-noted
    # uncalled-return line. For non-fold terminal actions its preceding stack
    # totals already reflect PokerKit's exact uncalled excess handling.
    committed_before_terminal = sum(scaled["starting_stacks"]) - sum(chips_before_terminal)
    committed_ticks = committed_before_terminal * scale_factor
    if terminal_action.split()[1:2] == ["f"]:
        returned_ticks = sum(unmatched_returns) * money_scale
        if returned_ticks != int(returned_ticks):
            raise RejectHand("uncalled_return_not_exact_at_replay_chip_scale")
        committed_ticks -= int(returned_ticks)
    replayed_gross_pot_ticks = committed_ticks
    pot_ticks = source_pot * money_scale
    rake_ticks = source_rake * money_scale
    if pot_ticks != int(pot_ticks) or rake_ticks != int(rake_ticks):
        raise RejectHand("terminal_money_not_exact_at_replay_chip_scale")
    if replayed_gross_pot_ticks != int(pot_ticks):
        raise RejectHand("strict_replay_gross_pot_differs_from_source_total_pot")

    payout_status = "summary_awards_match_total_pot_plus_rake"
    if award_values:
        awards_ticks = sum(award_values) * money_scale
        if awards_ticks != int(awards_ticks) or awards_ticks + rake_ticks != pot_ticks:
            raise RejectHand("source_terminal_awards_plus_rake_do_not_sum_to_total_pot")
    else:
        payout_status = "source_award_not_machine_readable_total_pot_replay_checked"

    # Include pot/rake precision in the integer unit even when the source's
    # bets happen to use whole currency units.
    return {
        "chip_ticks_per_currency_unit": money_scale,
        "replay_chip_ticks_per_currency_unit": replay_scale,
        "replay_to_money_scale_factor": scale_factor,
        "source_total_pot_currency": str(source_pot),
        "source_rake_currency": str(source_rake),
        "replayed_gross_pot_ticks": replayed_gross_pot_ticks,
        "source_total_pot_ticks": int(pot_ticks),
        "source_awards_plus_rake_check": payout_status,
        "strict_terminal_chip_conservation": True,
    }


def _board_before(actions: list[str], before_index: int) -> list[str]:
    board: list[str] = []
    for action in actions[:before_index]:
        pieces = action.split()
        if len(pieces) == 3 and pieces[:2] == ["d", "db"]:
            packed = pieces[2]
            if len(packed) % 2:
                raise RejectHand("malformed_board_prefix")
            board.extend(normalize_card(packed[offset:offset + 2])
                         for offset in range(0, len(packed), 2))
    return board


def _candidate_rows(record: dict[str, Any], ft_id: str, source_hash: str,
                    document: dict[str, Any], replay_rows: list[dict[str, Any]],
                    terminal: dict[str, Any], baseline_observations: set[str]) -> tuple[list[dict[str, Any]], int]:
    players, actions = document["players"], document["actions"]
    hero_index = [index for index, name in enumerate(players)
                  if isinstance(name, str) and name.strip().casefold() == HERO_NAME.casefold()][0]
    hero_actor = hero_index + 1
    hero_action_indices = []
    for index, action in enumerate(actions):
        pieces = action.split()
        if len(pieces) >= 2 and pieces[1] in ("f", "cc", "cbr"):
            if pieces[0] == f"p{hero_actor}":
                hero_action_indices.append(index)
    cards = _known_hero_cards(record)
    if cards is None:
        if replay_rows:
            raise RejectHand("unknown_hero_cards_emitted_a_decision")
        return [], 0
    if len(hero_action_indices) != len(replay_rows):
        raise RejectHand("strict_replay_decision_count_does_not_match_action_prefixes")

    output: list[dict[str, Any]] = []
    baseline_drops = 0
    opponent_cards = []
    for encoded in actions:
        pieces = encoded.split()
        if len(pieces) != 3 or pieces[1] != "sm" or pieces[2] == "????":
            continue
        actor = re.fullmatch(r"p([1-9]\d*)", pieces[0])
        if actor and int(actor.group(1)) != hero_actor:
            packed = pieces[2]
            if len(packed) % 2:
                raise RejectHand("malformed_opponent_show_cards")
            opponent_cards.extend(normalize_card(packed[offset:offset + 2])
                                  for offset in range(0, len(packed), 2))
    for index, (source_action_index, replay) in enumerate(zip(hero_action_indices, replay_rows)):
        observation = copy.deepcopy(replay["state"])
        expected = copy.deepcopy(replay["expected"])
        multiplier = terminal["replay_to_money_scale_factor"]
        if multiplier != 1:
            for key in ("pot", "to_call", "stack", "current_bet", "min_raise_to",
                        "max_raise_to", "big_blind", "contestable_pot"):
                observation[key] *= multiplier
            for item in observation["history"]:
                item["amount"] *= multiplier
                item["added"] *= multiplier
            if expected.get("action") == "raise":
                expected["amount"] *= multiplier
        action = actions[source_action_index]
        pieces = action.split()
        if pieces[1] == "f":
            encoded_expected = {"action": "fold"}
        elif pieces[1] == "cc":
            encoded_expected = {"action": "call" if observation["to_call"] else "check"}
        else:
            if len(pieces) != 3:
                raise RejectHand("malformed_hero_raise_action")
            encoded_expected = {"action": "raise", "amount": int(Decimal(pieces[2]) * terminal["chip_ticks_per_currency_unit"])}
        if expected != encoded_expected:
            raise RejectHand("replayed_label_does_not_match_source_action")
        expected_board = _board_before(actions, source_action_index)
        if observation.get("board") != expected_board:
            raise RejectHand("preaction_observation_board_boundary_mismatch")
        if observation.get("hole_cards") != cards:
            raise RejectHand("preaction_observation_hero_cards_mismatch")
        prefix_betting_count = sum(
            len(previous.split()) >= 2 and previous.split()[1] in ("f", "cc", "cbr")
            for previous in actions[:source_action_index])
        if len(observation.get("history", [])) != prefix_betting_count:
            raise RejectHand("preaction_observation_action_prefix_boundary_mismatch")
        visible_cards = set(observation["hole_cards"]) | set(observation["board"])
        if visible_cards.intersection(opponent_cards):
            raise RejectHand("opponent_hole_card_leaked_into_preaction_observation")

        # Reconstruct the corpus identity with the established strict label
        # and legal-action validators, then keep the observation/label separate.
        canonical_hand = f"fulltilt:{ft_id}"
        corpus_row = {
            "hand_id": canonical_hand,
            "canonical_hand_id": canonical_hand,
            "state": observation,
            "expected": expected,
            "format": "cash_nlhe",
            "source": _source_url(record),
            "evidence_tier": "acquired_history_pending_independent_source_review",
        }
        try:
            validated = validate_rows([corpus_row])[0]
        except ValueError as exc:
            raise RejectHand("replayed_candidate_failed_corpus_validation") from exc
        baseline_signature = _observation_signature(validated["state"])
        if baseline_signature in baseline_observations:
            baseline_drops += 1
            continue

        prefix = actions[:source_action_index]
        prefix_hash = _sha256(_canonical_json(prefix))
        source = record["source"]
        identity = {
            "namespace": "fulltilt",
            "hand_id": ft_id,
            "actor": f"p{hero_actor}",
            "action_index": source_action_index,
            "prefix_action_count": len(prefix),
            "prefix_actions_sha256": prefix_hash,
            "identity": f"fulltilt:{ft_id}:p{hero_actor}:action:{source_action_index}:prefix:{prefix_hash}",
        }
        candidate = {
            "decision_id": validated["decision_id"],
            "hand_id": canonical_hand,
            "source_url": source["url"],
            "source_record_id": record["record_id"],
            "raw_extract_sha256": source_hash,
            "strict_action_prefix_identity": identity,
            "observations": validated["state"],
            "expected": expected,
            "terminal_facts": copy.deepcopy(terminal),
            "normalizations": copy.deepcopy(record.get("_normalizations", [])),
            "admission_status": "pending_independent_source_and_conversion_review",
            "evidence_tier": "forum_hand_history_replay_pending_independent_review",
            "source_evidence": {key: copy.deepcopy(value) for key, value in record.items()
                                 if not key.startswith("_")},
            "source_aliases": copy.deepcopy(record.get("_source_aliases", [])),
            "replay_validation": "pokerkit_fulltilt_parse_and_ivey_strict_replay",
            "chip_ticks_per_currency_unit": terminal["chip_ticks_per_currency_unit"],
            "inspected_label_no_fresh_holdout_claim": True,
        }
        output.append(candidate)
    return output, baseline_drops


def _observation_signature(state: dict[str, Any]) -> str:
    observation = ivey.policy_observation(state)
    return _sha256(_canonical_json(observation))


def _process_fulltilt_record(record: dict[str, Any], ft_id: str, source_hash: str,
                             normalized_dir: Path, baseline_observations: set[str],
                             aliases: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    raw_text = record.get("raw_source_text")
    if not isinstance(raw_text, str) or not raw_text:
        raise RejectHand("raw_source_text_missing")
    source_id = _exact_fulltilt_id(record)
    if source_id != ft_id:
        raise RejectHand("raw_fulltilt_hand_id_does_not_match_source_record")
    if str(record.get("hand_id")) != ft_id:
        raise RejectHand("structured_hand_id_does_not_match_raw_fulltilt_id")
    classification = record.get("classification")
    if not isinstance(classification, dict) or classification.get("complete_candidate") is not True:
        raise RejectHand("source_record_marked_partial_or_incomplete")
    if classification.get("raw_prefix_complete") is not True:
        raise RejectHand("source_raw_prefix_incomplete")
    if _has_source_card_conflict(record):
        raise RejectHand("source_card_conflict_excluded")
    if record.get("game") != "No Limit Hold'em":
        raise RejectHand("source_game_not_explicit_nlhe")
    _source_url(record)

    history, parser_warning_count = _parse_source_history(raw_text)
    parsed_document, _, normalizations = _phh_document(history)
    if str(parsed_document.get("hand", "")) != ft_id:
        raise RejectHand("pokerkit_hand_id_differs_from_exact_source_id")
    if parser_warning_count and not any(n["operation"] == "retain_but_ignore_source_timezone_annotation"
                                       for n in normalizations):
        normalizations.append({
            "operation": "retain_but_ignore_source_timezone_annotation",
            "field": "time_zone_abbreviation",
            "parser_warning": PARSER_WARNING,
        })
    hero_cards = _known_hero_cards(record)
    normalizations.extend(_inject_source_shown_hero_cards(parsed_document, hero_cards))
    history.actions = list(parsed_document["actions"])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        normalized_phh = history.dumps()
    if any(str(item.message) != PARSER_WARNING for item in caught):
        raise RejectHand("unexpected_normalized_phh_warning")
    parsed_document = tomllib.loads(normalized_phh, parse_float=Decimal)
    terminal = _terminal_replay_and_pot(parsed_document, raw_text)
    normalized_name = f"fulltilt_{ft_id}.phh"
    normalized_dir.mkdir(parents=True, exist_ok=True)
    (normalized_dir / normalized_name).write_text(normalized_phh, encoding="utf-8")
    normalizations.append({
        "operation": "exact_decimal_currency_to_integer_chip_ticks",
        "chip_ticks_per_currency_unit": terminal["chip_ticks_per_currency_unit"],
        "details": "The existing Ivey replay scaling helper chose exact integer ticks from every stack, forced bet, min bet, ante, and raise; no fractional amount was truncated.",
    })

    with tempfile.TemporaryDirectory(prefix="forum-acquisition-replay-") as temporary:
        phh_path = Path(temporary) / normalized_name
        phh_path.write_text(normalized_phh, encoding="utf-8")
        replay_rows = ivey.load_decisions(phh_path)
        replay_report = copy.deepcopy(ivey.LAST_LOAD_REPORT)
    file_exclusions = {key for key in replay_report["exclusions"] if key.startswith("file:")}
    if file_exclusions - {"file:no_usable_ivey_decisions"}:
        raise RejectHand("history_rejected_by_ivey_strict_replay")
    # Attach documented normalization without mutating the pristine source row.
    candidate_source = copy.deepcopy(record)
    candidate_source["_normalizations"] = normalizations
    candidate_source["_source_aliases"] = aliases or []
    candidates, baseline_drops = _candidate_rows(
        candidate_source, ft_id, source_hash, parsed_document, replay_rows,
        terminal, baseline_observations)
    return {
        "fulltilt_hand_id": ft_id,
        "canonical_hand_id": f"fulltilt:{ft_id}",
        "source_record_id": record["record_id"],
        "raw_extract_sha256": source_hash,
        "normalized_phh_path": normalized_name,
        "normalized_phh_sha256": _sha_text(normalized_phh),
        "status": "replayed_pending_independent_review" if candidates else (
            "replayed_no_known_hero_decisions" if hero_cards is None else "replayed_no_reviewable_decisions"),
        "strict_replay_report": replay_report,
        "terminal_facts": terminal,
        "normalizations": normalizations,
        "candidate_decisions": candidates,
        "baseline_overlap_decisions_removed": baseline_drops,
        "source_aliases": aliases or [],
    }


def _baseline_observations(path: Path) -> set[str]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    records = manifest.get("records")
    if not isinstance(records, list):
        raise ValueError("baseline_manifest_missing_records")
    return {_observation_signature(record["state"]) for record in records}


def _source_alias(record: dict[str, Any], raw_hash: str) -> dict[str, Any]:
    return {
        "source_record_id": record.get("record_id"),
        "source_url": (record.get("source") or {}).get("url")
        if isinstance(record.get("source"), dict) else None,
        "raw_extract_sha256": raw_hash,
        "source_classification": copy.deepcopy(record.get("classification")),
    }


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def convert(input_path: Path = DEFAULT_INPUT, output_dir: Path = DEFAULT_OUTPUT,
            baseline_path: Path = DEFAULT_BASELINE) -> dict[str, Any]:
    input_path, output_dir, baseline_path = Path(input_path), Path(output_dir), Path(baseline_path)
    records, input_hash, source_bytes = _read_records(input_path)
    baseline_hash = _sha256(baseline_path.read_bytes())
    baseline_obs = _baseline_observations(baseline_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    # Keep an exact byte-for-byte local snapshot to make this batch rerunnable.
    snapshot_path = output_dir / "source_records.jsonl"
    snapshot_path.write_bytes(source_bytes)
    normalized_dir = output_dir / "normalized_phh"
    raw_hashes = [_sha_text(record.get("raw_source_text", ""))
                  if isinstance(record.get("raw_source_text"), str) else None for record in records]
    id_groups: dict[str, list[tuple[int, dict[str, Any], str]]] = defaultdict(list)
    pending_identity: list[dict[str, Any]] = []
    source_entries: list[dict[str, Any]] = []
    hand_reports: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []

    for index, (record, raw_hash) in enumerate(zip(records, raw_hashes)):
        source_id = _exact_fulltilt_id(record)
        entry = {
            "source_record_id": record.get("record_id"),
            "source_url": (record.get("source") or {}).get("url")
            if isinstance(record.get("source"), dict) else None,
            "source_classification": copy.deepcopy(record.get("classification")),
            "structured_hand_id": record.get("hand_id"),
            "exact_fulltilt_hand_id": source_id,
            "raw_extract_sha256": raw_hash,
            "input_record_index": index,
        }
        source_entries.append(entry)
        if source_id is None:
            reason = "converted_history_without_exact_fulltilt_hand_id_pending_cross_source_identity_review"
            pending_identity.append({**entry, "status": "pending_cross_source_identity_review", "reason": reason})
            continue
        id_groups[source_id].append((index, record, raw_hash or ""))

    # Full Tilt IDs are the unique identity. Exact copies retain all aliases;
    # divergent payloads under one ID are excluded as an identity conflict.
    unique_hands: list[tuple[str, dict[str, Any], str, list[dict[str, Any]]]] = []
    duplicate_aliases = 0
    identity_conflicts = 0
    for ft_id, group in sorted(id_groups.items(), key=lambda pair: min(item[0] for item in pair[1])):
        hashes = {item[2] for item in group}
        if len(hashes) > 1:
            identity_conflicts += 1
            conflict = {
                "fulltilt_hand_id": ft_id,
                "reason": "conflicting_source_payloads_for_exact_fulltilt_hand_id",
                "source_record_ids": [item[1].get("record_id") for item in group],
                "raw_extract_sha256s": sorted(hashes),
            }
            rejections.append(conflict)
            for item in group:
                source_entries[item[0]]["status"] = "rejected_identity_conflict"
                source_entries[item[0]]["reason"] = conflict["reason"]
            continue
        group.sort(key=lambda item: item[0])
        first_index, primary, raw_hash = group[0]
        aliases = [_source_alias(item[1], item[2]) for item in group[1:]]
        duplicate_aliases += len(aliases)
        for item in group:
            source_entries[item[0]]["status"] = "deduplicated_alias" if item[0] != first_index else "queued_for_replay"
            source_entries[item[0]]["canonical_hand_id"] = f"fulltilt:{ft_id}"
        unique_hands.append((ft_id, primary, raw_hash, aliases))

    # Establish the source-level expected counts independently of replay.
    known_complete_after_conflict = []
    partial_records = []
    source_card_conflicts = []
    for record in records:
        classification = record.get("classification", {})
        if not isinstance(classification, dict):
            continue
        known = _known_hero_cards(record) is not None
        complete = classification.get("complete_candidate") is True
        conflict = _has_source_card_conflict(record)
        if complete and known and not conflict:
            known_complete_after_conflict.append(record)
        if not complete:
            partial_records.append(record)
        if conflict:
            source_card_conflicts.append(record)

    # Id-less converted histories cannot be safely replayed here: they lack
    # exact identities and some reconstructed their forced bets from positions.
    for item in pending_identity:
        source_entries[item["input_record_index"]]["status"] = "pending_cross_source_identity_review"
        source_entries[item["input_record_index"]]["reason"] = item["reason"]

    # Do not replay source-marked partial histories or known card conflicts.
    for ft_id, record, raw_hash, aliases in unique_hands:
        classification = record.get("classification", {})
        if not isinstance(classification, dict) or classification.get("complete_candidate") is not True:
            reason = "source_record_marked_partial_or_incomplete"
            report = {"fulltilt_hand_id": ft_id, "source_record_id": record.get("record_id"),
                      "raw_extract_sha256": raw_hash, "status": "partial_or_rejected", "reason": reason}
            hand_reports.append(report)
            rejections.append(report.copy())
            continue
        if _has_source_card_conflict(record):
            reason = "source_card_conflict_excluded"
            report = {"fulltilt_hand_id": ft_id, "source_record_id": record.get("record_id"),
                      "raw_extract_sha256": raw_hash, "status": "partial_or_rejected", "reason": reason}
            hand_reports.append(report)
            rejections.append(report.copy())
            continue
        try:
            report = _process_fulltilt_record(record, ft_id, raw_hash, normalized_dir,
                                              baseline_obs, aliases)
            hand_reports.append(report)
            source_entries[next(i for i, r, _ in id_groups[ft_id] if r is record)]["status"] = report["status"]
        except (OSError, ValueError, TypeError, KeyError, IndexError, Warning) as exc:
            report = {"fulltilt_hand_id": ft_id, "source_record_id": record.get("record_id"),
                      "raw_extract_sha256": raw_hash, "status": "partial_or_rejected",
                      "reason": str(exc)}
            hand_reports.append(report)
            rejections.append(report.copy())
            for entry in source_entries:
                if entry["source_record_id"] == record.get("record_id"):
                    entry["status"] = "partial_or_rejected"
                    entry["reason"] = str(exc)

    candidates = [candidate for hand in hand_reports for candidate in hand.get("candidate_decisions", [])]
    # Defensive dedupe on strict action-prefix identity. Conflicting labels for
    # one exact identity remove all variants rather than selecting a source.
    identity_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        identity_rows[candidate["strict_action_prefix_identity"]["identity"]].append(candidate)
    conflicting_prefix_ids = set()
    dedup_candidates = []
    duplicates_removed = 0
    for identity, group in identity_rows.items():
        labels = {_canonical_json(row["expected"]) for row in group}
        if len(labels) > 1:
            conflicting_prefix_ids.add(identity)
            rejections.append({"strict_action_prefix_identity": identity,
                               "reason": "conflicting_labels_for_same_strict_action_prefix"})
            continue
        dedup_candidates.append(group[0])
        duplicates_removed += len(group) - 1
    candidates = dedup_candidates

    converted_known_pending = sum(
        1 for record in records
        if _exact_fulltilt_id(record) is None
        and record.get("classification", {}).get("complete_candidate") is True
        and _known_hero_cards(record) is not None)
    replayed_known_hands = sum(
        1 for hand in hand_reports
        if hand.get("candidate_decisions") and hand.get("status") == "replayed_pending_independent_review")
    unique_replayable_decisions = len(candidates)
    raw_hands = sum(_exact_fulltilt_id(record) is not None for record in records)
    replay_failures = sum(hand.get("status") == "partial_or_rejected" for hand in hand_reports)
    baseline_removed = sum(hand.get("baseline_overlap_decisions_removed", 0) for hand in hand_reports)
    replayed_id_histories = sum(str(hand.get("status", "")).startswith("replayed_")
                                for hand in hand_reports)
    replayed_without_known_cards = sum(hand.get("status") == "replayed_no_known_hero_decisions"
                                       for hand in hand_reports)
    try:
        pokerkit_version = importlib.metadata.version("pokerkit")
    except importlib.metadata.PackageNotFoundError:
        pokerkit_version = "unavailable"
    result = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "review_candidates_pending_independent_source_and_conversion_review",
        "input_path": str(input_path),
        "input_records_sha256": input_hash,
        "baseline_path": str(baseline_path),
        "baseline_sha256": baseline_hash,
        "replay_engine": {
            "name": "PokerKit Full Tilt parser + pokerbot.ivey strict replay",
            "pokerkit_version": pokerkit_version,
        },
        "snapshot_path": str(snapshot_path),
        "counts": {
            "raw_source_records": len(records),
            "raw_fulltilt_histories_with_exact_hand_id": raw_hands,
            "unique_fulltilt_hand_ids": len(id_groups),
            "unique_fulltilt_histories_attempted": len(unique_hands),
            "complete_exact_id_histories_replayed": replayed_id_histories,
            "complete_exact_id_histories_replayed_without_known_hero_cards": replayed_without_known_cards,
            "duplicate_exact_hand_aliases_removed": duplicate_aliases,
            "conflicting_payload_identities_excluded": identity_conflicts,
            "complete_known_card_source_records_after_recorded_conflict_exclusion": len(known_complete_after_conflict),
            "complete_known_card_exact_id_histories": sum(
                _exact_fulltilt_id(record) is not None
                and record.get("classification", {}).get("complete_candidate") is True
                and _known_hero_cards(record) is not None
                and not _has_source_card_conflict(record)
                for record in records),
            "known_card_converted_histories_pending_identity_review": converted_known_pending,
            "converted_histories_pending_cross_source_identity_review": len(pending_identity),
            "partial_source_records": len(partial_records),
            "source_card_conflict_records": len(source_card_conflicts),
            "replayed_known_card_hands_with_decisions": replayed_known_hands,
            "unique_replayable_known_card_decisions": unique_replayable_decisions,
            "baseline_overlap_decisions_removed": baseline_removed,
            "strict_replay_or_conversion_rejections": replay_failures,
            "decision_identity_duplicates_removed": duplicates_removed,
            "conflicting_action_prefix_identities_excluded": len(conflicting_prefix_ids),
            "validated_candidate_decisions_pending_review": unique_replayable_decisions,
            "newly_admitted_decisions": 0,
        },
        "source_records": source_entries,
        "pending_cross_source_identity_review": pending_identity,
        "hand_reports": hand_reports,
        "rejections": rejections,
        "records": candidates,
        "limitations": [
            "Replay validity does not establish that a public forum transcription is source-accurate.",
            "Converted histories without exact Full Tilt hand IDs remain pending cross-source identity review and are not counted as unique decisions.",
            "All rows are pending independent source and conversion review; no source is automatically admitted.",
            "The labels and source histories were inspected during conversion; this batch makes no fresh heldout claim.",
        ],
    }
    if len(known_complete_after_conflict) != 43:
        result["source_count_check"] = {
            "expected_known_card_complete_after_conflict": 43,
            "actual": len(known_complete_after_conflict),
            "status": "source_checkpoint_count_mismatch",
        }
    else:
        result["source_count_check"] = {
            "expected_known_card_complete_after_conflict": 43,
            "actual": 43,
            "status": "verified_from_source_records",
        }
    (output_dir / "review_candidates.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8")
    (output_dir / "manifest.json").write_text(
        json.dumps({
            "schema_version": 1,
            "converter_version": CONVERTER_VERSION,
            "input_records_path": str(input_path),
            "input_records_sha256": input_hash,
            "baseline_path": str(baseline_path),
            "baseline_sha256": baseline_hash,
            "replay_engine": result["replay_engine"],
            "source_records_snapshot": "source_records.jsonl",
            "review_candidates": "review_candidates.json",
            "counts": result["counts"],
            "source_records": source_entries,
        }, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = convert(args.input, args.output_dir, args.baseline)
    print(json.dumps(result["counts"], sort_keys=True))


if __name__ == "__main__":
    main()
