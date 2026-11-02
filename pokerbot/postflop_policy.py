"""Compact public-state postflop policy with a frozen fast-MAP preflop layer.

The postflop rules use the existing bounded made-hand/draw estimate, public
action order, price, and opponent aggression.  Training adjusts four explicit
cutoffs around conservative defaults; it never learns features or stores row,
hand, or source identifiers.  Runtime work is constant-size apart from the
existing hand-rank and suited-board helpers, and no runout enumeration occurs.
"""

from __future__ import annotations

import json
import math
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping

from .cards import rank_hand
from .fast import _postflop_equity
from .imitation import TIE_BREAK_ORDER, _bounded_ratio
from .map_policy import decide as _fast_map_decide
from .state import Observation, POSITIONS

ALGORITHM = "public-state-postflop-threshold-policy-v1"
FEATURE_VERSION = "public-postflop-state-v1"
_AGGRESSIVE = frozenset({"raise", "bet", "all-in", "all_in", "all in"})
_PREVIOUS_STREET = {"flop": "preflop", "turn": "flop", "river": "turn"}
_THRESHOLD_CANDIDATES = {
    "call_cushion": (0.00, 0.02, 0.04, 0.06, 0.08),
    "value_strength": (0.64, 0.68, 0.72, 0.76, 0.80),
    "continuation_strength": (0.30, 0.36, 0.42, 0.48, 0.54),
    "raise_strength": (0.78, 0.82, 0.86, 0.90, 0.94),
}
_DEFAULT_THRESHOLDS = {name: values[2] for name, values in _THRESHOLD_CANDIDATES.items()}
_DEFAULT_REGULARIZATION = 3.0


def _actor_is_hero(item: Mapping[str, Any], obs: Observation) -> bool | None:
    actor = item.get("player")
    if obs.player_id is not None and actor is not None:
        return type(actor) is type(obs.player_id) and actor == obs.player_id
    # MP represents multiple seats at seven/eight-player tables. Without IDs,
    # that label cannot identify which middle-position player took an action.
    position = item.get("position")
    if isinstance(position, str) and position in POSITIONS:
        if position == obs.position == "MP" and obs.table_size > 6:
            return None
        return position == obs.position
    return None


def _action(item: Mapping[str, Any]) -> str:
    value = item.get("action", "")
    return value.strip().lower() if isinstance(value, str) else ""


def _history_context(obs: Observation) -> dict[str, Any]:
    current = [item for item in obs.history
               if item.get("street", obs.street) == obs.street]
    previous_street = _PREVIOUS_STREET.get(obs.street)
    previous = [item for item in obs.history
                if previous_street is not None
                and item.get("street", obs.street) == previous_street]

    current_aggressions = [item for item in current if _action(item) in _AGGRESSIVE]
    previous_aggressions = [item for item in previous if _action(item) in _AGGRESSIVE]
    current_last = current[-1] if current else None
    current_last_role = _actor_is_hero(current_last, obs) if current_last is not None else None
    checked_to_hero = (
        current_last is not None and current_last_role is False
        and _action(current_last) == "check" and obs.to_call == 0
    )
    last_current_aggressor = current_aggressions[-1] if current_aggressions else None
    last_previous_aggressor = previous_aggressions[-1] if previous_aggressions else None
    return {
        "checked_to_hero": checked_to_hero,
        "last_action": _action(current_last) if current_last is not None else "",
        "hero_last_aggressor_current": (
            last_current_aggressor is not None
            and _actor_is_hero(last_current_aggressor, obs) is True
        ),
        "hero_aggressed_current": any(
            _actor_is_hero(item, obs) is True for item in current_aggressions
        ),
        "hero_last_aggressor_previous": (
            last_previous_aggressor is not None
            and _actor_is_hero(last_previous_aggressor, obs) is True
        ),
        "opponent_aggressions_current": sum(
            _actor_is_hero(item, obs) is False for item in current_aggressions
        ),
        "opponent_last_aggressor_previous": (
            last_previous_aggressor is not None
            and _actor_is_hero(last_previous_aggressor, obs) is False
        ),
    }


def _relative_hand(obs: Observation, detail: Mapping[str, Any]) -> dict[str, Any]:
    """Describe how the private cards support the made hand and board texture."""
    rank_value = {rank: value for value, rank in enumerate("23456789TJQKA", 2)}
    hole_ranks = tuple(rank_value[card[0]] for card in obs.hole_cards)
    board_ranks = tuple(rank_value[card[0]] for card in obs.board)
    board_high = max(board_ranks)
    category = int(detail["made_hand_category"])
    evaluated = rank_hand(obs.hole_cards + obs.board)
    primary = int(evaluated[1]) if len(evaluated) > 1 else 0
    # Fast's evaluator reports category and rank only. This relative-strength
    # signal separates private top pair/overpairs from a pair already on board.
    pocket_pair = hole_ranks[0] == hole_ranks[1]
    overpair = pocket_pair and hole_ranks[0] > board_high
    top_pair = category == 1 and primary == board_high and board_high in hole_ranks
    private_pair = category == 1 and primary in hole_ranks
    board_pair = category == 1 and not private_pair
    overcards = sum(rank > board_high for rank in hole_ranks)
    relative = 0.0
    if category >= 2:
        relative = 0.72 + 0.04 * min(4, category - 2)
    elif overpair:
        relative = 0.67
    elif top_pair:
        relative = 0.60
    elif private_pair:
        relative = 0.47
    elif board_pair:
        relative = 0.34
    else:
        relative = 0.22 + 0.035 * overcards
    if len(set(board_ranks)) < len(board_ranks):
        relative -= 0.025
    return {
        "relative_hand_strength": max(0.0, min(1.0, relative)),
        "made_hand_category": category,
        "top_pair": top_pair,
        "overpair": overpair,
        "board_pair_only": board_pair,
        "private_made_hand": category > 0 and not board_pair,
        "overcards": overcards,
    }


def _context(raw: Mapping[str, Any] | Observation) -> dict[str, Any]:
    obs = raw if isinstance(raw, Observation) else Observation.from_dict(raw)
    equity, detail = _postflop_equity(obs)
    history = _history_context(obs)
    relative = _relative_hand(obs, detail)
    pot_after_call = max(1, obs.contestable_pot + obs.to_call)
    size_ratio = _bounded_ratio(obs.to_call, max(1, obs.contestable_pot), 100.0)
    pressure = 0.025 * max(0, obs.players_active - 2)
    if obs.to_call:
        pressure += 0.025
        pressure += 0.04 if size_ratio >= 0.75 else 0.025 if size_ratio >= 0.40 else 0.01
        pressure += min(0.08, history["opponent_aggressions_current"] * 0.035)
        pressure += 0.025 if history["opponent_last_aggressor_previous"] else 0.0
        pressure += 0.025 if history["hero_aggressed_current"] else 0.0
        pressure += 0.01 if obs.players_to_act > 0 else 0.0
    adjusted = max(0.0, min(1.0, equity - min(0.22, pressure)))
    return {
        "obs": obs,
        "equity": equity,
        "adjusted_strength": adjusted,
        "pressure": min(0.22, pressure),
        "pot_odds": _bounded_ratio(obs.to_call, pot_after_call),
        "bet_to_pot_ratio": size_ratio,
        "history": history,
        "relative": relative,
        "detail": detail,
    }


def _dry_board(context: Mapping[str, Any]) -> bool:
    obs = context["obs"]
    board_ranks = [card[0] for card in obs.board]
    suit_counts = {suit: sum(card[1] == suit for card in obs.board) for suit in "cdhs"}
    return (
        len(set(board_ranks)) == len(board_ranks)
        and not context["detail"].get("board_connected", False)
        and not context["detail"].get("board_paired", False)
        and int(context["detail"].get("draw_outs", 0)) < 8
        and max(suit_counts.values()) < 3
    )


def _raise_target(obs: Observation, *, strength: float) -> int:
    """Choose a legal pot-sized total bet using overflow-safe integer math."""
    effective_pot = max(obs.big_blind, obs.contestable_pot)
    if obs.to_call == 0:
        if obs.stack * 10 <= effective_pot * 7:
            return obs.max_raise_to
        numerator, denominator = (55, 100) if strength >= 0.78 else (38, 100)
        increment = max(obs.big_blind, round(Fraction(effective_pot * numerator, denominator)))
        target = obs.current_bet + increment
    else:
        pot_after_call = max(1, obs.contestable_pot + obs.to_call)
        if obs.stack * 100 <= pot_after_call * 65:
            return obs.max_raise_to
        numerator, denominator = (82, 100) if strength >= 0.82 else (62, 100)
        extra = max(obs.to_call, round(Fraction(pot_after_call * numerator, denominator)))
        target = obs.current_bet + obs.to_call + extra
    return max(obs.min_raise_to, min(obs.max_raise_to, target))


def _select_action(context: Mapping[str, Any], thresholds: Mapping[str, float]) -> str:
    obs: Observation = context["obs"]
    legal = obs.legal_actions
    strength = context["adjusted_strength"]
    relative = context["relative"]
    history = context["history"]
    detail = context["detail"]

    if obs.to_call == 0:
        if "raise" not in legal:
            return "check" if "check" in legal else next(a for a in TIE_BREAK_ORDER if a in legal)
        # The value region includes useful one-pair hands on safe boards, while
        # explicit board-play hands avoid betting a tied shared runout.
        strong_value = (
            not detail.get("board_play", False)
            and strength >= thresholds["value_strength"]
            and (relative["made_hand_category"] >= 1 or detail.get("exact_unbeatable_hand", False))
        )
        thin_value = (
            not detail.get("board_play", False)
            and (relative["top_pair"] or relative["overpair"])
            and history["checked_to_hero"] and obs.players_active <= 3
            and _dry_board(context)
            and strength >= max(0.52, thresholds["value_strength"] - 0.12)
        )
        if detail.get("exact_unbeatable_hand", False) or strong_value or thin_value:
            return "raise"

        # A continuation bet is available only with prior-street initiative,
        # no current-street opposing aggression, and action reaching an
        # in-position hero. A dry board supplies range pressure for a small bet.
        initiative = history["hero_last_aggressor_previous"]
        no_opponent_bet = history["opponent_aggressions_current"] == 0
        in_position_or_checked_to = obs.players_to_act == 0 or history["checked_to_hero"]
        cbet_spot = (
            obs.street in {"flop", "turn"} and initiative and no_opponent_bet
            and obs.players_active <= 3 and in_position_or_checked_to
            and _dry_board(context)
        )
        if cbet_spot and strength >= thresholds["continuation_strength"]:
            return "raise"
        return "check" if "check" in legal else next(a for a in TIE_BREAK_ORDER if a in legal)

    if "raise" in legal and not detail.get("board_play", False):
        if (detail.get("exact_unbeatable_hand", False)
                or strength >= thresholds["raise_strength"]):
            return "raise"
        # A strong open-ended/flush draw can semi-bluff against a single
        # opponent when the current price and aggression history remain modest.
        draw_outs = int(detail.get("draw_outs", 0))
        semi_bluff = (
            obs.players_active == 2 and draw_outs >= 8
            and history["opponent_aggressions_current"] <= 1
            and context["bet_to_pot_ratio"] <= 0.75
            and strength >= max(0.36, context["pot_odds"] + thresholds["call_cushion"])
        )
        if semi_bluff:
            return "raise"
    if "call" in legal:
        if strength >= context["pot_odds"] + thresholds["call_cushion"]:
            return "call"
        if "fold" not in legal:
            return "call"
        return "fold"
    if "check" in legal:
        return "check"
    return next(a for a in TIE_BREAK_ORDER if a in legal)


def _threshold_values(value: Any) -> dict[str, float]:
    if not isinstance(value, Mapping) or set(value) != set(_THRESHOLD_CANDIDATES):
        raise ValueError("postflop model thresholds are invalid")
    output = {}
    for name, candidates in _THRESHOLD_CANDIDATES.items():
        raw = value[name]
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError("postflop model threshold must be numeric")
        try:
            number = float(raw)
        except (OverflowError, TypeError, ValueError) as exc:
            raise ValueError("postflop model threshold must be finite") from exc
        if not math.isfinite(number) or number not in candidates:
            raise ValueError("postflop model threshold is outside its fixed candidate set")
        output[name] = number
    return output


def _reject_uncertain_evidence(row: Mapping[str, Any]) -> None:
    if row.get("fresh_holdout") is True:
        raise ValueError("evaluation/holdout rows cannot fit the postflop model")
    quality = row.get("data_quality") or {}
    if not isinstance(quality, Mapping):
        raise ValueError("data_quality must be an object")
    evidence = row.get("evidence_tier", "")
    admission = row.get("admission_status", "")
    quality_status = quality.get("status", "")
    if evidence == "video_snapshot_with_rounded_or_missing_context":
        raise ValueError("partial or pending evidence cannot fit the postflop model")
    for value in (admission, quality_status):
        if isinstance(value, str) and ("partial" in value.casefold() or "pending" in value.casefold()):
            raise ValueError("partial or pending evidence cannot fit the postflop model")
    reviewed_admission = (
        admission == "admitted_source_reviewed_development_only"
        and row.get("policy_use") == "development_only"
        and row.get("fresh_holdout") is False
    )
    if isinstance(evidence, str) and (
        "partial" in evidence.casefold()
        or ("pending" in evidence.casefold() and not reviewed_admission)
    ):
        raise ValueError("partial or pending evidence cannot fit the postflop model")


def _training_objective(contexts, labels, thresholds, regularization):
    correct = 0
    for context, label in zip(contexts, labels):
        correct += int(_select_action(context, thresholds) == label)
    if not contexts:
        return 0.0
    distance = sum(
        (_THRESHOLD_CANDIDATES[name].index(thresholds[name]) - 2) ** 2
        for name in _THRESHOLD_CANDIDATES
    )
    return correct - regularization * distance


def fit_model(rows, *, include_development: bool = False,
              regularization: float = _DEFAULT_REGULARIZATION) -> dict[str, Any]:
    """Fit four conservative cutoffs using only the supplied training rows.

    The fitter performs two short coordinate passes over fixed, theory-centered
    candidate sets. A move one step from the default costs ``regularization``
    equivalent correct decisions, so small and unstable gains retain the prior.
    """
    if type(include_development) is not bool:
        raise ValueError("include_development must be a boolean")
    try:
        reg = float(regularization)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError("regularization must be finite and between zero and 100") from exc
    if (isinstance(regularization, bool) or not isinstance(regularization, (int, float))
            or not math.isfinite(reg) or not 0.0 <= reg <= 100.0):
        raise ValueError("regularization must be finite and between zero and 100")
    training_rows = list(rows)
    if not training_rows:
        raise ValueError("at least one training row is required")

    contexts = []
    labels = []
    partition_names = set()
    postflop_count = 0
    for row in training_rows:
        if not isinstance(row, Mapping):
            raise ValueError("training rows must be objects")
        partition = row.get("partition")
        marked_development = (row.get("policy_use") == "development_only"
                              or row.get("admission_status") == "admitted_source_reviewed_development_only")
        if marked_development:
            if partition == "train":
                raise ValueError("development-only evidence cannot be relabeled train")
            if not include_development:
                raise ValueError("development rows require include_development=True")
            partition_names.add("development")
        if partition is not None:
            if not isinstance(partition, str) or partition not in {"train", "development", "evaluation"}:
                raise ValueError("unknown training partition")
            if partition == "evaluation":
                raise ValueError("evaluation rows cannot fit the postflop model")
            if partition == "development" and not include_development:
                raise ValueError("development rows require include_development=True")
            partition_names.add(partition)
        _reject_uncertain_evidence(row)
        obs = Observation.from_dict(row.get("state"))
        expected = row.get("expected")
        if (not isinstance(expected, Mapping) or not isinstance(expected.get("action"), str)
                or expected.get("action") not in obs.legal_actions):
            raise ValueError("training row contains an illegal expected action")
        action = expected["action"]
        if action == "raise":
            amount = expected.get("amount")
            if type(amount) is not int or not obs.min_raise_to <= amount <= obs.max_raise_to:
                raise ValueError("training row contains an illegal raise target")
        if obs.street != "preflop":
            contexts.append(_context(obs))
            labels.append(action)
            postflop_count += 1

    thresholds = dict(_DEFAULT_THRESHOLDS)
    for _ in range(2):
        for name, candidates in _THRESHOLD_CANDIDATES.items():
            best = thresholds[name]
            best_score = _training_objective(contexts, labels, thresholds, reg)
            for candidate in candidates:
                proposal = dict(thresholds)
                proposal[name] = candidate
                score = _training_objective(contexts, labels, proposal, reg)
                # Deterministic tie-breaking prefers the theoretical default.
                candidate_key = (abs(candidates.index(candidate) - 2), candidates.index(candidate))
                best_key = (abs(candidates.index(best) - 2), candidates.index(best))
                if score > best_score + 1e-12 or (abs(score - best_score) <= 1e-12 and candidate_key < best_key):
                    best, best_score = candidate, score
            thresholds[name] = best

    model = {
        "schema_version": 1,
        "algorithm": ALGORITHM,
        "feature_version": FEATURE_VERSION,
        "thresholds": thresholds,
        "metadata": {
            "training_decisions": len(training_rows),
            "training_postflop_decisions": postflop_count,
            "partitions_used": [name for name in ("train", "development") if name in partition_names],
            "development_included_explicitly": include_development,
            "regularization": reg,
            "default_thresholds": dict(_DEFAULT_THRESHOLDS),
        },
    }
    _validate_model(model)
    return model


def _validate_model(model: Any) -> None:
    if not isinstance(model, Mapping) or set(model) != {
            "schema_version", "algorithm", "feature_version", "thresholds", "metadata"}:
        raise ValueError("postflop model fields are invalid")
    if (type(model.get("schema_version")) is not int or model.get("schema_version") != 1
            or model.get("algorithm") != ALGORITHM
            or model.get("feature_version") != FEATURE_VERSION):
        raise ValueError("unsupported postflop model schema")
    _threshold_values(model.get("thresholds"))
    metadata = model.get("metadata")
    expected_metadata = {
        "training_decisions", "training_postflop_decisions",
        "partitions_used", "development_included_explicitly", "regularization",
        "default_thresholds",
    }
    if not isinstance(metadata, Mapping) or set(metadata) != expected_metadata:
        raise ValueError("postflop model metadata is invalid")
    for field in ("training_decisions", "training_postflop_decisions"):
        if type(metadata.get(field)) is not int or metadata[field] < 0:
            raise ValueError("postflop model training counts are invalid")
    if metadata["training_postflop_decisions"] > metadata["training_decisions"]:
        raise ValueError("postflop model training counts are inconsistent")
    if type(metadata.get("development_included_explicitly")) is not bool:
        raise ValueError("postflop model development metadata is invalid")
    parts = metadata.get("partitions_used")
    if (not isinstance(parts, list)
            or any(not isinstance(part, str) or part not in {"train", "development"} for part in parts)
            or parts != [part for part in ("train", "development") if part in parts]):
        raise ValueError("postflop model partitions are invalid")
    if "development" in parts and not metadata["development_included_explicitly"]:
        raise ValueError("postflop model development metadata is inconsistent")
    reg = metadata.get("regularization")
    try:
        reg_value = float(reg)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError("postflop model regularization is invalid") from exc
    if (isinstance(reg, bool) or not isinstance(reg, (int, float))
            or not math.isfinite(reg_value) or not 0.0 <= reg_value <= 100.0):
        raise ValueError("postflop model regularization is invalid")
    defaults = metadata.get("default_thresholds")
    if _threshold_values(defaults) != _DEFAULT_THRESHOLDS:
        raise ValueError("postflop model prior thresholds are invalid")


def load_model(path: str | Path) -> dict[str, Any]:
    """Load and validate a JSON policy model."""
    try:
        model = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("unable to load postflop model JSON") from exc
    _validate_model(model)
    return model


def decide(raw: Mapping[str, Any], model: Mapping[str, Any]) -> dict[str, Any]:
    """Return a legal deterministic action and legal total raise size."""
    _validate_model(model)
    obs = Observation.from_dict(raw)
    if obs.street == "preflop":
        result = _fast_map_decide(raw)
        return {**result, "diagnostics": {**result["diagnostics"], "policy": "postflop-overlay-fast-map-preflop-v1"}}

    context = _context(obs)
    thresholds = _threshold_values(model["thresholds"])
    action = _select_action(context, thresholds)
    raise_amount = 0
    if action == "raise":
        raise_amount = _raise_target(obs, strength=context["adjusted_strength"])
    probabilities = {legal: float(legal == action) for legal in sorted(obs.legal_actions)}
    return {
        "action": action,
        "amount": raise_amount if action == "raise" else 0,
        "raise_amount": raise_amount,
        "probabilities": probabilities,
        "diagnostics": {
            "policy": ALGORITHM,
            "feature_version": FEATURE_VERSION,
            "street": obs.street,
            "estimated_strength_vs_random": round(context["equity"], 4),
            "adjusted_strength_vs_range": round(context["adjusted_strength"], 4),
            "relative_hand_strength": round(context["relative"]["relative_hand_strength"], 4),
            "pot_odds": round(context["pot_odds"], 4),
            "bet_to_pot_ratio": round(context["bet_to_pot_ratio"], 4),
            "range_pressure_discount": round(context["pressure"], 4),
            "checked_to_hero": context["history"]["checked_to_hero"],
            "last_public_action": context["history"]["last_action"],
            "hero_last_aggressor_current": context["history"]["hero_last_aggressor_current"],
            "hero_aggressed_current": context["history"]["hero_aggressed_current"],
            "hero_last_aggressor_previous": context["history"]["hero_last_aggressor_previous"],
            "opponent_aggressions_current": context["history"]["opponent_aggressions_current"],
            "thresholds": thresholds,
            "reason": _reason(context, thresholds, action),
        },
    }


def _reason(context: Mapping[str, Any], thresholds: Mapping[str, float], action: str) -> str:
    if action == "raise":
        if context["obs"].to_call == 0:
            if context["detail"].get("exact_unbeatable_hand", False):
                return "unbeatable value bet"
            if context["adjusted_strength"] >= thresholds["value_strength"]:
                return "thin or strong value bet"
            relative = context["relative"]
            if (context["history"]["checked_to_hero"] and context["obs"].players_active <= 3
                    and (relative["top_pair"] or relative["overpair"])
                    and _dry_board(context)):
                return "thin value after a check-through"
            return "in-position continuation bet with initiative"
        if context["adjusted_strength"] >= thresholds["raise_strength"]:
            return "strong value raise"
        return "heads-up draw semi-bluff"
    if action == "call":
        return "continue with adjusted strength above price"
    if action == "fold":
        return "fold under conservative range pressure"
    return "check without a value or continuation-bet condition"
