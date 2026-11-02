import unittest

from pokerbot.simulation import (
    InvalidActionError,
    benchmark,
    calling_station,
    play_hand,
    random_legal,
)


class SimulationTests(unittest.TestCase):
    def test_hu_chip_conservation_and_reproducibility_without_latency(self):
        first = play_hand([calling_station, calling_station], seed=418, trace=True)
        second = play_hand([calling_station, calling_station], seed=418, trace=True)

        self.assertEqual(first, second)
        self.assertEqual(sum(first["payoffs"]), 0)
        self.assertEqual(sum(first["stacks"]), 4000)
        self.assertGreater(len(first["actions"]), 0)
        self.assertNotIn("latency", first)

    def test_eight_player_hand_conserves_chips(self):
        result = play_hand([calling_station] * 8, seed=99)

        self.assertEqual(result["table_size"], 8)
        self.assertEqual(len(result["payoffs"]), 8)
        self.assertEqual(sum(result["payoffs"]), 0)
        self.assertEqual(sum(result["stacks"]), 8 * 2000)

    def test_unequal_stack_all_in_settles_side_pots_and_returns_excess(self):
        def button_jams(observation):
            if (observation["position"] == "BTN"
                    and observation["street"] == "preflop"
                    and "raise" in observation["legal_actions"]):
                return {"action": "raise", "amount": observation["max_raise_to"]}
            return {"action": "call" if observation["to_call"] else "check"}

        result = play_hand(
            [calling_station, calling_station, button_jams],
            seed=2,
            stacks=[100, 200, 300],
            trace=True,
        )

        self.assertEqual(result["payoffs"], [-100, -200, 300])
        self.assertEqual(result["stacks"], [0, 0, 600])
        self.assertEqual(sum(result["stacks"]), 600)
        raise_action = next(action for action in result["actions"] if action["action"] == "raise")
        self.assertEqual(raise_action["amount"], 300)
        self.assertEqual(raise_action["added"], 300)

        small_blind_observation = next(
            item["observation"] for item in result["trace"]
            if item["observation"]["position"] == "SB"
            and item["observation"]["street"] == "preflop"
        )
        self.assertEqual(small_blind_observation["pot"], 330)
        self.assertEqual(small_blind_observation["contestable_pot"], 130)
        self.assertEqual(small_blind_observation["to_call"], 90)

    def test_observations_are_hero_only_and_use_visible_history(self):
        result = play_hand([calling_station] * 3, seed=2026, trace=True)
        forbidden = {
            "deck", "future_board", "opponent_hole_cards", "payoffs",
            "stacks", "outcome", "winner",
        }

        for item in result["trace"]:
            observation = item["observation"]
            self.assertTrue(forbidden.isdisjoint(observation))
            self.assertEqual(len(observation["hole_cards"]), 2)
            self.assertIn(len(observation["board"]), (0, 3, 4, 5))
            self.assertEqual(observation["players_active"] >= 2, True)
            for action in observation["history"]:
                self.assertLessEqual(
                    set(action),
                    {"street", "player", "position", "action", "amount", "added"},
                )

    def test_raise_bounds_and_action_amounts_are_street_totals(self):
        def min_open(observation):
            if (observation["position"] == "BTN"
                    and observation["street"] == "preflop"
                    and "raise" in observation["legal_actions"]):
                return {"action": "raise", "amount": observation["min_raise_to"]}
            return {"action": "call" if observation["to_call"] else "check"}

        result = play_hand(
            [calling_station, calling_station, min_open], seed=11, trace=True
        )
        first = result["trace"][0]
        self.assertEqual(first["observation"]["position"], "BTN")
        self.assertEqual(first["observation"]["current_bet"], 0)
        self.assertEqual(first["observation"]["to_call"], 20)
        self.assertEqual(first["observation"]["min_raise_to"], 40)
        self.assertEqual(first["observation"]["max_raise_to"], 2000)
        self.assertEqual(first["action"]["amount"], 40)
        self.assertEqual(first["action"]["added"], 40)

        sb_call = next(
            action for action in result["actions"]
            if action["position"] == "SB" and action["street"] == "preflop"
        )
        bb_call = next(
            action for action in result["actions"]
            if action["position"] == "BB" and action["street"] == "preflop"
        )
        self.assertEqual((sb_call["amount"], sb_call["added"]), (40, 30))
        self.assertEqual((bb_call["amount"], bb_call["added"]), (40, 20))

    def test_short_all_in_raise_does_not_reopen_prior_actor(self):
        def small_blind_policy(observation):
            if (observation["position"] == "SB"
                    and observation["street"] == "flop"
                    and observation["to_call"] == 0
                    and "raise" in observation["legal_actions"]):
                return {"action": "raise", "amount": 40}
            return {"action": "call" if observation["to_call"] else "check"}

        def short_all_in_big_blind(observation):
            if (observation["position"] == "BB"
                    and observation["street"] == "flop"
                    and observation["to_call"] == 40
                    and "raise" in observation["legal_actions"]):
                return {"action": "raise", "amount": observation["max_raise_to"]}
            return {"action": "call" if observation["to_call"] else "check"}

        result = play_hand(
            [small_blind_policy, short_all_in_big_blind, calling_station],
            seed=22,
            stacks=[200, 70, 200],
            trace=True,
        )
        big_blind_raise = next(
            item for item in result["trace"]
            if item["observation"]["position"] == "BB"
            and item["observation"]["street"] == "flop"
            and item["decision"]["action"] == "raise"
        )
        self.assertEqual(big_blind_raise["observation"]["min_raise_to"], 50)
        self.assertEqual(big_blind_raise["observation"]["max_raise_to"], 50)
        self.assertEqual(big_blind_raise["action"]["amount"], 50)

        prior_actor = next(
            item["observation"] for item in result["trace"]
            if item["observation"]["position"] == "SB"
            and item["observation"]["street"] == "flop"
            and item["observation"]["to_call"] == 10
        )
        self.assertNotIn("raise", prior_actor["legal_actions"])
        self.assertEqual(prior_actor["min_raise_to"], 0)
        self.assertEqual(prior_actor["max_raise_to"], 0)

    def test_illegal_policy_output_fails_strictly_and_is_counted_otherwise(self):
        def illegal(_observation):
            return {"action": "raise"}

        with self.assertRaises(InvalidActionError):
            play_hand([illegal, calling_station], seed=17)

        result = play_hand(
            [illegal, calling_station], seed=17, strict=False, trace=True
        )
        self.assertGreater(len(result["invalid_actions"]), 0)
        for invalid in result["invalid_actions"]:
            self.assertIn("integer total street bet", invalid["reason"])
            self.assertIn(invalid["fallback"]["action"], ("check", "fold", "call"))

    def test_random_legal_policy_and_clustered_benchmark_metrics(self):
        first = play_hand([random_legal, calling_station], seed=5)
        second = play_hand([random_legal, calling_station], seed=5)
        self.assertEqual(first, second)

        result = benchmark(
            calling_station,
            [calling_station],
            hands=4,
            seed=3,
        )
        self.assertEqual(result["hands_requested"], 4)
        self.assertEqual(result["hands_played"], 4)
        self.assertEqual(result["uncertainty"]["blocks"], 2)
        self.assertIsNotNone(result["uncertainty"]["standard_error_bb_per_100"])
        self.assertGreater(result["hero_decisions"]["count"], 0)
        self.assertIn("latency_ms", result["hero_decisions"])
        self.assertIn("distribution", result["hero_decisions"]["legal_action_count"])


if __name__ == "__main__":
    unittest.main()
