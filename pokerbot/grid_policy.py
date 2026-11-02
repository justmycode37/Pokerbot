"""Sizing-only observed-chip-grid wrapper for the frozen fast policy.

The inferred grid is a heuristic from public integer chip fields. It is not
evidence of a table's minimum chip denomination.
"""

from __future__ import annotations

from math import gcd
from typing import Any, Mapping

from .fast import decide as decide_fast
from .state import Observation


GRID_HEURISTIC = "gcd_of_positive_public_integer_chip_fields"
GRID_FALLBACK_BIG_BLIND_DIVISOR = 8
GRID_FIELDS = (
    "pot",
    "contestable_pot",
    "current_bet",
    "stack",
    "min_raise_to",
    "max_raise_to",
    "to_call",
    "big_blind",
)


def observed_rounding_grid(raw: Mapping[str, Any]) -> int:
    """Infer a conservative observed rounding grid from public chip amounts.

    This GCD is only a rounding heuristic. It does not establish the minimum
    chip denomination used by the game. If the inferred grid would be larger
    than one eighth of the big blind, use one chip to avoid coarse rounding.
    """
    obs = Observation.from_dict(raw)
    values = [getattr(obs, field) for field in GRID_FIELDS]
    grid = 0
    for value in values:
        if value > 0:
            grid = gcd(grid, value)
    # big_blind is positive and included in GRID_FIELDS, so grid cannot be zero.
    if grid * GRID_FALLBACK_BIG_BLIND_DIVISOR > obs.big_blind:
        return 1
    return grid


def _round_integer_to_grid_ties_even(target: int, grid: int) -> int:
    """Round a nonnegative integer to a grid multiple with integer ties-to-even."""
    if type(target) is not int or target < 0:
        raise ValueError("target must be a nonnegative integer")
    if type(grid) is not int or grid < 1:
        raise ValueError("grid must be a positive integer")
    quotient, remainder = divmod(target, grid)
    doubled = remainder * 2
    if doubled < grid:
        rounded = quotient
    elif doubled > grid:
        rounded = quotient + 1
    else:
        rounded = quotient if quotient % 2 == 0 else quotient + 1
    return rounded * grid


def _legal_grid_target(target: int, obs: Observation, grid: int) -> int:
    """Round a proposed total street target and keep it inside legal bounds."""
    if target in (obs.min_raise_to, obs.max_raise_to):
        return target
    rounded = _round_integer_to_grid_ties_even(target, grid)
    return max(obs.min_raise_to, min(obs.max_raise_to, rounded))


def decide_with_grid(raw: dict) -> dict:
    """Apply observed-grid rounding to fast's proposed size only.

    The frozen fast policy still selects the action and probability
    distribution. This wrapper changes only ``raise_amount`` and, when the
    selected action is raise, its matching ``amount``.
    """
    obs = Observation.from_dict(raw)
    result = dict(decide_fast(raw))
    target = result["raise_amount"]
    grid = observed_rounding_grid(raw)
    if "raise" in obs.legal_actions and type(target) is int and target:
        target = _legal_grid_target(target, obs, grid)
        result["raise_amount"] = target
        if result["action"] == "raise":
            result["amount"] = target
    diagnostics = dict(result["diagnostics"])
    diagnostics["experimental_observed_rounding_grid"] = grid
    diagnostics["experimental_grid_heuristic"] = GRID_HEURISTIC
    diagnostics["experimental_grid_is_minimum_denomination_proof"] = False
    diagnostics["raise_amount"] = result["raise_amount"]
    result["diagnostics"] = diagnostics
    return result
