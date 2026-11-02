#!/usr/bin/env python3
"""Verify the reviewed development ledger without fitting or scoring a policy."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pokerbot.corpus import _digest, load_split, validate_rows


def verify(root: Path = ROOT) -> dict:
    baseline = root / "data/corpus_splits/development-after-prospective-v1.json"
    records = load_split(baseline)["records"]
    frozen_count = len(records)
    batches = sorted((root / "data/acquisition_resume/2026-11-01/admissions").glob("batch-*.json"))
    source_keys = {row.get("stable_source_decision_key") for row in records}
    source_keys.discard(None)
    checked_files = {}
    batch_counts = {}
    legacy_aggregate_hash_mismatches = []
    for path in batches:
        batch = json.loads(path.read_text())
        clean = validate_rows(batch["records"])
        if any(row["record_hash"] != verified["record_hash"]
               for row, verified in zip(batch["records"], clean)):
            raise ValueError(f"record hash changed: {path.name}")
        actual_dataset_hash = _digest(sorted(row["record_hash"] for row in clean))
        if batch.get("dataset_hash") and batch["dataset_hash"] != actual_dataset_hash:
            # Batch 001 predates the explicit batch-local hash convention.
            # Preserve its immutable bytes; validate each row and report the
            # stale aggregate separately from the current verified ledger.
            if (path.name != "batch-001.json" or batch["dataset_hash"] !=
                    "0fb1783be6d45081a820a97ba1a1c4df98a5034c5422a956ce552cb191cb6c96"):
                raise ValueError(f"batch dataset hash changed: {path.name}")
            legacy_aggregate_hash_mismatches.append({
                "batch": path.name, "recorded": batch["dataset_hash"],
                "verified_batch_record_hashes": actual_dataset_hash})
        for row in clean:
            key = row["stable_source_decision_key"]
            if key in source_keys:
                raise ValueError(f"duplicate source decision: {key}")
            source_keys.add(key)
            if (row.get("fresh_holdout") is not False
                    or row.get("policy_use") != "development_only"
                    or row.get("admission_status") != "admitted_source_reviewed_development_only"):
                raise ValueError(f"invalid admission status: {key}")
            for field, value in row.items():
                if not field.endswith("_path") or not isinstance(value, str):
                    continue
                hash_field = field[:-5] + "_sha256"
                if hash_field not in row:
                    continue
                referenced = root / value
                if value not in checked_files:
                    checked_files[value] = hashlib.sha256(referenced.read_bytes()).hexdigest()
                digest = checked_files[value]
                if digest != row[hash_field]:
                    raise ValueError(f"provenance hash changed: {value}")
        batch_counts[path.name] = len(clean)
        records.extend(clean)
    # Identity validation also rejects one observation appearing in two batches.
    validate_rows(records)
    frozen = json.loads((root / "data/acquisition_resume/2026-11-01/takeover-checkpoint.json").read_text())["freeze_sha256"]
    for value, expected in frozen.items():
        if hashlib.sha256((root / value).read_bytes()).hexdigest() != expected:
            raise ValueError(f"protected file changed: {value}")
    return {"admitted_decisions": len(records),
            "unique_hands": len({row["hand_id"] for row in records}),
            "source_groups": len({row["group_id"] for row in records}),
            "frozen_baseline_decisions": frozen_count,
            "admission_batches": batch_counts,
            "verified_provenance_files": len(checked_files),
            "verified_protected_files": len(frozen),
            "current_record_hash_set_sha256": _digest(sorted(row["record_hash"] for row in records)),
            "legacy_aggregate_hash_mismatches": legacy_aggregate_hash_mismatches,
            "fresh_holdouts_created": 0,
            "use": "inspected_development_data"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify()
    serialized = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(serialized)
    print(serialized, end="")


if __name__ == "__main__":
    main()
