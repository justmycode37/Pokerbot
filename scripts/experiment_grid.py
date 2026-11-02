"""Run the fixed observed-chip-grid sizing experiment on frozen development data."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pokerbot.corpus import load_split
from pokerbot.fast import decide as decide_fast
from pokerbot.grid_policy import (
    GRID_FALLBACK_BIG_BLIND_DIVISOR,
    GRID_FIELDS,
    GRID_HEURISTIC,
    decide_with_grid,
)


DEFAULT_MANIFEST = ROOT / "data/corpus_splits/development-after-prospective-v1.json"
DEFAULT_OUTPUT = ROOT / "reports/chip-grid-development-v1.json"
EXPECTED_COUNTS = {"decisions": 45, "hands": 12, "groups": 8}


def _score(rows, decide):
    action_matches = 0
    exact_matches = 0
    predicted_actions = Counter()
    raise_errors = []
    raise_fraction_errors = []
    exact_size_matches = 0
    expected_raise_count = 0
    missing_size_count = 0

    for row in rows:
        state = row["state"]
        expected = row["expected"]
        result = decide(state)
        action = result["action"]
        predicted_actions[action] += 1
        action_match = action == expected["action"]
        action_matches += action_match
        exact_match = action_match
        if expected["action"] == "raise":
            expected_raise_count += 1
            target = result.get("raise_amount")
            if (type(target) is int and state["min_raise_to"] <= target <= state["max_raise_to"]):
                error = abs(target - expected["amount"])
                raise_errors.append(error)
                raise_fraction_errors.append(error / max(
                    1, state.get("contestable_pot", state["pot"]) + state["to_call"]))
                exact_size_matches += target == expected["amount"]
            else:
                missing_size_count += 1
            exact_match = exact_match and result.get("amount") == expected["amount"]
        exact_matches += exact_match

    decision_count = len(rows)
    return {
        "decision_count": decision_count,
        "action_agreement_count": action_matches,
        "action_agreement_rate": action_matches / decision_count if decision_count else None,
        "exact_action_and_size_match_count": exact_matches,
        "exact_action_and_size_match_rate": exact_matches / decision_count if decision_count else None,
        "predicted_action_counts": dict(sorted(predicted_actions.items())),
        "raise_size_errors": {
            "scoring_scope": (
                "proposed raise_amount on every recorded raise decision, even when the sampled "
                "action is not raise"
            ),
            "expected_raise_count": expected_raise_count,
            "sizing_predictions_scored": len(raise_errors),
            "missing_or_illegal_size_count": missing_size_count,
            "exact_size_match_count": exact_size_matches,
            "mean_absolute_error_chips": statistics.mean(raise_errors) if raise_errors else None,
            "median_absolute_error_chips": statistics.median(raise_errors) if raise_errors else None,
            "mean_absolute_error_pot_after_call_fraction": (
                statistics.mean(raise_fraction_errors) if raise_fraction_errors else None
            ),
        },
    }


def _group_results(rows):
    group_ids = sorted({row["group_id"] for row in rows})
    output = []
    for group_id in group_ids:
        grouped = [row for row in rows if row["group_id"] == group_id]
        output.append({
            "group_id": group_id,
            "hand_count": len({row["hand_id"] for row in grouped}),
            "decision_count": len(grouped),
            "expected_action_counts": dict(sorted(Counter(
                row["expected"]["action"] for row in grouped).items())),
            "fast_baseline": _score(grouped, decide_fast),
            "observed_grid_wrapper": _score(grouped, decide_with_grid),
        })
    return output


def experiment(manifest_path: Path):
    manifest = load_split(manifest_path)
    rows = [row for row in manifest["records"] if row["partition"] == "development"]
    counts = {
        "decisions": len(rows),
        "hands": len({row["hand_id"] for row in rows}),
        "groups": len({row["group_id"] for row in rows}),
    }
    if counts != EXPECTED_COUNTS:
        raise ValueError(f"expected the frozen 45-decision development set, got {counts}")

    baseline_predictions = [decide_fast(row["state"]) for row in rows]
    wrapper_predictions = [decide_with_grid(row["state"]) for row in rows]
    action_and_probability_invariance = all(
        base["action"] == wrapped["action"]
        and base["probabilities"] == wrapped["probabilities"]
        for base, wrapped in zip(baseline_predictions, wrapper_predictions)
    )
    if not action_and_probability_invariance:
        raise AssertionError("grid wrapper changed fast action or probabilities")

    groups = _group_results(rows)
    if len(groups) != EXPECTED_COUNTS["groups"]:
        raise AssertionError("unexpected development group count")
    return {
        "report_type": "development_only_observed_chip_grid_sizing_experiment",
        "partition_used": "development",
        "sample": counts,
        "expected_action_counts": dict(sorted(Counter(
            row["expected"]["action"] for row in rows).items())),
        "configuration": {
            "baseline": "pokerbot.fast.decide (frozen fast policy)",
            "wrapper": "pokerbot.grid_policy.decide_with_grid",
            "predeclared_single_wrapper_configuration": True,
            "grid_heuristic": GRID_HEURISTIC,
            "grid_fields": list(GRID_FIELDS),
            "grid_fallback": (
                f"use 1 if inferred_grid * {GRID_FALLBACK_BIG_BLIND_DIVISOR} "
                "is greater than big_blind"
            ),
            "rounding": "nearest integer grid multiple; integer ties to even",
            "bounds": "clamp to supplied min_raise_to/max_raise_to; retain boundary targets exactly",
            "action_and_probabilities": "copied unchanged from fast baseline",
            "gcd_interpretation": (
                "observed rounding heuristic only; not proof of minimum chip denomination"
            ),
            "search_after_results": False,
        },
        "action_and_probability_invariance": action_and_probability_invariance,
        "overall": {
            "fast_baseline": _score(rows, decide_fast),
            "observed_grid_wrapper": _score(rows, decide_with_grid),
        },
        "per_group_results": groups,
        "data_fingerprints": {
            "manifest_path": str(manifest_path.relative_to(ROOT)),
            "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "manifest_dataset_sha256": manifest["dataset_hash"],
            "manifest_split_sha256": manifest["split_hash"],
            "development_record_hashes_sha256": hashlib.sha256(
                "\n".join(sorted(row["record_hash"] for row in rows)).encode("utf-8")
            ).hexdigest(),
        },
        "code_fingerprints": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (
                Path(__file__),
                ROOT / "pokerbot/grid_policy.py",
                ROOT / "pokerbot/fast.py",
            )
        },
        "fresh_accuracy_claim": None,
        "limitations": [
            "All 45 development decisions had been inspected before this experiment; no fresh accuracy claim is made.",
            "The data are selected decisions with repeated streets within hands and grouped source dependence.",
            "Raise-size error is scored separately on recorded raises using the proposed raise_amount, including counterfactual sizes when fast selected another action.",
            "The observed GCD is a heuristic and does not prove the minimum chip denomination.",
            "This experiment does not alter the default fast policy, register a candidate, or change candidate-lock-v2.",
            "Any later candidate consideration belongs after the current frozen v2 prospective test; these development rows are not a future holdout.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    manifest_path = args.manifest.resolve()
    output_path = args.output.resolve()
    if output_path.exists():
        parser.error(f"output already exists; preserve experiments under a new version: {output_path}")
    if manifest_path != DEFAULT_MANIFEST.resolve():
        parser.error("this bounded experiment is fixed to development-after-prospective-v1.json")

    report = experiment(manifest_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as fp:
        json.dump(report, fp, indent=2, sort_keys=True, allow_nan=False)
        fp.write("\n")
    print(json.dumps(report["overall"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
