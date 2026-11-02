"""Optional evolved policy driven by an injected public-state equity estimator.

The estimator contract is ``estimator(hole_cards, board, players_active)`` and
its result is a uniform random-opponent showdown share conditional on the
actual number of active players. This module never loads, trains, or samples an
estimator; callers own that lifecycle and pass a ready callable in.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Callable

from . import evolution_strategies as strategies
from .fast import _history_actions
from .state import Observation


EquityEstimator = Callable[[tuple[str, str], tuple[str, ...], int], float]


def _validated_params(genome: strategies.Genome) -> dict[str, float]:
    """Return defaults plus bounded genes, including for a future family."""
    if not isinstance(genome, strategies.Genome):
        raise TypeError("make_equity_policy expects a Genome")
    values = dict(strategies.DEFAULT_PARAMS)
    for name, raw in genome.params.items():
        if name not in strategies.PARAMETER_BOUNDS:
            raise ValueError(f"unknown genome parameter {name!r}")
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError(f"parameter {name!r} must be a finite number")
        try:
            value = float(raw)
        except (OverflowError, TypeError, ValueError) as exc:
            raise ValueError(f"parameter {name!r} must be a finite number") from exc
        low, high = strategies.PARAMETER_BOUNDS[name]
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"parameter {name!r} must be finite and within [{low}, {high}]")
        values[name] = value
    return values


def _copy_metadata(value: Any, *, path: str = "model_metadata") -> Any:
    """Make a private, JSON-safe metadata snapshot for decision diagnostics."""
    if value is None or isinstance(value, (str, bool)):
        return value
    if type(value) is int:
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} values must be finite")
        return value
    if isinstance(value, Mapping):
        copied: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} keys must be strings")
            copied[key] = _copy_metadata(item, path=f"{path}.{key}")
        return copied
    if isinstance(value, (list, tuple)):
        return [_copy_metadata(item, path=f"{path}[]") for item in value]
    raise ValueError(f"{path} must contain only JSON-safe values")


def _validated_share(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("equity estimator must return a finite number in [0, 1]")
    try:
        share = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError("equity estimator must return a finite number in [0, 1]") from exc
    if not math.isfinite(share) or not 0.0 <= share <= 1.0:
        raise ValueError("equity estimator must return a finite number in [0, 1]")
    return share


def _postflop_decision(
    obs: Observation,
    params: Mapping[str, float],
    salt: int,
    estimator: EquityEstimator,
    model_metadata: Any,
    family: str,
) -> dict[str, Any]:
    # Use the existing helper only for public board texture, draw diagnostics,
    # and cheap exact-proof flags. Its non-exact share is intentionally unused.
    _heuristic_share, public_detail = strategies._public_equity(obs)
    try:
        estimate = estimator(obs.hole_cards, obs.board, obs.players_active)
    except Exception as exc:
        raise RuntimeError("equity estimator failed during a postflop decision") from exc
    raw_share = _validated_share(estimate)

    exact_tie = bool(public_detail["exact_shared_board_tie"])
    exact_nuts = bool(public_detail["exact_unbeatable_hand"])
    exact = exact_tie or exact_nuts
    # These proof cases supersede even a miscalibrated injected estimate. A
    # A shared board tie divides the pot among every active player.
    if exact_nuts:
        unpressured_equity = 1.0
    elif exact_tie:
        unpressured_equity = 1.0 / obs.players_active
    else:
        unpressured_equity = raw_share

    history = _history_actions(obs, obs.street)
    aggression = sum(
        str(item.get("action", "")).lower() in {"raise", "bet", "all-in", "all_in"}
        for item in history
    )
    pressure_discount = 0.0
    if obs.to_call and not exact:
        pressure_discount += 0.035
        if obs.to_call / max(1, obs.contestable_pot) >= 0.65:
            pressure_discount += 0.045
        if aggression:
            pressure_discount += min(0.07, 0.035 * aggression)
    decision_equity = max(0.0, min(1.0, unpressured_equity - pressure_discount))
    position_delta = strategies._position_delta(obs.position, params["position_sensitivity"])
    raise_amount = 0
    can_raise = "raise" in obs.legal_actions
    board_play = bool(public_detail["board_play"])
    effective_stack_bb = (obs.stack + obs.current_bet) / obs.big_blind
    short_stack = effective_stack_bb <= params["short_stack_bb"]

    # Do not report the fast heuristic's deductions as applied equity. Keep the
    # diagnostic features while naming the discarded penalties explicitly.
    diagnostics: dict[str, Any] = {
        key: value for key, value in public_detail.items()
        if key not in {"texture_penalty", "multiway_penalty", "equity_model"}
    }
    diagnostics.update({
        "policy": "equity-estimator-v1",
        "family": family,
        "street": obs.street,
        "equity_model": "injected_uniform_random_opponents",
        "estimator_raw_share": raw_share,
        "pressure_discount": pressure_discount,
        "decision_equity": decision_equity,
        "pot_odds": obs.pot_odds,
        "model_metadata": _copy_metadata(model_metadata),
        "public_heuristic_texture_penalty_ignored": public_detail.get("texture_penalty", 0.0),
        "public_heuristic_multiway_penalty_ignored": public_detail.get("multiway_penalty", 0.0),
        "multiway_equity_subtraction": 0.0,
        "aggression_level": aggression,
        "opponents_in_pot": obs.players_active - 1,
        "effective_stack_bb": round(effective_stack_bb, 2),
        "short_stack": short_stack,
        # Keep the legacy-style name useful to callers while preserving the
        # explicit estimator/final-equity fields above.
        "estimated_equity": decision_equity,
    })

    if obs.to_call > 0:
        range_margin = (
            0.02 + 0.015 * max(0, obs.players_active - 2)
            + params["postflop_call_margin"] + position_delta
        )
        continue_threshold = obs.pot_odds if exact else max(0.0, obs.pot_odds + range_margin)
        diagnostics["range_threshold_margin"] = 0.0 if exact else range_margin
        diagnostics["continue_threshold"] = continue_threshold
        value_cutoff = max(params["value_raise_threshold"], continue_threshold + 0.18)
        raise_probability = 0.0
        reason = "fold below pot-odds threshold"

        if can_raise and not board_play and decision_equity >= value_cutoff:
            raise_probability = params["raise_frequency"] * max(
                0.30, min(0.62, 0.30 + (decision_equity - 0.73) * 1.5),
            )
            reason = "value raise mix"
        elif (
            can_raise and not board_play and obs.players_active == 2
            and obs.position in strategies._LATE_POSITIONS
            and public_detail["draw_outs"] >= 8 and aggression == 0
            and decision_equity >= continue_threshold
        ):
            raise_probability = params["bluff_frequency"]
            reason = "semi-bluff mix"

        if raise_probability > 0.0:
            raise_amount = strategies._raise_target(
                obs, params, preflop=False, short_stack=short_stack,
            )
            if "call" in obs.legal_actions and decision_equity >= continue_threshold:
                weights = {"raise": raise_probability, "call": 1.0 - raise_probability}
                if raise_probability < 1.0 and not exact:
                    weights["call"] *= params["call_frequency"]
                    weights["fold"] = (1.0 - raise_probability) * (1.0 - params["call_frequency"])
            elif exact and decision_equity >= continue_threshold:
                # A favorable exact proof cannot be randomly folded, even if
                # an unusual legal-action projection omits call.
                weights = {"raise": 1.0} if can_raise else {strategies._free_action(obs): 1.0}
            else:
                weights = {"raise": raise_probability, "fold": 1.0 - raise_probability}
        elif "call" in obs.legal_actions and decision_equity >= continue_threshold:
            frequency = 1.0 if exact else params["call_frequency"]
            weights = {"call": frequency, "fold": 1.0 - frequency}
            reason = "continue by pot odds"
        elif exact and decision_equity >= continue_threshold and can_raise:
            weights = {"raise": 1.0}
            raise_amount = strategies._raise_target(
                obs, params, preflop=False, short_stack=short_stack,
            )
            reason = "exact favorable equity; call unavailable"
        elif "call" in obs.legal_actions and "fold" not in obs.legal_actions:
            weights = {"call": 1.0}
            reason = "call forced by legal actions"
        else:
            weights = {"fold": 1.0}
        diagnostics["reason"] = reason
    else:
        raise_probability = 0.0
        if can_raise and not board_play and decision_equity >= max(params["value_raise_threshold"], 0.62):
            raise_probability = params["raise_frequency"] * max(
                0.30, min(0.85, 0.42 + (decision_equity - 0.72) * 1.25),
            )
            reason = "value bet mix"
        elif (
            can_raise and not board_play and obs.players_active == 2
            and obs.position in strategies._LATE_POSITIONS and aggression == 0
            and not public_detail["board_paired"] and not public_detail["board_connected"]
        ):
            raise_probability = params["bluff_frequency"]
            reason = "position bluff mix"
        else:
            reason = "check"
        if can_raise and raise_probability > 0.0:
            weights = {"raise": raise_probability, strategies._free_action(obs): 1.0 - raise_probability}
            raise_amount = strategies._raise_target(
                obs, params, preflop=False, short_stack=short_stack,
            )
        else:
            weights = {strategies._free_action(obs): 1.0}
        diagnostics["reason"] = reason

    return strategies._decision(
        weights, obs, salt, raise_amount=raise_amount, diagnostics=diagnostics,
    )


def make_equity_policy(
    genome: strategies.Genome,
    estimator: EquityEstimator,
    model_metadata: Mapping[str, Any] | None = None,
):
    """Create a stateless per-table policy using an injected share estimator.

    The estimator is called only postflop and receives exactly the hero's two
    cards, the public board, and the current active-player count. Preflop uses
    the existing evolved policy implementation unchanged.
    """
    params = _validated_params(genome)
    if not callable(estimator):
        raise TypeError("estimator must be a callable accepting hole_cards, board, players_active")
    if model_metadata is not None and not isinstance(model_metadata, Mapping):
        raise ValueError("model_metadata must be a mapping of JSON-safe values")
    metadata = _copy_metadata(model_metadata if model_metadata is not None else {})
    salt = strategies._mix_salt(genome.bot_id, 401)

    def policy(raw: Mapping[str, Any]) -> dict[str, Any]:
        obs = strategies._evolved_observation(raw)
        decision_salt = salt + (101 if obs.street == "preflop" else 211 + len(obs.board))
        if obs.street == "preflop":
            return strategies._evolved_preflop(obs, params, decision_salt)
        return _postflop_decision(
            obs, params, decision_salt, estimator, metadata, genome.family,
        )

    return policy
