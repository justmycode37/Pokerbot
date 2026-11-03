"""Bounded, public-information-only strategy genomes for self-play evolution.

The evolved family uses the repository's offline preflop priors and fast
postflop hand/draw heuristic. It keeps no state between decisions, so a policy
factory result is safe to use for one table and unrelated tables cannot affect
one another.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
import random
import threading
from typing import Any, Mapping

from . import fast
from .preflop import opening_threshold, preflop_equity
from .state import Observation


FAMILIES = frozenset({
    "evolved", "adaptive", "calibrated", "corrected-calibrated", "saved", "fast", "calling-station", "tight-passive", "random-legal",
})

# Bounds are deliberately broad enough for distinct playing styles, while
# excluding degenerate policies that always fold, call, or jam.
PARAMETER_BOUNDS: dict[str, tuple[float, float]] = {
    "opening_shift": (-0.12, 0.12),
    "opening_frequency": (0.45, 1.0),
    "call_margin": (-0.08, 0.10),
    "postflop_call_margin": (-0.02, 0.08),
    "call_frequency": (0.45, 1.0),
    "value_raise_threshold": (0.56, 0.84),
    "raise_frequency": (0.20, 1.0),
    "bet_size": (0.15, 0.90),
    "bluff_frequency": (0.0, 0.24),
    "short_stack_bb": (4.0, 18.0),
    "short_stack_cutoff": (0.45, 0.76),
    "multiway_penalty": (0.015, 0.10),
    "position_sensitivity": (0.0, 0.045),
}

DEFAULT_PARAMS: dict[str, float] = {
    "opening_shift": 0.0,
    "opening_frequency": 0.88,
    "call_margin": 0.0,
    "postflop_call_margin": 0.0,
    "call_frequency": 0.95,
    "value_raise_threshold": 0.69,
    "raise_frequency": 0.62,
    "bet_size": 0.50,
    "bluff_frequency": 0.05,
    "short_stack_bb": 10.0,
    "short_stack_cutoff": 0.56,
    "multiway_penalty": 0.045,
    "position_sensitivity": 0.018,
}

_ACTION_ORDER = ("raise", "call", "check", "fold")
_EARLY_POSITIONS = frozenset({"UTG", "MP"})
_LATE_POSITIONS = frozenset({"CO", "BTN"})


class _FrozenParams(dict):
    """A JSON-friendly dict that cannot be mutated after Genome creation."""

    def _immutable(self, *args, **kwargs):
        raise TypeError("genome params are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


def _validate_generation(generation: Any) -> int:
    if type(generation) is not int or generation < 0:
        raise ValueError("generation must be an integer >= 0")
    return generation


def _clean_params(params: Any, family: str) -> _FrozenParams:
    if not isinstance(params, Mapping):
        raise ValueError("params must be an object")
    unknown = set(params) - set(PARAMETER_BOUNDS)
    if unknown:
        raise ValueError(f"unknown genome parameter(s): {', '.join(sorted(map(str, unknown)))}")
    if family not in {"evolved", "adaptive", "calibrated", "corrected-calibrated"} and params:
        raise ValueError(f"family {family!r} does not accept strategy parameters")
    values: dict[str, float] = {}
    for name, raw_value in params.items():
        if not isinstance(name, str):
            raise ValueError("parameter names must be strings")
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            raise ValueError(f"parameter {name!r} must be a finite number")
        value = float(raw_value)
        low, high = PARAMETER_BOUNDS[name]
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"parameter {name!r} must be finite and within [{low}, {high}]")
        values[name] = value
    frozen = _FrozenParams()
    dict.__init__(frozen, values)
    return frozen


@dataclass(frozen=True)
class Genome:
    """One immutable strategy description with JSON-safe serialization."""

    bot_id: str
    family: str = "evolved"
    params: dict[str, float] = field(default_factory=dict)
    parents: tuple[str, ...] = ()
    generation: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.bot_id, str) or not self.bot_id.strip():
            raise ValueError("bot_id must be a nonempty string")
        if not isinstance(self.family, str) or self.family not in FAMILIES:
            raise ValueError(f"family must be one of {', '.join(sorted(FAMILIES))}")
        clean_params = _clean_params(self.params, self.family)
        if not isinstance(self.parents, (list, tuple)) or any(
            not isinstance(parent, str) or not parent.strip() for parent in self.parents
        ):
            raise ValueError("parents must be a sequence of nonempty strings")
        _validate_generation(self.generation)
        object.__setattr__(self, "params", clean_params)
        object.__setattr__(self, "parents", tuple(self.parents))

    def to_dict(self) -> dict[str, Any]:
        return {
            "bot_id": self.bot_id,
            "family": self.family,
            "params": {name: float(value) for name, value in self.params.items()},
            "parents": list(self.parents),
            "generation": self.generation,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Genome":
        if not isinstance(raw, Mapping):
            raise ValueError("genome must be an object")
        unknown = set(raw) - {"bot_id", "family", "params", "parents", "generation"}
        if unknown:
            raise ValueError(f"unknown genome field(s): {', '.join(sorted(map(str, unknown)))}")
        return cls(
            bot_id=raw.get("bot_id"),
            family=raw.get("family", "evolved"),
            params=raw.get("params", {}),
            parents=raw.get("parents", ()),
            generation=raw.get("generation", 0),
        )


def _genes(genome: Genome) -> dict[str, float]:
    values = dict(DEFAULT_PARAMS)
    if genome.family in {"evolved", "adaptive", "calibrated", "corrected-calibrated"}:
        values.update(genome.params)
    return values


def new_random(rng: random.Random, bot_id: str, generation: int = 0) -> Genome:
    """Create a diverse, bounded genome using only the caller's RNG."""
    if not hasattr(rng, "uniform"):
        raise TypeError("rng must provide random.Random's uniform method")
    _validate_generation(generation)
    params = {
        name: round(rng.uniform(low, high), 6)
        for name, (low, high) in PARAMETER_BOUNDS.items()
    }
    return Genome(bot_id=bot_id, params=params, generation=generation)


def breed(
    parent: Genome,
    other: Genome | None,
    rng: random.Random,
    bot_id: str,
    generation: int,
) -> Genome:
    """Crossover optional parents, then mutate at least one bounded gene."""
    if not isinstance(parent, Genome) or (other is not None and not isinstance(other, Genome)):
        raise TypeError("breed parents must be Genome instances")
    if not hasattr(rng, "random") or not hasattr(rng, "gauss"):
        raise TypeError("rng must provide random.Random methods")
    _validate_generation(generation)
    first = _genes(parent)
    second = _genes(other) if other is not None else first
    child = {
        name: (second[name] if other is not None and rng.random() < 0.5 else first[name])
        for name in PARAMETER_BOUNDS
    }

    mutated: set[str] = set()
    for name, (low, high) in PARAMETER_BOUNDS.items():
        if rng.random() < 0.30:
            child[name] = min(high, max(low, child[name] + rng.gauss(0.0, (high - low) * 0.12)))
            mutated.add(name)
    if not mutated:
        mutated.add(rng.choice(tuple(PARAMETER_BOUNDS)))
    # Rounding can erase a very small Gaussian step or a step at a boundary.
    # Ensure a reproducible, nontrivial offspring difference in every breed.
    mutation_name = rng.choice(tuple(sorted(mutated)))
    low, high = PARAMETER_BOUNDS[mutation_name]
    old = child[mutation_name]
    step = (high - low) * 0.04
    direction = 1.0 if old <= (low + high) / 2 else -1.0
    nudged = min(high, max(low, old + direction * step))
    if abs(nudged - old) < (high - low) * 0.01:
        nudged = high if old < high else low
    child[mutation_name] = nudged
    child = {name: round(value, 6) for name, value in child.items()}
    if child == first or (other is not None and child == second):
        for name, (low, high) in PARAMETER_BOUNDS.items():
            candidates = (low, high, (low + high) / 2.0)
            replacement = next((
                round(value, 6) for value in candidates
                if round(value, 6) != first[name]
                and (other is None or round(value, 6) != second[name])
            ), None)
            if replacement is not None:
                child[name] = replacement
                break

    parents = (parent.bot_id,) if other is None else (parent.bot_id, other.bot_id)
    families = [item.family for item in (parent, other)
                if item is not None and item.family in {"evolved", "adaptive", "calibrated", "corrected-calibrated"}]
    family = rng.choice(families) if families else "evolved"
    return Genome(bot_id=bot_id, family=family, params=child, parents=parents, generation=generation)


def anchor_genomes() -> list[Genome]:
    """Return stable reference families for self-play evaluation."""
    return [
        Genome("anchor-saved", family="saved"),
        Genome("anchor-fast", family="fast"),
        Genome("anchor-station", family="calling-station"),
        Genome("anchor-tight", family="tight-passive"),
        Genome("anchor-random", family="random-legal"),
    ]


def _safe_payload(obs: Observation) -> dict[str, Any]:
    """Rebuild a clean public observation after the protocol whitelist pass."""
    return {
        "hole_cards": list(obs.hole_cards),
        "board": list(obs.board),
        "pot": obs.pot,
        "to_call": obs.to_call,
        "stack": obs.stack,
        "current_bet": obs.current_bet,
        "min_raise_to": obs.min_raise_to,
        "max_raise_to": obs.max_raise_to,
        "big_blind": obs.big_blind,
        "position": obs.position,
        "players_active": obs.players_active,
        "players_to_act": obs.players_to_act,
        "legal_actions": [action for action in _ACTION_ORDER if action in obs.legal_actions],
        "street": obs.street,
        "seed": obs.seed,
        "history": [dict(action) for action in obs.history],
        "player_id": obs.player_id,
        "contestable_pot": obs.contestable_pot,
        "table_size": obs.table_size,
    }


def _mix_salt(bot_id: str, salt: int) -> int:
    value = 0x811C9DC5 ^ salt
    for byte in bot_id.encode("utf-8"):
        value = ((value ^ byte) * 0x01000193) & 0xFFFFFFFF
    return value


def _normalise(weights: Mapping[str, float], obs: Observation) -> dict[str, float]:
    kept = {
        action: max(0.0, float(weights.get(action, 0.0)))
        for action in _ACTION_ORDER if action in obs.legal_actions
    }
    total = sum(kept.values())
    if total <= 0:
        fallback = "check" if "check" in obs.legal_actions else "call" if "call" in obs.legal_actions else "fold"
        kept = {action: float(action == fallback) for action in kept}
        total = 1.0
    return {action: probability / total for action, probability in kept.items()}


def _decision(
    probabilities: Mapping[str, float], obs: Observation, salt: int, *,
    raise_amount: int = 0, diagnostics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    probs = _normalise(probabilities, obs)
    action = fast._select(probs, obs, salt)
    if action not in obs.legal_actions:
        action = "check" if "check" in obs.legal_actions else "call" if "call" in obs.legal_actions else "fold"
    if action != "raise":
        amount = 0
    else:
        amount = int(raise_amount)
        if not obs.min_raise_to <= amount <= obs.max_raise_to:
            amount = obs.raise_to(amount)
    details = dict(diagnostics or {})
    details["raise_amount"] = int(raise_amount if "raise" in obs.legal_actions else 0)
    return {
        "action": action,
        "amount": amount,
        "raise_amount": int(raise_amount if "raise" in obs.legal_actions else 0),
        "probabilities": probs,
        "diagnostics": details,
    }


def _raise_target(
    obs: Observation,
    params: Mapping[str, float],
    *,
    preflop: bool,
    aggression: int = 0,
    unopened: bool = False,
    short_stack: bool = False,
) -> int:
    """Choose a legal street-total raise size using the mutable sizing gene."""
    size = params["bet_size"]
    if short_stack:
        return obs.max_raise_to
    if preflop:
        if unopened or obs.to_call == 0:
            target = round((1.75 + 1.25 * size) * obs.big_blind)
        else:
            call_total = obs.current_bet + obs.to_call
            multiplier = max(2.0, 2.0 + 1.8 * size - 0.2 * max(0, aggression - 1))
            target = round(call_total * multiplier)
        return obs.raise_to(target)

    effective_pot = max(obs.big_blind, obs.contestable_pot)
    if obs.to_call == 0:
        fraction = 0.20 + 0.70 * size
        target = obs.current_bet + max(obs.big_blind, round(effective_pot * fraction))
    else:
        call_total = obs.current_bet + obs.to_call
        fraction = 0.35 + 0.70 * size
        extra = max(obs.to_call, round((obs.contestable_pot + obs.to_call) * fraction))
        target = call_total + extra
    return obs.raise_to(target)


def _position_delta(position: str, sensitivity: float) -> float:
    if position in _EARLY_POSITIONS or position == "SB":
        return sensitivity
    if position in _LATE_POSITIONS:
        return -sensitivity
    return 0.0


def _free_action(obs: Observation) -> str:
    if "check" in obs.legal_actions:
        return "check"
    if "call" in obs.legal_actions:
        return "call"
    return "fold"


def _public_equity(obs: Observation) -> tuple[float, dict[str, Any]]:
    """Use public priors, correcting cheaply provable shared river nuts."""
    equity, detail = fast._postflop_equity(obs)
    if len(obs.board) != 5:
        return equity, detail
    board_rank = fast.rank_hand(obs.board)
    rainbow_broadway = (board_rank == (4, 14)
                        and max(sum(card[1] == suit for card in obs.board) for suit in "cdhs") <= 2)
    quad_nuts = (board_rank[0] == 7
                 and board_rank[2] == (13 if board_rank[1] == 14 else 14))
    if rainbow_broadway or quad_nuts:
        return 1 / obs.players_active, {
            **detail, "board_play": True, "exact_shared_board_tie": True,
            "exact_unbeatable_hand": False, "equity_model": "provably_shared_river_nuts",
            "texture_penalty": 0.0, "multiway_penalty": 0.0,
        }
    return equity, detail


def _evolved_observation(raw: Mapping[str, Any]) -> Observation:
    obs = Observation.from_dict(raw)
    if obs.table_size == 2 and obs.position == "SB":
        obs = replace(obs, position="BTN")
    return obs


def _evolved_preflop(
    obs: Observation, params: Mapping[str, float], salt: int,
) -> dict[str, Any]:
    equity = preflop_equity(obs.hole_cards)
    name = fast.hand_class(obs.hole_cards)
    raises = fast._raise_count(obs, "preflop")
    entered, limpers = fast._preflop_entry_counts(obs)
    highest_bet = obs.current_bet + obs.to_call
    if raises > 0 or highest_bet > obs.big_blind:
        situation = "raised"
        aggression = max(1, raises)
    elif entered:
        situation = "limped"
        aggression = 0
    else:
        situation = "unopened"
        aggression = 0
    if situation == "raised" and aggression == 0:
        aggression = 1

    effective_bb = (obs.stack + obs.current_bet) / obs.big_blind
    short_stack = effective_bb <= params["short_stack_bb"]
    raise_amount = 0
    diagnostics: dict[str, Any] = {
        "policy": "evolved-fast-prior-v1",
        "family": "evolved",
        "street": obs.street,
        "preflop_situation": situation,
        "hand_class": name,
        "preflop_equity_vs_random": round(equity, 4),
        "effective_stack_bb": round(effective_bb, 2),
        "opponents_in_pot": entered,
        "players_waiting": obs.players_to_act,
    }

    if obs.position == "BB" and obs.to_call == 0:
        if limpers and equity >= params["value_raise_threshold"] and "raise" in obs.legal_actions:
            raise_amount = _raise_target(
                obs, params, preflop=True, short_stack=short_stack,
            )
            raise_probability = min(1.0, params["raise_frequency"] * 0.84)
            weights = {"raise": raise_probability, "check": 1.0 - raise_probability}
            diagnostics["reason"] = "value raise over limpers"
        else:
            weights = {_free_action(obs): 1.0}
            diagnostics["reason"] = "free big-blind check"
        return _decision(weights, obs, salt, raise_amount=raise_amount, diagnostics=diagnostics)

    if situation == "unopened":
        position_delta = _position_delta(obs.position, params["position_sensitivity"])
        threshold = opening_threshold(obs.position) + params["opening_shift"] + position_delta
        threshold += 0.004 * min(5, max(0, obs.players_to_act - 1))
        if effective_bb <= 6:
            threshold -= 0.045
        elif effective_bb <= 10:
            threshold -= 0.025
        elif effective_bb <= 16:
            threshold -= 0.01
        diagnostics["open_threshold"] = round(threshold, 4)
        if equity >= threshold and "raise" in obs.legal_actions:
            raise_amount = _raise_target(
                obs, params, preflop=True, unopened=True,
                short_stack=short_stack,
            )
            margin = equity - threshold
            raise_probability = min(1.0, params["opening_frequency"] * max(0.45, 0.78 + margin * 1.5))
            if name in {"AA", "KK"}:
                raise_probability = 1.0
            weights = {"raise": raise_probability, "fold": 1.0 - raise_probability}
            diagnostics["reason"] = "unopened raise first in"
        elif "fold" in obs.legal_actions:
            weights = {"fold": 1.0}
            diagnostics["reason"] = "fold below opening cutoff"
        else:
            weights = {_free_action(obs): 1.0}
            diagnostics["reason"] = "passive action forced by legal actions"
        return _decision(weights, obs, salt, raise_amount=raise_amount, diagnostics=diagnostics)

    range_discount = 0.015 if aggression == 0 else 0.065 if aggression == 1 else 0.13
    range_discount += min(0.35, params["multiway_penalty"] * max(0, entered - 1))
    if obs.position in {"UTG", "MP", "SB"}:
        range_discount += 0.015
    elif obs.position in {"BTN", "BB"}:
        range_discount -= 0.005
    adjusted = max(0.0, min(1.0, equity - range_discount))
    margin = 0.025 + 0.025 * aggression + 0.02 * max(0, entered - 1) + params["call_margin"]
    if obs.position == "BB":
        margin -= 0.015
    if obs.to_call >= obs.stack:
        margin -= 0.015
    floor = 0.42 if obs.position == "BB" else 0.50 if obs.position in {"UTG", "MP", "SB"} else 0.48
    cutoff = max(obs.pot_odds + margin, floor + 0.045 * (aggression > 1))
    diagnostics.update({
        "aggression_level": aggression,
        "estimated_equity_after_range_adjustment": round(adjusted, 4),
        "pot_odds": round(obs.pot_odds, 4),
        "continue_threshold": round(cutoff, 4),
    })
    can_call = "call" in obs.legal_actions
    can_raise = "raise" in obs.legal_actions
    raise_cutoff = params["short_stack_cutoff"] + (0.12 if aggression > 1 else 0.0)
    value_cutoff = params["value_raise_threshold"] + (0.07 if aggression > 1 else 0.0)
    should_raise = adjusted >= (raise_cutoff if short_stack else value_cutoff)

    if can_raise and should_raise:
        raise_amount = _raise_target(
            obs, params, preflop=True, aggression=aggression,
            short_stack=short_stack,
        )
        frequency = params["raise_frequency"] * (0.70 if short_stack else 0.56)
        if name in {"AA", "KK"}:
            frequency = 1.0
        weights = {"raise": frequency, "call": 1.0 - frequency} if can_call else {"raise": frequency, "fold": 1.0 - frequency}
        diagnostics["reason"] = "short-stack value push" if short_stack else "value re-raise"
    elif can_call and adjusted >= cutoff:
        weights = {"call": params["call_frequency"], "fold": 1.0 - params["call_frequency"]}
        diagnostics["reason"] = "pot odds and range threshold met"
    elif can_call and "fold" not in obs.legal_actions:
        weights = {"call": 1.0}
        diagnostics["reason"] = "call forced by legal actions"
    else:
        weights = {"fold": 1.0}
        diagnostics["reason"] = "fold below continue threshold"
    return _decision(weights, obs, salt, raise_amount=raise_amount, diagnostics=diagnostics)


def _evolved_postflop(
    obs: Observation, params: Mapping[str, float], salt: int,
) -> dict[str, Any]:
    equity, detail = _public_equity(obs)
    history = fast._history_actions(obs, obs.street)
    aggression = sum(
        str(item.get("action", "")).lower() in {"raise", "bet", "all-in", "all_in"}
        for item in history
    )
    exact = detail["exact_shared_board_tie"] or detail["exact_unbeatable_hand"]
    if not exact:
        target_penalty = min(0.22, params["multiway_penalty"] * max(0, obs.players_active - 2))
        equity = max(0.0, min(1.0, equity + detail["multiway_penalty"] - target_penalty))
        detail = {**detail, "multiway_penalty": round(target_penalty, 4)}
    pressure_discount = 0.0
    if obs.to_call:
        pressure_discount += 0.035
        if obs.to_call / max(1, obs.contestable_pot) >= 0.65:
            pressure_discount += 0.045
        if aggression:
            pressure_discount += min(0.07, 0.035 * aggression)
    if exact:
        pressure_discount = 0.0
    adjusted = equity if exact else max(0.0, min(1.0, equity - pressure_discount))
    position_delta = _position_delta(obs.position, params["position_sensitivity"])
    diagnostics: dict[str, Any] = {
        "policy": "evolved-fast-prior-v1",
        "family": "evolved",
        "street": obs.street,
        "estimated_equity": round(adjusted, 4),
        "raw_hand_draw_estimate": round(equity, 4),
        "pot_odds": round(obs.pot_odds, 4),
        "pressure_discount": round(pressure_discount, 4),
        "aggression_level": aggression,
        "opponents_in_pot": obs.players_active - 1,
        **detail,
    }
    raise_amount = 0
    can_raise = "raise" in obs.legal_actions
    board_play = bool(detail["board_play"])

    if obs.to_call > 0:
        if exact:
            continue_threshold = obs.pot_odds
        else:
            continue_threshold = max(
                0.0,
                obs.pot_odds + 0.02 + 0.015 * max(0, obs.players_active - 2)
                + params["postflop_call_margin"] + position_delta,
            )
        diagnostics["continue_threshold"] = round(continue_threshold, 4)
        value_cutoff = max(params["value_raise_threshold"], continue_threshold + 0.18)
        raise_probability = 0.0
        reason = "fold below pot-odds threshold"
        if can_raise and not board_play and adjusted >= value_cutoff:
            raise_probability = params["raise_frequency"] * max(
                0.30, min(0.62, 0.30 + (adjusted - 0.73) * 1.5),
            )
            reason = "value raise mix"
        elif (
            can_raise and not board_play and obs.players_active == 2
            and obs.position in _LATE_POSITIONS and detail["draw_outs"] >= 8
            and aggression == 0 and adjusted >= continue_threshold
        ):
            raise_probability = params["bluff_frequency"]
            reason = "semi-bluff mix"
        if raise_probability > 0:
            raise_amount = _raise_target(obs, params, preflop=False)
            if "call" in obs.legal_actions and adjusted >= continue_threshold:
                weights = {"raise": raise_probability, "call": 1.0 - raise_probability}
                if raise_probability < 1.0 and not exact:
                    weights["call"] *= params["call_frequency"]
                    weights["fold"] = (1.0 - raise_probability) * (1.0 - params["call_frequency"])
            else:
                weights = {"raise": raise_probability, "fold": 1.0 - raise_probability}
        elif "call" in obs.legal_actions and adjusted >= continue_threshold:
            frequency = 1.0 if exact else params["call_frequency"]
            weights = {"call": frequency, "fold": 1.0 - frequency}
            reason = "continue by pot odds"
        elif "call" in obs.legal_actions and "fold" not in obs.legal_actions:
            weights = {"call": 1.0}
            reason = "call forced by legal actions"
        else:
            weights = {"fold": 1.0}
        diagnostics["reason"] = reason
    else:
        value_probability = 0.0
        if can_raise and not board_play and adjusted >= max(params["value_raise_threshold"], 0.62):
            value_probability = params["raise_frequency"] * max(
                0.30, min(0.85, 0.42 + (adjusted - 0.72) * 1.25),
            )
            reason = "value bet mix"
        elif (
            can_raise and not board_play and obs.players_active == 2
            and obs.position in _LATE_POSITIONS and aggression == 0
            and not detail["board_paired"] and not detail["board_connected"]
        ):
            value_probability = params["bluff_frequency"]
            reason = "position bluff mix"
        else:
            reason = "check"
        if can_raise and value_probability > 0:
            raise_amount = _raise_target(obs, params, preflop=False)
            weights = {"raise": value_probability, _free_action(obs): 1.0 - value_probability}
        else:
            weights = {_free_action(obs): 1.0}
        diagnostics["reason"] = reason
    return _decision(weights, obs, salt, raise_amount=raise_amount, diagnostics=diagnostics)


def _evolved_policy(genome: Genome):
    params = dict(DEFAULT_PARAMS)
    params.update(genome.params)
    salt = _mix_salt(genome.bot_id, 401)

    def policy(raw: Mapping[str, Any]) -> dict[str, Any]:
        obs = _evolved_observation(raw)
        decision_salt = salt + (101 if obs.street == "preflop" else 211 + len(obs.board))
        if obs.street == "preflop":
            return _evolved_preflop(obs, params, decision_salt)
        return _evolved_postflop(obs, params, decision_salt)

    return policy


def _simple_decision(obs: Observation, action: str, bot_id: str, *, reason: str) -> dict[str, Any]:
    amount = obs.min_raise_to if action == "raise" else 0
    probs = {candidate: float(candidate == action) for candidate in _ACTION_ORDER if candidate in obs.legal_actions}
    return _decision(probs, obs, _mix_salt(bot_id, 701), raise_amount=amount, diagnostics={"family": reason, "reason": reason})


def _calling_station_policy(bot_id: str):
    def policy(raw: Mapping[str, Any]) -> dict[str, Any]:
        obs = Observation.from_dict(raw)
        action = "call" if "call" in obs.legal_actions else _free_action(obs)
        return _simple_decision(obs, action, bot_id, reason="calling-station")
    return policy


def _tight_passive_policy(bot_id: str):
    def policy(raw: Mapping[str, Any]) -> dict[str, Any]:
        obs = Observation.from_dict(raw)
        if obs.street == "preflop":
            equity = preflop_equity(obs.hole_cards)
            aggressive = fast._raise_count(obs, "preflop")
            cutoff = opening_threshold(obs.position) + 0.055
            if aggressive:
                cutoff = max(cutoff, obs.pot_odds + 0.10 + 0.04 * aggressive)
        else:
            equity, detail = _public_equity(obs)
            if detail["exact_shared_board_tie"] or detail["exact_unbeatable_hand"]:
                cutoff = obs.pot_odds
            else:
                cutoff = obs.pot_odds + 0.10
        if "call" in obs.legal_actions:
            action = "call" if equity >= cutoff else "fold"
            if action not in obs.legal_actions:
                action = "call"
        else:
            action = _free_action(obs)
        return _simple_decision(obs, action, bot_id, reason="tight-passive")
    return policy


def _random_legal_policy(bot_id: str):
    salt = _mix_salt(bot_id, 907)

    def policy(raw: Mapping[str, Any]) -> dict[str, Any]:
        obs = Observation.from_dict(raw)
        choices = [action for action in _ACTION_ORDER if action in obs.legal_actions]
        weights = {action: 1.0 / len(choices) for action in choices}
        amount = obs.raise_to(round((obs.min_raise_to + obs.max_raise_to) / 2)) if "raise" in obs.legal_actions else 0
        return _decision(weights, obs, salt, raise_amount=amount, diagnostics={"family": "random-legal"})
    return policy


_saved_lock = threading.Lock()
_saved_callable = None


def _load_saved_callable():
    global _saved_callable
    if _saved_callable is None:
        with _saved_lock:
            if _saved_callable is None:
                from .saved_bot import load_bot
                _saved_callable = load_bot()
    return _saved_callable


def policy_for(genome: Genome):
    """Return a fresh policy callable for one table; adaptive state is local."""
    if not isinstance(genome, Genome):
        raise TypeError("policy_for expects a Genome")
    if genome.family == "adaptive":
        from .evolution_adaptive import make_adaptive_policy
        return make_adaptive_policy(genome)
    if genome.family == "evolved":
        return _evolved_policy(genome)
    if genome.family == "calibrated":
        from .calibrated_bot import make_calibrated_policy
        return make_calibrated_policy(genome)
    if genome.family == "corrected-calibrated":
        from .corrected_calibrated_bot import make_corrected_calibrated_policy
        return make_corrected_calibrated_policy(genome)
    if genome.family == "saved":
        saved = _load_saved_callable()

        def saved_policy(raw: Mapping[str, Any]) -> dict[str, Any]:
            obs = Observation.from_dict(raw)
            return saved(_safe_payload(obs))
        return saved_policy
    if genome.family == "fast":
        def fast_policy(raw: Mapping[str, Any]) -> dict[str, Any]:
            obs = Observation.from_dict(raw)
            return fast.decide(_safe_payload(obs))
        return fast_policy
    if genome.family == "calling-station":
        return _calling_station_policy(genome.bot_id)
    if genome.family == "tight-passive":
        return _tight_passive_policy(genome.bot_id)
    return _random_legal_policy(genome.bot_id)

