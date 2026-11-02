"""Experimental raise-size regression, independent of action classification.

The classifier can have a pure ``raise`` leaf containing several different
sizes. This separate shallow tree can distinguish those sizes using validated
visible-state features. It has no hand/source-ID features.
"""

from __future__ import annotations

import math
from statistics import median

from .imitation import FEATURE_VERSION, decide_with_model, features, fit_model
from .state import Observation

SIZE_FEATURES = (
    "street_preflop", "street_flop", "street_turn", "street_river",
    "pot_odds", "stack_to_pot_log", "current_bet_fraction_of_pot",
    "min_raise_increment_fraction_of_pot", "made_hand_category",
    "board_paired", "board_max_suit_count", "players_active_fraction",
)


def _loss(values):
    center = median(values)
    return sum(abs(value - center) for value in values)


def _tree(examples, depth, max_depth, min_leaf):
    values = [item[1] for item in examples]
    leaf = {"leaf": True, "raise_ratio": median(values), "sample_count": len(values)}
    if depth >= max_depth or len(examples) < 2 * min_leaf:
        return leaf
    best_loss = _loss(values)
    best = None
    for name in SIZE_FEATURES:
        ordered = sorted(examples, key=lambda item: item[0][name])
        for offset in range(min_leaf, len(ordered) - min_leaf + 1):
            left_value = ordered[offset - 1][0][name]
            right_value = ordered[offset][0][name]
            if left_value == right_value:
                continue
            left, right = ordered[:offset], ordered[offset:]
            loss = _loss([item[1] for item in left]) + _loss([item[1] for item in right])
            if loss < best_loss - 1e-12:
                best_loss = loss
                best = name, (left_value + right_value) / 2, left, right
    if best is None:
        return leaf
    name, threshold, left, right = best
    return {"feature": name, "threshold": threshold,
            "left": _tree(left, depth + 1, max_depth, min_leaf),
            "right": _tree(right, depth + 1, max_depth, min_leaf)}


def fit_sizer(rows, *, include_development=False, max_depth=2, min_leaf=2):
    """Fit only legal recorded raises from explicitly permitted partitions."""
    if type(max_depth) is not int or not 0 <= max_depth <= 8:
        raise ValueError("max_depth must be an integer from 0 through 8")
    if type(min_leaf) is not int or min_leaf < 1:
        raise ValueError("min_leaf must be a positive integer")
    rows = list(rows)
    if any(row.get("evidence_tier") == "video_snapshot_with_rounded_or_missing_context"
           or row.get("data_quality", {}).get("status") == "partial" for row in rows):
        raise ValueError("partial video records cannot fit an exact sizing model")
    # Reuse the classifier's partition and expected-action validation. A
    # depth-zero validation fit does not select splits for this regressor.
    checked = fit_model(rows, include_development=include_development, max_depth=0)
    examples = []
    groups = set()
    for row in rows:
        if row["expected"]["action"] != "raise":
            continue
        obs = Observation.from_dict(row["state"])
        ratio = (row["expected"]["amount"] - obs.current_bet - obs.to_call) / max(
            1, obs.contestable_pot + obs.to_call)
        if not math.isfinite(ratio) or ratio < 0:
            raise ValueError("raise ratio must be finite and nonnegative")
        examples.append((features(row["state"]), ratio))
        groups.add(row.get("group_id", row.get("hand_id")))
    return {"schema_version": 1, "algorithm": "independent-l1-raise-size-tree",
            "feature_version": FEATURE_VERSION, "feature_names": list(SIZE_FEATURES),
            "tree": _tree(examples, 0, max_depth, min_leaf) if examples else None,
            "metadata": {"fitting_decisions": len(rows), "raise_decisions": len(examples),
                         "raise_source_groups": len(groups), "max_depth": max_depth,
                         "min_leaf": min_leaf,
                         "partitions_used": checked["metadata"]["partitions_used"],
                         "target": "increment above call / contestable pot after call"}}


def predict_raise_to(raw, model):
    """Return a legal total street target, or None when no sizes were fitted."""
    obs = Observation.from_dict(raw)
    if (model.get("schema_version") != 1 or model.get("feature_version") != FEATURE_VERSION
            or model.get("feature_names") != list(SIZE_FEATURES)):
        raise ValueError("unsupported raise-size model")
    if "raise" not in obs.legal_actions or model.get("tree") is None:
        return None
    values = features(raw)
    node = model["tree"]
    for _ in range(9):
        if not isinstance(node, dict):
            raise ValueError("invalid raise-size tree")
        if node.get("leaf") is True:
            ratio = node.get("raise_ratio")
            if (isinstance(ratio, bool) or not isinstance(ratio, (int, float))
                    or not math.isfinite(ratio) or ratio < 0):
                raise ValueError("invalid raise-size ratio")
            target = obs.current_bet + obs.to_call + round(
                ratio * max(1, obs.contestable_pot + obs.to_call))
            return obs.raise_to(target)
        name, threshold = node.get("feature"), node.get("threshold")
        if (name not in SIZE_FEATURES or isinstance(threshold, bool)
                or not isinstance(threshold, (int, float)) or not math.isfinite(threshold)):
            raise ValueError("invalid raise-size split")
        node = node.get("left" if values[name] <= threshold else "right")
    raise ValueError("raise-size tree exceeds supported depth")


def decide_with_sizer(raw, classifier, sizer):
    result = decide_with_model(raw, classifier)
    target = predict_raise_to(raw, sizer)
    if target is not None:
        result["raise_amount"] = target
        result["amount"] = target if result["action"] == "raise" else 0
    result["diagnostics"]["experimental_size_model"] = sizer["algorithm"]
    return result
