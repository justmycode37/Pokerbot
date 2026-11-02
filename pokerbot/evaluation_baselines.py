"""Simple fitted baselines that reveal class imbalance in imitation tests."""

from collections import Counter

from .state import Observation


def majority_action_policy(training_rows):
    """Choose the most frequent fitting action that is currently legal.

    This intentionally ignores card strength and action history. It is a
    diagnostic benchmark, not a useful poker strategy or an Ivey model.
    """
    counts = Counter(row["expected"]["action"] for row in training_rows)
    if not counts:
        raise ValueError("majority-action baseline needs fitting rows")
    tie_order = ("check", "call", "fold", "raise")

    def decide(raw):
        obs = Observation.from_dict(raw)
        action = max((a for a in tie_order if a in obs.legal_actions), key=lambda a: counts[a])
        result = {"action": action,
                  "probabilities": {a: float(a == action) for a in obs.legal_actions}}
        if action == "raise":
            result["amount"] = obs.min_raise_to
        return result
    return decide
