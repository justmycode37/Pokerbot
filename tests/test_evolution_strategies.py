import json
import os
import random
import subprocess
import sys
import unittest

from pokerbot.evolution_strategies import (
    DEFAULT_PARAMS,
    PARAMETER_BOUNDS,
    Genome,
    anchor_genomes,
    breed,
    new_random,
    policy_for,
)
from pokerbot.simulation import calling_station, play_hand, random_legal


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


class EvolutionStrategyTests(unittest.TestCase):
    def test_breeding_reproduces_across_python_hash_seeds(self):
        program = (
            "import json, random; "
            "from pokerbot.evolution_strategies import new_random, breed; "
            "p=new_random(random.Random(4),'parent'); "
            "print(json.dumps([breed(p,None,random.Random(i),'child',1).to_dict() "
            "for i in range(12)],sort_keys=True))"
        )
        outputs = [
            subprocess.check_output(
                [sys.executable, "-c", program],
                env={**os.environ, "PYTHONHASHSEED": seed}, text=True,
            )
            for seed in ("1", "8675309")
        ]
        self.assertEqual(outputs[0], outputs[1])

    def test_genome_json_round_trip_validation_and_immutable_parameters(self):
        genome = Genome("test-1", params={"opening_shift": 0.025, "bet_size": 0.7},
                        parents=("parent-a",), generation=3)
        round_trip = Genome.from_dict(json.loads(json.dumps(genome.to_dict())))
        self.assertEqual(round_trip, genome)
        with self.assertRaises(TypeError):
            genome.params["opening_shift"] = 0.1
        for invalid in (
            {"unknown_gene": 0.2},
            {"bet_size": float("nan")},
            {"call_frequency": float("inf")},
            {"opening_shift": 0.121},
            {"raise_frequency": True},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                Genome.from_dict({"bot_id": "invalid", "params": invalid})
        with self.assertRaises(ValueError):
            Genome.from_dict({"bot_id": "invalid", "untrusted": True})

    def test_random_creation_and_breeding_are_reproducible_bounded_and_nonmutating(self):
        parent = new_random(random.Random(4), "random-parent", generation=2)
        second = Genome("fast-anchor", family="fast")
        original_parent = parent.to_dict()
        first_child = breed(parent, second, random.Random(71), "child", generation=3)
        second_child = breed(parent, second, random.Random(71), "child", generation=3)
        self.assertEqual(first_child.to_dict(), second_child.to_dict())
        self.assertEqual(parent.to_dict(), original_parent)
        self.assertEqual(first_child.parents, ("random-parent", "fast-anchor"))
        self.assertEqual(first_child.generation, 3)
        self.assertTrue(any(first_child.params[name] != parent.params[name] for name in PARAMETER_BOUNDS))
        for name, (low, high) in PARAMETER_BOUNDS.items():
            self.assertTrue(low <= first_child.params[name] <= high, name)

    def test_anchor_families_and_ids_are_stable(self):
        anchors = anchor_genomes()
        self.assertEqual(
            [(genome.bot_id, genome.family) for genome in anchors],
            [
                ("anchor-saved", "saved"),
                ("anchor-fast", "fast"),
                ("anchor-station", "calling-station"),
                ("anchor-tight", "tight-passive"),
                ("anchor-random", "random-legal"),
            ],
        )

    def test_adaptive_family_preserves_genes_through_breeding(self):
        parent = Genome("adaptive-parent", family="adaptive", params={"opening_shift": -0.10})
        child = breed(parent, None, random.Random(123), "adaptive-child", 1)
        self.assertEqual(child.family, "adaptive")
        self.assertIn("opening_shift", child.params)
        self.assertEqual(Genome.from_dict(parent.to_dict()), parent)

    def test_opening_cutoff_and_raise_size_genes_change_actions(self):
        raw = observation(hole_cards=["8s", "7s"])
        conservative = Genome("closed", params={
            **DEFAULT_PARAMS, "opening_shift": 0.12, "position_sensitivity": 0.0,
        })
        exploratory = Genome("open", params={
            **DEFAULT_PARAMS, "opening_shift": -0.12, "position_sensitivity": 0.0,
        })
        tight_decision = policy_for(conservative)(raw)
        wide_decision = policy_for(exploratory)(raw)
        self.assertEqual(tight_decision["probabilities"].get("raise", 0), 0)
        self.assertGreater(wide_decision["probabilities"].get("raise", 0), 0)

        premium = observation(hole_cards=["As", "Ah"])
        small = policy_for(Genome("small", params={**DEFAULT_PARAMS, "bet_size": 0.15}))(premium)
        large = policy_for(Genome("large", params={**DEFAULT_PARAMS, "bet_size": 0.90}))(premium)
        self.assertEqual(small["action"], "raise")
        self.assertEqual(large["action"], "raise")
        self.assertLess(small["amount"], large["amount"])

    def test_bluff_frequency_changes_postflop_raise_mix(self):
        raw = observation(
            hole_cards=["As", "Kd"], board=["2h", "7d", "9c"],
            pot=100, current_bet=0, to_call=0,
            min_raise_to=20, max_raise_to=1000, players_active=2,
            position="BTN", legal_actions=["check", "raise"],
        )
        no_bluff = policy_for(Genome("no-bluff", params={**DEFAULT_PARAMS, "bluff_frequency": 0.0}))(raw)
        bluff = policy_for(Genome("bluff", params={**DEFAULT_PARAMS, "bluff_frequency": 0.24}))(raw)
        self.assertEqual(no_bluff["probabilities"].get("raise", 0), 0)
        self.assertEqual(bluff["probabilities"].get("raise"), 0.24)

    def test_multiway_penalty_changes_a_marginal_postflop_call(self):
        raw = observation(
            hole_cards=["As", "Kd"], board=["2h", "7d", "9c"],
            pot=200, to_call=30, stack=1000, current_bet=0,
            min_raise_to=0, max_raise_to=0, players_active=5,
            players_to_act=0, legal_actions=["fold", "call"],
        )
        loose = policy_for(Genome("loose-multiway", params={
            **DEFAULT_PARAMS, "multiway_penalty": 0.015, "call_frequency": 1.0,
        }))(raw)
        tight = policy_for(Genome("tight-multiway", params={
            **DEFAULT_PARAMS, "multiway_penalty": 0.10, "call_frequency": 1.0,
        }))(raw)
        self.assertEqual(loose["action"], "call")
        self.assertEqual(tight["action"], "fold")
        self.assertGreater(loose["diagnostics"]["estimated_equity"], tight["diagnostics"]["estimated_equity"])

    def test_short_all_in_and_nonreopened_raise_are_respected(self):
        short_all_in = observation(
            hole_cards=["As", "Ah"], to_call=80, current_bet=0, stack=100,
            pot=300, min_raise_to=100, max_raise_to=100,
            legal_actions=["fold", "call", "raise"],
            history=[{"street": "preflop", "player": "opponent", "action": "raise", "amount": 100}],
        )
        decision = policy_for(Genome("jam", params={
            **DEFAULT_PARAMS, "short_stack_bb": 18.0, "short_stack_cutoff": 0.45,
        }))(short_all_in)
        self.assertEqual(decision["action"], "raise")
        self.assertEqual(decision["amount"], 100)

        not_reopened = {
            **short_all_in,
            "to_call": 10,
            "current_bet": 80,
            "min_raise_to": 0,
            "max_raise_to": 0,
            "legal_actions": ["fold", "call"],
        }
        no_raise_decision = policy_for(Genome("closed-action", params={**DEFAULT_PARAMS}))(not_reopened)
        self.assertIn(no_raise_decision["action"], {"fold", "call"})
        self.assertEqual(no_raise_decision["raise_amount"], 0)
        self.assertNotIn("raise", no_raise_decision["probabilities"])

    def test_unknown_observation_fields_do_not_affect_policy(self):
        policy = policy_for(Genome("public-only", params={**DEFAULT_PARAMS}))
        raw = observation(hole_cards=["As", "Ah"])
        altered = {
            **raw,
            "opponent_cards": ["2c", "3d"],
            "expected_action": "fold",
            "future_board": ["2h", "3h", "4h"],
            "history": [{"outcome": "won", "expected": "fold"}],
        }
        self.assertEqual(policy(raw), policy(altered))

    def test_proven_shared_river_nuts_are_called_without_random_folds(self):
        boards = (["As", "Kh", "Qc", "Jd", "Ts"],
                  ["9s", "9h", "9c", "9d", "As"],
                  ["As", "Ah", "Ac", "Ad", "Ks"])
        for board in boards:
            raw = observation(
                hole_cards=["2c", "3d"], board=board, pot=100,
                to_call=1, stack=1000, players_active=8,
                legal_actions=["fold", "call"], min_raise_to=0, max_raise_to=0,
            )
            decision = policy_for(Genome("shared-nuts", params={"call_frequency": 0.45}))(raw)
            self.assertEqual(decision["probabilities"].get("call"), 1.0)
            self.assertTrue(decision["diagnostics"]["exact_shared_board_tie"])

    def test_exact_unbeatable_flush_never_folds(self):
        raw = observation(
            hole_cards=["Ah", "Qc"], board=["2h", "4h", "7h", "9h", "Kc"],
            pot=100, to_call=10, stack=1000,
            min_raise_to=20, max_raise_to=1000,
            legal_actions=["fold", "call", "raise"],
        )
        decision = policy_for(Genome("flush-nuts", params={"call_frequency": 0.45}))(raw)
        self.assertTrue(decision["diagnostics"]["exact_unbeatable_hand"])
        self.assertEqual(decision["probabilities"].get("fold", 0), 0)

    def test_short_stack_boundary_uses_chips_owned_instead_of_price_to_call(self):
        raw = observation(
            hole_cards=["8s", "7s"], stack=190, to_call=20, big_blind=20,
            pot=60, min_raise_to=40, max_raise_to=190,
            legal_actions=["fold", "call", "raise"],
            history=[{"player": "opponent", "action": "call", "street": "preflop", "amount": 20}],
        )
        decision = policy_for(Genome("short", params={
            "short_stack_bb": 10, "short_stack_cutoff": 0.45,
            "value_raise_threshold": 0.84,
        }))(raw)
        self.assertEqual(decision["diagnostics"]["effective_stack_bb"], 9.5)
        self.assertGreater(decision["probabilities"].get("raise", 0), 0)
        self.assertEqual(decision["raise_amount"], 190)

    def test_heads_up_small_blind_alias_uses_button_strategy(self):
        raw = observation(
            hole_cards=["As", "Kd"], board=["2h", "7d", "9c"],
            pot=100, to_call=0, min_raise_to=20, max_raise_to=1000,
            table_size=2, players_active=2, legal_actions=["check", "raise"],
        )
        policy = policy_for(Genome("hu", params={"bluff_frequency": 0.24}))
        self.assertEqual(policy({**raw, "position": "SB"}), policy({**raw, "position": "BTN"}))

    def test_policy_is_legal_on_real_multi_action_simulation_traces(self):
        genome = new_random(random.Random(15), "table-policy")
        policy = policy_for(genome)
        for seed in (12, 38, 109):
            result = play_hand([policy, calling_station, random_legal], seed=seed, stacks=600, trace=True)
            self.assertEqual(result["invalid_actions"], [])
            hero_trace = [item for item in result["trace"] if item["observation"]["player_id"] == "p0"]
            self.assertTrue(hero_trace)
            for item in hero_trace:
                replay = policy(item["observation"])
                self.assertIn(replay["action"], item["observation"]["legal_actions"])
                self.assertEqual(replay["action"], item["decision"]["action"])
                if replay["action"] == "raise":
                    self.assertIs(type(replay["amount"]), int)
                    self.assertGreaterEqual(replay["amount"], item["observation"]["min_raise_to"])
                    self.assertLessEqual(replay["amount"], item["observation"]["max_raise_to"])


if __name__ == "__main__":
    unittest.main()
