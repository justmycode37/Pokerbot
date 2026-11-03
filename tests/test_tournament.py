import json
import unittest
from unittest.mock import patch

from pokerbot.simulation import InvalidActionError, calling_station
from pokerbot.tournament import icm_equities, play_tournament


def _mock_hand_engine(outcome, calls=None):
    """Build a deterministic hand engine whose outcome is in original IDs."""
    calls = [] if calls is None else calls

    def play(policies, *, stacks, big_blind, strict, include_trace, seed):
        order = [policy.original_index for policy in policies]
        current = {index: stack for index, stack in zip(order, stacks)}
        calls.append({"order": order, "big_blind": big_blind, "stacks": current})
        final = outcome(order, current, len(calls) - 1)
        engine_final = [final[index] for index in order]
        actions = [
            {
                "street": "preflop", "player": f"p{seat}", "position": "BTN",
                "action": "check", "amount": 0, "added": 0,
            }
            for seat in range(len(order))
        ]
        result = {
            "stacks": engine_final,
            "payoffs": [after - before for before, after in zip(stacks, engine_final)],
            "invalid_actions": [],
            "actions": actions,
        }
        metrics = [
            {"seat": seat, "latency_ns": (seat + 1) * 1_000_000}
            for seat in range(len(order))
        ]
        return result, metrics

    return play


class TournamentTests(unittest.TestCase):
    def test_icm_equal_stacks_and_payout_conservation(self):
        equities = icm_equities([100, 100, 100], [90, 30, 0])

        self.assertEqual(equities, [40.0, 40.0, 40.0])
        self.assertAlmostEqual(sum(equities), 120.0)

    def test_icm_respects_stack_weight_and_validates_payout_order(self):
        equities = icm_equities([300, 100], [80, 20])

        self.assertEqual(equities, [65.0, 35.0])
        with self.assertRaises(ValueError):
            icm_equities([100, 100], [10, 20])

    def test_icm_normalizes_large_finite_stacks_before_summing(self):
        self.assertEqual(icm_equities([1e308, 1e308], [80, 20]), [50.0, 50.0])
        self.assertEqual(icm_equities([1e308, 1e-308, 1e-308], [80, 20, 0]), [80.0, 10.0, 10.0])

    def test_button_and_big_blind_rotate_once_each_over_full_three_handed_cycle(self):
        calls = []
        mock = _mock_hand_engine(lambda _order, stacks, _hand: stacks, calls)
        with patch("pokerbot.tournament._play_hand", side_effect=mock):
            result = play_tournament(
                [calling_station] * 3, stacks=100, big_blinds=(10, 20),
                hands_per_level=1, max_hands=3, trace=True,
            )

        self.assertTrue(result["capped"])
        self.assertIsNone(result["winner"])
        self.assertEqual([row["order"] for row in calls], [[0, 1, 2], [1, 2, 0], [2, 0, 1]])
        self.assertEqual([row["button"] for row in result["trace"]], [2, 0, 1])
        self.assertEqual([row["big_blind_player"] for row in result["trace"]], [1, 2, 0])
        self.assertEqual([row["big_blind"] for row in calls], [10, 20, 20])
        self.assertEqual([player["decisions"] for player in result["players"]], [3, 3, 3])
        self.assertEqual(
            [player["latency_mean_ms"] for player in result["players"]],
            [2.0, 2.0, 2.0],
        )
        self.assertEqual(
            [player["latency_p95_ms"] for player in result["players"]],
            [3.0, 3.0, 3.0],
        )
        self.assertEqual([player["over_1ms"] for player in result["players"]], [2, 2, 2])
        self.assertEqual(sum(player["points"] for player in result["players"]), 6.0)

    def test_heads_up_initial_button_and_alternation_use_bb_btn_engine_order(self):
        calls = []
        mock = _mock_hand_engine(lambda _order, stacks, _hand: stacks, calls)
        with patch("pokerbot.tournament._play_hand", side_effect=mock):
            result = play_tournament(
                [calling_station, calling_station], stacks=100,
                big_blinds=(20,), max_hands=2, trace=True,
            )

        self.assertEqual([row["order"] for row in calls], [[0, 1], [1, 0]])
        self.assertEqual([row["button"] for row in result["trace"]], [1, 0])
        self.assertEqual([row["small_blind"] for row in result["trace"]], [1, 0])
        self.assertEqual([row["big_blind_player"] for row in result["trace"]], [0, 1])

    def test_bust_in_either_blind_transitions_to_heads_up_without_repeating_bb(self):
        scenarios = (
            ("SB", [0, 200, 100], 1, 2),
            ("BB", [100, 0, 200], 0, 2),
        )
        for busted_position, first_result, next_button, next_bb in scenarios:
            with self.subTest(busted_position=busted_position):
                calls = []

                def outcome(order, current, hand_number):
                    if hand_number == 0:
                        self.assertEqual(order, [0, 1, 2])
                        return first_result
                    return current

                mock = _mock_hand_engine(outcome, calls)
                with patch("pokerbot.tournament._play_hand", side_effect=mock):
                    result = play_tournament(
                        [calling_station] * 3, stacks=100, big_blinds=(20,),
                        max_hands=2, trace=True,
                    )

                self.assertEqual(result["trace"][1]["button"], next_button)
                self.assertEqual(result["trace"][1]["big_blind_player"], next_bb)
                self.assertNotEqual(result["trace"][0]["big_blind_player"], next_bb)
                self.assertEqual(result["trace"][1]["seat_order"], [next_bb, next_button])

    def test_busted_button_does_not_make_surviving_bb_post_bb_twice_at_hu(self):
        mock = _mock_hand_engine(lambda _order, _stacks, _hand: [150, 150, 0])
        with patch("pokerbot.tournament._play_hand", side_effect=mock):
            result = play_tournament(
                [calling_station] * 3, stacks=100, big_blinds=(20,),
                max_hands=2, trace=True,
            )

        # Previous BB (1) gets BTN/SB, while previous SB (0) becomes BB.
        self.assertEqual(result["trace"][1]["button"], 1)
        self.assertEqual(result["trace"][1]["big_blind_player"], 0)

    def test_simultaneous_busts_split_rank_points_and_capped_survivors_get_icm(self):
        mock = _mock_hand_engine(
            lambda _order, _stacks, _hand: [150, 150, 0, 0]
        )
        with patch("pokerbot.tournament._play_hand", side_effect=mock):
            result = play_tournament(
                [calling_station] * 4, stacks=[100, 100, 50, 50],
                big_blinds=(20,), max_hands=1, trace=True,
            )

        self.assertTrue(result["capped"])
        self.assertIsNone(result["winner"])
        self.assertEqual([player["finish"] for player in result["players"]], [1.5, 1.5, 3.5, 3.5])
        self.assertEqual([player["points"] for player in result["players"]], [3.5, 3.5, 1.5, 1.5])
        self.assertEqual(sum(player["points"] for player in result["players"]), 10.0)

    def test_simultaneous_busts_are_ordered_by_stack_entering_the_hand(self):
        mock = _mock_hand_engine(lambda _order, _stacks, _hand: [200, 0, 140, 0])
        with patch("pokerbot.tournament._play_hand", side_effect=mock):
            result = play_tournament(
                [calling_station] * 4, stacks=[100, 90, 80, 70],
                big_blinds=(20,), max_hands=1,
            )

        self.assertEqual(result["players"][1]["finish"], 3.0)
        self.assertEqual(result["players"][3]["finish"], 4.0)
        self.assertEqual(result["players"][1]["points"], 2.0)
        self.assertEqual(result["players"][3]["points"], 1.0)
        self.assertAlmostEqual(result["players"][0]["finish"], 24 / 17)
        self.assertAlmostEqual(result["players"][2]["finish"], 27 / 17)

    def test_complete_mock_tournament_declares_only_actual_survivor_winner(self):
        mock = _mock_hand_engine(lambda _order, _stacks, _hand: [100, 0])
        with patch("pokerbot.tournament._play_hand", side_effect=mock):
            result = play_tournament(
                [calling_station, calling_station], stacks=50,
                big_blinds=(20,), max_hands=1,
            )

        self.assertEqual(result["winner"], 0)
        self.assertFalse(result["capped"])
        self.assertEqual([player["finish"] for player in result["players"]], [1.0, 2.0])
        self.assertEqual([player["won"] for player in result["players"]], [True, False])

    def test_real_pokerkit_tournament_handles_odd_stacks_and_json_output(self):
        result = play_tournament(
            [calling_station] * 3, seed=71, stacks=[1, 3, 5],
            big_blinds=(20,), max_hands=1, trace=True,
        )

        self.assertEqual(sum(result["final_stacks"]), 9)
        self.assertEqual(result["hands_played"], 1)
        self.assertEqual(len(result["trace"][0]["seat_order"]), 3)
        self.assertGreaterEqual(sum(player["decisions"] for player in result["players"]), 1)
        json.dumps(result)

    def test_hand_seed_makes_tournament_actions_reproducible(self):
        first = play_tournament(
            [calling_station] * 3, seed=241, stacks=500,
            big_blinds=(20,), max_hands=3, trace=True,
        )
        second = play_tournament(
            [calling_station] * 3, seed=241, stacks=500,
            big_blinds=(20,), max_hands=3, trace=True,
        )

        self.assertEqual(first["trace"], second["trace"])
        self.assertEqual(first["final_stacks"], second["final_stacks"])
        self.assertEqual(first["winner"], second["winner"])

    def test_real_heads_up_hands_track_stable_anonymous_ids_and_metrics(self):
        observed = [[], []]

        def policy(index):
            def act(observation):
                observed[index].append(observation)
                return calling_station(observation)
            return act

        result = play_tournament(
            [policy(0), policy(1)], seed=19, stacks=500,
            big_blinds=(20,), max_hands=2, trace=True,
        )

        for index, items in enumerate(observed):
            self.assertTrue(items)
            self.assertTrue(all(item["player_id"] == f"p{index}" for item in items))
            self.assertEqual(sorted({item["hand_index"] for item in items}), [0, 1])
            for item in items:
                self.assertNotIn("opponent_hole_cards", item)
                self.assertTrue(all(action["player"] in {"p0", "p1"} for action in item["history"]))
        self.assertTrue(all(player["decisions"] > 0 for player in result["players"]))
        self.assertEqual(result["trace"][0]["seat_order"], [0, 1])
        self.assertEqual(result["trace"][0]["button"], 1)
        first_action = result["trace"][0]["actions"][0]
        self.assertEqual((first_action["player"], first_action["position"]), ("p1", "BTN"))

    def test_illegal_actions_raise_or_are_visible_in_non_strict_mode(self):
        def illegal(_observation):
            return {"action": "raise"}

        with self.assertRaises(InvalidActionError):
            play_tournament([illegal, calling_station], big_blinds=(20,), max_hands=1)

        result = play_tournament(
            [illegal, calling_station], big_blinds=(20,), max_hands=1, strict=False,
        )
        self.assertGreater(result["invalid_actions"], 0)
        self.assertEqual(
            sum(player["invalid_actions"] for player in result["players"]),
            result["invalid_actions"],
        )

    def test_config_persists_illustrative_defaults_and_validates_inputs(self):
        result = play_tournament(
            [calling_station] * 2, stacks=100, max_hands=1, big_blinds=(20,),
        )

        self.assertEqual(result["config"]["payouts"], [2.0, 1.0])
        self.assertTrue(result["config"]["payouts_defaulted"])
        self.assertIn("illustrative", result["config"]["blind_schedule_caveat"])
        with self.assertRaises(ValueError):
            play_tournament([calling_station] * 2, payouts=[1, 2])
        with self.assertRaises(ValueError):
            play_tournament([calling_station] * 2, payouts=[1, float("nan")])
        with self.assertRaises(ValueError):
            play_tournament([calling_station] * 2, payouts=[1])
        with self.assertRaises(ValueError):
            play_tournament([calling_station] * 2, big_blinds=(20, 10))

    def test_reset_hook_runs_once_per_distinct_policy_object(self):
        class ResettablePolicy:
            def __init__(self):
                self.reset_calls = 0

            def reset(self):
                self.reset_calls += 1

            def __call__(self, observation):
                return calling_station(observation)

        policy = ResettablePolicy()
        play_tournament([policy, policy], stacks=100, big_blinds=(20,), max_hands=1)

        self.assertEqual(policy.reset_calls, 1)


if __name__ == "__main__":
    unittest.main()
