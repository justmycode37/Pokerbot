"""Explore sizing on old fitting data with whole-source-group cross-validation."""

import argparse
import hashlib
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pokerbot.corpus import load_split
from pokerbot.imitation import decide_with_model, fit_model
from pokerbot.ivey import compare_decisions
from pokerbot.sizing import decide_with_sizer, fit_sizer, predict_raise_to


def experiment(manifest):
    fitting = [r for r in manifest["records"] if r["partition"] in {"train", "development"}]
    groups = sorted({r["group_id"] for r in fitting})
    if len(groups) < 2:
        raise ValueError("need at least two fitting source groups")
    folds = []
    sizes = {name: [] for name in ("classifier_leaf", "global_median", "size_tree_depth1", "size_tree_depth2")}
    full_results = {name: [] for name in sizes}
    for held_group in groups:
        train = [r for r in fitting if r["group_id"] != held_group]
        held = [r for r in fitting if r["group_id"] == held_group]
        classifier = fit_model(train, include_development=True)
        sizers = {"global_median": fit_sizer(train, include_development=True, max_depth=0),
                  "size_tree_depth1": fit_sizer(train, include_development=True, max_depth=1),
                  "size_tree_depth2": fit_sizer(train, include_development=True, max_depth=2)}
        policies = {"classifier_leaf": lambda raw: decide_with_model(raw, classifier)}
        policies.update({name: (lambda raw, sizer=model: decide_with_sizer(raw, classifier, sizer))
                         for name, model in sizers.items()})
        comparisons = {name: compare_decisions(held, policy) for name, policy in policies.items()}
        for name, result in comparisons.items():
            full_results[name].extend(result["predictions"])
        fold_sizes = []
        for row in held:
            if row["expected"]["action"] != "raise":
                continue
            state, expected = row["state"], row["expected"]["amount"]
            for name in sizes:
                target = (decide_with_model(state, classifier)["raise_amount"] if name == "classifier_leaf"
                          else predict_raise_to(state, sizers[name]))
                valid = type(target) is int and state["min_raise_to"] <= target <= state["max_raise_to"]
                entry = {"hand_id": row["hand_id"], "expected_target": expected,
                         "predicted_target": target if valid else None,
                         "absolute_error_pot_fraction": abs(target - expected) / max(
                             1, state.get("contestable_pot", state["pot"]) + state["to_call"]) if valid else None,
                         "exact_size": target == expected if valid else False}
                sizes[name].append(entry)
                fold_sizes.append(dict(entry, candidate=name))
        folds.append({"held_group": held_group, "train_groups": sorted({r["group_id"] for r in train}),
                      "held_decisions": len(held), "comparisons": comparisons, "size_diagnostics": fold_sizes})
    summary = {}
    for name, entries in sizes.items():
        errors = [r["absolute_error_pot_fraction"] for r in entries if r["absolute_error_pot_fraction"] is not None]
        predictions = full_results[name]
        summary[name] = {"decision_count": len(predictions),
                         "action_matches": sum(p["action_match"] for p in predictions),
                         "exact_action_and_size_matches": sum(p["exact_action_and_size_match"] for p in predictions),
                         "recorded_raise_count": len(entries), "sizing_predictions_available": len(errors),
                         "exact_size_matches_conditional_on_recorded_raise": sum(r["exact_size"] for r in entries),
                         "mean_absolute_error_pot_fraction": statistics.mean(errors) if errors else None,
                         "median_absolute_error_pot_fraction": statistics.median(errors) if errors else None}
    return {"report_type": "exploratory_group_cross_validation_on_old_fitting_data",
            "fitting_decisions": len(fitting), "source_groups": len(groups),
            "original_evaluation_rows_used": 0, "prospective_rows_used": 0,
            "summary": summary, "folds": folds,
            "population_accuracy_claim": None,
            "limitations": ["Previously inspected development data; this is model development, not fresh held-out accuracy.",
                            "Hyperparameter comparison consumes these folds for model selection.",
                            "Conditional sizing diagnostics do not imply the policy selected a raise.",
                            "Small, selected and correlated source groups cannot verify 99% imitation."]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        parser.error("output exists; preserve experiments under a new version")
    source = Path(args.manifest)
    report = experiment(load_split(source))
    report["manifest_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    report["code_sha256"] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in (Path(__file__), ROOT / "pokerbot/sizing.py", ROOT / "pokerbot/imitation.py")}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as fp:
        json.dump(report, fp, indent=2, sort_keys=True, allow_nan=False)
        fp.write("\n")
    print(json.dumps(report["summary"], indent=2))
