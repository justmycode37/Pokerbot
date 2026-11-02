"""Deterministic maximum-probability action from the frozen fast strategy.

This targets top-1 decision similarity; it does not assert higher poker EV.
"""
from .fast import decide as fast_decide
from .imitation import TIE_BREAK_ORDER


def decide(raw):
    result = fast_decide(raw)
    action = max(TIE_BREAK_ORDER, key=lambda a: result["probabilities"].get(a, -1.0))
    return {
        **result,
        "action": action,
        "amount": result["raise_amount"] if action == "raise" else 0,
        "diagnostics": {**result["diagnostics"], "policy": "fast-map-v1"},
    }
