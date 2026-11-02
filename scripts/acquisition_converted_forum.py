#!/usr/bin/env python3
"""Normalize converted Full Tilt forum histories into pending-review PHH rows.

This converter is local-only. It preserves publisher/post identity for records
without a visible Full Tilt game number and never treats a publisher-reported
database number as a Full Tilt ID.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import re
import sys
import tempfile
import tomllib
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pokerbot import ivey
from pokerbot.cards import normalize_card
from pokerbot.corpus import validate_rows
from scripts import acquisition_forum_convert as fulltilt

OLD_INPUT = ROOT / "data/acquisition_sprint_1h/online_forum/records.jsonl"
MID_INPUT = ROOT / "data/acquisition_resume/2026-11-02/forum_2009_2011/records.jsonl"
PLUS_INPUT = ROOT / "data/acquisition_resume/2026-11-01/forum_2012_plus/rawrecords.jsonl"
NEW_PLUS_INPUT = ROOT / "data/acquisition_resume/2026-11-02/forum_2012_plus/rawrecords.jsonl"
REGISTRATION = ROOT / "data/acquisition_resume/2026-11-02/forum-batch-registration-001.json"
IDENTITY_BASIS = ROOT / "data/acquisition_resume/2026-11-01/forum_2012_plus/identity-basis.json"
IDENTITY_EVIDENCE = ROOT / "data/acquisition_sprint_1h/identity-evidence.json"
ORIGINAL_MANIFEST = ROOT / "data/acquisition_resume/2026-11-01/forum_conversion/manifest.json"
OUTPUT = ROOT / "data/acquisition_resume/2026-11-02/converted_forum"
HERO = "Phil Ivey"
ALIAS = "Polarizing"
CONVERTER_VERSION = 1
REGISTERED_INPUTS = {
    "data/acquisition_resume/2026-11-02/forum_2009_2011/records.jsonl":
        "56d38be218115370c85832478a3121a2905318f2b0c6bf673e654eb82b265ac8",
    "data/acquisition_resume/2026-11-02/forum_2012_plus/rawrecords.jsonl":
        "cb8272a63b7a2e9f07609773cc61bb7e750556977d5b7ae9c68b1932e25d7c55",
}


class RejectHand(ValueError):
    """A converted source lacks a fact needed for a faithful replay."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _text_sha(text: str) -> str:
    return _sha(text.encode("utf-8"))


def _money(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value).replace("$", "").replace(",", "").strip())
    except (InvalidOperation, ValueError) as exc:
        raise RejectHand("invalid_source_money") from exc
    if not amount.is_finite() or amount < 0:
        raise RejectHand("source_money_must_be_finite_and_nonnegative")
    return amount


def _load_jsonl(path: Path) -> tuple[list[dict[str, Any]], str]:
    raw = path.read_bytes()
    rows = []
    for line_number, line in enumerate(raw.decode("utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid_jsonl_line_{line_number}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"jsonl_record_{line_number}_is_not_an_object")
        rows.append(row)
    return rows, _sha(raw)


def _role(value: str) -> str:
    role = re.sub(r"\s+", "", value).upper()
    if role in {"BU/SB", "SB/BU", "BTN/SB", "SB/BTN"}:
        return "BTN/SB"
    if role in {"BU", "BUTTON"}:
        return "BTN"
    return role


def _policy_position(value: str) -> str:
    # Pokerbot's position schema represents a heads-up button/small blind as BTN.
    return "BTN" if value == "BTN/SB" else value


def _hero_name(record: dict[str, Any], identity_basis: dict[str, Any]) -> tuple[str, str, dict[str, Any] | None]:
    alias = record.get("hero_alias")
    if alias is None:
        hero = record.get("hero")
        if hero != HERO:
            raise RejectHand("hero_not_explicitly_identified_as_phil_ivey")
        return HERO, HERO, None
    if alias != ALIAS or identity_basis.get("alias") != ALIAS or identity_basis.get("reported_identity") != HERO:
        raise RejectHand("hero_alias_identity_basis_mismatch")
    identity_sha = _sha(IDENTITY_EVIDENCE.read_bytes())
    if identity_basis.get("upstream_sha256") != identity_sha:
        raise RejectHand("hero_alias_identity_evidence_hash_mismatch")
    identity_source = record.get("hero_alias_identity_source")
    if not isinstance(identity_source, dict) or identity_source.get("file") not in {
            "identity-basis.json", "data/acquisition_sprint_1h/identity-evidence.json"}:
        raise RejectHand("hero_alias_identity_source_not_recorded")
    if identity_source.get("upstream_sha256") != identity_sha:
        raise RejectHand("hero_alias_identity_source_hash_mismatch")
    if identity_basis.get("use") != "Source identity metadata only; not an observation or hand-state feature.":
        raise RejectHand("hero_alias_identity_scope_mismatch")
    return ALIAS, ALIAS, {
        "source_alias": ALIAS,
        "normalized_player_name": HERO,
        "identity_basis_path": "data/acquisition_resume/2026-11-01/forum_2012_plus/identity-basis.json",
        "identity_basis_sha256": _sha(IDENTITY_BASIS.read_bytes()),
        "upstream_identity_evidence_path": "data/acquisition_sprint_1h/identity-evidence.json",
        "upstream_identity_evidence_sha256": identity_sha,
        "attribution_limit": "publisher-reported alias attribution; identity does not establish hand facts",
    }


def _seat_facts(record: dict[str, Any], hero_source: str) -> tuple[list[str], dict[str, str], dict[str, Decimal], str, str, Decimal, Decimal]:
    seats = record.get("seats")
    if not isinstance(seats, dict) or not 2 <= len(seats) <= 8:
        raise RejectHand("missing_or_unsupported_source_seats")
    position_by_name: dict[str, str] = {}
    stacks: dict[str, Decimal] = {}
    for key, value in seats.items():
        if not isinstance(value, dict):
            raise RejectHand("invalid_source_seat_record")
        name = value.get("player") or key
        if not isinstance(name, str) or not name:
            raise RejectHand("source_seat_player_missing")
        position = value.get("position")
        if not isinstance(position, str):
            raise RejectHand("source_position_missing")
        position_by_name[name] = _role(position)
        stack = value.get("starting_stack")
        if stack is None:
            raise RejectHand("source_starting_stack_missing")
        stacks[name] = _money(stack)
    count = len(position_by_name)
    if count == 2:
        for name, position in list(position_by_name.items()):
            if position == "SB":
                # In a heads-up hand the source SB is also the button.
                position_by_name[name] = "BTN/SB"
    if len(set(position_by_name.values())) != len(position_by_name):
        raise RejectHand("source_positions_not_unique")
    if hero_source not in position_by_name:
        raise RejectHand("identified_hero_not_in_source_seats")
    if count == 2:
        buttons = [name for name, pos in position_by_name.items() if pos in {"BTN/SB", "SB"}]
        big_blinds = [name for name, pos in position_by_name.items() if pos == "BB"]
        if len(buttons) != 1 or len(big_blinds) != 1:
            raise RejectHand("heads_up_button_or_big_blind_not_unique")
        button_name, sb_name, bb_name = buttons[0], buttons[0], big_blinds[0]
        ordered = [bb_name, button_name]
    else:
        buttons = [name for name, pos in position_by_name.items() if pos == "BTN"]
        small_blinds = [name for name, pos in position_by_name.items() if pos == "SB"]
        big_blinds = [name for name, pos in position_by_name.items() if pos == "BB"]
        if any(len(group) != 1 for group in (buttons, small_blinds, big_blinds)):
            raise RejectHand("button_or_blind_position_not_unique")
        button_name, sb_name, bb_name = buttons[0], small_blinds[0], big_blinds[0]
        middle_rank = {"UTG": 0, "UTG+1": 1, "UTG+2": 2, "MP": 3,
                       "HJ": 4, "CO": 5, "MP1": 6, "MP2": 7}
        middle = [name for name, pos in position_by_name.items()
                  if pos not in {"SB", "BB", "BTN"}]
        if any(position_by_name[name] not in middle_rank for name in middle):
            raise RejectHand("unsupported_or_ambiguous_source_position")
        middle.sort(key=lambda name: (middle_rank[position_by_name[name]], name.casefold()))
        ordered = [sb_name, bb_name, *middle, button_name]
        if len(ordered) != count or len(set(ordered)) != count:
            raise RejectHand("source_positions_do_not_define_complete_seat_order")

    small_blind, big_blind = _source_blinds(record)
    if small_blind <= 0 or big_blind <= 0 or small_blind > big_blind:
        raise RejectHand("explicit_blinds_missing_or_invalid")
    if count == 2 and ordered != [bb_name, button_name]:
        raise RejectHand("heads_up_seat_order_mismatch")
    return ordered, position_by_name, stacks, button_name, sb_name, small_blind, big_blind


def _source_blinds(record: dict[str, Any]) -> tuple[Decimal, Decimal]:
    forced = record.get("forced_bets")
    if isinstance(forced, dict):
        sb = forced.get("small_blind")
        bb = forced.get("big_blind")
        if isinstance(sb, dict) and isinstance(bb, dict) and sb.get("amount") is not None and bb.get("amount") is not None:
            return _money(sb["amount"]), _money(bb["amount"])
        if forced.get("small_blind_amount") is not None and forced.get("big_blind_amount") is not None:
            return _money(forced["small_blind_amount"]), _money(forced["big_blind_amount"])
        if isinstance(sb, (str, int, float, Decimal)) and isinstance(bb, (str, int, float, Decimal)):
            return _money(sb), _money(bb)
    raw = record.get("raw_source_text", "")
    match = re.search(r"\$([\d,]+(?:\.\d+)?)\s*/\s*\$([\d,]+(?:\.\d+)?)", raw)
    if match:
        return _money(match.group(1)), _money(match.group(2))
    posted: dict[str, Decimal] = {}
    names = record.get("seats", {})
    for line in raw.splitlines():
        for name in names:
            for blind, code in (("small_blind", "SB"), ("big_blind", "BB")):
                pattern = rf"^{re.escape(name)}\s+posts\s+{code}\s+\$?([\d,]+(?:\.\d+)?)\b"
                found = re.search(pattern, line.strip(), re.I)
                if found:
                    posted[blind] = _money(found.group(1))
    if set(posted) == {"small_blind", "big_blind"}:
        return posted["small_blind"], posted["big_blind"]
    raise RejectHand("explicit_small_and_big_blind_amounts_missing")


def _split_action_tokens(value: str) -> list[str]:
    return [part.strip().lstrip(".").strip() for part in value.split(", ") if part.strip().lstrip(".").strip()]


_CARD_CODE = r"[2-9TJQKA][cdhs]"
_CARD_ALT = r"[2-9TJQKA]\s*Image:\s*(?:Club|Diamond|Heart|Spade)"
_CARD_ALT_SUIT = {"club": "c", "diamond": "d", "heart": "h", "spade": "s"}


def _parse_explicit_card(value: str, allow_alt: bool = False) -> str:
    if re.fullmatch(_CARD_CODE, value, re.I):
        return normalize_card(value)
    if allow_alt:
        match = re.fullmatch(r"([2-9TJQKA])\s*Image:\s*(Club|Diamond|Heart|Spade)", value, re.I)
        if match:
            return normalize_card(match.group(1) + _CARD_ALT_SUIT[match.group(2).casefold()])
    raise RejectHand("source_card_not_explicit")


def _shown_line_pattern(source_name: str, allow_alt: bool) -> re.Pattern[str]:
    card = rf"(?:{_CARD_CODE}|{_CARD_ALT})" if allow_alt else _CARD_CODE
    return re.compile(
        rf"(?im)^{re.escape(source_name)}(?:\s+\([^)]*\))?\s+shows\s+(?:\*?\[?\s*)"
        rf"({card})\]?(?:\s+\[?\s*)({card})\]?"
    )


def _show_cards_match(match: re.Match[str], allow_alt: bool) -> list[str]:
    try:
        return [_parse_explicit_card(match.group(1), allow_alt),
                _parse_explicit_card(match.group(2), allow_alt)]
    except RejectHand as exc:
        raise RejectHand("source_shown_cards_not_explicit") from exc


def _parse_action_token(token: str, names: list[str]) -> list[dict[str, Any]]:
    token = token.strip().rstrip(".").strip()
    if any(re.fullmatch(rf"{re.escape(name)}\s+requests\s+TIME", token, re.I)
           for name in names):
        return []  # source time-bank metadata, not a poker action
    folded = re.fullmatch(r"(?:(\d+)\s+)?folds?", token, re.I)
    if folded:
        count = int(folded.group(1) or 1)
        if count > 8:
            raise RejectHand("invalid_aggregate_fold_count")
        return [{"kind": "fold", "actor": None} for _ in range(count)]
    for source_name in sorted(names, key=len, reverse=True):
        if not token.startswith(source_name):
            continue
        rest = token[len(source_name):].strip()
        role = re.match(r"^\([^)]*\)\s*", rest)
        if role:
            rest = rest[role.end():]
        rest = re.sub(r"\s*\(\s*all[\s-]?in\s*\)\s*$", "", rest, flags=re.I).strip()
        rest = re.sub(r"\s*,?\s*(?:and\s+is\s+)?all[\s-]?in\s*$", "", rest, flags=re.I).strip()
        action: dict[str, Any] = {"actor": source_name}
        if re.fullmatch(r"folds?", rest, re.I):
            action["kind"] = "fold"
        elif re.fullmatch(r"checks?", rest, re.I):
            action["kind"] = "check"
        else:
            call = re.fullmatch(r"calls?\s+\$?([\d,]+(?:\.\d+)?)", rest, re.I)
            bet = re.fullmatch(r"bets?\s+\$?([\d,]+(?:\.\d+)?)", rest, re.I)
            raise_match = re.fullmatch(
                r"(?:raises?|\d+(?:st|nd|rd|th)?-bets?)\s+to\s+\$?([\d,]+(?:\.\d+)?)",
                rest, re.I)
            if call:
                action.update(kind="call", amount=_money(call.group(1)))
            elif bet:
                action.update(kind="bet", amount=_money(bet.group(1)))
            elif raise_match:
                action.update(kind="raise", amount=_money(raise_match.group(1)))
            else:
                continue
        return [action]
    raise RejectHand("unparsed_or_ambiguous_converted_action")


def _extract_board(rest: str, count: int, allow_alt: bool = False) -> tuple[list[str], str]:
    if allow_alt and re.match(rf"^\s*{_CARD_ALT}\b", rest, re.I):
        pattern = re.compile(_CARD_ALT, re.I)
        matches = list(pattern.finditer(rest))
        if len(matches) < count or rest[:matches[0].start()].strip():
            raise RejectHand("street_board_cards_missing")
        between = [rest[matches[i].end():matches[i + 1].start()] for i in range(count - 1)]
        if any(value.strip() for value in between):
            raise RejectHand("street_board_cards_not_explicit")
        cards = [_parse_explicit_card(match.group(0), True) for match in matches[:count]]
        leftover = rest[matches[count - 1].end():].strip()
        if re.fullmatch(r"\(\d+\s+players?(?:\s*[-,]\s*\d+\s+(?:(?:is|are)\s+)?all[\s-]?in)?\)", leftover, re.I):
            leftover = ""
        return cards, leftover.lstrip(".").strip()
    tokens = rest.strip().split()
    if len(tokens) < count:
        raise RejectHand("street_board_cards_missing")
    cards: list[str] = []
    for token in tokens[:count]:
        token = token.rstrip(".")
        try:
            cards.append(_parse_explicit_card(token, allow_alt))
        except (TypeError, ValueError, RejectHand) as exc:
            raise RejectHand("street_board_cards_not_explicit") from exc
    leftover = " ".join(tokens[count:]).strip()
    if re.fullmatch(r"\(\d+\s+players?(?:\s*[-,]\s*\d+\s+(?:(?:is|are)\s+)?all[\s-]?in)?\)", leftover, re.I):
        leftover = ""
    return cards, leftover.lstrip(".").strip()


def _parse_converted_history(record: dict[str, Any], source_names: list[str]) -> list[dict[str, Any]]:
    raw = record.get("raw_source_text")
    if not isinstance(raw, str) or not raw.strip():
        raise RejectHand("raw_converted_history_missing")
    if re.search(r"\b(?:Cap|PLO|Pot Limit|Short Deck|run it twice|run twice|Flop\s+#2)\b", raw, re.I):
        raise RejectHand("unsupported_cap_pot_limit_or_multiple_runout_format")
    if re.search(r"\bposts?\s+(?:the\s+)?ante\b|\bante\s*[:=]\s*\$?\d", raw, re.I):
        raise RejectHand("ante_format_requires_dedicated_importer")
    classification = record.get("classification") or {}
    allow_alt_cards = classification.get("card_alt_text_normalized") is True
    header = raw.splitlines()[0]
    if not (re.search(r"No\s+Limit\s+Hold.?em", header, re.I)
            or re.search(r"Hold.?em\s+NL\b", header, re.I)
            or re.search(r"\$[\d,.]+\s+NL\b.*Hold.?em", header, re.I)):
        raise RejectHand("source_header_does_not_explicitly_identify_nlhe")
    events: list[dict[str, Any]] = []
    current_street: str | None = None
    source_action_count = 0
    for line_number, line in enumerate(raw.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        if re.search(r"\b(?:run it twice|run twice|Flop\s+#2|Turn\s+#2|River\s+#2)\b", line, re.I):
            raise RejectHand("multiple_runout_format_unsupported")
        pre = re.match(r"^Pre\s*Flop\s*:\s*(?:\([^)]*\))?\s*(.*)$", line, re.I)
        if pre:
            current_street = "preflop"
            action_text = pre.group(1).strip()
            if action_text:
                for token_index, token in enumerate(_split_action_tokens(action_text), 1):
                    for expansion, action in enumerate(_parse_action_token(token, source_names), 1):
                        source_action_count += 1
                        events.append({**action, "street": current_street,
                                       "locator": {"raw_line": line_number, "token": token_index,
                                                    "fold_expansion": expansion}})
            continue
        street = re.match(r"^(Flop|Turn|River)\s*:\s*\([^)]*\)\s*(.*)$", line, re.I)
        if street:
            current_street = street.group(1).casefold()
            expected_count = 3 if current_street == "flop" else 1
            cards, action_text = _extract_board(street.group(2), expected_count, allow_alt_cards)
            events.append({"kind": "board", "street": current_street, "cards": cards,
                           "locator": {"raw_line": line_number, "token": 0}})
            if action_text:
                for token_index, token in enumerate(_split_action_tokens(action_text), 1):
                    for expansion, action in enumerate(_parse_action_token(token, source_names), 1):
                        source_action_count += 1
                        events.append({**action, "street": current_street,
                                       "locator": {"raw_line": line_number, "token": token_index,
                                                    "fold_expansion": expansion}})
            continue
        if re.match(r"^(?:Full Tilt|The Official|HSDB Parser|Final Pot|Total pot|Rake paid|Showdown:|\(Rake:|Board:|.*\b(?:shows|mucks|collected|wins?|ties for the pot)\b|Uncalled bet|Seat\s+\d+:)", line, re.I):
            continue
        if re.match(r"^.{1,100}\s+posts\s+(?:SB|BB)\s+\$?", line, re.I):
            if current_street is None:
                current_street = "preflop"
            continue
        if re.match(r"^(?:players? agreed|\*\*\*)", line, re.I):
            continue
        if current_street is None:
            continue
        # Seat stacks, converter attribution, source dates, and other metadata
        # are ignored; action-looking text in a street must parse completely.
        if re.search(r"\b(?:folds?|checks?|calls?|bets?|raises?|\d+-bets?)\b", line, re.I):
            for token_index, token in enumerate(_split_action_tokens(line), 1):
                for expansion, action in enumerate(_parse_action_token(token, source_names), 1):
                    source_action_count += 1
                    events.append({**action, "street": current_street,
                                   "locator": {"raw_line": line_number, "token": token_index,
                                                "fold_expansion": expansion}})
    if source_action_count == 0:
        raise RejectHand("converted_history_has_no_actions")
    if not any(event["kind"] == "board" and event["street"] == "flop" for event in events):
        raise RejectHand("complete_history_flop_missing")
    if [len(event["cards"]) for event in events if event["kind"] == "board"] not in ([3, 1, 1], [3], [3, 1]):
        raise RejectHand("unsupported_or_incomplete_board_runout")
    if allow_alt_cards:
        try:
            structured_board = [normalize_card(card) for card in record.get("board", [])]
        except (TypeError, ValueError) as exc:
            raise RejectHand("normalized_source_board_field_invalid") from exc
        parsed_board = [card for event in events if event["kind"] == "board" for card in event["cards"]]
        if len(structured_board) != len(parsed_board) or structured_board != parsed_board:
            raise RejectHand("raw_image_card_labels_conflict_with_structured_board")
    return events


def _bind_source_action_locators(record: dict[str, Any], events: list[dict[str, Any]],
                                 source_names: list[str]) -> None:
    source_events = record.get("action_events")
    if not isinstance(source_events, list) or not source_events:
        return
    source_actions = [event for event in source_events
                      if isinstance(event, dict)
                      and str(event.get("street", "")).casefold() in {"preflop", "flop", "turn", "river"}]
    parsed_actions = [event for event in events if event.get("kind") != "board"]
    if len(source_actions) != len(parsed_actions):
        raise RejectHand("source_action_event_count_differs_from_raw_history")
    street_indices: dict[str, int] = defaultdict(int)
    for parsed, source in zip(parsed_actions, source_actions):
        street = str(source.get("street", "")).casefold()
        source_key = source.get("canonical_action_key")
        if street != parsed.get("street") or not isinstance(source_key, str) or not source_key:
            raise RejectHand("source_action_round_or_identity_missing_or_conflicting")
        street_indices[street] += 1
        street_index = source.get("street_action_index")
        if street_index is not None and int(street_index) != street_indices[street]:
            raise RejectHand("source_action_street_index_conflicts_with_raw_history")
        key_suffix = re.search(r"\|(preflop|flop|turn|river):(\d+)$", source_key)
        if key_suffix and (key_suffix.group(1) != street
                           or int(key_suffix.group(2)) != street_indices[street]):
            raise RejectHand("source_canonical_action_key_conflicts_with_round_index")
        parsed_token = _parse_action_token(str(source.get("action_text", "")), source_names)
        if len(parsed_token) != 1:
            raise RejectHand("source_action_identity_token_not_single_action")
        source_action = parsed_token[0]
        if source_action["kind"] != parsed["kind"]:
            raise RejectHand("source_action_identity_differs_from_raw_history")
        if source_action["actor"] is not None and source_action["actor"] != parsed["actor"]:
            raise RejectHand("source_action_actor_differs_from_raw_history")
        if (source.get("actor_status") == "explicit"
                and source.get("actor") != source_action.get("actor")):
            raise RejectHand("source_action_actor_field_conflicts_with_action_text")
        if source_action.get("amount") != parsed.get("amount"):
            raise RejectHand("source_action_amount_differs_from_raw_history")
        parsed["locator"].update({
            "canonical_action_key": source_key,
            "source_round": street,
            "source_street_action_index": source.get("street_action_index"),
            "source_actor_status": source.get("actor_status"),
        })


def _source_cards(record: dict[str, Any], source_hero: str, source_names: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    cards = fulltilt._known_hero_cards(record)
    if cards is None:
        raise RejectHand("source_hero_cards_not_known")
    raw = record["raw_source_text"]
    allow_alt_cards = (record.get("classification") or {}).get("card_alt_text_normalized") is True
    shown = _shown_line_pattern(source_hero, allow_alt_cards).search(raw)
    if not shown:
        raise RejectHand("known_hero_cards_not_shown_under_source_identity")
    try:
        shown_cards = _show_cards_match(shown, allow_alt_cards)
    except (ValueError, RejectHand) as exc:
        raise RejectHand("invalid_source_shown_hero_cards") from exc
    if set(shown_cards) != set(cards):
        raise RejectHand("structured_and_raw_hero_cards_conflict")
    opponent_shows: dict[str, list[str]] = {}
    for name in source_names:
        if name == source_hero:
            continue
        found = _shown_line_pattern(name, allow_alt_cards).search(raw)
        if found:
            opponent_shows[name] = _show_cards_match(found, allow_alt_cards)
    all_cards = [*cards, *(card for pair in opponent_shows.values() for card in pair)]
    for event in _parse_board_only(raw, allow_alt_cards):
        all_cards.extend(event)
    if len(set(all_cards)) != len(all_cards):
        raise RejectHand("source_hero_opponent_or_board_card_conflict")
    return cards, opponent_shows


def _parse_board_only(raw: str, allow_alt: bool = False) -> list[list[str]]:
    output = []
    for line in raw.splitlines():
        street = re.match(r"^(Flop|Turn|River)\s*:\s*\([^)]*\)\s*(.*)$", line.strip(), re.I)
        if street:
            count = 3 if street.group(1).casefold() == "flop" else 1
            cards, _ = _extract_board(street.group(2), count, allow_alt)
            output.append(cards)
    return output


def _state_for(model: dict[str, Any]):
    from pokerkit import Automation, Mode, NoLimitTexasHoldem
    actions = tuple(getattr(Automation, name) for name in (
        "ANTE_POSTING", "BET_COLLECTION", "BLIND_OR_STRADDLE_POSTING",
        "RUNOUT_COUNT_SELECTION", "HAND_KILLING", "CHIPS_PUSHING", "CHIPS_PULLING"))
    return NoLimitTexasHoldem.create_state(
        actions, False, model["antes"], model["blinds_or_straddles"], model["min_bet"],
        model["starting_stacks"], len(model["players"]), mode=Mode.CASH_GAME)


def _encode_and_replay(model: dict[str, Any], events: list[dict[str, Any]], hero_cards: list[str],
                       shown_cards: list[dict[str, Any]], mucked_names: list[str]) -> tuple[list[str], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    from pokerkit import parse_action
    players = model["players"]
    actor_by_name = {name: index + 1 for index, name in enumerate(players)}
    source_to_phh = model["source_to_phh"]
    initial = [f"d dh p{index + 1} {''.join(hero_cards) if name == HERO else '????'}"
               for index, name in enumerate(players)]
    document: dict[str, Any] = {
        "variant": "NT", "ante_trimming_status": False, "antes": model["antes"],
        "blinds_or_straddles": model["blinds_or_straddles"], "min_bet": model["min_bet"],
        "starting_stacks": model["starting_stacks"], "actions": initial,
        "seats": list(range(1, len(players) + 1)), "players": players,
        "hand": model["source_hand_key"],
    }
    scale_document, replay_scale = ivey._scale_chips(document)
    state = _state_for(scale_document)
    for encoded in initial:
        if state.can_burn_card():
            state.burn_card("??")
        parse_action(state, encoded)
    output_events = []
    hero_action_indices = []
    terminal = {"action": None, "before_stacks": None, "before_contributions": None}
    betting_ordinal = 0
    street_ordinal: dict[str, int] = defaultdict(int)
    for event in events:
        was_active = bool(state.status)
        stacks_before = list(state.stacks)
        if event["kind"] == "board":
            packed = "".join(event["cards"])
            encoded = f"d db {packed}"
            if (state.status and state.actor_index is None
                    and not state.can_burn_card() and not state.can_deal_board()):
                raise RejectHand("unsupported_single_remaining_stack_runout_semantics")
            if state.can_burn_card():
                state.burn_card("??")
            if was_active and not state.status:
                terminal.update(action=encoded, before_stacks=stacks_before,
                                before_contributions=[start - now for start, now in zip(scale_document["starting_stacks"], stacks_before)])
            action_index = len(document["actions"])
            document["actions"].append(encoded)
            parse_action(state, encoded)
            output_events.append({"kind": "board", "street": event["street"], "cards": event["cards"],
                                  "phh_action_index": action_index, "source_locator": event["locator"]})
            if was_active and not state.status:
                terminal.update(action=encoded, before_stacks=stacks_before,
                                before_contributions=[start - now for start, now in zip(scale_document["starting_stacks"], stacks_before)])
            continue
        if not state.status:
            raise RejectHand("source_action_follows_terminal_hand")
        if state.actor_index is None:
            raise RejectHand("pokerkit_actor_missing_at_source_action")
        actor_index = state.actor_index
        actor_name = players[actor_index]
        if event["actor"] is None:
            if event["kind"] != "fold":
                raise RejectHand("only_position_order_folds_may_be_inferred")
            inferred = actor_name
            event["actor_resolution"] = {
                "status": "derived_from_unambiguous_standard_action_order",
                "actor": inferred,
                "basis": "complete seat/button/blind order and the preceding source actions identify the only player to act",
            }
        else:
            inferred = source_to_phh.get(event["actor"])
            if inferred is None or inferred != actor_name:
                raise RejectHand("explicit_source_actor_conflicts_with_turn_order")
        kind = event["kind"]
        action_before = state.bets[actor_index]
        due = state.checking_or_calling_amount or 0
        if kind == "fold":
            encoded = f"p{actor_index + 1} f"
            label = "fold"
        elif kind == "check":
            if due:
                raise RejectHand("source_check_when_call_amount_is_due")
            encoded = f"p{actor_index + 1} cc"
            label = "check"
        elif kind == "call":
            if not due:
                raise RejectHand("source_call_without_amount_due")
            amount = event["amount"]
            amount_ticks = amount * replay_scale
            actual_ticks = min(due, state.stacks[actor_index])
            if amount_ticks != actual_ticks:
                raise RejectHand("source_call_amount_differs_from_exact_replay_due")
            encoded = f"p{actor_index + 1} cc"
            label = "call"
        elif kind in {"bet", "raise"}:
            if kind == "bet" and due:
                raise RejectHand("source_bet_token_used_while_facing_a_bet")
            amount_ticks = event["amount"] * replay_scale
            if amount_ticks != int(amount_ticks):
                raise RejectHand("source_raise_not_exact_at_replay_chip_scale")
            target = int(amount_ticks)
            encoded = f"p{actor_index + 1} cbr {target}"
            label = "raise"
        else:
            raise RejectHand("unsupported_source_betting_action")
        action_index = len(document["actions"])
        # PHH stores currency units; only the replay State receives exact
        # integer ticks. ivey.load_decisions applies its own exact scaler.
        phh_encoded = (f"p{actor_index + 1} cbr {event['amount']}"
                       if label == "raise" else encoded)
        document["actions"].append(phh_encoded)
        parse_action(state, encoded)
        betting_ordinal += 1
        street_ordinal[event["street"]] += 1
        fact = {
            "kind": "action", "street": event["street"], "actor": actor_name,
            "action": label,
            "amount_to": str(Decimal(target) / replay_scale) if label == "raise" else None,
            "source_action_ordinal": betting_ordinal,
            "street_action_ordinal": street_ordinal[event["street"]],
            "phh_action_index": action_index,
            "source_locator": event["locator"],
        }
        if "actor_resolution" in event:
            fact["actor_resolution"] = event["actor_resolution"]
        output_events.append(fact)
        if actor_name == HERO:
            hero_action_indices.append(action_index)
        if was_active and not state.status:
            terminal.update(action=encoded, before_stacks=stacks_before,
                            before_contributions=[start - now for start, now in zip(scale_document["starting_stacks"], stacks_before)])
    for item in shown_cards:
        if not state.status:
            raise RejectHand("source_showdown_cards_followed_a_terminal_transition")
        name = item["player"]
        actor_index = actor_by_name[name]
        encoded = f"p{actor_index} sm {''.join(item['cards'])}"
        stacks_before = list(state.stacks)
        was_active = bool(state.status)
        action_index = len(document["actions"])
        document["actions"].append(encoded)
        parse_action(state, encoded)
        if was_active and not state.status:
            terminal.update(action=encoded, before_stacks=stacks_before,
                            before_contributions=[start - now for start, now in zip(scale_document["starting_stacks"], stacks_before)])
        output_events.append({"kind": "showdown", "player": name, "cards": item["cards"],
                              "phh_action_index": action_index, "source_locator": item["source_locator"]})
    for name in mucked_names:
        if not state.status:
            raise RejectHand("source_muck_follows_a_terminal_transition")
        if name not in source_to_phh:
            raise RejectHand("source_muck_actor_not_in_source_seats")
        actor_index = actor_by_name[source_to_phh[name]]
        encoded = f"p{actor_index} sm ????"
        stacks_before = list(state.stacks)
        was_active = bool(state.status)
        action_index = len(document["actions"])
        document["actions"].append(encoded)
        parse_action(state, encoded)
        if was_active and not state.status:
            terminal.update(action=encoded, before_stacks=stacks_before,
                            before_contributions=[start - now for start, now in zip(scale_document["starting_stacks"], stacks_before)])
        output_events.append({"kind": "muck", "player": source_to_phh[name],
                              "phh_action_index": action_index, "source_locator": "raw_source_text:muck_line"})
    # Converted summaries sometimes omit losing players' showdown lines.
    # Close those states with explicit unknown cards only; never reveal a
    # source card before the later public showdown.
    shown_players = {item["player"] for item in shown_cards}
    mucked_players = {source_to_phh[name] for name in mucked_names}
    for name in players:
        if not state.status:
            break
        if name not in shown_players and name not in mucked_players and state.can_show_or_muck_hole_cards("????", actor_by_name[name] - 1):
            encoded = f"p{actor_by_name[name]} sm ????"
            stacks_before = list(state.stacks)
            was_active = bool(state.status)
            action_index = len(document["actions"])
            document["actions"].append(encoded)
            parse_action(state, encoded)
            if was_active and not state.status:
                terminal.update(action=encoded, before_stacks=stacks_before,
                                before_contributions=[start - now for start, now in zip(scale_document["starting_stacks"], stacks_before)])
            output_events.append({"kind": "unknown_showdown_cards", "player": name,
                                  "phh_action_index": action_index,
                                  "source_locator": "converter_terminal_unknown_cards_placeholder"})
    if state.status:
        raise RejectHand("converted_history_did_not_reach_terminal_state")
    if sum(state.stacks) != sum(scale_document["starting_stacks"]):
        raise RejectHand("strict_replay_chip_conservation_failed")
    if not terminal["action"]:
        raise RejectHand("strict_replay_terminal_transition_not_recorded")
    return document["actions"], document, output_events, {
        "strict_terminal_chip_conservation": True,
        "terminal_action": terminal["action"],
        "terminal_before_contributions_ticks": terminal["before_contributions"],
        "replay_chip_ticks_per_currency_unit": replay_scale,
    }


def _terminal_facts(record: dict[str, Any], replay: dict[str, Any], stacks: dict[str, Decimal],
                    source_to_phh: dict[str, str], player_order: list[str], terminal_action: str) -> dict[str, Any]:
    raw = record["raw_source_text"]
    pot_match = re.search(r"\b(?:Final\s+Pot|Total\s+pot)\s*:?\s*\$?([\d,]+(?:\.\d+)?)", raw, re.I)
    rake_match = re.search(r"\bRake(?:\s+paid)?\s*:?\s*\$?([\d,]+(?:\.\d+)?)", raw, re.I)
    awards = [_money(value) for value in re.findall(
        r"\b(?:wins?|won|collected|collects|ties?\s+for\s+the\s+pot)\s*\(??\$([\d,]+(?:\.\d+)?)", raw, re.I)]
    if re.search(r"\bEach\s+wins?\s+\$", raw, re.I) and len(awards) == 1:
        awards = [awards[0], awards[0]]
    source_pot = _money(pot_match.group(1)) if pot_match else None
    source_rake = _money(rake_match.group(1)) if rake_match else None
    if source_pot is None and awards and source_rake is not None:
        source_pot = sum(awards, Decimal(0)) + source_rake
    replay_scale = replay["replay_chip_ticks_per_currency_unit"]
    terminal_precision = max(
        [0] + [-value.as_tuple().exponent for value in [*stacks.values(), *awards]
               if value.as_tuple().exponent < 0]
        + ([-source_pot.as_tuple().exponent] if source_pot is not None and source_pot.as_tuple().exponent < 0 else [])
        + ([-source_rake.as_tuple().exponent] if source_rake is not None and source_rake.as_tuple().exponent < 0 else []))
    if terminal_precision > 6:
        raise RejectHand("terminal_money_precision_exceeds_six_decimal_places")
    money_scale = max(replay_scale, 10 ** terminal_precision)
    if money_scale % replay_scale:
        raise RejectHand("source_terminal_precision_not_exact_at_replay_scale")
    factor = money_scale // replay_scale
    committed = sum(replay["terminal_before_contributions_ticks"])
    unmatched = 0
    if terminal_action.endswith(" f"):
        contributions = sorted(replay["terminal_before_contributions_ticks"], reverse=True)
        unmatched = contributions[0] - (contributions[1] if len(contributions) > 1 else 0)
    replayed_pot_ticks = (committed - unmatched) * factor
    source_pot_ticks = None if source_pot is None else source_pot * money_scale
    if source_pot_ticks is not None and (source_pot_ticks != int(source_pot_ticks)
                                         or int(source_pot_ticks) != replayed_pot_ticks):
        raise RejectHand("strict_replay_gross_pot_differs_from_source_terminal_pot")
    award_status = "not_reported_source_terminal_accounting_pending"
    if awards and source_rake is not None and source_pot is not None:
        awards_ticks = sum(awards, Decimal(0)) * money_scale
        rake_ticks = source_rake * money_scale
        if awards_ticks != int(awards_ticks) or rake_ticks != int(rake_ticks) or int(awards_ticks + rake_ticks) != int(source_pot_ticks):
            raise RejectHand("source_awards_plus_rake_do_not_sum_to_reported_pot")
        award_status = "source_awards_plus_rake_match_total_pot"
    elif source_pot is not None:
        award_status = "source_total_pot_matches_strict_replay"
    return {
        "chip_ticks_per_currency_unit": money_scale,
        "replay_chip_ticks_per_currency_unit": replay_scale,
        "replay_to_money_scale_factor": factor,
        "source_total_pot_currency": str(source_pot) if source_pot is not None else None,
        "source_rake_currency": str(source_rake) if source_rake is not None else None,
        "source_awards_currency": [str(value) for value in awards],
        "replayed_gross_pot_ticks": replayed_pot_ticks,
        "source_awards_plus_rake_check": award_status,
        "strict_terminal_chip_conservation": True,
        "uncalled_return_ticks_applied_from_strict_replay": unmatched * factor,
        "accounting_status": "verified_against_source" if source_pot is not None else "pending_source_terminal_accounting_not_reported",
    }


def _shown_cards(raw: str, names: list[str], source_hero: str, source_to_phh: dict[str, str],
                 allow_alt_cards: bool = False) -> list[dict[str, Any]]:
    out = []
    for name in names:
        found = _shown_line_pattern(name, allow_alt_cards).search(raw)
        if found:
            out.append({"player": source_to_phh[name], "source_alias": name,
                        "cards": _show_cards_match(found, allow_alt_cards),
                        "source_locator": "raw_source_text:showdown_line"})
    return out


def _mucked_names(raw: str, names: list[str]) -> list[str]:
    return [name for name in names
            if re.search(rf"(?im)^{re.escape(name)}\s+mucks?\b", raw)]


def _full_fact_fingerprint(model: dict[str, Any], events: list[dict[str, Any]], hero_cards: list[str],
                           shown_cards: list[dict[str, Any]], blinds: tuple[Decimal, Decimal]) -> tuple[str, dict[str, Any]]:
    normalized_events = []
    for event in events:
        if event["kind"] == "board":
            normalized_events.append(["board", event["street"], *event["cards"]])
        elif event["kind"] == "action":
            code = {"fold": "f", "call": "cc", "check": "cc", "raise": "cbr"}[event["action"]]
            normalized_events.append(["action", event["street"], event["actor"], code,
                                      event["amount_to"] if code == "cbr" else None])
    facts = {
        "variant": "NT",
        "players_and_stacks": sorted([[name, str(model["stack_by_name"][name])] for name in model["source_order"]], key=lambda row: row[0].casefold()),
        "button_player": model["button_source_name"],
        "small_blind": [model["small_blind_source_name"], str(blinds[0])],
        "big_blind": [model["big_blind_source_name"], str(blinds[1])],
        "hero": [HERO, sorted(hero_cards)],
        "actions_and_board": normalized_events,
        "shown_cards": sorted([[item["player"], *sorted(item["cards"])] for item in shown_cards]),
    }
    return _sha(_canonical_json(facts)), facts


def _eligible_records(sources: list[tuple[str, list[dict[str, Any]]]]) -> tuple[
        list[tuple[str, dict[str, Any]]], dict[str, int], list[dict[str, Any]]]:
    selected = []
    counts: dict[str, int] = {}
    not_selected = []
    for kind, rows in sources:
        for row in rows:
            if kind == "original" and fulltilt._exact_fulltilt_id(row) is not None:
                continue
            counts[f"{kind}_converted_rows"] = counts.get(f"{kind}_converted_rows", 0) + 1
            classification = row.get("classification") or {}
            has_cards = fulltilt._known_hero_cards(row) is not None
            is_conflict = fulltilt._has_source_card_conflict(row)
            is_ante = bool(row.get("requires_dedicated_ante_importer") or row.get("ante_amount"))
            complete = classification.get("complete_candidate") is True
            eligible = (complete and has_cards and not is_conflict and not is_ante
                        and classification.get("candidate_eligible") is not False
                        and not classification.get("partial_source_record"))
            if eligible:
                selected.append((kind, row))
                key = f"{kind}_known_card_complete"
                counts[key] = counts.get(key, 0) + 1
                continue
            if is_conflict:
                reason = "source_card_conflict_excluded"
            elif is_ante:
                reason = "ante_format_requires_dedicated_importer"
            elif classification.get("partial_source_record") or classification.get("partial_source_record") is True:
                reason = "source_record_partial_or_incomplete"
            elif not complete:
                reason = "source_record_not_marked_complete"
            elif not has_cards:
                reason = "source_hero_cards_not_known"
            elif classification.get("candidate_eligible") is False:
                reason = "source_candidate_explicitly_ineligible"
            else:
                reason = "source_record_not_eligible_for_conversion"
            not_selected.append({"source_record_id": row.get("record_id"), "source_set": kind,
                                 "raw_extract_sha256": _text_sha(row.get("raw_source_text", "")),
                                 "status": "partial_or_rejected", "reason": reason})
            counts[f"{kind}_not_attempted"] = counts.get(f"{kind}_not_attempted", 0) + 1
    if "original_known_card_complete" in counts:
        counts["original_converted_known_card_complete_after_conflict_filter"] = counts["original_known_card_complete"]
    return selected, counts, not_selected


def _source_locator(kind: str, record: dict[str, Any]) -> dict[str, Any]:
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    locator = {
        "publisher": source.get("publisher"),
        "thread": source.get("thread"),
        "source_url": source.get("url"),
        "source_record_id": record.get("record_id"),
        "post_number": source.get("post_number"),
        "within_post_ordinal": record.get("source_hand_id") or record.get("hand_id") or 1,
    }
    if kind.startswith("forum_2012_plus") or kind == "plus":
        locator["canonical_source_hand_key"] = record.get("canonical_hand_key")
        locator["publisher_reported_hand_id"] = source.get("publisher_reported_hand_id")
    elif kind == "forum_2009_2011":
        locator["canonical_source_hand_key"] = record.get("canonical_hand_key")
        locator["thread_id"] = source.get("thread_id")
        locator["page_number"] = source.get("page_number")
    return locator


def _convert_one(kind: str, record: dict[str, Any], identity_basis: dict[str, Any],
                 normalized_dir: Path) -> dict[str, Any]:
    classification = record.get("classification")
    if not isinstance(classification, dict) or classification.get("complete_candidate") is not True:
        raise RejectHand("source_record_not_marked_complete")
    if fulltilt._has_source_card_conflict(record):
        raise RejectHand("source_record_card_conflict_excluded")
    if (record.get("requires_dedicated_ante_importer") or record.get("ante_amount")
            or classification.get("partial_source_record")):
        raise RejectHand("ante_or_partial_source_requires_separate_path")
    source_hero, hero_alias, alias_evidence = _hero_name(record, identity_basis)
    source_order, positions, source_stacks, button_name, sb_name, small_blind, big_blind = _seat_facts(record, source_hero)
    source_names = list(source_order)
    source_to_phh = {name: (HERO if name == source_hero else name) for name in source_names}
    if len(set(source_to_phh.values())) != len(source_to_phh):
        raise RejectHand("source_alias_collides_with_another_player_name")
    phh_order = [source_to_phh[name] for name in source_order]
    if HERO not in phh_order:
        raise RejectHand("normalized_hero_name_missing_from_phh_seats")
    hero_cards, opponent_cards = _source_cards(record, source_hero, source_names)
    events = _parse_converted_history(record, source_names)
    _bind_source_action_locators(record, events, source_names)
    shown = _shown_cards(
        record["raw_source_text"], source_names, source_hero, source_to_phh,
        (classification.get("card_alt_text_normalized") is True))
    mucked = _mucked_names(record["raw_source_text"], source_names)
    # A board may only advance flop -> turn -> river, exactly once each.
    street_order = {"flop": 1, "turn": 2, "river": 3}
    seen_streets = []
    for event in events:
        if event["kind"] == "board":
            seen_streets.append(event["street"])
    if seen_streets not in (["flop"], ["flop", "turn"], ["flop", "turn", "river"]):
        raise RejectHand("board_street_order_incomplete_or_ambiguous")
    bb_name = next(name for name, role in positions.items() if role == "BB")
    blinds_vector: list[Decimal] = [Decimal(0)] * len(phh_order)
    if len(phh_order) == 2:
        blinds_vector = [small_blind, big_blind]
    else:
        blinds_vector[phh_order.index(source_to_phh[sb_name])] = small_blind
        blinds_vector[phh_order.index(source_to_phh[bb_name])] = big_blind
    model = {
        "players": phh_order,
        "source_order": source_order,
        "source_to_phh": source_to_phh,
        "position_by_name": positions,
        "stack_by_name": source_stacks,
        "starting_stacks": [source_stacks[name] for name in source_order],
        "antes": [Decimal(0)] * len(source_order),
        "blinds_or_straddles": blinds_vector,
        "min_bet": big_blind,
        "source_hand_key": record.get("canonical_hand_key") or record.get("record_id"),
        "button_source_name": button_name,
        "small_blind_source_name": sb_name,
        "big_blind_source_name": bb_name,
    }
    action_list, phh_doc, replay_events, replay_facts = _encode_and_replay(model, events, hero_cards, shown, mucked)
    fingerprint, source_facts = _full_fact_fingerprint(model, replay_events, hero_cards, shown,
                                                       (small_blind, big_blind))
    fingerprint_id = f"converted-forum:facts:{fingerprint}"
    phh_doc["hand"] = fingerprint_id
    phh_doc["venue"] = "Full Tilt Poker"
    phh_doc["currency_symbol"] = "$"
    normalized_phh = _serialize_phh(phh_doc)
    normalized_dir.mkdir(parents=True, exist_ok=True)
    normalized_name = f"forum_{fingerprint[:20]}.phh"
    (normalized_dir / normalized_name).write_text(normalized_phh, encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="converted-forum-replay-") as temporary:
        test_path = Path(temporary) / normalized_name
        test_path.write_text(normalized_phh, encoding="utf-8")
        decision_rows = ivey.load_decisions(test_path)
        replay_report = copy.deepcopy(ivey.LAST_LOAD_REPORT)
    if replay_report["files_included"] != 1 or replay_report["files_excluded"]:
        raise RejectHand(f"strict_ivey_replay_rejected_normalized_phh:{replay_report['exclusions']}")
    hero_actor = phh_order.index(HERO)
    action_indices = []
    for index, action in enumerate(action_list):
        pieces = action.split()
        if len(pieces) >= 2 and pieces[0] == f"p{hero_actor + 1}" and pieces[1] in {"f", "cc", "cbr"}:
            action_indices.append(index)
    if len(action_indices) != len(decision_rows):
        raise RejectHand("strict_replay_decisions_do_not_match_source_hero_actions")
    terminal = _terminal_facts(record, replay_facts, source_stacks, source_to_phh,
                               source_order, replay_facts["terminal_action"])
    if terminal["accounting_status"] == "pending_source_terminal_accounting_not_reported":
        admission_status = "pending_independent_review_and_terminal_accounting"
    else:
        admission_status = "pending_independent_source_and_conversion_review"
    candidates = []
    facts_by_index = {event["phh_action_index"]: event for event in replay_events if event["kind"] == "action"}
    for index, (action_index, replay_row) in enumerate(zip(action_indices, decision_rows), 1):
        observation = ivey.policy_observation(replay_row["state"])
        # PokerKit's internal four-handed label is UTG for the only seat between
        # blinds and button. Preserve the explicit source role in the review row.
        for history_item in observation["history"]:
            player_match = re.fullmatch(r"p([1-9]\d*)", history_item["player"])
            if player_match:
                source_player = source_order[int(player_match.group(1)) - 1]
                history_item["position"] = _policy_position(positions[source_player])
        observation["position"] = _policy_position(positions[source_order[hero_actor]])
        event = facts_by_index[action_index]
        expected = copy.deepcopy(replay_row["expected"])
        factor = terminal["replay_to_money_scale_factor"]
        if factor != 1:
            for key in ("pot", "to_call", "stack", "current_bet", "min_raise_to", "max_raise_to", "big_blind", "contestable_pot"):
                observation[key] *= factor
            for item in observation["history"]:
                item["amount"] *= factor
                item["added"] *= factor
            if expected.get("action") == "raise":
                expected["amount"] *= factor
        action_identity = {
            "namespace": "converted_forum_source_facts",
            "canonical_hand_id": fingerprint_id,
            "actor": f"p{hero_actor + 1}",
            "action_index": action_index,
            "source_round": event["street"],
            "source_action_ordinal": event["source_action_ordinal"],
            "source_street_action_ordinal": event["street_action_ordinal"],
            "source_action_locator": event["source_locator"],
            "prefix_action_count": action_index,
            "prefix_actions_sha256": _sha(_canonical_json(action_list[:action_index])),
        }
        action_identity["identity"] = (
            f"{fingerprint_id}:p{hero_actor + 1}:action:{action_index}:"
            f"prefix:{action_identity['prefix_actions_sha256']}"
        )
        source_locator = _source_locator(kind, record)
        capture_hash = (record.get("source_capture_sha256")
                        or (record.get("source") or {}).get("raw_extract_sha256"))
        normalizations = [
            {"operation": "converted_forum_text_to_strict_phh_action_stream",
             "details": "Source amounts, position order, board cards, and action prefix were parsed and replayed without filling missing hand facts."},
            {"operation": "source_hero_cards_to_private_predeal",
             "source_alias": hero_alias, "source_cards": hero_cards,
             "details": "Only cards explicitly shown for the source-identified hero are moved to the initial private deal."},
            {"operation": "unknown_opponent_hole_cards_preserved_as_unknown",
             "details": "No opponent hole card is placed in a policy observation."},
        ]
        if classification.get("card_alt_text_normalized") is True:
            normalizations.append({
                "operation": "source_suit_icon_labels_normalized_to_card_codes",
                "details": "Explicit rank and suit labels were converted to standard card codes and cross-checked against the captured board and hero-card fields.",
            })
        row = {
            "decision_id": f"{fingerprint_id}:decision:{index}",
            "hand_id": fingerprint_id,
            "canonical_hand_id": fingerprint_id,
            "source_url": source_locator["source_url"],
            "source_record_id": record.get("record_id"),
            "source_locator": source_locator,
            "raw_extract_sha256": _text_sha(record["raw_source_text"]),
            "source_capture_sha256": capture_hash,
            "full_fact_fingerprint_sha256": fingerprint,
            "strict_action_prefix_identity": action_identity,
            "observations": observation,
            "expected": expected,
            "terminal_facts": copy.deepcopy(terminal),
            "source_alias_identity": copy.deepcopy(alias_evidence),
            "source_shown_cards_at_showdown": copy.deepcopy(shown),
            "normalizations": normalizations,
            "source_evidence": {
                "source_format": record.get("raw_source_text_format") or record.get("source", {}).get("source_hand_format"),
                "source_game_header": record.get("game_header") or record["raw_source_text"].splitlines()[0],
                "source_positions": copy.deepcopy(positions),
                "source_button_player": button_name,
                "source_small_blind": {"player": sb_name, "amount": str(small_blind)},
                "source_big_blind": {"player": model["big_blind_source_name"], "amount": str(big_blind)},
                "source_stacks": {name: str(value) for name, value in source_stacks.items()},
                "source_facts": source_facts,
                "source_action_events": replay_events,
                "source_declared_raw_extract_sha256": (record.get("source") or {}).get("raw_extract_sha256"),
                "source_capture_sha256": capture_hash,
                "normalized_phh_path": normalized_name,
                "normalized_phh_sha256": _text_sha(normalized_phh),
                "replay_engine": "PokerKit 0.7.7 + pokerbot.ivey strict replay",
                "source_terminal_accounting_status": terminal["accounting_status"],
            },
            "admission_status": admission_status,
            "evidence_tier": "converted_forum_history_pending_independent_review",
            "chip_ticks_per_currency_unit": terminal["chip_ticks_per_currency_unit"],
            "inspected_label_no_fresh_holdout_claim": True,
        }
        # Validate exact labels and observations through the existing corpus
        # validator, then keep the pre-action observation and label separate.
        validated = validate_rows([{
            "hand_id": fingerprint_id,
            "canonical_hand_id": fingerprint_id,
            "state": observation,
            "expected": expected,
            "format": "cash_nlhe",
            "source": source_locator["source_url"],
            "evidence_tier": "acquired_history_pending_independent_source_review",
        }])[0]
        row["decision_id"] = validated["decision_id"]
        candidates.append(row)
    return {
        "source_record_id": record.get("record_id"),
        "source_locator": _source_locator(kind, record),
        "raw_extract_sha256": _text_sha(record["raw_source_text"]),
        "full_fact_fingerprint_sha256": fingerprint,
        "canonical_hand_id": fingerprint_id,
        "normalized_phh_path": normalized_name,
        "normalized_phh_sha256": _text_sha(normalized_phh),
        "status": "replayed_pending_independent_review" if candidates else "replayed_no_known_hero_decisions",
        "candidate_decisions": candidates,
        "terminal_facts": terminal,
        "source_facts": source_facts,
        "source_shown_cards_at_showdown": shown,
        "strict_replay_report": replay_report,
    }


def _serialize_phh(document: dict[str, Any]) -> str:
    def toml_value(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, int):
            return str(value)
        if isinstance(value, str):
            return json.dumps(value, ensure_ascii=False)
        if isinstance(value, list):
            return "[" + ", ".join(toml_value(item) for item in value) + "]"
        raise TypeError(f"unsupported PHH value: {type(value).__name__}")
    keys = ("variant", "ante_trimming_status", "antes", "blinds_or_straddles", "min_bet",
            "starting_stacks", "actions", "seats", "players", "currency_symbol", "hand", "venue")
    return "\n".join(f"{key} = {toml_value(document[key])}" for key in keys if key in document) + "\n"


def _original_fact_fingerprints(old_rows: list[dict[str, Any]]) -> tuple[dict[str, str], list[dict[str, str]]]:
    import warnings
    from pokerkit import HandHistory
    fingerprints: dict[str, str] = {}
    failures: list[dict[str, str]] = []
    for row in old_rows:
        hand_id = fulltilt._exact_fulltilt_id(row)
        if hand_id is None:
            continue
        classification = row.get("classification") or {}
        if classification.get("raw_prefix_complete") is False or classification.get("partial_source_record") is True:
            failures.append({"fulltilt_hand_id": hand_id,
                             "reason": "incomplete_original_source_facts_not_comparable"})
            continue
        try:
            # This pass is identity-only. It also fingerprints source-card
            # conflicts that the replay converter correctly rejects.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                histories = list(HandHistory.from_full_tilt_poker(
                    row["raw_source_text"].rstrip() + "\n\n\n",
                    parse_value=lambda value: Decimal(value.replace(",", "")),
                    error_status=True))
                if len(histories) != 1:
                    raise RejectHand("original_fulltilt_history_not_single")
                document = tomllib.loads(histories[0].dumps(), parse_float=Decimal)
            scaled, scale = ivey._scale_chips(document)
            names = document["players"]
            street = "preflop"
            hero_cards = fulltilt._known_hero_cards(row)
            board_cards = []
            events = []
            shown_cards = []
            for encoded in scaled["actions"]:
                pieces = encoded.split()
                if pieces[:2] == ["d", "db"]:
                    packed = pieces[-1]
                    cards = [normalize_card(packed[i:i + 2]) for i in range(0, len(packed), 2)]
                    board_cards.extend(cards)
                    street = {3: "flop", 4: "turn", 5: "river"}.get(len(board_cards), "board")
                    events.append(["board", street, *cards])
                elif len(pieces) >= 2 and pieces[1] in {"f", "cc", "cbr"}:
                    actor = int(pieces[0][1:]) - 1
                    if pieces[1] == "f":
                        kind, amount = "fold", None
                    elif pieces[1] == "cc":
                        kind, amount = "cc", None
                    else:
                        kind, amount = "cbr", str(Decimal(int(pieces[2])) / scale)
                    events.append(["action", street, names[actor], kind, amount])
                elif len(pieces) == 3 and pieces[1] == "sm" and pieces[2] != "????":
                    actor_match = re.fullmatch(r"p([1-9]\d*)", pieces[0])
                    if actor_match:
                        packed = pieces[2]
                        if len(packed) % 2:
                            raise RejectHand("original_malformed_showdown_cards")
                        shown_cards.append([names[int(actor_match.group(1)) - 1], *[
                            normalize_card(packed[i:i + 2]) for i in range(0, len(packed), 2)]])
            seats = row.get("seats") or {}
            active_names = set(names)
            stacks = {}
            seat_numbers = {}
            for seat in seats.values():
                name = seat.get("player")
                if name in active_names:
                    stacks[name] = str(_money(seat.get("starting_stack")))
            for seat_number, seat in seats.items():
                if seat.get("player") in active_names:
                    seat_numbers[seat["player"]] = int(seat_number)
            forced = row.get("forced_bets") or {}
            sb = forced.get("small_blind", {})
            bb = forced.get("big_blind", {})
            button_name = next((name for name, seat_number in seat_numbers.items()
                                if str(seat_number) == str(row.get("button_seat"))), None)
            if not button_name or not sb.get("player") or not bb.get("player"):
                raise RejectHand("original_source_button_or_blind_poster_missing")
            if len(stacks) == 2:
                if sb["player"] != button_name or bb["player"] == button_name:
                    raise RejectHand("original_heads_up_button_and_blind_positions_conflict")
            else:
                if (sb["player"] == bb["player"] or button_name in {sb["player"], bb["player"]}
                        or sb["player"] not in stacks or bb["player"] not in stacks):
                    raise RejectHand("original_source_button_or_blind_posters_conflict")
            normalized_events = []
            for event in events:
                normalized_events.append(event)
            facts = {
                "variant": "NT",
                "players_and_stacks": sorted([[name, value] for name, value in stacks.items()], key=lambda item: item[0].casefold()),
                "button_player": button_name,
                "small_blind": [sb.get("player"), str(_money(sb.get("amount")))],
                "big_blind": [bb.get("player"), str(_money(bb.get("amount")))],
                "hero": [HERO, sorted(hero_cards or [])],
                "actions_and_board": normalized_events,
                "shown_cards": sorted([[shown[0], *sorted(shown[1:])] for shown in shown_cards]),
            }
            fingerprints[hand_id] = _sha(_canonical_json(facts))
        except Exception as exc:
            failures.append({"fulltilt_hand_id": hand_id, "reason": str(exc) or "original_hand_fingerprint_unavailable"})
    return fingerprints, failures


def _repo_label(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def _verify_registered_inputs(mid_input: Path, new_plus_input: Path,
                              registration_path: Path) -> tuple[dict[str, str], str]:
    registration, registration_hash = _load_jsonl(registration_path) if registration_path.suffix == ".jsonl" else (None, None)
    if registration is None:
        raw = registration_path.read_bytes()
        registration = json.loads(raw.decode("utf-8"))
        registration_hash = _sha(raw)
    if not isinstance(registration, dict) or not isinstance(registration.get("batches"), list):
        raise ValueError("registered_input_ledger_invalid")
    entries = {entry.get("path"): entry for entry in registration["batches"]
               if isinstance(entry, dict)}
    verified: dict[str, str] = {}
    for path in (mid_input, new_plus_input):
        label = _repo_label(path)
        expected = REGISTERED_INPUTS.get(label)
        entry = entries.get(label)
        if expected is None or entry is None or entry.get("sha256") != expected:
            raise ValueError(f"registered_input_ledger_hash_mismatch:{label}")
        raw = path.read_bytes()
        actual = _sha(raw)
        if actual != expected:
            raise ValueError(f"registered_input_hash_mismatch:{label}")
        rows, _ = _load_jsonl(path)
        if len(rows) != entry.get("records"):
            raise ValueError(f"registered_input_record_count_mismatch:{label}")
        verified[label] = actual
    return verified, str(registration_hash)


def convert(old_input: Path = OLD_INPUT, mid_input: Path = MID_INPUT,
            plus_input: Path = PLUS_INPUT, new_plus_input: Path = NEW_PLUS_INPUT,
            registration_path: Path = REGISTRATION,
            output_dir: Path = OUTPUT) -> dict[str, Any]:
    old_input, mid_input, plus_input = Path(old_input), Path(mid_input), Path(plus_input)
    new_plus_input, registration_path, output_dir = Path(new_plus_input), Path(registration_path), Path(output_dir)
    old_rows, old_hash = _load_jsonl(old_input)
    mid_rows, mid_hash = _load_jsonl(mid_input)
    plus_rows, plus_hash = _load_jsonl(plus_input)
    new_plus_rows, new_plus_hash = _load_jsonl(new_plus_input)
    registered_hashes, registration_hash = _verify_registered_inputs(mid_input, new_plus_input, registration_path)
    registration_doc = json.loads(registration_path.read_text(encoding="utf-8"))
    registered_batch_counts = {
        entry["path"]: entry.get("counts", {})
        for entry in registration_doc["batches"]
        if entry.get("path") in registered_hashes
    }
    identity_basis = json.loads(IDENTITY_BASIS.read_text(encoding="utf-8"))
    sources = [
        ("original", old_rows),
        ("forum_2009_2011", mid_rows),
        ("forum_2012_plus_2026_11_01", plus_rows),
        ("forum_2012_plus_2026_11_02", new_plus_rows),
    ]
    selected, counts, not_selected = _eligible_records(sources)
    original_fingerprints, original_failures = _original_fact_fingerprints(old_rows)
    normalized_dir = output_dir / "normalized_phh"
    normalized_dir.mkdir(parents=True, exist_ok=True)
    for stale in normalized_dir.glob("forum_[0-9a-f]*.phh"):
        stale.unlink()
    reports = []
    rejections = list(not_selected)
    for kind, record in selected:
        try:
            report = _convert_one(kind, record, identity_basis, normalized_dir)
            report["source_set"] = kind
            if report["full_fact_fingerprint_sha256"] in set(original_fingerprints.values()):
                rejections.append({"source_record_id": record.get("record_id"),
                                   "canonical_hand_id": report["canonical_hand_id"],
                                   "reason": "full_facts_duplicate_an_original_fulltilt_id_history"})
                report["status"] = "duplicate_original_fulltilt_history_excluded"
                report["candidate_decisions"] = []
            reports.append(report)
        except (OSError, ValueError, TypeError, KeyError, IndexError, Warning) as exc:
            rejections.append({"source_record_id": record.get("record_id"), "source_set": kind,
                               "raw_extract_sha256": _text_sha(record.get("raw_source_text", "")),
                               "status": "partial_or_rejected", "reason": str(exc)})
    # Cross-source copies with identical complete facts are collapsed. If the
    # same facts produce different hero labels, remove every copy.
    fact_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for report in reports:
        if report["status"] == "replayed_pending_independent_review":
            fact_groups[report["full_fact_fingerprint_sha256"]].append(report)
    candidate_reports = []
    exact_fact_aliases = 0
    conflicting_facts = 0
    for fingerprint, group in fact_groups.items():
        labels = {_canonical_json(row["expected"]) for report in group for row in report["candidate_decisions"]}
        if len(group) > 1 and len(labels) > 1:
            conflicting_facts += 1
            rejections.append({"full_fact_fingerprint_sha256": fingerprint,
                               "reason": "conflicting_labels_for_identical_complete_hand_facts"})
            continue
        primary = group[0]
        aliases = [row["source_record_id"] for row in group[1:]]
        exact_fact_aliases += len(aliases)
        for candidate in primary["candidate_decisions"]:
            candidate["source_fact_alias_record_ids"] = aliases
        candidate_reports.extend(primary["candidate_decisions"])
    counts.update({
        "original_fulltilt_ids_seen": len(original_fingerprints) + len(original_failures),
        "original_fulltilt_ids_fingerprinted": len(original_fingerprints),
        "original_fulltilt_ids_fingerprint_failures": len(original_failures),
        "converted_histories_attempted": len(selected),
        "converted_histories_strictly_replayed": sum(bool(row.get("strict_replay_report", {}).get("files_included")) for row in reports),
        "converted_histories_rejected_or_partial": len(rejections) - sum(reason.get("reason") == "full_facts_duplicate_an_original_fulltilt_id_history" for reason in rejections),
        "full_fact_duplicate_converted_copies_removed": exact_fact_aliases,
        "conflicting_full_fact_groups_excluded": conflicting_facts,
        "full_fact_duplicates_of_original_ids_excluded": sum(reason.get("reason") == "full_facts_duplicate_an_original_fulltilt_id_history" for reason in rejections),
        "pending_review_hands": len({row["hand_id"] for row in candidate_reports}),
        "pending_review_decisions": len(candidate_reports),
        "newly_admitted_decisions": 0,
    })
    counts["forum_2009_2011_registered_known_card_hero_action_events"] = (
        registered_batch_counts["data/acquisition_resume/2026-11-02/forum_2009_2011/records.jsonl"]
        ["hero_action_events_known_card_source_rows"])
    counts["forum_2012_plus_2026_11_02_registered_known_card_hero_action_events"] = (
        registered_batch_counts["data/acquisition_resume/2026-11-02/forum_2012_plus/rawrecords.jsonl"]
        ["known_card_hero_action_events"])
    try:
        pokerkit_version = importlib.metadata.version("pokerkit")
    except importlib.metadata.PackageNotFoundError:
        pokerkit_version = "unavailable"
    result = {
        "schema_version": 1,
        "converter_version": CONVERTER_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "pending_independent_source_and_conversion_review_no_admissions",
        "input_hashes": {_repo_label(old_input): old_hash,
                         _repo_label(mid_input): mid_hash,
                         _repo_label(plus_input): plus_hash,
                         _repo_label(new_plus_input): new_plus_hash,
                         _repo_label(registration_path): registration_hash,
                         str(IDENTITY_BASIS.relative_to(ROOT)): _sha(IDENTITY_BASIS.read_bytes()),
                         str(IDENTITY_EVIDENCE.relative_to(ROOT)): _sha(IDENTITY_EVIDENCE.read_bytes())},
        "registered_input_hashes": registered_hashes,
        "registered_batch_counts": registered_batch_counts,
        "replay_engine": {"name": "PokerKit Full Tilt action semantics + pokerbot.ivey strict PHH replay",
                          "pokerkit_version": pokerkit_version},
        "counts": counts,
        "source_identity_policy": "Publisher URL/thread/post/ordinal and complete fact fingerprints are used; missing Full Tilt game IDs stay missing.",
        "original_fulltilt_fingerprint_failures": original_failures,
        "hand_reports": reports,
        "rejections": rejections,
        "records": candidate_reports,
        "limitations": [
            "All converted source decisions were inspected during acquisition/conversion and are development-only; this batch makes no fresh heldout claim.",
            "All rows remain pending independent source and conversion review; no rows were admitted.",
            "Unknown or source-unshown hole cards remain unknown; incomplete, ambiguous, unsupported, and ante-format rows are excluded.",
            "The alias Polarizing is mapped to Phil Ivey only through the recorded publisher-reported identity evidence.",
        ],
    }
    (output_dir / "review_candidates.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    (output_dir / "manifest.json").write_text(json.dumps({
        "schema_version": 1, "converter_version": CONVERTER_VERSION,
        "review_candidates": "review_candidates.json", "normalized_phh_directory": "normalized_phh",
        "input_hashes": result["input_hashes"], "replay_engine": result["replay_engine"],
        "counts": counts, "status": result["status"],
    }, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-input", type=Path, default=OLD_INPUT)
    parser.add_argument("--mid-input", type=Path, default=MID_INPUT)
    parser.add_argument("--plus-input", type=Path, default=PLUS_INPUT)
    parser.add_argument("--new-plus-input", type=Path, default=NEW_PLUS_INPUT)
    parser.add_argument("--registration", type=Path, default=REGISTRATION)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    args = parser.parse_args()
    result = convert(args.old_input, args.mid_input, args.plus_input,
                     args.new_plus_input, args.registration, args.output_dir)
    print(json.dumps(result["counts"], sort_keys=True))


if __name__ == "__main__":
    main()
