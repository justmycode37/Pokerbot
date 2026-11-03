"""Deterministic short-stack and heads-up tournament policy overlays.

The push/fold rules use the repository's offline preflop equity table as a
compact, transparent approximation to chip-EV charts. The heads-up postflop
line reuses the fast policy's public hand/draw evaluator, with tournament
specific preflop play around it. No opponent cards, stacks, or outcomes are
read.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Callable

from . import fast
from .preflop import preflop_equity
from .state import Observation


DEFAULT_SHORT_STACK_BB = 16.0
_POSITION_OPEN = {"UTG": 0.715, "MP": 0.675, "CO": 0.625, "BTN": 0.565, "SB": 0.585}


def _value(params: Mapping[str, float] | None, key: str, default: float) -> float:
    if params is None or key not in params:
        return default
    raw = params[key]
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise TypeError(f"{key} must be a finite number")
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"{key} must be a finite number")
    return value


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _safe_passive(obs: Observation) -> str:
    if "check" in obs.legal_actions:
        return "check"
    if "call" in obs.legal_actions:
        return "call"
    return "fold"


def _decision(obs: Observation, action: str, *, amount: int = 0,
              diagnostics: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build the canonical policy result while enforcing protocol legality."""
    if action not in obs.legal_actions:
        action = _safe_passive(obs)
    if action == "raise":
        amount = obs.raise_to(amount)
    else:
        amount = 0
    probabilities = {name: float(name == action) for name in ("raise", "call", "check", "fold")
                     if name in obs.legal_actions}
    details = dict(diagnostics or {})
    details.setdefault("policy", "endgame-v1")
    details["raise_amount"] = amount
    return {"action": action, "amount": amount, "raise_amount": amount,
            "probabilities": probabilities, "diagnostics": details}


def _raise_count(obs: Observation, *, exclude_hero: bool = False) -> int:
    return sum(
        str(item.get("action", "")).lower() in {"raise", "bet", "all-in", "all_in"}
        and (not exclude_hero or item.get("player") != obs.player_id)
        for item in obs.history if item.get("street", "preflop") == "preflop"
    )


def _limper_count(obs: Observation) -> int:
    actions: dict[str, str] = {}
    anonymous = 0
    for item in obs.history:
        if item.get("street", "preflop") != "preflop":
            continue
        action = str(item.get("action", "")).lower()
        if action not in {"call", "raise", "bet", "all-in", "all_in"}:
            continue
        actor = item.get("player")
        if actor is None:
            anonymous += int(action == "call")
        else:
            actions[str(actor)] = action
    return anonymous + sum(action == "call" for action in actions.values())


def _last_opponent_raise_position(obs: Observation) -> str | None:
    for item in reversed(obs.history):
        if item.get("street", "preflop") != "preflop":
            continue
        action = str(item.get("action", "")).lower()
        if action in {"raise", "bet", "all-in", "all_in"} and item.get("player") != obs.player_id:
            position = item.get("position")
            return position if isinstance(position, str) else None
    return None


def _call_frequency(stats: Any, player: Any = None) -> float | None:
    """Read a supplied player estimate or use its mean; malformed values vanish."""
    if not isinstance(stats, Mapping):
        return None
    value = stats.get(player) if player is not None else None
    if value is None:
        values = [v for key, v in stats.items() if key != "_meta"]
        parsed = [_coerce_frequency(v) for v in values]
        parsed = [v for v in parsed if v is not None]
        return sum(parsed) / len(parsed) if parsed else None
    return _coerce_frequency(value)


def _coerce_frequency(value: Any) -> float | None:
    if isinstance(value, Mapping):
        value = value.get("call_frequency", value.get("calls_per_opportunity"))
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return _clamp(value) if math.isfinite(value) else None


def shove_equity_cutoff(*, position: str, stack_bb: float, players_to_act: int,
                        limpers: int = 0, caller_frequency: float | None = None,
                        players_active: int = 8, ante_bb: float = 0.0) -> float:
    """Return the minimum random-opponent equity for an open shove.

    Cutoffs are generated analytically from the offline equity scale: later
    position and shorter depth widen the range; more players behind and loose
    callers tighten it. This is a chip-EV approximation, not a solver output.
    """
    base = _POSITION_OPEN.get(position, 0.72)
    depth_adjustment = 0.010 * (stack_bb - 6.0)
    depth_adjustment = _clamp(depth_adjustment, -0.045, 0.075)
    behind_adjustment = 0.012 * min(5, max(0, players_to_act))
    field_adjustment = 0.006 * min(4, max(0, players_active - players_to_act - 2))
    limper_adjustment = -0.018 * min(3, max(0, limpers))
    caller_adjustment = 0.0
    if caller_frequency is not None:
        caller_adjustment = 0.10 * (caller_frequency - 0.40)
    dead_money_adjustment = -min(0.06, max(0.0, ante_bb) * max(2, players_active) * 0.007)
    return _clamp(base + depth_adjustment + behind_adjustment + field_adjustment
                  + limper_adjustment + caller_adjustment + dead_money_adjustment,
                  0.34, 0.90)


def _open_shove(obs: Observation, depth_bb: float, params: Mapping[str, float] | None,
                opponent_stats: Any) -> dict[str, Any]:
    equity = preflop_equity(obs.hole_cards)
    limpers = _limper_count(obs)
    caller_frequency = _call_frequency(opponent_stats)
    ante_bb = max(0.0, _value(params, "ante_bb", 0.0))
    cutoff = shove_equity_cutoff(
        position=obs.position, stack_bb=depth_bb,
        players_to_act=obs.players_to_act, limpers=limpers,
        caller_frequency=caller_frequency, players_active=obs.players_active,
        ante_bb=ante_bb,
    )
    details = {"module": "short_stack_push_fold", "hand_equity_vs_random": round(equity, 4),
               "equity_cutoff": round(cutoff, 4), "stack_bb": round(depth_bb, 2),
               "players_to_act": obs.players_to_act, "limpers": limpers,
               "caller_frequency": caller_frequency, "ante_bb": ante_bb}
    if equity >= cutoff and "raise" in obs.legal_actions:
        return _decision(obs, "raise", amount=obs.max_raise_to,
                         diagnostics={**details, "reason": "open shove above chip-EV chart cutoff"})
    # When no shove is selected, retain a free check; otherwise fold rather
    # than bleed chips by completing a marginal hand at short depth.
    if obs.to_call == 0:
        return _decision(obs, _safe_passive(obs), diagnostics={**details, "reason": "decline weak shove"})
    return _decision(obs, "fold", diagnostics={**details, "reason": "fold below open-shove cutoff"})


def _call_shove(obs: Observation, depth_bb: float, params: Mapping[str, float] | None) -> dict[str, Any]:
    equity = preflop_equity(obs.hole_cards)
    ante_bb = max(0.0, _value(params, "ante_bb", 0.0))
    dead_money = ante_bb * obs.players_active * obs.big_blind
    pot_odds = obs.to_call / max(1, obs.contestable_pot + obs.to_call + round(dead_money))
    # A raise or a price that commits at least 40% of the remaining stack is
    # treated as a shove decision. The random-equity threshold discounts the
    # opponent's range versus a random holding and accounts for overcalls.
    raise_count = _raise_count(obs, exclude_hero=True)
    caller_count = max(0, obs.players_active - 2 - obs.players_to_act)
    aggressor_position = _last_opponent_raise_position(obs)
    position_adjustment = {"UTG": 0.045, "MP": 0.030, "CO": 0.010,
                           "BTN": -0.020, "SB": -0.010, "BB": 0.0}.get(aggressor_position, 0.0)
    future_caller_adjustment = 0.009 * min(4, max(0, obs.players_to_act))
    range_discount = (0.080 + 0.020 * max(0, raise_count - 1) + 0.015 * caller_count
                      + position_adjustment + future_caller_adjustment)
    depth_credit = 0.025 if depth_bb <= 4 else 0.0
    cutoff = max(pot_odds + 0.095, 0.60 + range_discount - depth_credit)
    cutoff = _clamp(cutoff, 0.48, 0.84)
    details = {"module": "short_stack_call_shove", "hand_equity_vs_random": round(equity, 4),
               "equity_cutoff": round(cutoff, 4), "pot_odds": round(pot_odds, 4),
               "stack_bb": round(depth_bb, 2), "raise_count": raise_count,
               "players_to_act": obs.players_to_act, "aggressor_position": aggressor_position,
               "ante_bb": ante_bb}
    if "call" in obs.legal_actions and equity >= cutoff:
        return _decision(obs, "call", diagnostics={**details, "reason": "call shove above range-adjusted cutoff"})
    return _decision(obs, "fold", diagnostics={**details, "reason": "fold shove below range-adjusted cutoff"})


def _short_stack_decision(obs: Observation, params: Mapping[str, float] | None,
                          opponent_stats: Any) -> dict[str, Any] | None:
    if obs.street != "preflop":
        return None
    threshold = _value(params, "short_stack_bb", DEFAULT_SHORT_STACK_BB)
    if threshold <= 0:
        raise ValueError("short_stack_bb must be positive")
    depth_bb = (obs.stack + obs.current_bet) / obs.big_blind
    if depth_bb > threshold:
        return None
    # Avoid treating a blind completion or a single standard open as an all-in
    # facing spot; the cost and raise history jointly identify shove pressure.
    other_raises = _raise_count(obs, exclude_hero=True)
    price_fraction = obs.to_call / max(1, obs.stack + obs.to_call)
    if other_raises > 0 and obs.to_call > 0:
        facing_shove = price_fraction >= 0.35 or obs.to_call >= 4 * obs.big_blind
        if facing_shove:
            return _call_shove(obs, depth_bb, params)
        equity = preflop_equity(obs.hole_cards)
        pot_odds = obs.pot_odds
        call_cutoff = max(0.39, pot_odds + 0.055, 0.51 + 0.025 * max(0, other_raises - 1))
        jam_cutoff = 0.69 if depth_bb <= 10 else 0.75
        details = {"module": "short_stack_vs_open", "hand_equity_vs_random": round(equity, 4),
                   "stack_bb": round(depth_bb, 2), "pot_odds": round(pot_odds, 4),
                   "call_cutoff": round(call_cutoff, 4), "jam_cutoff": jam_cutoff}
        if equity >= jam_cutoff and "raise" in obs.legal_actions:
            return _decision(obs, "raise", amount=obs.max_raise_to,
                             diagnostics={**details, "reason": "short-stack rejam over open"})
        if equity >= call_cutoff and "call" in obs.legal_actions:
            return _decision(obs, "call", diagnostics={**details, "reason": "defend short stack versus open"})
        return _decision(obs, "fold", diagnostics={**details, "reason": "fold below short-stack open defense"})
    # A big blind with no voluntary action to face should retain its free check.
    if obs.position == "BB" and obs.to_call == 0 and _limper_count(obs) == 0:
        return _decision(obs, _safe_passive(obs), diagnostics={"module": "short_stack_push_fold",
                                                              "reason": "big blind takes free option"})
    return _open_shove(obs, depth_bb, params, opponent_stats)


def _hu_preflop(obs: Observation, params: Mapping[str, float] | None,
                opponent_stats: Any) -> dict[str, Any]:
    equity = preflop_equity(obs.hole_cards)
    depth_bb = (obs.stack + obs.current_bet) / obs.big_blind
    raise_count = _raise_count(obs)
    opp_raise_count = _raise_count(obs, exclude_hero=True)
    caller_frequency = _call_frequency(opponent_stats)
    adjusted_open = 0.455 + 0.006 * min(5.0, max(0.0, depth_bb - 20.0))
    if caller_frequency is not None:
        adjusted_open += 0.035 * (caller_frequency - 0.40)
    details = {"module": "heads_up_preflop", "hand_equity_vs_random": round(equity, 4),
               "stack_bb": round(depth_bb, 2), "raise_count": raise_count,
               "opponent_raises": opp_raise_count, "open_cutoff": round(adjusted_open, 4)}

    # Button is the small blind and acts first preflop. It may limp for half a
    # blind, open to a compact 2.2–2.5 BB size, or shove at very short depth.
    if obs.position in {"BTN", "SB"} and opp_raise_count == 0:
        if depth_bb <= 7.5:
            cutoff = _clamp(0.44 + (depth_bb - 4.0) * 0.006, 0.40, 0.50)
            if equity >= cutoff and "raise" in obs.legal_actions:
                return _decision(obs, "raise", amount=obs.max_raise_to,
                                 diagnostics={**details, "equity_cutoff": cutoff, "reason": "heads-up button short-stack shove"})
        elif equity >= adjusted_open and "raise" in obs.legal_actions:
            target = max(obs.min_raise_to, round((2.2 if depth_bb <= 20 else 2.35) * obs.big_blind))
            return _decision(obs, "raise", amount=target,
                             diagnostics={**details, "reason": "heads-up button open raise"})
        if equity >= 0.335 and "call" in obs.legal_actions:
            return _decision(obs, "call", diagnostics={**details, "reason": "heads-up button limp"})
        fallback = "fold" if "fold" in obs.legal_actions else _safe_passive(obs)
        return _decision(obs, fallback, diagnostics={**details, "reason": "button folds weakest hands"})

    if obs.to_call == 0:
        if obs.position == "BB" and _limper_count(obs) and equity >= 0.66 and "raise" in obs.legal_actions:
            target = max(obs.min_raise_to, round(3.5 * obs.big_blind))
            return _decision(obs, "raise", amount=target,
                             diagnostics={**details, "reason": "big blind isolates limp for value"})
        return _decision(obs, _safe_passive(obs), diagnostics={**details, "reason": "big blind checks option"})

    pot_odds = obs.pot_odds
    call_cutoff = max(0.33, pot_odds + 0.045)
    jam_cutoff = 0.66 if depth_bb <= 15 else 0.76
    if obs.position == "BB" and opp_raise_count > 0:
        if depth_bb <= 15 and equity >= jam_cutoff and "raise" in obs.legal_actions:
            return _decision(obs, "raise", amount=obs.max_raise_to,
                             diagnostics={**details, "call_cutoff": call_cutoff, "equity_cutoff": jam_cutoff,
                                          "reason": "big blind short-stack rejam"})
        if depth_bb > 15 and equity >= 0.75 and "raise" in obs.legal_actions:
            target = max(obs.min_raise_to, round(3.25 * (obs.current_bet + obs.to_call)))
            return _decision(obs, "raise", amount=target,
                             diagnostics={**details, "reason": "big blind value three-bet"})
    elif opp_raise_count > 0 and depth_bb <= 15 and equity >= 0.74 and "raise" in obs.legal_actions:
        return _decision(obs, "raise", amount=obs.max_raise_to,
                         diagnostics={**details, "reason": "button short-stack four-bet shove"})

    if "call" in obs.legal_actions and equity >= call_cutoff:
        return _decision(obs, "call", diagnostics={**details, "call_cutoff": round(call_cutoff, 4),
                                                    "reason": "heads-up defend by pot odds"})
    return _decision(obs, "fold", diagnostics={**details, "call_cutoff": round(call_cutoff, 4),
                                                "reason": "heads-up fold below defend threshold"})


def _hu_postflop(obs: Observation) -> dict[str, Any]:
    probabilities, amount, diagnostics = fast._postflop_decision(obs)
    # Preserve the fast heuristic's stable, observation-seeded bet/check and
    # raise/call mix while marking the heads-up overlay in the diagnostics.
    action = fast._select(probabilities, obs, 211 + len(obs.board) + 901)
    return _decision(obs, action, amount=amount,
                     diagnostics={**diagnostics, "module": "heads_up_postflop"})


def endgame_decision(obs: Observation, params: Mapping[str, float] | None = None,
                     opponent_stats: Any = None) -> dict[str, Any] | None:
    """Return an endgame action, or ``None`` when the overlay does not apply.

    ``opponent_stats`` may map stable public player IDs to call frequencies in
    ``[0, 1]`` (or ``{"call_frequency": value}``).
    """
    if not isinstance(obs, Observation):
        raise TypeError("obs must be an Observation")
    if obs.players_active == 2:
        if obs.street == "preflop":
            return _hu_preflop(obs, params, opponent_stats)
        return _hu_postflop(obs)
    return _short_stack_decision(obs, params, opponent_stats)


class _WrappedPolicy:
    """One-table wrapper with lightweight public call-frequency estimates."""

    def __init__(self, base_policy: Callable[[Mapping[str, Any]], dict[str, Any]],
                 params: Mapping[str, float] | None):
        self.base_policy = base_policy
        self.params = None if params is None else dict(params)
        self._history_cursor = 0
        self._counts: dict[str, list[int]] = {}

    def reset(self) -> None:
        self._history_cursor = 0
        self._counts.clear()
        reset = getattr(self.base_policy, "reset", None)
        if callable(reset):
            reset()

    def _observe_history(self, raw: Mapping[str, Any]) -> dict[str, float]:
        history = raw.get("history", [])
        if isinstance(history, (list, tuple)):
            if len(history) < self._history_cursor:
                self._history_cursor = 0
            hero_id = raw.get("player_id")
            for item in history[self._history_cursor:]:
                if not isinstance(item, Mapping):
                    continue
                actor = item.get("player")
                action = str(item.get("action", "")).lower()
                if hero_id is not None and actor is not None and actor != hero_id and action in {"call", "fold"}:
                    counts = self._counts.setdefault(str(actor), [0, 0])
                    counts[0] += int(action == "call")
                    counts[1] += 1
            self._history_cursor = len(history)
        return {player: (calls + 1) / (opportunities + 2)
                for player, (calls, opportunities) in self._counts.items()}

    def _might_apply(self, raw: Mapping[str, Any]) -> bool:
        active = raw.get("players_active")
        if type(active) is not int:
            return True
        if active == 2:
            return True
        if raw.get("street", "preflop") != "preflop":
            return False
        stack, current, blind = raw.get("stack"), raw.get("current_bet"), raw.get("big_blind")
        if any(type(value) is not int for value in (stack, current, blind)) or blind <= 0:
            return True
        threshold = _value(self.params, "short_stack_bb", DEFAULT_SHORT_STACK_BB)
        return stack + current <= threshold * blind

    def __call__(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(raw, Mapping):
            return self.base_policy(raw)
        stats = self._observe_history(raw)
        if not self._might_apply(raw):
            return self.base_policy(raw)
        try:
            obs = Observation.from_dict(raw)
        except (TypeError, ValueError, KeyError):
            return self.base_policy(raw)
        table_players = raw.get("table_player_ids") if isinstance(raw, Mapping) else None
        if isinstance(table_players, (list, tuple)) and obs.player_id is not None:
            current_opponents = {str(player) for player in table_players if player != obs.player_id}
            stats = {player: value for player, value in stats.items() if player in current_opponents}
        result = endgame_decision(obs, self.params, stats)
        return result if result is not None else self.base_policy(raw)


def wrap_policy(base_policy: Callable[[Mapping[str, Any]], dict[str, Any]],
                params: Mapping[str, float] | None = None) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    """Return a fresh callable that overlays endgame play on ``base_policy``."""
    if not callable(base_policy):
        raise TypeError("base_policy must be callable")
    return _WrappedPolicy(base_policy, params)
