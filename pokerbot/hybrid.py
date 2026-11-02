"""Frozen-fast policy with a small regularized residual action model.

The classifier adds multinomial logit corrections to the frozen fast policy's
legal-action probabilities. It uses only ``pokerbot.imitation.features`` and
keeps the predeclared feature order in the model file. Raise sizing is a
separate fitted model from ``pokerbot.sizing``. Runtime code is stdlib-only.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

from .fast import decide as fast_decide
from .imitation import FEATURE_NAMES, FEATURE_VERSION, TIE_BREAK_ORDER, features
from .sizing import SIZE_FEATURES, predict_raise_to
from .state import Observation

ALGORITHM = "fast-prior-multinomial-residual-v2"
ACTION_ORDER = ("raise", "call", "check", "fold")
PRIOR_FLOOR = 0.02
MAX_ITERATIONS = 500
LEARNING_RATE = 0.05


def _group_id(row: Mapping[str, Any]) -> str:
    value = row.get("group_id", row.get("hand_id"))
    if not isinstance(value, str) or not value:
        raise ValueError("every fitting row needs a nonempty source group_id")
    return value


def _inference_state(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Canonicalize actor IDs together, preserving public hero/opponent roles."""
    if not isinstance(raw, Mapping):
        raise ValueError("observation must be an object")
    safe = dict(raw)
    hero = raw.get("player_id")
    safe["player_id"] = "hero" if hero is not None else None
    actors = {}
    history = []
    for original in raw.get("history", []):
        item = dict(original)
        actor = item.get("player")
        if hero is not None and actor == hero:
            item["player"] = "hero"
        elif actor is not None:
            key = (type(actor).__name__, str(actor))
            if key not in actors:
                actors[key] = "opponent-" + str(len(actors))
            item["player"] = actors[key]
        history.append(item)
    safe["history"] = history
    return safe


def _prior_probabilities(raw: Mapping[str, Any], legal: frozenset[str]) -> dict[str, float]:
    result = fast_decide(_inference_state(raw))
    supplied = result.get("probabilities")
    if not isinstance(supplied, Mapping):
        raise ValueError("fast policy returned no probability distribution")
    values = {}
    for action in ACTION_ORDER:
        if action not in legal:
            continue
        value = supplied.get(action, 0.0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError("fast policy returned invalid action probabilities")
        values[action] = max(PRIOR_FLOOR, float(value))
    total = sum(values.values())
    if total <= 0:
        raise ValueError("observation has no supported legal action")
    return {action: value / total for action, value in values.items()}


def _softmax(logits: Mapping[str, float]) -> dict[str, float]:
    if not logits:
        raise ValueError("softmax needs at least one legal action")
    highest = max(logits.values())
    values = {action: math.exp(value - highest) for action, value in logits.items()}
    total = sum(values.values())
    return {action: value / total for action, value in values.items()}


def _validated_rows(rows) -> tuple[list[dict[str, Any]], list[str]]:
    checked = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("training rows must be objects")
        if row.get("partition") not in (None, "train", "development"):
            raise ValueError("evaluation/unknown partitions cannot fit a hybrid model")
        quality = row.get("data_quality") or {}
        if not isinstance(quality, Mapping):
            raise ValueError("data_quality must be an object")
        if (row.get("evidence_tier") == "video_snapshot_with_rounded_or_missing_context"
                or quality.get("status") == "partial"):
            raise ValueError("partial evidence cannot fit a hybrid model")
        group_id = _group_id(row)
        raw = row.get("state")
        obs = Observation.from_dict(raw)
        expected = row.get("expected")
        if not isinstance(expected, Mapping) or expected.get("action") not in obs.legal_actions:
            raise ValueError("training row contains an illegal expected action")
        if expected["action"] == "raise" and (
            type(expected.get("amount")) is not int
            or not obs.min_raise_to <= expected["amount"] <= obs.max_raise_to
        ):
            raise ValueError("training row contains an illegal raise target")
        checked.append({
            "group_id": group_id,
            "state": dict(raw),
            "action": expected["action"],
            "legal_actions": obs.legal_actions,
            "feature_map": features(raw),
            "prior": _prior_probabilities(raw, obs.legal_actions),
        })
    if not checked:
        raise ValueError("at least one training row is required")
    groups = sorted({row["group_id"] for row in checked})
    return checked, groups


def fit_model(
    rows,
    *,
    regularization: float,
    blend: float,
    sizer: Mapping[str, Any] | None = None,
    manifest_hash: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Fit group-balanced multinomial residual corrections.

    Each source group receives equal total fitting weight. ``regularization``
    is the L2 coefficient on feature weights; class intercepts are unpenalized.
    Hyperparameters are selected outside this function by whole-group CV.
    """
    if isinstance(regularization, bool) or not isinstance(regularization, (int, float)) or not math.isfinite(regularization) or regularization <= 0:
        raise ValueError("regularization must be finite and positive")
    if isinstance(blend, bool) or not isinstance(blend, (int, float)) or not math.isfinite(blend) or not 0 <= blend <= 1:
        raise ValueError("blend must be between zero and one")
    if sizer is not None and not isinstance(sizer, Mapping):
        raise ValueError("sizer must be a fitted sizing model or None")
    _validate_sizer(sizer)
    if manifest_hash is not None and (not isinstance(manifest_hash, str) or not manifest_hash):
        raise ValueError("manifest_hash must be a nonempty string or None")

    examples, groups = _validated_rows(rows)
    group_sizes = {group: sum(row["group_id"] == group for row in examples) for group in groups}
    sample_weights = [1.0 / (len(groups) * group_sizes[row["group_id"]]) for row in examples]

    means: dict[str, float] = {}
    scales: dict[str, float] = {}
    for name in FEATURE_NAMES:
        mean = sum(weight * row["feature_map"][name] for weight, row in zip(sample_weights, examples))
        variance = sum(
            weight * (row["feature_map"][name] - mean) ** 2
            for weight, row in zip(sample_weights, examples)
        )
        means[name] = mean
        scales[name] = math.sqrt(variance) if variance > 1e-12 else 1.0

    feature_count = len(FEATURE_NAMES)
    weights = [[0.0] * feature_count for _ in ACTION_ORDER]
    intercepts = [0.0] * len(ACTION_ORDER)
    action_index = {action: index for index, action in enumerate(ACTION_ORDER)}
    feature_rows = [
        [(row["feature_map"][name] - means[name]) / scales[name] for name in FEATURE_NAMES]
        for row in examples
    ]
    for _ in range(MAX_ITERATIONS):
        grad_w = [[regularization * weights[a][j] for j in range(feature_count)]
                  for a in range(len(ACTION_ORDER))]
        grad_b = [0.0] * len(ACTION_ORDER)
        for row, x, sample_weight in zip(examples, feature_rows, sample_weights):
            legal = row["legal_actions"]
            logits = {}
            for action in legal:
                index = action_index[action]
                logits[action] = math.log(max(PRIOR_FLOOR, row["prior"][action])) + intercepts[index] + sum(
                    weights[index][column] * x[column] for column in range(feature_count)
                )
            probabilities = _softmax(logits)
            target = row["action"]
            for action, probability in probabilities.items():
                index = action_index[action]
                error = sample_weight * (probability - float(action == target))
                grad_b[index] += error
                for column, value in enumerate(x):
                    grad_w[index][column] += error * value
        for action in range(len(ACTION_ORDER)):
            intercepts[action] -= LEARNING_RATE * grad_b[action]
            for column in range(feature_count):
                weights[action][column] -= LEARNING_RATE * grad_w[action][column]

    return {
        "schema_version": 1,
        "algorithm": ALGORITHM,
        "feature_version": FEATURE_VERSION,
        "feature_names": list(FEATURE_NAMES),
        "actions": list(ACTION_ORDER),
        "prior_floor": PRIOR_FLOOR,
        "blend": float(blend),
        "regularization": float(regularization),
        "normalization": {"means": means, "scales": scales},
        "residual": {"intercepts": intercepts, "weights": weights},
        "sizer": dict(sizer) if sizer is not None else None,
        "metadata": {
            **dict(metadata or {}),
            "manifest_hash": manifest_hash,
            "training_decisions": len(examples),
            "training_group_count": len(groups),
            "training_group_ids": groups,
            "feature_weighting": "equal total weight per source group",
            "optimizer": "deterministic full-batch gradient descent",
            "optimizer_iterations": MAX_ITERATIONS,
        },
    }


def _validate_sizer(sizer):
    if sizer is None:
        return
    if (not isinstance(sizer, Mapping) or sizer.get("schema_version") != 1
            or sizer.get("algorithm") != "independent-l1-raise-size-tree"
            or sizer.get("feature_version") != FEATURE_VERSION
            or sizer.get("feature_names") != list(SIZE_FEATURES) or "tree" not in sizer):
        raise ValueError("invalid nested hybrid sizing model")
    def walk(node, depth):
        if depth > 8 or not isinstance(node, Mapping):
            raise ValueError("invalid nested hybrid sizing tree")
        if node.get("leaf") is True:
            ratio = node.get("raise_ratio")
            if (isinstance(ratio, bool) or not isinstance(ratio, (int, float))
                    or not math.isfinite(ratio) or ratio < 0):
                raise ValueError("invalid nested hybrid sizing ratio")
            return
        threshold = node.get("threshold")
        if (node.get("feature") not in SIZE_FEATURES or isinstance(threshold, bool)
                or not isinstance(threshold, (int, float)) or not math.isfinite(threshold)):
            raise ValueError("invalid nested hybrid sizing split")
        walk(node.get("left"), depth + 1)
        walk(node.get("right"), depth + 1)
    if sizer["tree"] is not None:
        walk(sizer["tree"], 0)


def _validate_model(model: Mapping[str, Any]) -> None:
    if (model.get("schema_version") != 1 or model.get("algorithm") != ALGORITHM
            or model.get("feature_version") != FEATURE_VERSION
            or model.get("feature_names") != list(FEATURE_NAMES)
            or model.get("actions") != list(ACTION_ORDER)):
        raise ValueError("unsupported hybrid model schema or feature version")
    blend = model.get("blend")
    if isinstance(blend, bool) or not isinstance(blend, (int, float)) or not math.isfinite(blend) or not 0 <= blend <= 1:
        raise ValueError("invalid hybrid mix weight")
    regularization = model.get("regularization")
    if (isinstance(regularization, bool) or not isinstance(regularization, (int, float))
            or not math.isfinite(regularization) or regularization <= 0):
        raise ValueError("invalid hybrid regularization")
    if type(model.get("prior_floor")) not in (int, float) or model["prior_floor"] != PRIOR_FLOOR:
        raise ValueError("unsupported hybrid prior floor")
    normalization = model.get("normalization")
    residual = model.get("residual")
    if not isinstance(normalization, Mapping) or not isinstance(residual, Mapping):
        raise ValueError("hybrid model parameters are invalid")
    means, scales = normalization.get("means"), normalization.get("scales")
    intercepts, weights = residual.get("intercepts"), residual.get("weights")
    if (not isinstance(means, Mapping) or not isinstance(scales, Mapping)
            or set(means) != set(FEATURE_NAMES) or set(scales) != set(FEATURE_NAMES)
            or not isinstance(intercepts, list) or len(intercepts) != len(ACTION_ORDER)
            or not isinstance(weights, list) or len(weights) != len(ACTION_ORDER)):
        raise ValueError("hybrid model parameter dimensions are invalid")
    values = list(means.values()) + list(scales.values()) + intercepts
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in values):
        raise ValueError("hybrid model parameters must be finite")
    if any(value <= 0 for value in scales.values()):
        raise ValueError("hybrid feature scales must be positive")
    if any(not isinstance(vector, list) or len(vector) != len(FEATURE_NAMES) for vector in weights):
        raise ValueError("hybrid residual weight dimensions are invalid")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
           for vector in weights for value in vector):
        raise ValueError("hybrid residual weights must be finite")
    _validate_sizer(model.get("sizer"))


def load_model(path: str | Path) -> dict[str, Any]:
    """Load and validate a model once at the application boundary."""
    model = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(model, dict):
        raise ValueError("hybrid model file must contain an object")
    _validate_model(model)
    return model


def decide(raw: Mapping[str, Any], model: Mapping[str, Any]) -> dict[str, Any]:
    """Return a deterministic legal action and a normalized legal mix."""
    if (not isinstance(model, Mapping) or model.get("schema_version") != 1
            or model.get("algorithm") != ALGORITHM or model.get("feature_version") != FEATURE_VERSION):
        raise ValueError("unsupported hybrid model schema or feature version")
    obs = Observation.from_dict(raw)
    feature_map = features(raw)
    prior = _prior_probabilities(raw, obs.legal_actions)
    means = model["normalization"]["means"]
    scales = model["normalization"]["scales"]
    x = [(feature_map[name] - means[name]) / scales[name] for name in FEATURE_NAMES]
    residual = model["residual"]
    logits = {}
    for action in ACTION_ORDER:
        if action not in obs.legal_actions:
            continue
        index = ACTION_ORDER.index(action)
        logits[action] = math.log(max(PRIOR_FLOOR, prior[action])) + residual["intercepts"][index] + sum(
            residual["weights"][index][column] * x[column]
            for column in range(len(FEATURE_NAMES))
        )
    corrected = _softmax(logits)
    blend = float(model["blend"])
    probabilities = {
        action: (1.0 - blend) * prior[action] + blend * corrected[action]
        for action in prior
    }
    total = sum(probabilities.values())
    probabilities = {action: probability / total for action, probability in probabilities.items()}
    action = max(TIE_BREAK_ORDER, key=lambda candidate: probabilities.get(candidate, -1.0))
    if action not in obs.legal_actions:
        raise RuntimeError("hybrid action selection escaped legal-action mask")

    # Action-only fitting is supported, so absence of a fitted sizer still
    # needs a legal target when the classifier selects raise.
    raise_amount = obs.min_raise_to if "raise" in obs.legal_actions else 0
    sizer = model.get("sizer")
    if "raise" in obs.legal_actions and sizer is not None:
        target = predict_raise_to(raw, sizer)
        if target is not None:
            raise_amount = target
    return {
        "action": action,
        "amount": raise_amount if action == "raise" else 0,
        "raise_amount": raise_amount,
        "probabilities": probabilities,
        "diagnostics": {
            "policy": ALGORITHM,
            "feature_version": FEATURE_VERSION,
            "regularization": model["regularization"],
            "blend": blend,
            "raise_sizing_basis": "independent L1 raise-size tree",
        },
    }
