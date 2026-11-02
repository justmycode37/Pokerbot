"""Fit and evaluate the offline imitation model against a frozen corpus split.

Example (writes only when this command is explicitly run):
  python scripts/train_imitation.py data/ivey-imitation-split.json \
    --model-output models/ivey-imitation.json \
    --report-output reports/ivey-imitation.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pokerbot.corpus import load_split
from pokerbot.fast import decide as fast_decide
from pokerbot.imitation import decide_with_model, fit_model
from pokerbot.ivey import compare_decisions
from pokerbot.evaluation_baselines import majority_action_policy

SEEN_HANDS_PATH = ROOT / "data/seen_ivey_hands.json"
ACTION_CLASSES = ("fold", "check", "call", "raise")


def _read_development_ids(path: Path = SEEN_HANDS_PATH) -> set[str]:
    value = json.loads(path.read_text(encoding="utf-8"))
    identifiers = value.get("development_hand_ids") if isinstance(value, dict) else None
    if not isinstance(identifiers, list) or any(not isinstance(item, str) or not item for item in identifiers):
        raise ValueError("seen Ivey hand file needs a development_hand_ids string list")
    return set(identifiers)


def _group_count(rows: list[Mapping[str, Any]]) -> int:
    groups = set()
    for row in rows:
        group_id = row.get("group_id")
        if group_id is None:
            group_id = row.get("hand_id")
        if group_id is not None:
            groups.add(str(group_id))
    return len(groups)


def prepare_partitions(
    manifest: Mapping[str, Any],
    *,
    include_development: bool = False,
    development_hand_ids: set[str] | None = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Return fitting rows, evaluation rows and unused development rows.

    Evaluation rows never enter the fitting list. The previously inspected
    hand IDs in ``data/seen_ivey_hands.json`` must remain in development.
    """
    if development_hand_ids is None:
        development_hand_ids = _read_development_ids()
    records = manifest.get("records")
    if not isinstance(records, list):
        raise ValueError("frozen split needs a records list")
    by_partition = {name: [] for name in ("train", "evaluation", "development")}
    group_partition: dict[str, str] = {}
    for row in records:
        if not isinstance(row, dict):
            raise ValueError("frozen split rows must be objects")
        partition = row.get("partition")
        if partition not in by_partition:
            raise ValueError("frozen split contains an unknown partition")
        hand_ids = {str(value) for value in (row.get("hand_id"), row.get("canonical_hand_id")) if value is not None}
        if hand_ids.intersection(development_hand_ids) and partition != "development":
            raise ValueError("a previously inspected Ivey hand is not in the development partition")
        group_id = row.get("group_id")
        if not isinstance(group_id, str) or not group_id:
            raise ValueError("frozen split rows need a source group_id")
        prior = group_partition.setdefault(group_id, partition)
        if prior != partition:
            raise ValueError("a source group crosses frozen partitions")
        by_partition[partition].append(row)

    train_rows = by_partition["train"]
    evaluation_rows = by_partition["evaluation"]
    development_rows = by_partition["development"]
    if not train_rows or _group_count(train_rows) == 0:
        raise ValueError("frozen split has no train groups")
    if not evaluation_rows or _group_count(evaluation_rows) == 0:
        raise ValueError("frozen split has no evaluation groups")
    fitting_rows = train_rows + development_rows if include_development else train_rows
    fitting_groups = {row["group_id"] for row in fitting_rows}
    evaluation_groups = {row["group_id"] for row in evaluation_rows}
    if fitting_groups.intersection(evaluation_groups):
        raise ValueError("fitting and evaluation source groups overlap")
    return fitting_rows, evaluation_rows, development_rows


def _manifest_hash(manifest: Mapping[str, Any]) -> str:
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _class_metrics(comparison: Mapping[str, Any]) -> dict[str, Any]:
    predictions = comparison.get("predictions", [])
    metrics = {}
    for action in ACTION_CLASSES:
        expected_count = sum(item.get("expected_action") == action for item in predictions)
        predicted_count = sum(item.get("predicted_action") == action for item in predictions)
        matched_count = sum(
            item.get("expected_action") == action
            and item.get("predicted_action") == action
            and item.get("action_match")
            for item in predictions
        )
        metrics[action] = {
            "expected_count": expected_count,
            "predicted_count": predicted_count,
            "matched_count": matched_count,
            "precision": matched_count / predicted_count if predicted_count else None,
            "recall": matched_count / expected_count if expected_count else None,
        }
    return metrics


def train_and_evaluate_manifest(
    manifest_path: str | Path,
    *,
    include_development: bool = False,
    sizing_tolerance: int = 0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fit on train (optionally train + development) and score evaluation once."""
    manifest = load_split(manifest_path)
    fitting_rows, evaluation_rows, development_rows = prepare_partitions(
        manifest, include_development=include_development
    )
    manifest_hash = _manifest_hash(manifest)
    model = fit_model(
        fitting_rows,
        manifest_hash=manifest_hash,
        include_development=include_development,
    )
    model["metadata"].update({
        "dataset_hash": manifest["dataset_hash"],
        "split_hash": manifest["split_hash"],
    })

    # The frozen evaluation partition is passed only to these descriptive
    # comparisons. It is not used to change the tree, sizing rule, or options.
    imitation_result = compare_decisions(
        evaluation_rows,
        lambda state: decide_with_model(state, model),
        sizing_tolerance=sizing_tolerance,
    )
    fast_result = compare_decisions(
        evaluation_rows, fast_decide, sizing_tolerance=sizing_tolerance
    )
    majority_result = compare_decisions(
        evaluation_rows, majority_action_policy(fitting_rows), sizing_tolerance=sizing_tolerance
    )
    evaluation_groups = _group_count(evaluation_rows)
    is_exploratory = evaluation_groups < 30 or len(evaluation_rows) < 100
    report = {
        "schema_version": 1,
        "report_type": "frozen_group_evaluation_of_imitation_model",
        "manifest_hash": manifest_hash,
        "dataset_hash": manifest["dataset_hash"],
        "split_hash": manifest["split_hash"],
        "training": {
            "decision_count": len(fitting_rows),
            "group_count": _group_count(fitting_rows),
            "development_decision_count_available": len(development_rows),
            "development_included_explicitly": bool(include_development),
            "evaluation_rows_used_for_fitting": 0,
        },
        "evaluation": {
            "partition": "evaluation",
            "decision_count": len(evaluation_rows),
            "group_count": evaluation_groups,
        },
        "exploratory_only": is_exploratory,
        "scope_warning": (
            "EXPLORATORY ONLY: the frozen evaluation sample is small and selected; it cannot establish population agreement."
            if is_exploratory else
            "Selected public source groups describe this corpus only and cannot establish representative population agreement."
        ),
        "population_accuracy_claim": None,
        "99_percent_population_agreement_demonstrated": False,
        "imitation_comparison": imitation_result,
        "fast_baseline_comparison": fast_result,
        "majority_action_baseline_comparison": majority_result,
        "evaluation_action_counts": {action: sum(row["expected"]["action"] == action for row in evaluation_rows)
                                     for action in ACTION_CLASSES},
        "class_metrics": {
            "imitation": _class_metrics(imitation_result),
            "fast_baseline": _class_metrics(fast_result),
        },
        "raise_size_metrics": {
            "imitation": imitation_result["raise_sizing"],
            "fast_baseline": fast_result["raise_sizing"],
        },
        "mixed_action_metrics": {
            "imitation": imitation_result["mixed_action_comparison"],
            "fast_baseline": fast_result["mixed_action_comparison"],
        },
        "limitations": [
            "Evaluation hands are selected public examples; the report makes no population accuracy claim.",
            "All decisions from one source group stay in one partition, but decisions within a hand are correlated.",
            "The three previously inspected hands in data/seen_ivey_hands.json must remain development-only.",
            "No evaluation rows are used for fitting or tuning; inspecting them for future policy changes consumes this holdout.",
            "The fast baseline and imitation model are scored on the same frozen evaluation rows.",
        ],
    }
    return model, report


def _write_new_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, indent=2, sort_keys=True, allow_nan=False)
        output.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="frozen split JSON verified by pokerbot.corpus.load_split")
    parser.add_argument("--model-output", required=True, type=Path, help="new JSON model path")
    parser.add_argument("--report-output", required=True, type=Path, help="new JSON evaluation report path")
    parser.add_argument("--include-development", action="store_true",
                        help="explicitly add development rows to the train partition")
    parser.add_argument("--sizing-tolerance", type=int, default=0,
                        help="raise-size tolerance in chip ticks for descriptive scoring")
    args = parser.parse_args(argv)
    if args.sizing_tolerance < 0:
        parser.error("--sizing-tolerance must be nonnegative")
    if args.model_output.resolve() == args.report_output.resolve():
        parser.error("model and report outputs must be different files")
    if args.model_output.exists() or args.report_output.exists():
        parser.error("output paths must be new files so prior models and reports remain unchanged")

    model, report = train_and_evaluate_manifest(
        args.manifest,
        include_development=args.include_development,
        sizing_tolerance=args.sizing_tolerance,
    )
    _write_new_json(args.model_output, model)
    _write_new_json(args.report_output, report)
    print(json.dumps({
        "model_output": str(args.model_output),
        "report_output": str(args.report_output),
        "manifest_hash": report["manifest_hash"],
        "evaluation_decisions": report["evaluation"]["decision_count"],
        "exploratory_only": report["exploratory_only"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
