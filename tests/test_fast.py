import json
from pathlib import Path
import unittest

from pokerbot.fast import decide
from pokerbot.preflop import hand_class, preflop_equity
from pokerbot.fast import _postflop_equity
from pokerbot.state import Observation


def observation(**updates):
    raw = {
        "hole_cards": ["As", "Kd"],
        "board": [],
        "pot": 30,
        "to_call": 0,
        "stack": 1000,
        "current_bet": 0,
        "min_raise_to": 20,
        "max_raise_to": 1000,
        "big_blind": 10,
        "position": "BTN",
        "players_active": 2,
        "players_to_act": 1,
        "legal_actions": ["fold", "raise"],
        "seed": 73,
    }
    raw.update(updates)
    return raw


class FastPolicyTests(unittest.TestCase):
    def assert_legal_result(self, raw, result):
        self.assertIn(result["action"], raw["legal_actions"])
        self.assertAlmostEqual(sum(result["probabilities"].values()), 1.0)
        self.assertTrue(set(result["probabilities"]).issubset(raw["legal_actions"]))
        if result["action"] == "raise":
            self.assertGreaterEqual(result["amount"], raw["min_raise_to"])
            self.assertLessEqual(result["amount"], raw["max_raise_to"])
            self.assertLessEqual(result["amount"], raw["current_bet"] + raw["stack"])
            self.assertEqual(result["amount"], result["raise_amount"])
        else:
            self.assertEqual(result["amount"], 0)

    def test_premium_preflop_hand_opens_with_legal_total_bet(self):
        raw = observation(hole_cards=["As", "Ah"], position="UTG", players_to_act=6)
        raw["players_active"] = 8
        result = decide(raw)
        self.assertEqual(hand_class(raw["hole_cards"]), "AA")
        self.assertGreater(preflop_equity(raw["hole_cards"]), 0.80)
        self.assertEqual(result["action"], "raise")
        self.assertGreaterEqual(result["amount"], raw["min_raise_to"])
        self.assertLessEqual(result["amount"], raw["max_raise_to"])

    def test_repository_decision_example_is_an_unopened_raise_first_in(self):
        fixture_path = Path(__file__).resolve().parents[1] / "examples" / "decision.json"
        raw = json.loads(fixture_path.read_text(encoding="utf-8"))
        result = decide(raw)
        self.assertEqual(result["action"], "raise")
        self.assertEqual(result["diagnostics"]["preflop_situation"], "unopened")
        self.assertEqual(result["diagnostics"]["opponents_in_pot"], 0)
        self.assertEqual(result["diagnostics"]["players_waiting"], 7)
        self.assertEqual(result["amount"], 225)

    def test_low_flush_on_four_suited_turn_is_not_a_high_equity_value_hand(self):
        raw = observation(hole_cards=["8s", "4c"], board=["Jc", "9c", "Tc", "Ac"],
                          players_active=8, players_to_act=0, position="BB",
                          to_call=50, pot=100, stack=1000, current_bet=0,
                          min_raise_to=100, max_raise_to=1000,
                          legal_actions=["fold", "call", "raise"])
        result = decide(raw)
        self.assertEqual(result["action"], "fold")
        self.assertLess(result["diagnostics"]["raw_hand_draw_estimate"], 0.10)
        self.assertEqual(result["diagnostics"]["equity_model"], "conservative_suited_turn_floor")

    def test_suited_river_model_is_not_discounted_twice_for_multiple_opponents(self):
        from math import comb
        raw = observation(hole_cards=["8s", "4c"], board=["Jc", "9c", "Tc", "Ac", "2d"],
                          players_active=4, players_to_act=0, legal_actions=["check"])
        equity, details = _postflop_equity(Observation.from_dict(raw))
        self.assertAlmostEqual(equity, comb(39, 6) / comb(45, 6), places=12)
        self.assertEqual(details["multiway_penalty"], 0)
        self.assertEqual(details["equity_model"], "exact_uniform_suited_river")

    def test_aa_and_kk_raise_first_in_across_positions_with_players_behind(self):
        fixtures = [("UTG", 7, ["As", "Ah"]), ("MP", 5, ["Ks", "Kh"]), ("CO", 3, ["As", "Ah"])]
        for position, waiting, hole_cards in fixtures:
            raw = observation(
                hole_cards=hole_cards,
                pot=150,
                to_call=100,
                stack=10000,
                current_bet=0,
                min_raise_to=200,
                max_raise_to=10000,
                big_blind=100,
                position=position,
                players_active=8,
                players_to_act=waiting,
                legal_actions=["fold", "call", "raise"],
                history=[],
            )
            result = decide(raw)
            with self.subTest(position=position, waiting=waiting):
                self.assertEqual(result["action"], "raise")
                self.assertEqual(result["diagnostics"]["preflop_situation"], "unopened")
                self.assertEqual(result["diagnostics"]["opponents_in_pot"], 0)

    def test_unopened_weak_hand_folds_instead_of_limping(self):
        raw = observation(
            hole_cards=["7c", "2d"],
            pot=150,
            to_call=100,
            current_bet=0,
            min_raise_to=200,
            max_raise_to=1000,
            big_blind=100,
            position="UTG",
            players_active=8,
            players_to_act=7,
            legal_actions=["fold", "call", "raise"],
        )
        result = decide(raw)
        self.assertEqual(result["diagnostics"]["preflop_situation"], "unopened")
        self.assertEqual(result["action"], "fold")

    def test_visible_caller_makes_a_limped_pot_not_an_unopened_rfi(self):
        raw = observation(
            hole_cards=["As", "Ah"],
            pot=250,
            to_call=100,
            stack=10000,
            current_bet=0,
            min_raise_to=200,
            max_raise_to=10000,
            big_blind=100,
            position="MP",
            players_active=8,
            players_to_act=4,
            legal_actions=["fold", "call", "raise"],
            history=[{"street": "preflop", "player": "limper", "action": "call", "amount": 100}],
        )
        result = decide(raw)
        self.assertEqual(result["diagnostics"]["preflop_situation"], "limped")
        self.assertEqual(result["diagnostics"]["opponents_in_pot"], 1)
        self.assertEqual(result["action"], "raise")

    def test_big_blind_defends_against_late_opener_without_counting_waiters(self):
        raw = observation(
            hole_cards=["Kc", "Qc"],
            pot=400,
            to_call=100,
            stack=1000,
            current_bet=100,
            min_raise_to=201,
            max_raise_to=1100,
            big_blind=100,
            position="BB",
            players_active=8,
            players_to_act=0,
            legal_actions=["fold", "call", "raise"],
            history=[{"street": "preflop", "player": "button", "position": "BTN", "action": "raise", "amount": 200}],
        )
        result = decide(raw)
        self.assertEqual(result["action"], "call")
        self.assertEqual(result["diagnostics"]["preflop_situation"], "raised")
        self.assertEqual(result["diagnostics"]["opponents_in_pot"], 1)
        self.assertEqual(result["diagnostics"]["players_waiting"], 0)

    def test_free_big_blind_check_keeps_trash_out_of_a_raise(self):
        raw = observation(
            hole_cards=["7c", "2d"],
            position="BB",
            players_active=2,
            players_to_act=0,
            legal_actions=["check", "raise"],
        )
        result = decide(raw)
        self.assertEqual(result["action"], "check")
        self.assertEqual(result["probabilities"].get("check"), 1.0)
        self.assertEqual(result["probabilities"].get("raise"), 0.0)

    def test_big_blind_defends_wider_at_a_cheap_price(self):
        raw = observation(
            hole_cards=["Qc", "3d"],
            pot=50,
            to_call=10,
            stack=1000,
            current_bet=10,
            min_raise_to=21,
            max_raise_to=1010,
            position="BB",
            legal_actions=["fold", "call"],
            history=[{"street": "preflop", "player": "raiser", "action": "raise", "amount": 20}],
        )
        result = decide(raw)
        self.assertEqual(result["action"], "call")

    def test_board_play_tie_does_not_raise(self):
        raw = observation(
            hole_cards=["2c", "3d"],
            board=["Ah", "Kh", "Qh", "Jh", "Th"],
            pot=100,
            to_call=10,
            stack=500,
            current_bet=20,
            min_raise_to=60,
            max_raise_to=200,
            legal_actions=["fold", "call", "raise"],
        )
        result = decide(raw)
        self.assertTrue(result["diagnostics"]["board_play"])
        self.assertEqual(result["probabilities"].get("raise", 0.0), 0.0)
        self.assertEqual(result["action"], "call")

    def test_royal_flush_board_tie_keeps_exact_multiway_share_and_calls(self):
        raw = observation(
            hole_cards=["2h", "3d"],
            board=["As", "Ks", "Qs", "Js", "Ts"],
            pot=800,
            to_call=20,
            stack=1000,
            current_bet=0,
            min_raise_to=40,
            max_raise_to=1000,
            big_blind=20,
            position="BB",
            players_active=8,
            players_to_act=0,
            legal_actions=["fold", "call", "raise"],
        )
        result = decide(raw)
        self.assertTrue(result["diagnostics"]["exact_shared_board_tie"])
        self.assertAlmostEqual(result["diagnostics"]["estimated_equity"], 1 / 8)
        self.assertEqual(result["diagnostics"]["pressure_discount"], 0.0)
        self.assertEqual(result["diagnostics"]["multiway_penalty"], 0.0)
        self.assertEqual(result["diagnostics"]["texture_penalty"], 0.0)
        self.assertEqual(result["diagnostics"]["continue_threshold"], result["diagnostics"]["pot_odds"])
        self.assertEqual(result["probabilities"].get("raise", 0.0), 0.0)
        self.assertEqual(result["action"], "call")

    def test_policy_never_calls_for_free_or_folds_when_fold_is_illegal(self):
        free = observation(
            hole_cards=["7c", "2d"],
            position="BB",
            legal_actions=["check", "raise"],
        )
        free_result = decide(free)
        self.assertNotEqual(free_result["action"], "call")

        facing = observation(
            hole_cards=["As", "Ah"],
            pot=110,
            to_call=20,
            current_bet=40,
            min_raise_to=80,
            max_raise_to=300,
            legal_actions=["call", "raise"],
            history=[{"street": "preflop", "player": "villain", "action": "raise", "amount": 40}],
        )
        result = decide(facing)
        self.assertNotEqual(result["action"], "fold")
        self.assertIn(result["action"], facing["legal_actions"])

    def test_short_stack_raise_is_bounded_by_all_in_total(self):
        raw = observation(
            hole_cards=["As", "Ks"],
            position="UTG",
            stack=60,
            max_raise_to=60,
            players_to_act=6,
            players_active=8,
        )
        result = decide(raw)
        self.assertEqual(result["action"], "raise")
        self.assertEqual(result["amount"], 60)
        self.assert_legal_result(raw, result)

    def test_decisions_remain_legal_across_street_and_pressure_fixtures(self):
        fixtures = [
            observation(
                hole_cards=["Qh", "Jh"],
                board=["Th", "9h", "2c"],
                pot=120,
                to_call=20,
                stack=500,
                current_bet=40,
                min_raise_to=61,
                max_raise_to=500,
                legal_actions=["fold", "call", "raise"],
                position="BTN",
            ),
            observation(
                hole_cards=["8s", "8d"],
                board=["As", "Kh", "3c", "2d"],
                pot=150,
                to_call=100,
                stack=400,
                current_bet=120,
                min_raise_to=221,
                max_raise_to=520,
                legal_actions=["fold", "call", "raise"],
                position="MP",
                players_active=3,
                history=[{"street": "turn", "player": "v", "action": "raise", "added": 100}],
            ),
            observation(
                hole_cards=["9c", "9d"],
                position="CO",
                to_call=20,
                pot=50,
                current_bet=40,
                stack=250,
                min_raise_to=80,
                max_raise_to=290,
                legal_actions=["fold", "call", "raise"],
                players_active=2,
                history=[{"street": "preflop", "player": "v", "action": "raise", "amount": 40}],
            ),
        ]
        for raw in fixtures:
            with self.subTest(street=len(raw["board"]), hand=raw["hole_cards"]):
                self.assert_legal_result(raw, decide(raw))


if __name__ == "__main__":
    unittest.main()
