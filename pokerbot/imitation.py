"""Small, interpretable supervised policy for validated poker observations.

The model is a smoothed CART classifier over public/hero-visible state features.
Raise sizing is the median raise increment divided by the contestable pot after
calling for the training examples that reach the selected leaf. This module is
stdlib-only at runtime and never uses record IDs, labels, outcomes, seeds, or
future information as features.
"""

from __future__ import annotations

import math
from statistics import median
from typing import Any, Mapping

from .cards import rank_hand
from .state import ACTIONS, Observation

FEATURE_VERSION = "imitation-features-v1"
ACTION_ORDER = ("raise", "call", "check", "fold")
TIE_BREAK_ORDER = ("check", "call", "fold", "raise")
POSITIONS = ("UTG", "MP", "CO", "BTN", "SB", "BB")
STREETS = ("preflop", "flop", "turn", "river")
_RANK = {rank: value for value, rank in enumerate("23456789TJQKA", 2)}
_RAISE_ALIASES = frozenset({"raise", "bet", "all-in", "all_in", "all in"})

FEATURE_NAMES = tuple(
    [f"street_{street}" for street in STREETS]
    + [f"position_{position}" for position in POSITIONS]
    + [
        "hole_high_rank",
        "hole_low_rank",
        "hole_pair",
        "hole_suited",
        "hole_rank_gap",
        "hole_has_ace",
        "board_size",
        "board_high_rank",
        "board_low_rank",
        "board_paired",
        "board_distinct_ranks",
        "board_max_suit_count",
        "known_max_suit_count",
        "made_hand_category",
        "hole_ranks_on_board",
        "hole_overcards_to_board",
        "board_run_density",
        "pot_odds",
        "call_fraction_of_stack",
        "stack_to_pot_log",
        "stack_in_big_blinds_log",
        "pot_in_big_blinds_log",
        "current_bet_fraction_of_pot",
        "min_raise_increment_fraction_of_pot",
        "max_raise_increment_fraction_of_pot",
        "players_active_fraction",
        "players_to_act_fraction",
        "table_size_fraction",
        "legal_fold",
        "legal_check",
        "legal_call",
        "legal_raise",
        "history_current_action_count",
        "history_current_raise_count",
        "history_current_call_count",
        "history_current_fold_count",
        "history_preflop_raise_count",
        "history_raise_added_fraction_of_pot",
    ]
)


def _bounded_ratio(numerator: int, denominator: int, cap: float = 1.0) -> float:
    """Divide nonnegative chip counts without overflowing on unusual inputs."""
    if numerator <= 0:
        return 0.0
    if denominator <= 0:
        return cap
    cap_numerator, cap_denominator = cap.as_integer_ratio()
    if numerator * cap_denominator >= denominator * cap_numerator:
        return cap
    return numerator / denominator


def _log_ratio(numerator: int, denominator: int) -> float:
    ratio = _bounded_ratio(numerator, denominator, 1_000_000.0)
    return math.log1p(ratio) / math.log1p(1_000_000.0)


def _run_density(ranks: set[int]) -> float:
    if not ranks:
        return 0.0
    windows = [set(range(low, low + 5)) for low in range(2, 11)]
    windows.append({14, 2, 3, 4, 5})
    return max(len(ranks.intersection(window)) for window in windows) / 5.0


def _feature_map(obs: Observation) -> dict[str, float]:
    hole_ranks = sorted((_RANK[card[0]] for card in obs.hole_cards), reverse=True)
    board_ranks_list = [_RANK[card[0]] for card in obs.board]
    board_ranks = set(board_ranks_list)
    all_cards = obs.hole_cards + obs.board
    board_suits = {suit: sum(card[1] == suit for card in obs.board) for suit in "cdhs"}
    known_suits = {suit: sum(card[1] == suit for card in all_cards) for suit in "cdhs"}
    unique_board_ranks = set(board_ranks_list)
    current_history = []
    preflop_raise_count = 0
    current_raise_count = current_call_count = current_fold_count = 0
    current_raise_added = 0
    for item in obs.history:
        street = item.get("street", obs.street)
        action_value = item.get("action", "")
        action = action_value.strip().lower() if isinstance(action_value, str) else ""
        is_raise = action in _RAISE_ALIASES
        if street == "preflop" and is_raise:
            preflop_raise_count += 1
        if street != obs.street:
            continue
        current_history.append(item)
        current_raise_count += is_raise
        current_call_count += action == "call"
        current_fold_count += action == "fold"
        added = item.get("added")
        if is_raise and type(added) is int and added > 0:
            current_raise_added += added

    pot_after_call = obs.contestable_pot + obs.to_call
    pot_denominator = max(1, pot_after_call)
    if obs.board:
        made_category = rank_hand(obs.hole_cards + obs.board)[0] / 8.0
        board_high = max(board_ranks_list)
        board_low = min(board_ranks_list)
    else:
        made_category = 0.0
        board_high = board_low = 0

    features: dict[str, float] = {}
    features.update({f"street_{street}": float(obs.street == street) for street in STREETS})
    features.update({f"position_{position}": float(obs.position == position) for position in POSITIONS})
    features.update({
        "hole_high_rank": hole_ranks[0] / 14.0,
        "hole_low_rank": hole_ranks[1] / 14.0,
        "hole_pair": float(hole_ranks[0] == hole_ranks[1]),
        "hole_suited": float(obs.hole_cards[0][1] == obs.hole_cards[1][1]),
        "hole_rank_gap": (hole_ranks[0] - hole_ranks[1] - 1) / 12.0,
        "hole_has_ace": float(hole_ranks[0] == 14),
        "board_size": len(obs.board) / 5.0,
        "board_high_rank": board_high / 14.0,
        "board_low_rank": board_low / 14.0,
        "board_paired": float(len(unique_board_ranks) < len(board_ranks_list)),
        "board_distinct_ranks": len(unique_board_ranks) / 5.0,
        "board_max_suit_count": max(board_suits.values()) / 5.0,
        "known_max_suit_count": max(known_suits.values()) / 7.0,
        "made_hand_category": made_category,
        "hole_ranks_on_board": sum(rank in board_ranks for rank in hole_ranks) / 2.0,
        "hole_overcards_to_board": (
            sum(rank > board_high for rank in hole_ranks) / 2.0 if obs.board else 0.0
        ),
        "board_run_density": _run_density(unique_board_ranks),
        "pot_odds": obs.pot_odds,
        "call_fraction_of_stack": _bounded_ratio(obs.to_call, obs.stack),
        "stack_to_pot_log": _log_ratio(obs.stack + obs.to_call, pot_denominator),
        "stack_in_big_blinds_log": _log_ratio(obs.stack + obs.to_call, obs.big_blind),
        "pot_in_big_blinds_log": _log_ratio(obs.contestable_pot, obs.big_blind),
        "current_bet_fraction_of_pot": _bounded_ratio(obs.current_bet, pot_denominator),
        "min_raise_increment_fraction_of_pot": (
            _bounded_ratio(obs.min_raise_to - obs.current_bet - obs.to_call, pot_denominator, 100.0)
            if "raise" in obs.legal_actions else 0.0
        ),
        "max_raise_increment_fraction_of_pot": (
            _bounded_ratio(obs.max_raise_to - obs.current_bet - obs.to_call, pot_denominator, 100.0)
            if "raise" in obs.legal_actions else 0.0
        ),
        "players_active_fraction": obs.players_active / 8.0,
        "players_to_act_fraction": obs.players_to_act / 7.0,
        "table_size_fraction": obs.table_size / 8.0,
        "legal_fold": float("fold" in obs.legal_actions),
        "legal_check": float("check" in obs.legal_actions),
        "legal_call": float("call" in obs.legal_actions),
        "legal_raise": float("raise" in obs.legal_actions),
        "history_current_action_count": min(1.0, len(current_history) / 8.0),
        "history_current_raise_count": min(1.0, current_raise_count / 8.0),
        "history_current_call_count": min(1.0, current_call_count / 8.0),
        "history_current_fold_count": min(1.0, current_fold_count / 8.0),
        "history_preflop_raise_count": min(1.0, preflop_raise_count / 8.0),
        "history_raise_added_fraction_of_pot": _bounded_ratio(current_raise_added, pot_denominator),
    })
    # This is an internal contract: all model features are numeric and named,
    # and no raw observation extras can enter the learner.
    if tuple(features) != FEATURE_NAMES:
        raise RuntimeError("imitation feature order drifted from FEATURE_NAMES")
    if any(not math.isfinite(value) for value in features.values()):
        raise ValueError("observation produced a non-finite model feature")
    return features


def features(raw: Mapping[str, Any]) -> dict[str, float]:
    """Extract named numeric features from validated fields only.

    Extra fields such as hand/session/source IDs, expected labels, outcomes,
    opponent cards, future cards/actions, and seeds are ignored. ``player_id``
    is accepted by the observation protocol but is deliberately not modeled.
    """
    return _feature_map(Observation.from_dict(raw))


def _gini(counts: Mapping[str, int], total: int) -> float:
    if not total:
        return 0.0
    return 1.0 - sum((count / total) ** 2 for count in counts.values())


def _class_counts(examples: list[dict[str, Any]], indices: list[int], classes: tuple[str, ...]) -> dict[str, int]:
    counts = {action: 0 for action in classes}
    for index in indices:
        counts[examples[index]["action"]] += 1
    return counts


def _leaf(examples: list[dict[str, Any]], indices: list[int], classes: tuple[str, ...]) -> dict[str, Any]:
    counts = _class_counts(examples, indices, classes)
    sizes = [examples[index]["raise_ratio"] for index in indices
             if examples[index]["raise_ratio"] is not None]
    return {
        "leaf": True,
        "sample_count": len(indices),
        "action_counts": counts,
        "raise_ratio_median": median(sizes) if sizes else None,
    }


def _build_tree(
    examples: list[dict[str, Any]], indices: list[int], classes: tuple[str, ...],
    *, depth: int, max_depth: int, min_leaf: int,
) -> dict[str, Any]:
    counts = _class_counts(examples, indices, classes)
    leaf = _leaf(examples, indices, classes)
    if depth >= max_depth or len(indices) < min_leaf * 2 or sum(count > 0 for count in counts.values()) < 2:
        return leaf

    parent_impurity = _gini(counts, len(indices))
    best_gain = 0.0
    best_split: tuple[str, float, list[tuple[float, int]]] | None = None
    for feature_name in FEATURE_NAMES:
        ordered = sorted((examples[index]["features"][feature_name], index) for index in indices)
        left_counts = {action: 0 for action in classes}
        for offset in range(1, len(ordered)):
            action = examples[ordered[offset - 1][1]]["action"]
            left_counts[action] += 1
            if offset < min_leaf or len(ordered) - offset < min_leaf:
                continue
            left_value = ordered[offset - 1][0]
            right_value = ordered[offset][0]
            if left_value == right_value:
                continue
            right_counts = {name: counts[name] - left_counts[name] for name in classes}
            weighted = (
                offset * _gini(left_counts, offset)
                + (len(indices) - offset) * _gini(right_counts, len(indices) - offset)
            ) / len(indices)
            gain = parent_impurity - weighted
            if gain > best_gain + 1e-12:
                best_gain = gain
                threshold = left_value + (right_value - left_value) / 2.0
                best_split = (feature_name, threshold, ordered)

    if best_split is None:
        return leaf
    feature_name, threshold, ordered = best_split
    left_indices = [index for value, index in ordered if value <= threshold]
    right_indices = [index for value, index in ordered if value > threshold]
    return {
        "feature": feature_name,
        "threshold": threshold,
        "left": _build_tree(examples, left_indices, classes, depth=depth + 1,
                             max_depth=max_depth, min_leaf=min_leaf),
        "right": _build_tree(examples, right_indices, classes, depth=depth + 1,
                              max_depth=max_depth, min_leaf=min_leaf),
    }


def fit_model(
    rows,
    *,
    manifest_hash: str | None = None,
    include_development: bool = False,
    max_depth: int = 4,
    min_leaf: int = 2,
    smoothing: float = 1.0,
) -> dict[str, Any]:
    """Fit a compact smoothed decision tree and per-leaf median raise sizing.

    Rows carrying a ``partition`` field may come from ``train`` and, only when
    explicitly enabled, ``development``. Evaluation/holdout rows are rejected.
    Unpartitioned rows are accepted for small synthetic/offline experiments;
    corpus training should go through ``scripts/train_imitation.py``.
    """
    if type(max_depth) is not int or not 0 <= max_depth <= 8:
        raise ValueError("max_depth must be an integer from 0 through 8")
    if type(min_leaf) is not int or min_leaf < 1:
        raise ValueError("min_leaf must be a positive integer")
    if isinstance(smoothing, bool) or not isinstance(smoothing, (int, float)) or not math.isfinite(smoothing) or smoothing <= 0:
        raise ValueError("smoothing must be a finite positive number")
    if manifest_hash is not None and (not isinstance(manifest_hash, str) or not manifest_hash):
        raise ValueError("manifest_hash must be a nonempty string or None")

    training_rows = list(rows)
    if not training_rows:
        raise ValueError("at least one training row is required")
    examples = []
    observed_classes = set()
    raise_ratios = []
    group_ids = set()
    partition_names = set()
    for row in training_rows:
        if not isinstance(row, Mapping):
            raise ValueError("training rows must be objects")
        partition = row.get("partition")
        if partition is not None:
            if partition not in {"train", "development", "evaluation"}:
                raise ValueError("unknown training partition")
            if partition == "evaluation":
                raise ValueError("evaluation rows cannot be used to fit the model")
            if partition == "development" and not include_development:
                raise ValueError("development rows require include_development=True")
            partition_names.add(partition)
        raw_state = row.get("state")
        expected = row.get("expected")
        obs = Observation.from_dict(raw_state)
        if not isinstance(expected, Mapping) or expected.get("action") not in obs.legal_actions:
            raise ValueError("training row contains an illegal expected action or raise target")
        action = expected["action"]
        if action == "raise" and (
            type(expected.get("amount")) is not int
            or not obs.min_raise_to <= expected["amount"] <= obs.max_raise_to
        ):
            raise ValueError("training row contains an illegal expected action or raise target")
        ratio = None
        if action == "raise":
            denominator = max(1, obs.contestable_pot + obs.to_call)
            increment = max(0, expected["amount"] - (obs.current_bet + obs.to_call))
            ratio = increment / denominator
            raise_ratios.append(ratio)
        observed_classes.add(action)
        examples.append({"features": _feature_map(obs), "action": action, "raise_ratio": ratio})
        group_id = row.get("group_id", row.get("hand_id"))
        if group_id is not None:
            group_ids.add(str(group_id))

    classes = tuple(action for action in ACTION_ORDER if action in observed_classes)
    tree = _build_tree(examples, list(range(len(examples))), classes,
                       depth=0, max_depth=max_depth, min_leaf=min_leaf)
    return {
        "schema_version": 1,
        "algorithm": "smoothed-cart-with-leaf-median-raise-size",
        "feature_version": FEATURE_VERSION,
        "feature_names": list(FEATURE_NAMES),
        "classes": list(classes),
        "smoothing": float(smoothing),
        "tree": tree,
        "raise_ratio_median": median(raise_ratios) if raise_ratios else None,
        "metadata": {
            "manifest_hash": manifest_hash,
            "training_decisions": len(examples),
            "training_group_count": len(group_ids) if group_ids else None,
            "partitions_used": [name for name in ("train", "development") if name in partition_names],
            "development_included_explicitly": bool(include_development),
            "max_depth": max_depth,
            "min_leaf": min_leaf,
            "class_smoothing": "Laplace alpha over classes present in the fitting rows",
            "raise_size_target": "median (raise_to - current_bet - to_call) / (contestable_pot + to_call)",
        },
        "limits": [
            "A small selected source corpus is exploratory and cannot establish population agreement.",
            "Public action history and card strength features do not include private opponent ranges or live reads.",
            "Decision rows from one hand remain correlated even when source groups stay in one partition.",
        ],
    }


def _leaf_for(model: Mapping[str, Any], feature_map: Mapping[str, float]) -> tuple[Mapping[str, Any], list[dict[str, Any]]]:
    if model.get("schema_version") != 1 or model.get("feature_version") != FEATURE_VERSION:
        raise ValueError("unsupported imitation model schema or feature version")
    if model.get("feature_names") != list(FEATURE_NAMES):
        raise ValueError("imitation model features do not match this runtime")
    node = model.get("tree")
    path = []
    for _ in range(9):
        if not isinstance(node, Mapping):
            raise ValueError("imitation model tree node must be an object")
        if node.get("leaf") is True:
            return node, path
        feature_name = node.get("feature")
        threshold = node.get("threshold")
        if feature_name not in FEATURE_NAMES or isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold):
            raise ValueError("invalid imitation model split")
        branch = "left" if feature_map[feature_name] <= threshold else "right"
        path.append({"feature": feature_name, "threshold": float(threshold), "branch": branch})
        node = node.get(branch)
    raise ValueError("imitation model tree exceeds its supported depth")


def _safe_classes(model: Mapping[str, Any]) -> tuple[str, ...]:
    classes = model.get("classes")
    if not isinstance(classes, list) or not classes or any(item not in ACTIONS for item in classes):
        raise ValueError("imitation model classes are invalid")
    return tuple(action for action in ACTION_ORDER if action in classes)


def _fallback_action(legal: frozenset[str]) -> str:
    for action in TIE_BREAK_ORDER:
        if action in legal:
            return action
    raise ValueError("observation has no supported legal action")


def decide_with_model(raw: Mapping[str, Any], model: Mapping[str, Any]) -> dict[str, Any]:
    """Predict one legal action, a normalized legal-action distribution and size."""
    obs = Observation.from_dict(raw)
    feature_map = _feature_map(obs)
    leaf, path = _leaf_for(model, feature_map)
    classes = _safe_classes(model)
    try:
        alpha = float(model.get("smoothing"))
    except (TypeError, ValueError) as exc:
        raise ValueError("imitation model smoothing is invalid") from exc
    if not math.isfinite(alpha) or alpha <= 0:
        raise ValueError("imitation model smoothing is invalid")
    counts = leaf.get("action_counts")
    sample_count = leaf.get("sample_count")
    if not isinstance(counts, Mapping) or type(sample_count) is not int or sample_count < 0:
        raise ValueError("imitation model leaf counts are invalid")
    if any(type(counts.get(action, 0)) is not int or counts.get(action, 0) < 0 for action in classes):
        raise ValueError("imitation model leaf counts are invalid")

    denominator = sample_count + alpha * len(classes)
    class_probabilities = {
        action: (counts.get(action, 0) + alpha) / denominator for action in classes
    } if denominator else {}
    probabilities = {action: class_probabilities.get(action, 0.0)
                     for action in ACTION_ORDER if action in obs.legal_actions}
    total = sum(probabilities.values())
    if total > 0:
        probabilities = {action: value / total for action, value in probabilities.items()}
    else:
        fallback = _fallback_action(obs.legal_actions)
        probabilities = {action: float(action == fallback) for action in probabilities}

    action = max(TIE_BREAK_ORDER, key=lambda candidate: probabilities.get(candidate, -1.0))
    if action not in obs.legal_actions:
        action = _fallback_action(obs.legal_actions)

    raise_amount = 0
    selected_ratio = leaf.get("raise_ratio_median")
    if "raise" in obs.legal_actions and "raise" in classes:
        if selected_ratio is None:
            selected_ratio = model.get("raise_ratio_median")
        if selected_ratio is not None:
            if isinstance(selected_ratio, bool) or not isinstance(selected_ratio, (int, float)) or not math.isfinite(selected_ratio) or selected_ratio < 0:
                raise ValueError("imitation model raise sizing is invalid")
            pot_after_call = max(1, obs.contestable_pot + obs.to_call)
            target = obs.current_bet + obs.to_call + round(selected_ratio * pot_after_call)
            raise_amount = obs.raise_to(target)

    diagnostics = {
        "policy": "smoothed-cart-imitation-v1",
        "feature_version": FEATURE_VERSION,
        "leaf_sample_count": sample_count,
        "leaf_action_counts": {action: counts.get(action, 0) for action in classes},
        "split_path": path,
        "raise_size_ratio_median": selected_ratio,
        "raise_sizing_basis": "increment above call / contestable pot after call",
        "manifest_hash": (model.get("metadata") or {}).get("manifest_hash"),
    }
    return {
        "action": action,
        "amount": raise_amount if action == "raise" else 0,
        "probabilities": probabilities,
        "raise_amount": raise_amount,
        "diagnostics": diagnostics,
    }
