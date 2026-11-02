import json
import tempfile
import unittest
from pathlib import Path

from pokerbot import ivey
from pokerbot.state import Observation


class IveyReplayTests(unittest.TestCase):
    def setUp(self):
        self.decisions = ivey.load_decisions()

    def test_replays_ivey_actions_with_actual_pot_and_street_totals(self):
        self.assertEqual(len(self.decisions), 4)
        states = [row["state"] for row in self.decisions]

        self.assertEqual([row["expected"] for row in self.decisions], [
            {"action": "raise", "amount": 23000},
            {"action": "raise", "amount": 35000},
            {"action": "raise", "amount": 90000},
            {"action": "raise", "amount": 1067100},
        ])
        self.assertEqual([state["pot"] for state in states], [11500, 49500, 119500, 442100])
        self.assertEqual([state["street"] for state in states], ["preflop", "flop", "turn", "turn"])
        self.assertEqual([state["board"] for state in states], [
            [], ["Jc", "3d", "5c"], ["Jc", "3d", "5c", "4h"], ["Jc", "3d", "5c", "4h"],
        ])

        self.assertEqual(states[0]["position"], "SB")
        self.assertEqual(states[0]["hole_cards"], ["Ac", "2d"])
        self.assertEqual(states[0]["to_call"], 6000)
        self.assertEqual(states[0]["current_bet"], 1000)
        self.assertEqual(states[0]["stack"], 1124100)
        self.assertEqual(states[0]["min_raise_to"], 12000)
        self.assertEqual(states[0]["max_raise_to"], 1125100)

        self.assertEqual(states[3]["to_call"], 142600)
        self.assertEqual(states[3]["current_bet"], 90000)
        self.assertEqual(states[3]["min_raise_to"], 375200)
        self.assertEqual(states[3]["max_raise_to"], 1067100)
        self.assertEqual([state["players_active"] for state in states], [3, 2, 2, 2])
        self.assertEqual([state["players_to_act"] for state in states], [1, 1, 1, 0])
        self.assertEqual(states[0]["legal_actions"], ["fold", "call", "raise"])
        self.assertEqual(states[1]["legal_actions"], ["check", "raise"])
        self.assertEqual(ivey.LAST_LOAD_REPORT["decisions_excluded"], 0)

    def test_states_fit_the_bot_observation_protocol(self):
        for row in self.decisions:
            observation = Observation.from_dict(row["state"])
            self.assertEqual(observation.player_id, "p0")
            self.assertEqual(observation.contestable_pot, observation.pot)

    def test_states_do_not_expose_opponent_cards_or_future_board(self):
        serialized = json.dumps([row["state"] for row in self.decisions])
        for row in self.decisions:
            state = row["state"]
            self.assertEqual(state["hole_cards"], ["Ac", "2d"])
            self.assertNotIn("Jh", state["board"])
            self.assertNotIn("????", json.dumps(state))
            self.assertNotIn("7h", json.dumps(state))
            self.assertNotIn("6h", json.dumps(state))
            self.assertNotIn("expected", state)
        self.assertNotIn("Jh", serialized)
        self.assertNotIn("7h6h", serialized)

    def test_history_contains_only_prior_visible_betting(self):
        preflop, flop, turn, turn_raise = [row["state"] for row in self.decisions]
        self.assertEqual(preflop["history"], [{
            "street": "preflop", "player": "p2", "position": "BTN", "action": "raise",
            "amount": 7000, "added": 7000,
        }])
        self.assertEqual(len(flop["history"]), 4)
        self.assertEqual(len(turn["history"]), 6)
        self.assertEqual(len(turn_raise["history"]), 8)
        self.assertNotIn("river", {entry["street"] for entry in turn_raise["history"]})

    def test_expected_labels_follow_source_action_text(self):
        source = ivey.DEFAULT_PHH_PATH.read_text(encoding="utf-8")
        changed = source.replace('"p1 cbr 35000"', '"p1 cbr 40000"', 1)
        # Preserve a legal later all-in after spending another 5,000 here.
        changed = changed.replace('"p1 cbr 1067100"', '"p1 cbr 1062100"')
        with tempfile.TemporaryDirectory() as temporary:
            sample = Path(temporary) / "dwan-ivey-2009.phh"
            sample.write_text(changed, encoding="utf-8")
            decisions = ivey.load_decisions(sample)
        self.assertEqual(decisions[1]["expected"], {"action": "raise", "amount": 40000})

    def test_missing_files_are_excluded_and_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "not-present.phh"
            self.assertEqual(ivey.load_decisions(missing), [])
        self.assertEqual(ivey.LAST_LOAD_REPORT["files_excluded"], 1)
        self.assertEqual(ivey.LAST_LOAD_REPORT["exclusions"]["file:path_not_found"], 1)

    def test_hidden_hero_cards_are_not_recovered_from_later_showdown(self):
        source = ivey.DEFAULT_PHH_PATH.read_text(encoding="utf-8")
        hidden = source.replace('"d dh p1 Ac2d"', '"d dh p1 ????"', 1)
        with tempfile.TemporaryDirectory() as temporary:
            sample = Path(temporary) / "hidden-ivey.phh"
            sample.write_text(hidden, encoding="utf-8")
            decisions = ivey.load_decisions(sample)
        self.assertEqual(decisions, [])
        self.assertEqual(ivey.LAST_LOAD_REPORT["decisions_seen"], 4)
        self.assertEqual(ivey.LAST_LOAD_REPORT["decisions_excluded"], 4)
        self.assertEqual(
            ivey.LAST_LOAD_REPORT["exclusions"]["decision:hero_hole_cards_not_visible_at_decision"], 4
        )


class IveyScoringTests(unittest.TestCase):
    def test_action_agreement_sizing_and_hand_counts_are_separate(self):
        decisions = ivey.load_decisions()

        def sample_policy(state):
            if state["street"] == "flop":
                return {"action": "call"}
            target = {
                ("preflop", 1000): 23050,
                ("turn", 0): 90050,
                ("turn", 90000): 1067050,
            }[(state["street"], state["current_bet"])]
            return {"action": "raise", "amount": target}

        result = ivey.compare_decisions(decisions, sample_policy, sizing_tolerance=100)
        self.assertEqual(result["sample_count"], 4)
        self.assertEqual(result["hand_count"], 1)
        self.assertEqual(result["action_agreement_count"], 3)
        self.assertEqual(result["action_agreement"], 0.75)
        self.assertLess(result["action_agreement_ci95_wilson"][0], 0.75)
        self.assertGreater(result["action_agreement_ci95_wilson"][1], 0.75)
        self.assertEqual(result["raise_sizing"]["expected_raise_count"], 4)
        self.assertEqual(result["raise_sizing"]["sized_raise_count"], 3)
        self.assertEqual(result["raise_sizing"]["missing_or_unscored_count"], 1)
        self.assertEqual(result["raise_sizing"]["within_tolerance_count"], 3)
        self.assertEqual(result["raise_sizing"]["mean_absolute_error_chips"], 50)

    def test_empty_score_has_no_false_confidence_interval(self):
        result = ivey.compare_decisions([], lambda state: {"action": "check"})
        self.assertIsNone(result["action_agreement"])
        self.assertIsNone(result["action_agreement_ci95_wilson"])
        self.assertEqual(result["sample_count"], 0)


if __name__ == "__main__":
    unittest.main()
