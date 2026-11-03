import math
import unittest

from pokerbot.equity_policy import make_equity_policy
from pokerbot.evolution_strategies import DEFAULT_PARAMS, Genome, policy_for


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


def postflop_call(**updates):
    raw = observation(
        hole_cards=["Ad", "Kc"],
        board=["Ah", "7d", "2c"],
        pot=100,
        to_call=10,
        stack=1000,
        current_bet=0,
        min_raise_to=0,
        max_raise_to=0,
        players_active=2,
        players_to_act=1,
        legal_actions=["fold", "call"],
        seed=73,
    )
    raw.update(updates)
    return raw


class EquityPolicyTests(unittest.TestCase):
    def test_preflop_matches_evolved_policy_exactly_and_never_calls_estimator(self):
        genome = Genome("preflop-parity", params={
            **DEFAULT_PARAMS,
            "opening_shift": -0.06,
            "call_margin": 0.025,
            "bet_size": 0.71,
        })
        static = policy_for(genome)

        def forbidden_estimator(*_args):
            self.fail("preflop policy called the postflop estimator")

        calibrated = make_equity_policy(genome, forbidden_estimator)
        fixtures = (
            observation(hole_cards=["As", "Kd"], position="BTN"),
            observation(hole_cards=["7h", "7c"], position="CO"),
            observation(hole_cards=["2s", "7s"], position="UTG"),
            observation(hole_cards=["Ad", "Ac"], position="BB", to_call=0,
                        legal_actions=["check", "raise"]),
        )
        for fixture in fixtures:
            for seed in (0, 1, 42, 73, 2**31 - 1):
                raw = {**fixture, "seed": seed}
                with self.subTest(hole=fixture["hole_cards"], seed=seed):
                    self.assertEqual(calibrated(raw), static(raw))

    def test_calibrated_top_pair_uses_injected_share_and_keeps_pressure_separate(self):
        genome = Genome("top-pair", params={**DEFAULT_PARAMS, "call_frequency": 1.0})
        raw = postflop_call()
        high = make_equity_policy(genome, lambda _hole, _board, _active: 0.60)(raw)
        low = make_equity_policy(genome, lambda _hole, _board, _active: 0.0)(raw)

        self.assertEqual(high["action"], "call")
        self.assertEqual(high["probabilities"], {"call": 1.0, "fold": 0.0})
        self.assertEqual(high["diagnostics"]["estimator_raw_share"], 0.60)
        self.assertEqual(high["diagnostics"]["pressure_discount"], 0.035)
        self.assertAlmostEqual(high["diagnostics"]["decision_equity"], 0.565)
        self.assertAlmostEqual(high["diagnostics"]["pot_odds"], 10 / 110)
        self.assertEqual(low["action"], "fold")

    def test_multiway_estimate_is_not_penalized_twice(self):
        genome = Genome("multiway-share", params={**DEFAULT_PARAMS, "call_frequency": 1.0})
        raw = postflop_call(players_active=5, players_to_act=4)
        decision = make_equity_policy(genome, lambda _hole, _board, active: 0.60)(raw)
        details = decision["diagnostics"]

        self.assertEqual(details["opponents_in_pot"], 4)
        self.assertEqual(details["estimator_raw_share"], 0.60)
        self.assertEqual(details["pressure_discount"], 0.035)
        self.assertAlmostEqual(details["decision_equity"], 0.565)
        self.assertEqual(details["multiway_equity_subtraction"], 0.0)
        self.assertAlmostEqual(details["public_heuristic_multiway_penalty_ignored"], 0.135)
        self.assertEqual(decision["action"], "call")

    def test_exact_shared_board_tie_and_unbeatable_hand_override_bad_share(self):
        genome = Genome("exact-proof", params={**DEFAULT_PARAMS, "call_frequency": 0.45})
        calls = []

        def zero_estimator(hole_cards, board, players_active):
            calls.append((hole_cards, board, players_active))
            return 0.0

        tie_raw = postflop_call(
            hole_cards=["2c", "3d"],
            board=["As", "Kh", "Qc", "Jd", "Ts"],
            pot=100, to_call=1, players_active=4, players_to_act=3,
            legal_actions=["fold", "call"],
        )
        tie = make_equity_policy(genome, zero_estimator)(tie_raw)
        self.assertEqual(tie["diagnostics"]["estimator_raw_share"], 0.0)
        self.assertEqual(tie["diagnostics"]["decision_equity"], 0.25)
        self.assertEqual(tie["diagnostics"]["pressure_discount"], 0.0)
        self.assertTrue(tie["diagnostics"]["exact_shared_board_tie"])
        self.assertEqual(tie["probabilities"]["fold"], 0.0)
        self.assertEqual(tie["action"], "call")

        nuts_raw = postflop_call(
            hole_cards=["Ah", "Qc"],
            board=["2h", "4h", "7h", "9h", "Kc"],
            pot=100, to_call=10, legal_actions=["fold", "call"],
        )
        nuts = make_equity_policy(genome, zero_estimator)(nuts_raw)
        self.assertTrue(nuts["diagnostics"]["exact_unbeatable_hand"])
        self.assertEqual(nuts["diagnostics"]["decision_equity"], 1.0)
        self.assertEqual(nuts["probabilities"]["fold"], 0.0)
        self.assertEqual(nuts["action"], "call")
        self.assertEqual(len(calls), 2)

    def test_estimator_receives_only_normalized_public_cards_and_active_count(self):
        genome = Genome("public-estimator")
        calls = []

        def spy(hole_cards, board, players_active):
            calls.append((hole_cards, board, players_active))
            return 0.55

        policy = make_equity_policy(genome, spy)
        public = postflop_call(players_active=3, players_to_act=2)
        private_noise = {
            **public,
            "opponent_cards": ["2s", "3s"],
            "future_board": ["4s", "5s"],
            "private_outcome": "lost",
            "history": [{
                "street": "flop", "player": "p1", "action": "call", "amount": 10,
                "opponent_cards": ["2s", "3s"], "outcome": "won", "expected_action": "fold",
            }],
        }
        self.assertEqual(policy(public), policy(private_noise))
        self.assertEqual(calls, [(("Ad", "Kc"), ("Ah", "7d", "2c"), 3)] * 2)
        self.assertEqual(len(calls[0]), 3)
        self.assertIs(type(calls[0][2]), int)

    def test_bad_estimator_results_fail_clearly(self):
        genome = Genome("invalid-share")
        raw = postflop_call()
        for value in (math.nan, math.inf, -0.01, 1.01, True, "0.5", None):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, r"finite number in \[0, 1\]"):
                make_equity_policy(genome, lambda *_args, result=value: result)(raw)

    def test_missing_or_failing_estimator_raises_without_a_fallback(self):
        genome = Genome("unavailable-estimator")
        with self.assertRaisesRegex(TypeError, "estimator must be a callable"):
            make_equity_policy(genome, None)

        def unavailable(*_args):
            raise OSError("model service unavailable")

        policy = make_equity_policy(genome, unavailable)
        with self.assertRaisesRegex(RuntimeError, "equity estimator failed") as caught:
            policy(postflop_call())
        self.assertIsInstance(caught.exception.__cause__, OSError)

    def test_short_all_in_raise_amounts_and_legal_action_projection(self):
        genome = Genome("short-all-in", params={
            **DEFAULT_PARAMS,
            "short_stack_bb": 10.0,
            "short_stack_cutoff": 0.45,
            "value_raise_threshold": 0.56,
        })
        raw = postflop_call(
            to_call=80, stack=100, pot=300,
            min_raise_to=100, max_raise_to=100,
            legal_actions=["fold", "call", "raise"],
        )
        decision = make_equity_policy(genome, lambda *_args: 0.99)(raw)
        self.assertTrue(decision["diagnostics"]["short_stack"])
        self.assertEqual(decision["raise_amount"], 100)
        self.assertLessEqual(decision["raise_amount"], raw["max_raise_to"])
        self.assertGreaterEqual(decision["raise_amount"], raw["min_raise_to"])
        self.assertIn(decision["action"], raw["legal_actions"])
        self.assertEqual(set(decision["probabilities"]), set(raw["legal_actions"]))
        if decision["action"] == "raise":
            self.assertEqual(decision["amount"], 100)
        else:
            self.assertEqual(decision["amount"], 0)

        closed = postflop_call(legal_actions=["fold", "call"])
        projected = make_equity_policy(genome, lambda *_args: 0.99)(closed)
        self.assertNotIn("raise", projected["probabilities"])
        self.assertEqual(projected["raise_amount"], 0)
        self.assertIn(projected["action"], closed["legal_actions"])

    def test_policy_instances_keep_estimators_and_metadata_independent(self):
        genome = Genome("two-tables", params={**DEFAULT_PARAMS, "call_frequency": 1.0})
        source_metadata = {"model": {"version": 1}}
        first = make_equity_policy(genome, lambda *_args: 0.80, source_metadata)
        source_metadata["model"]["version"] = 2
        second = make_equity_policy(genome, lambda *_args: 0.10, {"model": {"version": 2}})
        raw = postflop_call()

        first_decision = first(raw)
        first_decision["diagnostics"]["model_metadata"]["model"]["version"] = 99
        self.assertEqual(first(raw)["diagnostics"]["model_metadata"], {"model": {"version": 1}})
        self.assertEqual(second(raw)["diagnostics"]["model_metadata"], {"model": {"version": 2}})
        self.assertEqual(first(raw)["diagnostics"]["estimator_raw_share"], 0.80)
        self.assertEqual(second(raw)["diagnostics"]["estimator_raw_share"], 0.10)
        self.assertIsNot(first, second)


if __name__ == "__main__":
    unittest.main()
