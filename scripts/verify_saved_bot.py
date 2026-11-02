#!/usr/bin/env python3
"""Verify the saved checkpoint and its recorded source-group comparison."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pokerbot.corpus import load_split, validate_rows
from pokerbot.ivey import compare_decisions
from pokerbot.saved_bot import _resource, load_bot
from pokerbot import expert_ranges, postflop_policy
from scripts.acquisition_admissions import verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    manifest = json.loads(_resource("ivey-transfer-v1-manifest.json"))
    load_bot()  # Validate checksums and prime the packaged equity table.
    checkpoint = json.loads(_resource("ivey-transfer-v1.json"))
    ledger = verify()
    if ledger["current_record_hash_set_sha256"] != manifest["ivey_corpus_record_hash_set_sha256"]:
        raise ValueError("admitted corpus differs from the saved checkpoint")
    rows = load_split(ROOT / "data/corpus_splits/development-after-prospective-v1.json")["records"]
    for path in sorted((ROOT / "data/acquisition_resume/2026-11-01/admissions").glob("batch-*.json")):
        rows.extend(validate_rows(json.loads(path.read_text())["records"]))
    groups = sorted({row["group_id"] for row in rows})
    predictions = {}
    group_matches = []
    for group in groups:
        train = [row for row in rows if row["group_id"] != group]
        test = [row for row in rows if row["group_id"] == group]
        train_hands = {row.get("canonical_hand_id", row["hand_id"]) for row in train}
        test_hands = {row.get("canonical_hand_id", row["hand_id"]) for row in test}
        if train_hands & test_hands:
            raise ValueError("canonical hand crosses the held-out source group")
        overlay = postflop_policy.fit_model(
            train, include_development=True,
            regularization=manifest["training_recipe"]["postflop_regularization"])
        for row in test:
            predictions[row["decision_id"]] = (
                postflop_policy.decide(row["state"], overlay) if row["state"]["board"]
                else expert_ranges.decide(row["state"], checkpoint["external_preflop"]))
        group_matches.append(sum(predictions[row["decision_id"]]["action"] == row["expected"]["action"]
                                 for row in test) / len(test))
    ordered = iter([predictions[row["decision_id"]] for row in rows])
    score = compare_decisions(rows, lambda _: next(ordered))
    for field in ("sample_count", "action_agreement_count", "exact_action_and_size_agreement_count", "illegal_prediction_count"):
        if score[field] != manifest["evaluation"][field]:
            raise ValueError(f"saved checkpoint comparison changed: {field}")
    result = {
        "checkpoint": "ivey-transfer-v1", "verified": True,
        "decisions": score["sample_count"], "source_groups": len(groups),
        "action_matches": score["action_agreement_count"], "action_agreement": score["action_agreement"],
        "illegal_predictions": score["illegal_prediction_count"],
        "macro_source_group_action_agreement": sum(group_matches) / len(group_matches),
        "scope": "inspected development groups held out from each fold's fitting",
        "fresh_holdout": False,
    }
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(text)
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
