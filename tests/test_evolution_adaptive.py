import unittest

from pokerbot.evolution_adaptive import make_adaptive_policy
from pokerbot.evolution_strategies import DEFAULT_PARAMS, Genome, policy_for
from pokerbot.simulation import calling_station
from pokerbot.tournament import play_tournament


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
        "player_id": "p0",
        "history": [],
    }
    raw.update(updates)
    return raw


def public_action(player="p1", action="call", *, street="preflop", added=0, position="CO"):
    return {
        "player": player,
        "action": action,
        "street": street,
        "amount": added,
        "added": added,
        "position": position,
    }


def train(policy, actions, *, start=0, street="preflop"):
    """Expose one public p1 action per indexed hand to the hero."""
    for hand_index, action in enumerate(actions, start=start):
        updates = {}
        if street != "preflop":
            updates.update(
                hole_cards=["As", "Kd"], board=["2h", "7d", "9c"],
                pot=100, current_bet=0, to_call=0,
                legal_actions=["check", "raise"], position="BTN",
            )
        policy(observation(
            **updates,
            hand_index=hand_index,
            history=[public_action(
                action=action, street=street, added=40 if action == "raise" else 0,
            )],
        ))


class EvolutionAdaptiveTests(unittest.TestCase):
    def setUp(self):
        self.genome = Genome("adaptive-test", params=dict(DEFAULT_PARAMS))

    def test_open_bets_do_not_dilute_price_facing_response_rates(self):
        policy = make_adaptive_policy(self.genome)
        for hand in range(12):
            action = public_action(action="raise" if hand < 8 else "fold", street="flop", added=40)
            action["to_call"] = 0 if hand < 8 else 10
            policy(observation(hand_index=hand, history=[action]))
        profile = policy._profiles["p1"]
        self.assertEqual(profile.postflop_raises, 8)
        self.assertEqual(profile._faced_actions("flop"), 4)
        self.assertEqual(profile.fold_rate("flop"), 0.75)
        self.assertEqual(profile.call_rate("flop"), 0.25)
        policy(observation(hand_index=12, history=[{**public_action(action="raise", street="flop"), "to_call": 10}]))
        self.assertEqual(profile._faced_actions("flop"), 5)
        self.assertAlmostEqual(profile.fold_rate("flop"), 6 / 9)

    def test_old_raise_history_without_price_is_unknown_response_context(self):
        policy = make_adaptive_policy(self.genome)
        train(policy, ["raise"] * 8, street="flop")
        self.assertEqual(policy._profiles["p1"].postflop_raises, 8)
        self.assertEqual(policy._profiles["p1"]._faced_actions("flop"), 0)

    def test_public_action_price_is_validated_separately_from_frozen_parser(self):
        from pokerbot.state import Observation
        action = {**public_action(), "to_call": 20, "future_winner": "p1"}
        parsed = Observation.from_dict(observation(history=[action]))
        self.assertNotIn("to_call", parsed.history[0])
        self.assertNotIn("future_winner", parsed.history[0])
        policy = make_adaptive_policy(self.genome)
        policy(observation(hand_index=0, history=[action]))
        self.assertEqual(policy._profiles["p1"]._faced_actions("preflop"), 1)
        for invalid in (-1, True, None):
            with self.assertRaises(ValueError):
                policy(observation(hand_index=1, history=[{**action, "to_call": invalid}]))

    def test_history_prefix_dedupes_but_same_actions_in_new_hands_count(self):
        policy = make_adaptive_policy(self.genome)
        first = observation(hand_index=0, history=[public_action(action="call")])
        policy(first)
        policy(first)
        self.assertEqual(policy._profiles["p1"].actions, 1)

        extended = observation(hand_index=0, history=[
            public_action(action="call"),
            public_action(player="p2", action="check"),
            public_action(player="p0", action="call"),
        ])
        policy(extended)
        self.assertEqual(policy._profiles["p1"].actions, 1)
        self.assertEqual(policy._profiles["p2"].actions, 1)
        self.assertNotIn("p0", policy._profiles)

        next_hand = observation(hand_index=1, history=[public_action(action="call")])
        policy(next_hand)
        self.assertEqual(policy._profiles["p1"].actions, 2)

    def test_profile_and_current_hand_dedupe_memory_are_bounded(self):
        policy = make_adaptive_policy(self.genome)
        nine_players = [public_action(player=f"p{seat}", action="check") for seat in range(1, 10)]
        policy(observation(hand_index=0, history=nine_players))
        self.assertLessEqual(len(policy._profiles), 8)

        long_prefix = [public_action(action="call") for _ in range(600)]
        policy(observation(hand_index=1, history=long_prefix))
        self.assertLessEqual(len(policy._profiles), 8)
        self.assertLessEqual(len(policy._seen_actions), 512)

    def test_missing_or_malformed_hand_index_is_conservative_and_validated(self):
        policy = make_adaptive_policy(self.genome)
        missing = observation(history=[public_action(action="raise", added=100)] * 8)
        policy(missing)
        self.assertEqual(policy._profiles, {})

        base = policy_for(self.genome)
        raised = observation(
            hole_cards=["Qc", "2d"], pot=100, to_call=20,
            legal_actions=["fold", "call", "raise"], min_raise_to=40,
            history=[public_action(action="raise", added=20)],
        )
        self.assertEqual(policy(raised), base(raised))
        train(policy, ["raise"] * 8)
        # A policy can have old table-local counts, but an observation without
        # a hand index still takes the static path (apart from SB completion).
        self.assertEqual(policy(raised), base(raised))

        for bad in (-1, True, 1.0, "2", None):
            with self.subTest(hand_index=bad), self.assertRaises(ValueError):
                policy(observation(hand_index=bad))

    def test_decreased_hand_index_and_reset_clear_all_table_profiles(self):
        policy = make_adaptive_policy(self.genome)
        policy(observation(hand_index=9, history=[public_action(action="call")]))
        self.assertIn("p1", policy._profiles)
        policy(observation(hand_index=0, history=[public_action(action="fold")]))
        self.assertEqual(policy._hand_index, 0)
        self.assertEqual(policy._profiles["p1"].actions, 1)
        self.assertEqual(policy._profiles["p1"].folds, 1)

        policy.reset()
        self.assertEqual(policy._profiles, {})
        self.assertIsNone(policy._hand_index)
        self.assertEqual(policy._seen_actions, set())

    def test_future_labels_and_private_fields_do_not_change_decisions_or_learning(self):
        clean = make_adaptive_policy(self.genome)
        opaque = make_adaptive_policy(self.genome)
        for index in range(8):
            history = [public_action(action="call")]
            clean(observation(hand_index=index, history=history))
            opaque(observation(
                hand_index=index,
                history=[{**history[0], "outcome": "won", "label": "calling station"}],
                opponent_hole_cards=["2c", "3d"],
                future_board=["4h", "5h", "6h"],
                expected_action="fold",
                tournament_result={"winner": "p1"},
            ))
        self.assertEqual(clean._profiles, opaque._profiles)

        raw = observation(hand_index=8, history=[public_action(action="call", street="flop")],
                          board=["2h", "7d", "9c"], pot=100,
                          legal_actions=["check", "raise"], current_bet=0,
                          to_call=0, position="BTN", players_active=2,
                          players_to_act=1)
        with_labels = {
            **raw,
            "opponent_cards": ["2c", "3d"],
            "future_board": ["4h", "5h", "6h"],
            "outcome": "loss",
            "expected_action": "fold",
        }
        self.assertEqual(clean(raw), opaque(with_labels))

    def test_policy_instances_are_table_isolated_and_resettable(self):
        station = make_adaptive_policy(self.genome)
        tight = make_adaptive_policy(self.genome)
        train(station, ["call"] * 8, street="flop")
        train(tight, ["fold"] * 8, street="flop")
        self.assertNotEqual(station._profiles["p1"], tight._profiles["p1"])

        raw = observation(
            hand_index=8,
            hole_cards=["As", "Kd"], board=["2h", "7d", "9c"],
            pot=100, legal_actions=["check", "raise"], position="BTN",
            history=[public_action(action="call"), public_action(action="check", street="flop")],
        )
        station_result = station(raw)
        tight_result = tight(raw)
        self.assertLess(station_result["probabilities"].get("raise", 0),
                        tight_result["probabilities"].get("raise", 0))

        station.reset()
        self.assertEqual(station._profiles, {})
        self.assertGreater(len(tight._profiles), 0)

    def test_calling_tendency_reduces_bluffs_and_increases_value_mix(self):
        params = {**DEFAULT_PARAMS, "bluff_frequency": 0.10, "raise_frequency": 0.80,
                  "value_raise_threshold": 0.56}
        genome = Genome("style-adjustments", params=params)
        station = make_adaptive_policy(genome)
        tight = make_adaptive_policy(genome)
        baseline = make_adaptive_policy(genome)
        train(station, ["call"] * 8, street="flop")
        train(tight, ["fold"] * 8, street="flop")

        bluff_spot = observation(
            hand_index=8, hole_cards=["As", "Kd"], board=["2h", "7d", "9c"],
            pot=100, legal_actions=["check", "raise"], position="BTN",
            history=[public_action(action="call"), public_action(action="check", street="flop")],
        )
        base_bluff = baseline(bluff_spot)["probabilities"].get("raise", 0)
        station_bluff = station(bluff_spot)["probabilities"].get("raise", 0)
        tight_bluff = tight(bluff_spot)["probabilities"].get("raise", 0)
        self.assertLess(station_bluff, base_bluff)
        self.assertGreater(tight_bluff, base_bluff)

        value_spot = observation(
            hand_index=9, hole_cards=["As", "Ah"], board=["2h", "3d", "4c"],
            pot=100, legal_actions=["check", "raise"], position="BTN",
            history=[public_action(action="call"), public_action(action="check", street="flop")],
        )
        base_value = baseline(value_spot)["probabilities"].get("raise", 0)
        station_value = station(value_spot)["probabilities"].get("raise", 0)
        self.assertGreater(station_value, base_value)

    def test_tight_preflop_folders_enable_small_steals_but_not_trash(self):
        tight = make_adaptive_policy(self.genome)
        base = policy_for(self.genome)
        train(tight, ["fold"] * 8)
        steal_spot = observation(
            hand_index=8, hole_cards=["Qc", "2d"], position="BTN",
            legal_actions=["fold", "raise"], players_active=2,
            players_to_act=1, history=[public_action(player="p2", action="fold")],
            table_size=3, table_player_ids=["p0", "p1", "p2"],
        )
        base_probability = base(steal_spot)["probabilities"].get("raise", 0)
        adapted_probability = tight(steal_spot)["probabilities"].get("raise", 0)
        self.assertEqual(base_probability, 0)
        self.assertGreater(adapted_probability, 0)
        self.assertLessEqual(adapted_probability, 0.16)

        folded_target = {**steal_spot, "hand_index": 9,
                         "history": [public_action(action="fold")],
                         "table_player_ids": ["p0", "p1", "p2"]}
        self.assertEqual(tight(folded_target)["probabilities"].get("raise", 0), 0)

        trash = tight({**steal_spot, "hand_index": 9, "hole_cards": ["7c", "2d"]})
        self.assertEqual(trash["probabilities"].get("raise", 0), 0)

    def test_loose_frequent_raiser_widens_calls_but_tight_big_raiser_does_not(self):
        loose = make_adaptive_policy(self.genome)
        tight = make_adaptive_policy(self.genome)
        train(loose, ["raise"] * 8)
        train(tight, ["raise"] + ["fold"] * 12)

        def faced(added):
            return observation(
                hand_index=20,
                hole_cards=["Qc", "2d"], pot=100, to_call=20,
                legal_actions=["fold", "call", "raise"], min_raise_to=40,
                max_raise_to=1000,
                history=[public_action(action="raise", added=added)],
            )

        loose_result = loose(faced(20))
        tight_result = tight(faced(60))
        self.assertGreater(loose_result["probabilities"].get("call", 0),
                           tight_result["probabilities"].get("call", 0))
        self.assertGreater(loose_result["probabilities"].get("call", 0), 0)
        self.assertEqual(tight_result["probabilities"].get("call", 0), 0)

    def test_small_sb_completion_is_bounded_and_not_added_to_other_seats(self):
        base = policy_for(self.genome)
        adaptive = make_adaptive_policy(self.genome)
        sb = observation(
            hand_index=0,
            hole_cards=["Jc", "9s"], pot=480, to_call=160, stack=3953,
            current_bet=160, min_raise_to=640, max_raise_to=4113,
            big_blind=320, position="SB", table_size=8,
            players_active=2, players_to_act=1,
            legal_actions=["fold", "call", "raise"],
            history=[public_action(player="p5", action="fold"),
                     public_action(player="p6", action="fold")],
        )
        static_sb = base(sb)
        completed = adaptive(sb)
        self.assertEqual(static_sb["probabilities"].get("call", 0), 0)
        self.assertGreater(completed["probabilities"].get("call", 0), 0)
        self.assertTrue(completed["diagnostics"]["adaptive_sb_completion"])

        trash = adaptive({**sb, "hole_cards": ["7c", "2d"], "hand_index": 1})
        self.assertEqual(trash["probabilities"].get("call", 0), 0)
        expensive = adaptive({**sb, "hand_index": 2, "to_call": 800, "pot": 1000,
                              "min_raise_to": 1000})
        self.assertEqual(expensive["probabilities"].get("call", 0), 0)

        btn = adaptive({**sb, "hand_index": 3, "position": "BTN"})
        self.assertEqual(btn["probabilities"].get("call", 0), 0)
        bb = adaptive({
            **observation(position="BB", legal_actions=["check", "raise"],
                          hand_index=4, big_blind=320,
                          history=[]),
        })
        self.assertEqual(bb["probabilities"].get("call", 0), 0)
        self.assertEqual(bb["probabilities"].get("check"), 1)

        # Missing hand metadata disables profiling but retains the small blind
        # completion rule, whose public price and cards are still available.
        no_index = adaptive({key: value for key, value in sb.items() if key != "hand_index"})
        self.assertGreater(no_index["probabilities"].get("call", 0), 0)

    def test_adaptive_policy_keeps_legal_short_all_in_and_nonreopened_actions(self):
        policy = make_adaptive_policy(self.genome)
        short_all_in = observation(
            hand_index=0, hole_cards=["As", "Ah"], to_call=80,
            current_bet=0, stack=100, pot=300, big_blind=10,
            min_raise_to=100, max_raise_to=100,
            legal_actions=["fold", "call", "raise"],
            history=[public_action(action="all_in", added=80)],
            players_to_act=0,
        )
        jam = policy(short_all_in)
        self.assertIn(jam["action"], short_all_in["legal_actions"])
        if jam["action"] == "raise":
            self.assertEqual(jam["amount"], 100)
            self.assertGreaterEqual(jam["amount"], short_all_in["min_raise_to"])
            self.assertLessEqual(jam["amount"], short_all_in["max_raise_to"])

        not_reopened = {
            **short_all_in,
            "hand_index": 1,
            "to_call": 10,
            "current_bet": 80,
            "min_raise_to": 0,
            "max_raise_to": 0,
            "legal_actions": ["fold", "call"],
        }
        response = policy(not_reopened)
        self.assertIn(response["action"], {"fold", "call"})
        self.assertEqual(response["raise_amount"], 0)
        self.assertNotIn("raise", response["probabilities"])

    def test_exact_shared_river_nuts_remain_unfoldable(self):
        policy = make_adaptive_policy(self.genome)
        raw = observation(
            hand_index=0, hole_cards=["2c", "3d"],
            board=["As", "Kh", "Qc", "Jd", "Ts"],
            pot=100, to_call=20, stack=1000, current_bet=0,
            min_raise_to=0, max_raise_to=0, players_active=4,
            players_to_act=0, legal_actions=["fold", "call"],
        )
        decision = policy(raw)
        self.assertEqual(decision["probabilities"].get("call"), 1.0)
        self.assertEqual(decision["probabilities"].get("fold", 0), 0.0)

    def test_real_eight_player_tournament_supplies_public_hand_index(self):
        adaptive = make_adaptive_policy(self.genome)

        class Recorder:
            def __init__(self, inner):
                self.inner = inner
                self.observations = []

            def reset(self):
                self.observations.clear()
                self.inner.reset()

            def __call__(self, raw):
                self.observations.append(raw)
                return self.inner(raw)

        recorder = Recorder(adaptive)
        result = play_tournament(
            [recorder] + [calling_station] * 7,
            seed=217, stacks=2000, big_blinds=(20,), max_hands=3, trace=True,
        )
        self.assertEqual(result["hands_played"], 3)
        self.assertTrue(recorder.observations)
        self.assertTrue(all(type(item["hand_index"]) is int for item in recorder.observations))
        self.assertTrue({item["hand_index"] for item in recorder.observations}.issubset({0, 1, 2}))
        self.assertTrue(all(item["player_id"] == "p0" for item in recorder.observations))
        self.assertTrue(all(
            item["player"].startswith("p")
            for raw in recorder.observations
            for item in raw["history"]
        ))
        self.assertEqual(result["invalid_actions"], 0)
        self.assertTrue(all(type(action["to_call"]) is int for hand in result["trace"] for action in hand["actions"]))


if __name__ == "__main__":
    unittest.main()
