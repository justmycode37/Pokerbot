"""Fit and compare the bounded hybrid candidate on consumed development data.

The input and outputs are deliberately fixed. This trainer accepts only the
inspected 45-decision development manifest, runs whole-source-group
leave-one-group-out CV, then fits the final model on all 45 rows. It has no
option to read later research or a fresh prospective evaluation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pokerbot.evaluation_baselines import majority_action_policy
from pokerbot.fast import decide as fast_decide
from pokerbot.hybrid import decide as hybrid_decide
from pokerbot.hybrid import fit_model as fit_hybrid_model
from pokerbot.hybrid import _validate_model as validate_hybrid_model
from pokerbot.imitation import decide_with_model as decide_with_cart
from pokerbot.imitation import fit_model as fit_cart_model
from pokerbot.sizing import fit_sizer
from pokerbot.state import Observation
from pokerbot.ivey import policy_observation

CORPUS_PATH = ROOT / "data/corpus_splits/development-after-prospective-v1.json"
MODEL_PATH = ROOT / "data/models/hybrid-v2.json"
REPORT_PATH = ROOT / "reports/hybrid-development-v2.json"
ACTION_REGULARIZATION_GRID = (0.001, 0.01, 0.1)
ACTION_BLEND_GRID = (0.5, 0.75, 1.0)
SIZING_DEPTH_GRID = (0, 1)
SIZING_MIN_LEAF = 3
FINGERPRINT_PATHS = (
    "pokerbot/hybrid.py", "scripts/train_hybrid.py", "pokerbot/fast.py",
    "pokerbot/imitation.py", "pokerbot/sizing.py", "pokerbot/state.py",
    "pokerbot/ivey.py", "pokerbot/evaluation_baselines.py", "pokerbot/corpus.py",
    "pokerbot/cards.py", "pokerbot/preflop.py", "pokerbot/texture.py", "data/preflop_equity.json",
)


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return _sha256_bytes(encoded)


def _group(row: Mapping[str, Any]) -> str:
    value = row.get("group_id", row.get("hand_id"))
    if not isinstance(value, str) or not value:
        raise ValueError("each corpus row needs a nonempty source group_id")
    return value


def leave_one_group_out(rows):
    """Yield deterministic whole-source-group folds with an overlap guard."""
    rows = list(rows)
    groups = sorted({_group(row) for row in rows})
    if len(groups) < 2:
        raise ValueError("whole-source-group CV needs at least two groups")
    for held_out in groups:
        training = [row for row in rows if _group(row) != held_out]
        validation = [row for row in rows if _group(row) == held_out]
        train_groups = {_group(row) for row in training}
        test_groups = {_group(row) for row in validation}
        if not training or not validation or train_groups.intersection(test_groups):
            raise RuntimeError("source group crossed a CV fold")
        yield held_out, training, validation


def validate_development_manifest(path: Path = CORPUS_PATH) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Reject any input other than the named, consumed 45-row manifest."""
    if path.resolve() != CORPUS_PATH.resolve():
        raise ValueError("trainer input is fixed to data/corpus_splits/development-after-prospective-v1.json")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("unsupported development manifest")
    rows = manifest.get("records")
    if not isinstance(rows, list) or len(rows) != 45 or any(not isinstance(row, dict) for row in rows):
        raise ValueError("the hybrid trainer requires the inspected 45-decision manifest")
    if any(row.get("partition") != "development" for row in rows):
        raise ValueError("hybrid training accepts development rows only")
    groups = {_group(row) for row in rows}
    hands = {str(row.get("hand_id")) for row in rows if row.get("hand_id") is not None}
    counts = manifest.get("counts")
    if len(groups) != 8 or len(hands) != 12:
        raise ValueError("development corpus must have 12 hands and 8 source groups")
    if counts != {
        "development": {"decisions": 45, "groups": 8},
        "evaluation": {"decisions": 0, "groups": 0},
        "train": {"decisions": 0, "groups": 0},
    }:
        raise ValueError("manifest partition counts do not match the approved development corpus")
    if any(not isinstance(row.get("evidence_tier"), str) or not row["evidence_tier"] for row in rows):
        raise ValueError("manifest contains a row with missing evidence provenance")
    return manifest, rows


def _predicted_raise_to(row: Mapping[str, Any], prediction: Mapping[str, Any]) -> int | None:
    obs = Observation.from_dict(row["state"])
    value = prediction.get("raise_amount")
    if value is None and prediction.get("action") == "raise":
        value = prediction.get("amount")
    if value is None or type(value) is not int or not obs.min_raise_to <= value <= obs.max_raise_to:
        return None
    return value


def _score(rows, predictions, *, details: bool = False) -> dict[str, Any]:
    """Score action, exact street amount, sizing, class, and probability metrics."""
    if len(rows) != len(predictions):
        raise ValueError("each score row needs one prediction")
    per_group: dict[str, list[dict[str, Any]]] = {}
    class_counts = {action: {"expected": 0, "predicted": 0, "matched": 0}
                    for action in ("fold", "check", "call", "raise")}
    action_matches = exact_matches = illegal = bad_dist = 0
    log_losses, expected_probabilities = [], []
    raise_sizes = []
    matched_raise_sizes = []
    result_rows = []
    for row, prediction in zip(rows, predictions):
        group = _group(row)
        expected = row["expected"]
        expected_action = expected["action"]
        expected_amount = expected.get("amount")
        obs = Observation.from_dict(row["state"])
        predicted_action = prediction.get("action")
        legal = predicted_action in obs.legal_actions
        illegal += not legal
        action_match = legal and predicted_action == expected_action
        action_matches += action_match
        class_counts[expected_action]["expected"] += 1
        if predicted_action in class_counts:
            class_counts[predicted_action]["predicted"] += 1
        if action_match:
            class_counts[expected_action]["matched"] += 1

        probabilities = prediction.get("probabilities")
        valid_distribution = (
            isinstance(probabilities, Mapping)
            and set(probabilities).issubset(obs.legal_actions)
            and all(type(value) in (float, int) and math.isfinite(value) and 0 <= value <= 1
                    for value in probabilities.values())
            and abs(sum(probabilities.values()) - 1.0) <= 1e-8
        )
        if valid_distribution:
            p_expected = float(probabilities.get(expected_action, 0.0))
            expected_probabilities.append(p_expected)
            row_log_loss = -math.log(max(1e-15, p_expected))
            log_losses.append(row_log_loss)
        else:
            bad_dist += 1
            p_expected = None
            row_log_loss = None

        predicted_raise_to = _predicted_raise_to(row, prediction) if "raise" in obs.legal_actions else None
        if expected_action == "raise":
            sizing = {"group": group, "error": None, "ratio_error": None, "exact": False,
                      "predicted_total_street_bet": predicted_raise_to}
            if predicted_raise_to is not None:
                error = abs(predicted_raise_to - expected_amount)
                pot_after_call = max(1, obs.contestable_pot + obs.to_call)
                sizing["error"] = error
                sizing["ratio_error"] = error / pot_after_call
                sizing["exact"] = predicted_raise_to == expected_amount
            raise_sizes.append(sizing)
            if action_match and predicted_action == "raise" and predicted_raise_to is not None:
                matched_raise_sizes.append(sizing)
        exact = action_match and (expected_action != "raise" or predicted_raise_to == expected_amount)
        exact_matches += exact
        record = {
            "decision_id": row.get("decision_id"), "group_id": group,
            "expected_action": expected_action, "predicted_action": predicted_action,
            "action_match": bool(action_match), "exact_action_and_size_match": bool(exact),
            "expected_total_street_bet": expected_amount,
            "predicted_total_street_bet": predicted_raise_to if expected_action == "raise" else None,
            "probability_of_recorded_action": p_expected,
        }
        result_rows.append(record)
        per_group.setdefault(group, []).append({
            "action_match": bool(action_match), "exact": bool(exact), "log_loss": row_log_loss,
            "probability": p_expected, "sizing": raise_sizes[-1] if expected_action == "raise" else None,
        })

    n = len(rows)
    size_scored = [item for item in raise_sizes if item["error"] is not None]
    matched_scored = [item for item in matched_raise_sizes if item["error"] is not None]
    groups = {}
    for group, entries in sorted(per_group.items()):
        group_log_loss = [item["log_loss"] for item in entries if item["log_loss"] is not None]
        group_sizing = [item["sizing"]["ratio_error"] for item in entries
                        if item["sizing"] is not None and item["sizing"]["ratio_error"] is not None]
        groups[group] = {
            "decision_count": len(entries),
            "action_agreement": sum(item["action_match"] for item in entries) / len(entries),
            "exact_action_and_size_agreement": sum(item["exact"] for item in entries) / len(entries),
            "mean_probability_of_recorded_action": (
                statistics.fmean(item["probability"] for item in entries if item["probability"] is not None)
                if any(item["probability"] is not None for item in entries) else None
            ),
            "multiclass_log_loss": statistics.fmean(group_log_loss) if group_log_loss else None,
            "raise_size_mean_absolute_pot_fraction_error": statistics.fmean(group_sizing) if group_sizing else None,
        }
    group_means = {}
    for metric in ("action_agreement", "exact_action_and_size_agreement",
                   "mean_probability_of_recorded_action", "multiclass_log_loss",
                   "raise_size_mean_absolute_pot_fraction_error"):
        values = [value[metric] for value in groups.values() if value[metric] is not None]
        group_means[metric] = statistics.fmean(values) if values else None

    classes = {}
    for action, counts in class_counts.items():
        classes[action] = {
            **counts,
            "precision": counts["matched"] / counts["predicted"] if counts["predicted"] else None,
            "recall": counts["matched"] / counts["expected"] if counts["expected"] else None,
        }
    result = {
        "sample_count": n,
        "source_group_count": len(per_group),
        "action_agreement_count": action_matches,
        "action_agreement": action_matches / n if n else None,
        "exact_action_and_size_agreement_count": exact_matches,
        "exact_action_and_size_agreement": exact_matches / n if n else None,
        "illegal_prediction_count": illegal,
        "class_metrics": classes,
        "mix_probability": {
            "scored_count": len(expected_probabilities), "invalid_distributions": bad_dist,
            "mean_probability_of_recorded_action_class": statistics.fmean(expected_probabilities) if expected_probabilities else None,
            "multiclass_log_loss": statistics.fmean(log_losses) if log_losses else None,
            "source_group_mean_multiclass_log_loss": group_means["multiclass_log_loss"],
        },
        "raise_sizing": {
            "expected_raise_count": len(raise_sizes),
            "sized_raise_count": len(size_scored),
            "missing_or_illegal_size_count": len(raise_sizes) - len(size_scored),
            "exact_total_street_size_count": sum(item["exact"] for item in size_scored),
            "exact_total_street_size_rate": (
                sum(item["exact"] for item in size_scored) / len(raise_sizes) if raise_sizes else None
            ),
            "mean_absolute_error_chips": statistics.fmean(item["error"] for item in size_scored) if size_scored else None,
            "mean_absolute_error_pot_after_call_fraction": statistics.fmean(item["ratio_error"] for item in size_scored) if size_scored else None,
            "matched_raise_action_count": len(matched_scored),
            "exact_size_given_action_match_count": sum(item["exact"] for item in matched_scored),
        },
        "group_mean_metrics": group_means,
        "per_group": groups,
    }
    if details:
        result["predictions"] = result_rows
    return result


def _predict_all(rows, policy):
    return [policy(policy_observation(row["state"])) for row in rows]


def _fit_sizer(training, depth):
    return fit_sizer(training, include_development=True, max_depth=depth, min_leaf=SIZING_MIN_LEAF)


def _candidate_action_model(rows, regularization, blend, *, manifest_hash=None):
    return fit_hybrid_model(rows, regularization=regularization, blend=blend,
                            sizer=None, manifest_hash=manifest_hash)


def _cv(rows, manifest_hash):
    folds = list(leave_one_group_out(rows))
    residual_predictions = {
        (regularization, blend): {}
        for regularization in ACTION_REGULARIZATION_GRID for blend in ACTION_BLEND_GRID
    }
    fold_records = []
    baseline_oof: dict[str, dict[int, dict[str, Any]]] = {name: {} for name in ("fast", "majority", "freshfold_cart")}
    for held_out, training, validation in folds:
        train_groups = {_group(row) for row in training}
        if held_out in train_groups:
            raise RuntimeError("held-out source group leaked into fitting rows")
        fitted_by_lambda = {}
        for regularization in ACTION_REGULARIZATION_GRID:
            fitted_by_lambda[regularization] = _candidate_action_model(
                training, regularization, ACTION_BLEND_GRID[0], manifest_hash=manifest_hash)
        fold_action_record = {
            "held_out_group": held_out,
            "validation_decisions": len(validation),
            "training_decisions": len(training),
            "validation_groups": [held_out],
            "training_groups": sorted(train_groups),
        }
        for regularization, model in fitted_by_lambda.items():
            for blend in ACTION_BLEND_GRID:
                model["blend"] = blend
                predictions = _predict_all(validation, lambda state, m=model: hybrid_decide(state, m))
                residual_predictions[(regularization, blend)].update(
                    {id(row): prediction for row, prediction in zip(validation, predictions)}
                )
        baseline_oof["fast"].update({
            id(row): prediction for row, prediction in
            zip(validation, _predict_all(validation, fast_decide))
        })
        majority = majority_action_policy(training)
        majority_predictions = _predict_all(validation, majority)
        for row, prediction in zip(validation, majority_predictions):
            obs = Observation.from_dict(row["state"])
            if "raise" in obs.legal_actions and prediction.get("raise_amount") is None:
                prediction["raise_amount"] = obs.min_raise_to
        baseline_oof["majority"].update({
            id(row): prediction for row, prediction in zip(validation, majority_predictions)
        })
        cart = fit_cart_model(training, include_development=True)
        cart_predictions = _predict_all(validation, lambda state: decide_with_cart(state, cart))
        baseline_oof["freshfold_cart"].update({
            id(row): prediction for row, prediction in zip(validation, cart_predictions)
        })
        fold_records.append(fold_action_record)

    action_grid = []
    ordered_residual_predictions = {
        key: [mapping[id(row)] for row in rows] for key, mapping in residual_predictions.items()
    }
    ordered_baseline_predictions = {
        name: [mapping[id(row)] for row in rows] for name, mapping in baseline_oof.items()
    }
    for regularization in ACTION_REGULARIZATION_GRID:
        for blend in ACTION_BLEND_GRID:
            score = _score(rows, ordered_residual_predictions[(regularization, blend)])
            action_grid.append({
                "regularization": regularization, "blend": blend,
                "group_mean_multiclass_log_loss": score["group_mean_metrics"]["multiclass_log_loss"],
                "mean_multiclass_log_loss": score["mix_probability"]["multiclass_log_loss"],
                "action_agreement": score["action_agreement"],
            })
    selected_action = min(
        action_grid,
        key=lambda item: (item["group_mean_multiclass_log_loss"], item["regularization"], -item["blend"]),
    )
    selected_key = (selected_action["regularization"], selected_action["blend"])

    sizing_predictions = {depth: {} for depth in SIZING_DEPTH_GRID}
    for held_out, training, validation in folds:
        action_model = _candidate_action_model(
            training, selected_action["regularization"], selected_action["blend"],
            manifest_hash=manifest_hash)
        for depth in SIZING_DEPTH_GRID:
            sizer = _fit_sizer(training, depth)
            action_model["sizer"] = sizer
            predictions = _predict_all(validation, lambda state, m=action_model: hybrid_decide(state, m))
            sizing_predictions[depth].update({
                id(row): prediction for row, prediction in zip(validation, predictions)
            })
    ordered_sizing_predictions = {
        depth: [mapping[id(row)] for row in rows] for depth, mapping in sizing_predictions.items()
    }
    sizing_grid = []
    for depth in SIZING_DEPTH_GRID:
        score = _score(rows, ordered_sizing_predictions[depth])
        sizing_grid.append({
            "max_depth": depth, "min_leaf": SIZING_MIN_LEAF,
            "source_group_mean_pot_fraction_mae": score["group_mean_metrics"]["raise_size_mean_absolute_pot_fraction_error"],
            "exact_total_street_size_rate": score["raise_sizing"]["exact_total_street_size_rate"],
            "mean_absolute_error_chips": score["raise_sizing"]["mean_absolute_error_chips"],
        })
    selected_sizing = min(
        sizing_grid,
        key=lambda item: (item["source_group_mean_pot_fraction_mae"] if item["source_group_mean_pot_fraction_mae"] is not None else math.inf,
                          item["max_depth"]),
    )

    final_candidate_oof = ordered_sizing_predictions[selected_sizing["max_depth"]]
    selected_action_score = _score(rows, ordered_residual_predictions[selected_key])
    candidate_score = _score(rows, final_candidate_oof, details=True)
    baseline_scores = {name: _score(rows, values, details=True) for name, values in ordered_baseline_predictions.items()}
    cv_record = {
        "method": "leave_one_source_group_out",
        "fold_count": len(folds),
        "source_group_count": len({_group(row) for row in rows}),
        "decision_count": len(rows),
        "training_group_weighting": "equal total weight per source group",
        "action_selection_criterion": "minimum source-group mean multiclass log loss",
        "sizing_selection_criterion": "minimum source-group mean absolute raise-size error / pot after call; depth breaks ties",
        "predeclared_action_grid": {
            "regularization": list(ACTION_REGULARIZATION_GRID),
            "blend": list(ACTION_BLEND_GRID),
        },
        "predeclared_sizing_grid": {"max_depth": list(SIZING_DEPTH_GRID), "min_leaf": SIZING_MIN_LEAF},
        "folds": fold_records,
        "action_grid": action_grid,
        "selected_action": {key: selected_action[key] for key in ("regularization", "blend")},
        "action_grid_selected_configuration_metrics": selected_action_score,
        "sizing_grid": sizing_grid,
        "selected_sizing": {key: selected_sizing[key] for key in ("max_depth", "min_leaf")},
        "oof_comparisons": {"hybrid_candidate": candidate_score, **baseline_scores},
        "selected_action_model_oof_before_sizing": selected_action_score,
    }
    return cv_record


def _synthetic_profile_states() -> list[dict[str, Any]]:
    """Small valid states used only for local warmed-call timing."""
    return [
        {"hole_cards": ["Ah", "Kh"], "board": [], "pot": 1000, "contestable_pot": 1000,
         "to_call": 100, "stack": 10000, "current_bet": 100, "min_raise_to": 300,
         "max_raise_to": 10000, "big_blind": 100, "position": "BTN", "players_active": 3,
         "players_to_act": 1, "table_size": 6, "legal_actions": ["call", "fold", "raise"],
         "street": "preflop", "seed": 11, "history": []},
        {"hole_cards": ["9h", "8h"], "board": ["As", "Ks", "2h"], "pot": 1600,
         "contestable_pot": 1600, "to_call": 250, "stack": 6000, "current_bet": 0,
         "min_raise_to": 500, "max_raise_to": 6000, "big_blind": 100, "position": "CO",
         "players_active": 2, "players_to_act": 1, "table_size": 6,
         "legal_actions": ["call", "fold", "raise"], "street": "flop", "seed": 29,
         "history": []},
        {"hole_cards": ["Qc", "Jc"], "board": ["8d", "9h", "Td", "2c"], "pot": 2400,
         "contestable_pot": 2400, "to_call": 0, "stack": 4000, "current_bet": 0,
         "min_raise_to": 100, "max_raise_to": 4000, "big_blind": 100, "position": "BB",
         "players_active": 2, "players_to_act": 1, "table_size": 6,
         "legal_actions": ["check", "raise"], "street": "turn", "seed": 71, "history": []},
        {"hole_cards": ["6d", "6h"], "board": ["2c", "3s", "4d", "8h", "Ts"], "pot": 800,
         "contestable_pot": 800, "to_call": 0, "stack": 2000, "current_bet": 0,
         "min_raise_to": 100, "max_raise_to": 2000, "big_blind": 100, "position": "SB",
         "players_active": 2, "players_to_act": 1, "table_size": 6,
         "legal_actions": ["check", "raise"], "street": "river", "seed": 5, "history": []},
    ]


def _profile(model, calls: int = 300) -> dict[str, Any]:
    if type(calls) is not int or calls < 1:
        raise ValueError("profile calls must be a positive integer")
    # Exercise the same object shape the runtime receives after one JSON load.
    model = json.loads(json.dumps(model, allow_nan=False))
    validate_hybrid_model(model)
    states = _synthetic_profile_states()
    for index in range(32):
        hybrid_decide(states[index % len(states)], model)
    elapsed = []
    for index in range(calls):
        start = time.perf_counter_ns()
        hybrid_decide(states[index % len(states)], model)
        elapsed.append((time.perf_counter_ns() - start) / 1000.0)
    ordered = sorted(elapsed)
    return {
        "observation_count": len(states), "warmed_calls": calls,
        "mean_microseconds": statistics.fmean(elapsed),
        "median_microseconds": statistics.median(elapsed),
        "p95_microseconds": ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)],
        "measurement_scope": "local synthetic observations only; not an official runtime guarantee",
        "model_loaded_once": True,
        "model_json_parsed_once": True,
    }


def train_development(*, corpus_path: Path = CORPUS_PATH, profile_calls: int = 300):
    manifest, rows = validate_development_manifest(corpus_path)
    manifest_hash = _canonical_hash(manifest)
    manifest_file_hash = _sha256_bytes(corpus_path.read_bytes())
    cv = _cv(rows, manifest_hash)
    selected_action = cv["selected_action"]
    selected_sizing = cv["selected_sizing"]
    final_sizer = _fit_sizer(rows, selected_sizing["max_depth"])
    final_model = fit_hybrid_model(
        rows,
        regularization=selected_action["regularization"],
        blend=selected_action["blend"],
        sizer=final_sizer,
        manifest_hash=manifest_hash,
        metadata={
            "development_partition_only": True,
            "development_decisions": len(rows),
            "development_hands": len({str(row.get("hand_id")) for row in rows}),
            "development_source_groups": len({_group(row) for row in rows}),
            "all_rows_previously_inspected": True,
            "prospective_batch2_consumed_as_development": True,
            "heldout_evaluation_rows": 0,
            "selected_via_whole_source_group_cv": True,
            "selected_sizing_depth": selected_sizing["max_depth"],
            "sizing_min_leaf": SIZING_MIN_LEAF,
            "population_accuracy_claim": None,
        },
    )
    fingerprints = {
        rel: _sha256_bytes((ROOT / rel).read_bytes())
        for rel in FINGERPRINT_PATHS
    }
    final_model["metadata"].update({
        "development_manifest_path": str(CORPUS_PATH.relative_to(ROOT)),
        "development_manifest_file_sha256": manifest_file_hash,
        "development_manifest_canonical_sha256": manifest_hash,
        "dataset_hash": manifest.get("dataset_hash"),
        "split_hash": manifest.get("split_hash"),
        "source_code_sha256": fingerprints,
        "runtime_requirement": "Python standard library only; caller loads model JSON once",
    })
    profile = _profile(final_model, profile_calls)
    fast_score = cv["oof_comparisons"]["fast"]
    hybrid_score = cv["oof_comparisons"]["hybrid_candidate"]
    improvement = {
        "action_agreement_improved_over_fast": hybrid_score["action_agreement"] > fast_score["action_agreement"],
        "exact_action_and_size_improved_over_fast": hybrid_score["exact_action_and_size_agreement"] > fast_score["exact_action_and_size_agreement"],
        "exact_total_street_sizing_rate_improved_over_fast": (
            hybrid_score["raise_sizing"]["exact_total_street_size_rate"] is not None
            and fast_score["raise_sizing"]["exact_total_street_size_rate"] is not None
            and hybrid_score["raise_sizing"]["exact_total_street_size_rate"] > fast_score["raise_sizing"]["exact_total_street_size_rate"]
        ),
    }
    is_superior = all(improvement.values())
    final_model["metadata"]["development_candidate_status"] = (
        "superior_on_predeclared_group_cv_metrics" if is_superior
        else "negative_result_not_superior_to_fast_on_all_required_cv_metrics"
    )
    report = {
        "schema_version": 1,
        "report_type": "consumed_development_group_cv_for_hybrid_ivey_imitation_candidate",
        "candidate_label": (
            "development candidate; superior on all predeclared CV metrics"
            if is_superior else
            "negative result; failed required action and exact sizing improvements over frozen fast"
        ),
        "development_data": {
            "path": str(CORPUS_PATH.relative_to(ROOT)),
            "file_sha256": manifest_file_hash,
            "canonical_manifest_sha256": manifest_hash,
            "dataset_hash": manifest.get("dataset_hash"),
            "split_hash": manifest.get("split_hash"),
            "decision_count": len(rows),
            "hand_count": len({str(row.get("hand_id")) for row in rows}),
            "source_group_count": len({_group(row) for row in rows}),
            "partition": "development only",
            "previously_inspected": True,
            "prospective_batch2_is_consumed_development": True,
            "fresh_heldout_evaluation_count": 0,
        },
        "source_code_sha256": fingerprints,
        "cv": cv,
        "cv_comparison_to_frozen_fast": improvement,
        "required_action_and_exact_sizing_improvements_met_in_cv": is_superior,
        "final_fit": {
            "decision_count": len(rows), "source_group_count": len({_group(row) for row in rows}),
            "fit_after_cv_selection": True,
            "selected_action": selected_action,
            "selected_sizing": selected_sizing,
            "heldout_evaluation_rows_used_for_fitting": 0,
        },
        "local_profile": profile,
        "population_accuracy_claim": None,
        "99_percent_population_agreement_demonstrated": False,
        "limitations": [
            "All 45 decisions have already been inspected; this corpus is consumed development data, not a fresh evaluation.",
            "Eight source groups are few; leave-one-source-group-out CV is exploratory and group rows can remain correlated.",
            "Public selected examples do not establish representative population agreement.",
            "The local warmed timing uses synthetic valid observations and is not an official runtime guarantee.",
            "The fast prior and feature model assume the repository's current no-limit Hold'em observation protocol.",
        ],
    }
    return final_model, report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Train a hybrid fast-prior candidate using only the consumed 45-row development corpus."
    )
    parser.add_argument("--corpus", type=Path, default=CORPUS_PATH,
                        help="fixed input: data/corpus_splits/development-after-prospective-v1.json")
    parser.add_argument("--model-output", type=Path, default=MODEL_PATH,
                        help="fixed create-once output: data/models/hybrid-v2.json")
    parser.add_argument("--report-output", type=Path, default=REPORT_PATH,
                        help="fixed create-once output: reports/hybrid-development-v2.json")
    parser.add_argument("--profile-calls", type=int, default=300,
                        help="warmed local calls on synthetic valid observations (default: 300)")
    args = parser.parse_args(argv)
    if args.model_output.resolve() != MODEL_PATH.resolve() or args.report_output.resolve() != REPORT_PATH.resolve():
        parser.error("outputs are fixed to data/models/hybrid-v2.json and reports/hybrid-development-v2.json")
    if args.model_output.exists() or args.report_output.exists():
        parser.error("model and report outputs are create-once; existing artifacts will be preserved")
    try:
        model, report = train_development(corpus_path=args.corpus, profile_calls=args.profile_calls)
        # Build both serialized payloads before creating either artifact.
        model_text = json.dumps(model, indent=2, sort_keys=True, allow_nan=False) + "\n"
        report_text = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
        args.model_output.parent.mkdir(parents=True, exist_ok=True)
        args.report_output.parent.mkdir(parents=True, exist_ok=True)
        with args.model_output.open("x", encoding="utf-8") as output:
            output.write(model_text)
        with args.report_output.open("x", encoding="utf-8") as output:
            output.write(report_text)
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        "model": str(args.model_output.relative_to(ROOT)),
        "report": str(args.report_output.relative_to(ROOT)),
        "selected_action": report["final_fit"]["selected_action"],
        "selected_sizing": report["final_fit"]["selected_sizing"],
        "cv_comparison_to_frozen_fast": report["cv_comparison_to_frozen_fast"],
        "local_profile": report["local_profile"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
