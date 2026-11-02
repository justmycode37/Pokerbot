"""Deduplicate public Triton source hands and count known-card Ivey actions.

These are acquisition counts. Accounting validity does not automatically admit
comparison observations or assert complete chronological broadcast coverage.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from acquisition_triton_fetch import HERO_ID
from verify_triton_semantics import inspect_hand

DELIBERATE = {"fold", "check", "call", "bet", "raise", "all_in"}


def hand_documents(value):
    if isinstance(value, dict):
        if all(key in value for key in ("handId", "players", "rounds", "pokerVariant")):
            yield value
        else:
            for nested in value.values():
                yield from hand_documents(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from hand_documents(nested)


def _facts(hand, *, include_cards=True):
    result = {k: hand.get(k) for k in ("handId", "gameId", "dealerSeatNo", "startTimestamp",
                                        "endTimestamp", "pokerVariant", "blindLevel", "rounds", "pots")}
    result["players"] = [{k: player.get(k) for k in
                           ("userId", "seatNo", "startChips", "endChips", "pocketCards")
                           if include_cards or k != "pocketCards"} for player in hand["players"]]
    return result


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def known_cards(hand):
    hero = next((p for p in hand["players"] if p.get("userId") == HERO_ID), None)
    if hero is None:
        return False
    cards = hero.get("pocketCards", [])
    return len(cards) == 2 and len(set(cards)) == 2 and all(
        re.fullmatch(r"CARD_[2-9TJQKA][CDHS]", str(card)) for card in cards)


def tally(inputs, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    hands, origins, conflicting, errors = {}, {}, set(), []
    copies = 0
    paths = sorted({p for root in inputs for p in Path(root).rglob("*")
                    if p.is_file() and p.suffix in {".json", ".jsonl"}
                    and not p.name.endswith((".request.json", "-request.json", ".error.json"))})
    for path in paths:
        try:
            text = path.read_text()
            documents = [json.loads(line) for line in text.splitlines() if line.strip()] if path.suffix == ".jsonl" else [json.loads(text)]
            for document in documents:
                for hand in hand_documents(document):
                    if not any(p.get("userId") == HERO_ID for p in hand["players"]):
                        continue
                    identity = hand["handId"]
                    origins.setdefault(identity, set()).add(str(path))
                    if identity in hands:
                        copies += 1
                        prior = hands[identity]
                        if _hash(_facts(prior, include_cards=False)) != _hash(_facts(hand, include_cards=False)):
                            conflicting.add(identity)
                        prior_cards = next(p for p in prior["players"] if p.get("userId") == HERO_ID).get("pocketCards", [])
                        new_cards = next(p for p in hand["players"] if p.get("userId") == HERO_ID).get("pocketCards", [])
                        if prior_cards and new_cards and prior_cards != new_cards:
                            conflicting.add(identity)
                        if not known_cards(prior) and known_cards(hand):
                            hands[identity] = hand  # retain an entire source, never splice state fields
                    else:
                        hands[identity] = hand
        except (OSError, ValueError, TypeError, KeyError) as exc:
            errors.append({"source_file": str(path), "reason": str(exc)})
    counts = Counter()
    counts["unique_ivey_hands_all_variants"] = len(hands)
    counts["duplicate_hand_copies_removed"] = copies
    counts["conflicting_hand_ids_excluded"] = len(conflicting)
    inspections = []
    known_rows, partial_rows = [], []
    for identity, hand in sorted(hands.items()):
        if identity in conflicting:
            continue
        if hand["pokerVariant"] != "texas":
            counts["non_texas_hands_excluded"] += 1
            continue
        counts["unique_texas_ivey_hands"] += 1
        actions = sum(action.get("userId") == HERO_ID and action.get("type") in DELIBERATE
                      for round_ in hand["rounds"] for action in round_["actions"])
        counts["raw_texas_ivey_deliberate_actions"] += actions
        try:
            inspection = inspect_hand(hand)
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            inspection = {"hand_id": identity, "accounting_and_prefix_price_checks_pass": False,
                          "problems": [{"reason": str(exc)}]}
        inspections.append(inspection)
        wrapped = {"hand": hand, "source_paths": sorted(origins[identity]),
                   "source_hand_sha256": _hash(hand),
                   "accounting_valid": inspection["accounting_and_prefix_price_checks_pass"],
                   "admission_status": "pending_converter_and_independent_review"}
        if known_cards(hand):
            counts["known_card_texas_ivey_hands"] += 1
            counts["known_card_texas_ivey_actions"] += actions
            if wrapped["accounting_valid"]:
                counts["accounting_valid_known_card_actions"] += actions
                counts["accounting_valid_known_card_hands"] += 1
            known_rows.append(wrapped)
        else:
            counts["unknown_card_texas_ivey_hands"] += 1
            counts["unknown_card_texas_ivey_actions"] += actions
            partial_rows.append(wrapped)
    for name, rows in (("known-card-hands.jsonl", known_rows), ("unknown-card-hands.jsonl", partial_rows)):
        with (output / name).open("w") as stream:
            for row in rows:
                stream.write(json.dumps(row, sort_keys=True) + "\n")
    result = {"schema_version": 1, "counts": dict(counts), "newly_admitted_comparison_decisions": 0,
              "inputs": [str(p) for p in inputs], "source_files_examined": len(paths),
              "conflicting_hand_ids": sorted(conflicting), "read_errors": errors,
              "accounting_checks": inspections,
              "limitations": ["Public hand numbers may be sparse; no complete session coverage is asserted.",
                              "Known-card action counts are source labels, not yet admitted observations.",
                              "Unknown cards never become invented decision inputs."]}
    (output / "summary.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = tally(args.inputs, args.output)
    print(json.dumps(result["counts"], sort_keys=True))
