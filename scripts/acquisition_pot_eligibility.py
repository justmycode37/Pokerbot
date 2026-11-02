#!/usr/bin/env python3
"""Derive Triton decision pots from the exact prior action prefix.

This module is deliberately independent of PokerKit and the converter. It
reads only the hand identity/variant, player IDs and starting stacks, and the
strictly prior ordered actions needed to reconstruct a decision. It never
reads cards, board state, terminal pots, winners, or ending stacks.

The returned ``pot`` includes every prior payment. Antes are reported as dead
common money and are not included in the live contribution tiers used for
side-pot matching. ``to_call`` is clipped to the hero's remaining stack, as
the simulation observation is. The independent evidence ledger is intended
for an engine cross-check by the converter integration.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import uuid
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
HERO_UUID = "3970ce21-3d14-4bdc-97ca-98df8220d040"
DEAD_FORCED = frozenset({"ante", "small_ante", "big_ante"})
LIVE_FORCED = frozenset({"small_blind", "big_blind", "straddle"})
BETTING = frozenset({"raise", "call", "bet", "all_in", "check", "fold"})
STREETS = ("pre_flop", "flop", "turn", "river")
SOURCE_DECISION_RE = re.compile(r"^triton:([0-9a-fA-F-]+):action:(0|[1-9][0-9]*)$")


class PrefixPotError(ValueError):
    """The requested decision prefix is malformed or unsupported."""


def _chips(value: Any, label: str, *, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0):
        raise PrefixPotError(f"invalid_{label}")
    return value


def _street_name(value: Any, index: int) -> str:
    if not isinstance(value, str):
        raise PrefixPotError("missing_round_name")
    normalized = value.lower().replace("preflop", "pre_flop")
    if index >= len(STREETS) or normalized != STREETS[index]:
        raise PrefixPotError("nonsequential_or_unsupported_round")
    return normalized


def _prefix_target(
    hand: dict[str, Any], ordinal: int, hero_id: str
) -> tuple[list[tuple[int, str, dict[str, Any]]], int, int, str, dict[str, Any]]:
    """Collect actions before ordinal and locate its hero decision.

    Iteration stops as soon as the target is found. In particular, no action
    content or round metadata after the target is examined.
    """
    rounds = hand.get("rounds")
    if not isinstance(rounds, list) or not rounds:
        raise PrefixPotError("missing_or_invalid_rounds")
    prefix: list[tuple[int, str, dict[str, Any]]] = []
    flat = 0
    for round_index, round_row in enumerate(rounds):
        if not isinstance(round_row, dict):
            raise PrefixPotError("invalid_round_record_in_prefix")
        street = _street_name(round_row.get("name"), round_index)
        actions = round_row.get("actions")
        if not isinstance(actions, list):
            raise PrefixPotError("missing_or_invalid_action_list_in_prefix")
        for action_index, action in enumerate(actions):
            if flat == ordinal:
                if not isinstance(action, dict):
                    raise PrefixPotError("invalid_target_action")
                if action.get("userId") != hero_id or action.get("type") not in BETTING:
                    raise PrefixPotError("target_is_not_hero_betting_decision")
                return prefix, round_index, action_index, street, action
            if not isinstance(action, dict):
                raise PrefixPotError("invalid_action_record_in_prefix")
            prefix.append((round_index, street, action))
            flat += 1
    raise PrefixPotError("target_action_ordinal_out_of_range")


def inspect_prefix_pot(
    hand: dict[str, Any], action_ordinal: int, *, hero_id: str = HERO_UUID
) -> dict[str, Any]:
    """Derive pot, clipped call amount, and contestable pot before a decision.

    ``action_ordinal`` is the original flattened action index across rounds.
    The target must be a hero betting decision; its type and amount are not
    used to derive any numeric result. Only its actor/type and original
    position are read to bind the evidence to the canonical decision key.

    Raises :class:`PrefixPotError` for malformed, incomplete, unsupported,
    or ambiguous prefixes. The converter should retain its existing raw
    validation and cross-check this result against the frozen engine before
    serializing an observation.
    """
    if not isinstance(hand, dict):
        raise PrefixPotError("hand_is_not_an_object")
    if hand.get("pokerVariant") != "texas":
        raise PrefixPotError("unsupported_or_non_texas_variant")
    if type(action_ordinal) is not int or action_ordinal < 0:
        raise PrefixPotError("invalid_target_action_ordinal")
    if not isinstance(hero_id, str) or not hero_id:
        raise PrefixPotError("invalid_hero_uuid")
    hand_id = hand.get("handId")
    if not isinstance(hand_id, str) or not hand_id.strip():
        raise PrefixPotError("missing_hand_uuid")
    hand_id = hand_id.strip()
    try:
        uuid.UUID(hand_id)
    except ValueError as exc:
        raise PrefixPotError("invalid_hand_uuid") from exc

    raw_players = hand.get("players")
    if not isinstance(raw_players, list) or not 2 <= len(raw_players) <= 9:
        raise PrefixPotError("unsupported_actual_player_count")
    starting: dict[str, int] = {}
    for row in raw_players:
        if not isinstance(row, dict):
            raise PrefixPotError("invalid_player_record")
        user_id = row.get("userId")
        if not isinstance(user_id, str) or not user_id or user_id in starting:
            raise PrefixPotError("missing_or_duplicate_player_uuid")
        starting[user_id] = _chips(row.get("startChips"), "starting_stack")
    if hero_id not in starting:
        raise PrefixPotError("hero_uuid_not_in_players")

    prefix, round_index, round_action_index, target_street, target = _prefix_target(
        hand, action_ordinal, hero_id)
    del target  # The current action amount/type never influences prior state.

    remaining = dict(starting)
    live_contributions = dict.fromkeys(starting, 0)
    dead_ante_by_player = dict.fromkeys(starting, 0)
    folded: set[str] = set()
    street_commitments = dict.fromkeys(starting, 0)
    current_street: str | None = None
    max_live_commitment = 0
    dead_antes = 0
    pot = 0
    betting_started = False
    live_forced_sequence: list[str] = []
    live_forced_actors: set[str] = set()
    small_blind_actor: str | None = None
    big_blind_actor: str | None = None

    for _, street, action in prefix:
        if street != current_street:
            current_street = street
            street_commitments = dict.fromkeys(starting, 0)
            max_live_commitment = 0
        kind = action.get("type")
        actor = action.get("userId")
        if kind not in DEAD_FORCED | LIVE_FORCED | BETTING:
            raise PrefixPotError("unknown_action_type_in_prefix")
        if actor not in starting:
            raise PrefixPotError("unknown_action_actor_in_prefix")
        if actor in folded:
            raise PrefixPotError("action_after_player_fold")

        if kind in DEAD_FORCED | LIVE_FORCED:
            if street != "pre_flop" or betting_started:
                raise PrefixPotError("forced_bet_outside_preflop_prefix")
            amount = _chips(action.get("amount"), "forced_action_amount", positive=True)
            if amount > remaining[actor]:
                raise PrefixPotError("forced_bet_exceeds_remaining_stack")
            if kind in DEAD_FORCED:
                remaining[actor] -= amount
                dead_ante_by_player[actor] += amount
                dead_antes += amount
                pot += amount
                continue

            if actor in live_forced_actors:
                raise PrefixPotError("multiple_live_forced_bets_by_player")
            expected_kind = ("small_blind" if not live_forced_sequence else
                             "big_blind" if len(live_forced_sequence) == 1 else "straddle")
            if kind != expected_kind:
                raise PrefixPotError("unsupported_live_forced_bet_order")
            if kind == "small_blind":
                small_blind_actor = actor
            elif kind == "big_blind":
                if amount < max_live_commitment:
                    raise PrefixPotError("big_blind_below_small_blind")
                big_blind_actor = actor
            elif kind == "straddle" and amount <= max_live_commitment:
                raise PrefixPotError("straddle_does_not_increase_live_price")
            live_forced_sequence.append(kind)
            live_forced_actors.add(actor)
            remaining[actor] -= amount
            live_contributions[actor] += amount
            street_commitments[actor] += amount
            max_live_commitment = max(max_live_commitment, street_commitments[actor])
            pot += amount
            continue

        betting_started = True
        if remaining[actor] <= 0:
            raise PrefixPotError("action_by_empty_stack")
        amount_value = action.get("amount")
        if kind in {"check", "fold"}:
            if "amount" in action:
                raise PrefixPotError("unexpected_amount_on_check_or_fold")
            amount = 0
        else:
            amount = _chips(amount_value, "action_amount", positive=True)
            if amount > remaining[actor]:
                raise PrefixPotError("action_exceeds_remaining_stack")

        due = max(0, max_live_commitment - street_commitments[actor])
        if kind == "check" and due:
            raise PrefixPotError("check_faces_live_wager")
        if kind == "call" and (due <= 0 or amount != min(due, remaining[actor])):
            raise PrefixPotError("call_amount_differs_from_clipped_price")
        if kind == "all_in" and amount != remaining[actor]:
            raise PrefixPotError("all_in_does_not_exhaust_remaining_stack")
        if kind == "bet" and max_live_commitment != 0:
            raise PrefixPotError("bet_faces_existing_live_wager")
        target_commitment = street_commitments[actor] + amount
        if kind == "raise" and target_commitment <= max_live_commitment:
            raise PrefixPotError("raise_does_not_increase_live_wager")
        if kind == "fold":
            folded.add(actor)
            continue
        if amount:
            remaining[actor] -= amount
            live_contributions[actor] += amount
            street_commitments[actor] += amount
            if target_commitment > max_live_commitment:
                max_live_commitment = target_commitment
            pot += amount

    if small_blind_actor is None or big_blind_actor is None:
        raise PrefixPotError("explicit_small_and_big_blind_actors_required_before_decision")
    if small_blind_actor == big_blind_actor:
        raise PrefixPotError("small_and_big_blind_actor_collision")
    if current_street != target_street:
        current_street = target_street
        street_commitments = dict.fromkeys(starting, 0)
        max_live_commitment = 0
    if hero_id in folded:
        raise PrefixPotError("hero_folded_before_target_decision")
    if remaining[hero_id] <= 0:
        raise PrefixPotError("hero_has_no_stack_for_target_decision")

    active_opponents = [player for player in starting if player != hero_id and player not in folded]
    if not active_opponents:
        raise PrefixPotError("no_live_opponent_at_target_decision")
    call_amount_due = max(0, max_live_commitment - street_commitments[hero_id])
    to_call = min(call_amount_due, remaining[hero_id])
    hero_reach_limit = live_contributions[hero_id] + to_call
    opponent_reach_limits = {
        player: live_contributions[player] + remaining[player]
        for player in active_opponents
    }

    tiers: list[dict[str, Any]] = []
    contestable_live_tiers = 0
    boundaries = set(live_contributions.values())
    boundaries.add(hero_reach_limit)
    boundaries.update(opponent_reach_limits.values())
    previous = 0
    for level in sorted(value for value in boundaries if value > 0):
        contributor_ids = [player for player, value in live_contributions.items()
                           if value >= level]
        layer_amount = (level - previous) * len(contributor_ids)
        hero_reaches = hero_reach_limit >= level
        reachable_opponents = [player for player, limit in opponent_reach_limits.items()
                               if limit >= level]
        counted = hero_reaches and bool(reachable_opponents)
        if counted:
            contestable_live_tiers += layer_amount
        tiers.append({
            "from_level": previous,
            "to_level": level,
            "contributor_ids_including_folded": contributor_ids,
            "layer_amount": layer_amount,
            "hero_can_reach": hero_reaches,
            "opponents_that_can_reach": reachable_opponents,
            "counted": counted,
        })
        previous = level

    contestable_pot = dead_antes + contestable_live_tiers
    if contestable_pot > pot:
        raise PrefixPotError("derived_contestable_pot_exceeds_prefix_pot")

    source_decision_id = f"triton:{hand_id}:action:{action_ordinal}"
    stable_key = (f"triton:{hand_id}:round:{round_index}:"
                  f"action:{round_action_index}")
    return {
        "hand_id": f"triton:{hand_id}",
        "source_action_index": action_ordinal,
        "source_round_index": round_index,
        "source_round_action_index": round_action_index,
        "source_decision_id": source_decision_id,
        "stable_source_decision_key": stable_key,
        "pot": pot,
        "call_amount_due": call_amount_due,
        "to_call": to_call,
        "contestable_pot": contestable_pot,
        "dead_antes": dead_antes,
        "dead_ante_contributions": dead_ante_by_player,
        "live_contributions": live_contributions,
        "street_commitments": street_commitments,
        "max_live_commitment": max_live_commitment,
        "evidence": {
            "prefix_action_count": action_ordinal,
            "target_street": target_street,
            "starting_stacks": starting,
            "remaining_stacks": remaining,
            "folded_players": sorted(folded),
            "active_opponents": active_opponents,
            "hero_reach_limit": hero_reach_limit,
            "opponent_reach_limits": opponent_reach_limits,
            "contestable_live_tiers": contestable_live_tiers,
            "tiers": tiers,
            "derivation": "dead_antes_plus_reachable_live_contribution_tiers",
        },
    }


def _hand_from_document(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        data = value.get("data")
        if isinstance(data, dict) and isinstance(data.get("handV2"), dict):
            return data["handV2"]
        if "handId" in value:
            return value
    raise PrefixPotError("raw_document_does_not_contain_hand")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_capture(root: Path, batch: str, hand_uuid: str) -> Path:
    raw_root = root / "data" / "acquisition_resume" / "2026-11-01" / f"triton_{batch}" / "raw"
    matches = sorted(raw_root.rglob(f"{hand_uuid}.json")) if raw_root.is_dir() else []
    if len(matches) != 1:
        raise PrefixPotError(f"expected_one_{batch}_raw_capture_for_{hand_uuid}_got_{len(matches)}")
    return matches[0]


def reproduce_ante_diagnostic(
    diagnostic_path: Path, *, root: Path = ROOT
) -> dict[str, Any]:
    """Recompute every canonical row in the saved 50-row ante diagnostic."""
    diagnostic_bytes = diagnostic_path.read_bytes()
    diagnostic = json.loads(diagnostic_bytes.decode("utf-8-sig"))
    rows = diagnostic.get("all_checked_rows")
    if not isinstance(rows, list) or not rows:
        raise PrefixPotError("diagnostic_has_no_checked_rows")
    if type(diagnostic.get("checked")) is not int or diagnostic["checked"] != len(rows):
        raise PrefixPotError("diagnostic_checked_count_mismatch")
    by_id = {row.get("source_decision_id"): row for row in diagnostic.get("rows_needing_correction", [])
             if isinstance(row, dict)}
    output_rows: list[dict[str, Any]] = []
    raw_hashes: dict[str, str] = {}
    mismatch_counts: Counter[str] = Counter()
    all_ids: set[str] = set()
    all_hands: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise PrefixPotError("invalid_diagnostic_row")
        source_decision_id = row.get("source_decision_id")
        matched = SOURCE_DECISION_RE.fullmatch(source_decision_id or "")
        batch = row.get("batch")
        if matched is None or batch not in {"2025", "2026"}:
            raise PrefixPotError("unsupported_diagnostic_identity")
        hand_uuid, ordinal_text = matched.groups()
        ordinal = int(ordinal_text)
        if hand_uuid != source_decision_id.split(":")[1]:
            raise PrefixPotError("noncanonical_source_decision_id")
        capture = _source_capture(root, batch, hand_uuid)
        capture_bytes = capture.read_bytes()
        capture_hash = _sha256(capture_bytes)
        raw_hashes[str(capture.relative_to(root))] = capture_hash
        document = json.loads(capture_bytes.decode("utf-8-sig"))
        hand = _hand_from_document(document)
        result = inspect_prefix_pot(hand, ordinal)
        if result["source_decision_id"] != source_decision_id:
            raise PrefixPotError("canonical_source_decision_id_mismatch")
        expected = _chips(row.get("expected_from_live_tiers_plus_dead_antes"), "diagnostic_expected")
        old_value = _chips(row.get("old_contestable_pot"), "diagnostic_old_contestable_pot")
        source_pot = _chips(row.get("source_prefix_pot"), "diagnostic_source_prefix_pot")
        diagnostic_pot = _chips(row.get("pot"), "diagnostic_pot")
        if result["pot"] != source_pot or result["pot"] != diagnostic_pot:
            raise PrefixPotError(f"source_prefix_pot_mismatch:{source_decision_id}")
        if result["contestable_pot"] != expected:
            raise PrefixPotError(f"expected_contestable_pot_mismatch:{source_decision_id}")
        old_mismatch = result["contestable_pot"] != old_value
        if old_mismatch:
            mismatch_counts[batch] += 1
        if (source_decision_id in by_id) != old_mismatch:
            raise PrefixPotError(f"correction_membership_mismatch:{source_decision_id}")
        all_ids.add(source_decision_id)
        all_hands.add(result["hand_id"])
        output_rows.append({
            "batch": batch,
            "source_capture_path": str(capture.relative_to(root)),
            "source_capture_sha256": capture_hash,
            "source_decision_id": result["source_decision_id"],
            "stable_source_decision_key": result["stable_source_decision_key"],
            "source_round_index": result["source_round_index"],
            "source_round_action_index": result["source_round_action_index"],
            "source_action_index": result["source_action_index"],
            "pot": result["pot"],
            "call_amount_due": result["call_amount_due"],
            "to_call": result["to_call"],
            "dead_antes": result["dead_antes"],
            "live_contributions": result["live_contributions"],
            "contestable_pot": result["contestable_pot"],
            "previous_contestable_pot": old_value,
            "corrected_value_differs_from_previous": old_mismatch,
            "diagnostic_expected_contestable_pot": expected,
        })
    expected_ids = {row.get("source_decision_id") for row in diagnostic.get("rows_needing_correction", [])
                    if isinstance(row, dict)}
    actual_ids = {row["source_decision_id"] for row in output_rows
                  if row["corrected_value_differs_from_previous"]}
    if actual_ids != expected_ids:
        raise PrefixPotError("diagnostic_correction_row_set_mismatch")
    if len(all_ids) != len(output_rows):
        raise PrefixPotError("duplicate_canonical_source_decision_id")

    ledger_path = root / "data/acquisition_resume/2026-11-01/admissions/batch-001.json"
    ledger_bytes = ledger_path.read_bytes()
    ledger = json.loads(ledger_bytes.decode("utf-8-sig"))
    admission_hashes: dict[str, str] = {}
    records: list[dict[str, Any]] = []
    held_ids: set[str] = set()
    source_keys: set[str] = set()
    for path in sorted(ledger_path.parent.glob("batch-*.json")):
        raw = path.read_bytes()
        batch = json.loads(raw.decode("utf-8-sig"))
        batch_records = batch.get("records")
        if not isinstance(batch_records, list):
            raise PrefixPotError("admission_ledger_records_missing")
        admission_hashes[str(path.relative_to(root))] = _sha256(raw)
        held_ids.update(batch.get("held_source_decision_ids", []))
        for record in batch_records:
            key = record.get("stable_source_decision_key", record.get("decision_id"))
            if not isinstance(key, str) or key in source_keys:
                raise PrefixPotError("duplicate_or_missing_admission_source_key")
            source_keys.add(key)
            records.append(record)
    held_ids.difference_update(record.get("source_decision_id") for record in records)
    known_card_records = sum(
        isinstance((record.get("state") or {}).get("hole_cards"), list)
        and len(record["state"]["hole_cards"]) == 2
        for record in records if isinstance(record, dict)
    )
    partial_inspection_records = sum(
        record.get("inspection_status") != "inspected"
        for record in records if isinstance(record, dict)
    )
    split_path = root / ledger["baseline_manifest"]
    baseline = json.loads(split_path.read_text(encoding="utf-8-sig"))
    module_path = Path(__file__).resolve()
    report = {
        "schema_version": 1,
        "status": "reproduced_source_prefix_diff_read_only_development_only",
        "diagnostic_path": str(diagnostic_path.resolve()),
        "source_code_path": str(module_path),
        "source_code_sha256": _sha256(module_path.read_bytes()),
        "input_sha256": {
            str(diagnostic_path.resolve()): _sha256(diagnostic_bytes),
            **admission_hashes,
            str(split_path.relative_to(root)): _sha256(split_path.read_bytes()),
        },
        "counts": {
            "diagnostic_decision_rows": len(output_rows),
            "canonical_hands_by_hand_uuid": len(all_hands),
            "exact_canonical_decision_keys": len(all_ids),
            "corrected_values_differing_from_old": sum(mismatch_counts.values()),
            "corrected_2025_values_differing_from_old": mismatch_counts["2025"],
            "corrected_2026_values_differing_from_old": mismatch_counts["2026"],
            "unchanged_values": len(output_rows) - sum(mismatch_counts.values()),
            "pending_ante_correction_rows_in_existing_ledger": len(held_ids),
            "existing_frozen_baseline_decisions": len(baseline["records"]),
            "existing_total_usable_decisions": len(baseline["records"]) + len(records),
            "existing_new_admitted_decisions": len(records),
            "existing_new_admitted_known_card_decisions": known_card_records,
            "existing_new_admitted_unknown_or_partial_card_decisions": len(records) - known_card_records,
            "existing_new_admitted_partial_inspection_records": partial_inspection_records,
            "helper_partial_rows_created": 0,
            "admission_changes": 0,
            "fresh_holdout_rows": 0,
        },
        "source_capture_sha256_by_path": raw_hashes,
        "rows": output_rows,
        "limitations": [
            "This audit recomputes prefix pot eligibility only; it does not correct or admit rows.",
            "The helper does not inspect cards. Known-card counts above are read from the unchanged existing admission ledger only.",
            "Hand aliases and episode metadata are not counted as decisions or hands.",
            "Existing new examples remain development-only, not fresh holdout data.",
        ],
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-ante-diagnostic", type=Path,
                        help="recompute a saved all_checked_rows diagnostic")
    parser.add_argument("--output", type=Path,
                        help="write reproducible verification JSON at this path")
    args = parser.parse_args(argv)
    if args.verify_ante_diagnostic is None:
        parser.error("--verify-ante-diagnostic is required for command-line use")
    report = reproduce_ante_diagnostic(args.verify_ante_diagnostic.resolve())
    if args.output is None:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                               encoding="utf-8")
        print(args.output.resolve())
    counts = report["counts"]
    if (counts["diagnostic_decision_rows"] != 50
            or counts["corrected_values_differing_from_old"] != 21
            or counts["corrected_2025_values_differing_from_old"] != 2
            or counts["corrected_2026_values_differing_from_old"] != 19):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised as a CLI separately
    raise SystemExit(main())
