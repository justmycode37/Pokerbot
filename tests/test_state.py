import copy
import json
import unittest
from pathlib import Path

from pokerbot.scenarios import observations
from pokerbot.state import Observation


class ObservationTests(unittest.TestCase):
    def test_varied_scenarios_validate(self):
        for state in observations(200):
            parsed = Observation.from_dict(state)
            self.assertLessEqual(parsed.pot_odds, 1)

    def test_bad_raise_bounds_and_duplicate_cards_rejected(self):
        valid = json.loads((Path(__file__).resolve().parents[1] / "examples/decision.json").read_text())
        for change in ({"min_raise_to": 0}, {"hole_cards": ["As", "As"]},
                       {"to_call": -1}, {"big_blind": True}, {"seed": "0"}):
            state = {**valid, **change}
            with self.assertRaises(ValueError):
                Observation.from_dict(state)

    def test_unknown_private_information_and_labels_are_dropped(self):
        valid = next(observations(1))
        valid.update({"expected_action": "raise", "opponent_cards": ["As", "Kd"],
                      "history": [{"action": "check", "future": "Ac", "expected": "fold"}]})
        parsed = Observation.from_dict(valid)
        self.assertFalse(hasattr(parsed, "opponent_cards"))
        self.assertEqual(parsed.history, ({"action": "check"},))

    def test_side_pot_odds_use_contestable_pot(self):
        state = copy.deepcopy(next(observations(1)))
        state.update({"pot": 1000, "contestable_pot": 100, "to_call": 20,
                      "stack": 2000, "min_raise_to": 80, "max_raise_to": 2020,
                      "current_bet": 20, "legal_actions": ["fold", "call", "raise"]})
        self.assertAlmostEqual(Observation.from_dict(state).pot_odds, 1 / 6)
