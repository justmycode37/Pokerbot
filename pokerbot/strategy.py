"""Offline Monte Carlo reference policy. This is not the 1 ms runtime bot."""

from __future__ import annotations

import random

from .equity import estimate_for_observation
from .state import Observation


def choose_action(obs, weights, *, raise_to=None, diagnostics=None):
    """Restrict and normalize a distribution, then reproducibly sample it."""
    weights = {a: max(0.0, float(weights.get(a, 0))) for a in sorted(obs.legal_actions)}
    if not sum(weights.values()):
        fallback = next(a for a in ("check", "fold", "call") if a in obs.legal_actions)
        weights[fallback] = 1.0
    denominator = sum(weights.values())
    probabilities = {a: w / denominator for a, w in weights.items()}
    roll = random.Random(obs.seed).random()
    cumulative = 0.0
    selected = next(reversed(probabilities))
    for action, probability in probabilities.items():
        cumulative += probability
        if roll < cumulative:
            selected = action
            break
    result = {"action": selected, "probabilities": probabilities,
              "diagnostics": diagnostics or {}}
    if probabilities.get("raise", 0):
        result["raise_amount"] = obs.raise_to(raise_to if raise_to is not None else obs.min_raise_to)
    if selected == "raise":
        result["amount"] = result["raise_amount"]
    return result


def decide(raw: dict, *, samples=1000, use_ranges=True) -> dict:
    obs = Observation.from_dict(raw)
    if obs.street == "preflop":
        # Both policies share the same explicit preflop priors, allowing the
        # postflop comparison to focus on equity estimation, not two charts.
        from .fast import decide as fast_decide
        return fast_decide(raw)
    equity, model = estimate_for_observation(obs, samples=samples, use_ranges=use_ranges)
    opponents = obs.players_active - 1
    realization = 1.0 if obs.street == "river" or obs.to_call == obs.stack else (
        0.95 if obs.position in ("BTN", "CO") else 0.88)
    effective_equity = equity * realization
    diagnostics = {"policy": "mc-range-v1" if use_ranges else "mc-uniform-v1",
                   "equity": equity, "realized_equity_heuristic": effective_equity,
                   "pot_odds": obs.pot_odds, "samples": samples, "range_model": model,
                   "runtime_role": "offline_reference"}
    weights = {}
    target = obs.current_bet + obs.to_call + 0.65 * (obs.contestable_pot + obs.to_call)
    if obs.to_call:
        edge = effective_equity - obs.pot_odds
        if edge < -0.025:
            weights = {"fold": 1}
        elif edge < 0.025:
            weights = {"call": 0.5 + 10 * edge, "fold": 0.5 - 10 * edge}
        else:
            weights = {"call": 1}
        # Showdown equity alone is not value-raise equity versus a continuing
        # range. Require a large margin and retain calls with strong hands.
        if equity > max(0.76, 1 / (opponents + 1) + 0.25):
            weights = {"raise": 0.75, "call": 0.25}
    else:
        threshold = max(0.5, 1 / (opponents + 1) + 0.10)
        if equity > threshold:
            weights = {"raise": 0.8, "check": 0.2}
            target = obs.current_bet + (0.75 if equity > 0.8 else 0.5) * obs.contestable_pot
        else:
            weights = {"check": 1}
    return choose_action(obs, weights, raise_to=target, diagnostics=diagnostics)
