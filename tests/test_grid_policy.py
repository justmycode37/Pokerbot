import copy
import unittest

from pokerbot.fast import decide as decide_fast
from pokerbot.grid_policy import (
    _legal_grid_target,
    _round_integer_to_grid_ties_even,
    decide_with_grid,
    observed_rounding_grid,
)
from pokerbot.state import Observation


def state(**updates):
    raw = {
        "hole_cards": ["As", "Ah"],
        "board": [],
        "pot": 330,
        "contestable_pot": 330,
        "to_call": 0,
        "stack": 2030,
        "current_bet": 0,
        "min_raise_to": 200,
        "max_raise_to": 2010,
        "big_blind": 100,
        "position": "BTN",
        "players_active": 2,
        "players_to_act": 1,
        "legal_actions": ["fold", "raise"],
        "seed": 17,
    }
    raw.update(updates)
    return raw


class GridPolicyTests(unittest.TestCase):
    def test_observed_gcd_and_coarse_grid_fallback(self):
        raw = state()
        self.assertEqual(observed_rounding_grid(raw), 10)

        coarse = state(pot=500, contestable_pot=500, stack=1000,
                       min_raise_to=200, max_raise_to=900)
        self.assertEqual(observed_rounding_grid(coarse), 1)

        # Every named public chip field participates in the GCD.
        adjusted = state(current_bet=5, to_call=5, legal_actions=["fold", "call", "raise"],
                         min_raise_to=205, max_raise_to=2010)
        self.assertEqual(observed_rounding_grid(adjusted), 5)

    def test_integer_rounding_uses_nearest_multiple_and_ties_to_even(self):
        self.assertEqual(_round_integer_to_grid_ties_even(224, 10), 220)
        self.assertEqual(_round_integer_to_grid_ties_even(225, 10), 220)
        self.assertEqual(_round_integer_to_grid_ties_even(235, 10), 240)
        self.assertEqual(_round_integer_to_grid_ties_even(236, 10), 240)
        self.assertEqual(_round_integer_to_grid_ties_even(17, 1), 17)

    def test_grid_wrapper_rounds_fast_size_and_stays_within_legal_bounds(self):
        raw = state()
        baseline = decide_fast(raw)
        wrapped = decide_with_grid(raw)
        self.assertEqual(baseline["action"], "raise")
        self.assertEqual(baseline["raise_amount"], 225)
        self.assertEqual(wrapped["raise_amount"], 220)
        self.assertEqual(wrapped["amount"], 220)
        self.assertGreaterEqual(wrapped["amount"], raw["min_raise_to"])
        self.assertLessEqual(wrapped["amount"], raw["max_raise_to"])

        obs = Observation.from_dict(raw)
        self.assertEqual(_legal_grid_target(226, obs, 10), raw["min_raise_to"] + 30)
        self.assertEqual(_legal_grid_target(2006, obs, 10), raw["max_raise_to"])

    def test_boundary_targets_and_short_all_in_are_preserved_exactly(self):
        raw = state(stack=300, min_raise_to=250, max_raise_to=300,
                    pot=300, contestable_pot=300)
        baseline = decide_fast(raw)
        wrapped = decide_with_grid(raw)
        self.assertEqual(baseline["raise_amount"], 300)
        self.assertEqual(wrapped["raise_amount"], 300)
        self.assertEqual(wrapped["amount"], 300)

        obs = Observation.from_dict(state())
        self.assertEqual(_legal_grid_target(obs.min_raise_to, obs, 7), obs.min_raise_to)
        self.assertEqual(_legal_grid_target(obs.max_raise_to, obs, 7), obs.max_raise_to)

    def test_action_and_probability_distribution_are_unchanged(self):
        for raw in (
            state(),
            state(hole_cards=["7c", "2d"], position="UTG", players_to_act=7,
                  players_active=8,
                  legal_actions=["fold", "call", "raise"], to_call=100,
                  current_bet=0, min_raise_to=200, max_raise_to=2010),
            state(legal_actions=["check"], max_raise_to=2010),
        ):
            baseline = decide_fast(raw)
            wrapped = decide_with_grid(raw)
            self.assertEqual(wrapped["action"], baseline["action"])
            self.assertEqual(wrapped["probabilities"], baseline["probabilities"])

    def test_source_label_and_private_extras_do_not_change_result(self):
        raw = state()
        changed = copy.deepcopy(raw)
        changed.update({
            "source": "synthetic-source",
            "hand_id": "unrelated-hand",
            "expected": {"action": "fold", "amount": 999999},
            "label": "secret-label",
            "opponent_hole_cards": ["2c", "2s"],
            "future_board": ["Qc", "Jc", "Tc"],
            "winner": "other-player",
        })
        self.assertEqual(decide_with_grid(changed), decide_with_grid(raw))

    def test_chip_scaling_preserves_grid_decision(self):
        raw = state()
        base = decide_with_grid(raw)
        multiplier = 7
        scaled = copy.deepcopy(raw)
        for field in (
            "pot", "contestable_pot", "to_call", "stack", "current_bet",
            "min_raise_to", "max_raise_to", "big_blind",
        ):
            scaled[field] *= multiplier
        result = decide_with_grid(scaled)
        self.assertEqual(result["action"], base["action"])
        self.assertEqual(result["probabilities"], base["probabilities"])
        self.assertEqual(result["raise_amount"], base["raise_amount"] * multiplier)


if __name__ == "__main__":
    unittest.main()
