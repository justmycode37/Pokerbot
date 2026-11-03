import contextlib
import copy
import io
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pokerbot import evolution
from pokerbot.evolution_strategies import anchor_genomes, new_random


class EvolutionTests(unittest.TestCase):
    def _config(self, **overrides):
        config = {
            "players": 8,
            "population": 8,
            "matches": 1,
            "validation_matches": 2,
            "confirmation_matches": 128,
            "seed": 20261102,
            "stacks": 2000,
            "big_blinds": (20, 40, 80, 160, 320, 640, 1280, 2560),
            "hands_per_level": 25,
            "max_hands": 200,
            "fixed_random_opponents": 7,
        }
        config.update(overrides)
        return config

    @staticmethod
    def _capped_tournament(policies, **kwargs):
        count = len(policies)
        return {
            "winner": None,
            "capped": True,
            "hands_played": 200,
            "final_stacks": [1000] * count,
            "players": [
                {
                    "index": index,
                    "finish": 4.5,
                    "points": 1.0,
                    "final_stack": 1000,
                    "won": False,
                    "invalid_actions": 1,
                    "decisions": 10,
                    "latency_mean_ms": 0.1,
                    "latency_p95_ms": 0.2,
                    "latency_max_ms": 0.3,
                    "over_1ms": 0,
                }
                for index in range(count)
            ],
            "invalid_actions": count,
            "config": kwargs,
        }

    @staticmethod
    def _all_winning_jobs(jobs, workers):
        return [
            {
                "bot_id": job["hero_id"],
                "kind": job["kind"],
                "seed": job["seed"],
                "hero_seat": job["hero_seat"],
                "seat_bot_ids": job["seat_bot_ids"],
                "winner_seat": job["hero_seat"],
                "capped": False,
                "hands_played": 30,
                "won": True,
                "lost": False,
                "final_stack": 16000,
                "points": 8.0,
                "finish": 1.0,
                "invalid_actions": 0,
                "decisions": 100,
                "latency_mean_ms": 0.1,
                "latency_p95_ms": 0.2,
                "latency_max_ms": 0.3,
                "over_1ms": 0,
                "runtime_ms": 1.0,
            }
            for job in jobs
        ]

    @staticmethod
    def _seed_genome(bot_id="imported-v2-leader", *, parents=("v2-parent-a", "v2-parent-b"), generation=7):
        genome = new_random(random.Random(301), bot_id, generation=generation)
        raw = genome.to_dict()
        raw["parents"] = list(parents)
        return raw

    @staticmethod
    def _adaptive_genome_factory():
        class GenomeProxy:
            def __init__(self, raw):
                self._raw = copy.deepcopy(raw)
                self.bot_id = raw["bot_id"]
                self.family = raw["family"]
                self.params = raw["params"]
                self.parents = raw["parents"]
                self.generation = raw["generation"]

            @classmethod
            def from_dict(cls, raw):
                return cls(raw)

            def to_dict(self):
                return copy.deepcopy(self._raw)

        return GenomeProxy

    def test_wilson_bounds_and_finite_sample_limit(self):
        self.assertIsNone(evolution.wilson_interval(0, 0))
        interval = evolution.wilson_interval(32, 32)
        self.assertEqual(len(interval), 2)
        self.assertLess(interval[0], 1.0)
        self.assertGreater(interval[1], 0.99)
        self.assertEqual(evolution.minimum_all_successes_for_bound(0.95, 0.0125), 96)
        self.assertGreater(evolution.wilson_lower_bound(128, 128, 0.0125), 0.95)

    def test_exact_gate_bounds_and_long_search_alpha(self):
        self.assertEqual(evolution.exact_lower_bound(0, 20, 0.025), 0.0)
        self.assertAlmostEqual(evolution.exact_lower_bound(1, 1, 0.025), 0.025)
        self.assertAlmostEqual(evolution.exact_lower_bound(1, 2, 0.025), 1 - 0.975 ** 0.5)
        self.assertGreater(evolution.exact_lower_bound(86, 86, 0.0125), 0.95)
        self.assertLess(evolution.exact_lower_bound(85, 85, 0.0125), 0.95)
        alpha = evolution._one_sided_alpha(0.025, 10_000)
        self.assertGreater(evolution.exact_lower_bound(128, 128, alpha), 0)
        self.assertLess(sum(evolution._one_sided_alpha(0.025, i) for i in range(10_000)), 0.025)

    def test_eliminated_player_at_capped_table_is_only_a_loss(self):
        config = evolution._validate_config(self._config(players=2))
        anchors = anchor_genomes()
        job = evolution._build_tournament_job(anchors[0], anchors[1:], 23, "training", config)

        def eliminated_at_cap(policies, **kwargs):
            result = self._capped_tournament(policies, **kwargs)
            result["players"][job["hero_seat"]]["final_stack"] = 0
            return result

        with mock.patch.object(evolution, "policy_for", return_value=object()), mock.patch.object(
            evolution, "play_tournament", side_effect=eliminated_at_cap
        ):
            result = evolution._run_tournament_job(job)
        self.assertTrue(result["table_capped"])
        self.assertTrue(result["lost"])
        self.assertFalse(result["capped"])
        self.assertFalse(result["won"])

    def test_capped_table_is_never_a_win_even_if_winner_seat_is_set(self):
        anchors = anchor_genomes()
        config = evolution._validate_config(self._config(players=2))
        job = evolution._build_tournament_job(anchors[0], anchors[1:], 23, "training", config)

        def capped_with_winner(policies, **kwargs):
            result = self._capped_tournament(policies, **kwargs)
            result["winner"] = job["hero_seat"]
            return result

        with mock.patch.object(evolution, "policy_for", return_value=object()), mock.patch.object(
            evolution, "play_tournament", side_effect=capped_with_winner
        ):
            result = evolution._run_tournament_job(job)
        self.assertTrue(result["capped"])
        self.assertFalse(result["won"])
        self.assertFalse(result["lost"])
        self.assertEqual(len(result["seat_bot_ids"]), 2)

    def test_real_eight_player_tournament_adapter_smoke(self):
        anchors = anchor_genomes()
        candidates = anchors + [
            new_random(random.Random(index), f"smoke-evolved-{index}")
            for index in range(3)
        ]
        candidate = anchors[1]
        opponents = [genome for genome in candidates if genome.bot_id != candidate.bot_id]
        config = evolution._validate_config(self._config(max_hands=1, matches=1))
        job = evolution._build_tournament_job(candidate, opponents, 48271, "training", config)
        result = evolution._run_tournament_job(job)
        self.assertEqual(result["kind"], "training")
        self.assertEqual(len(result["seat_bot_ids"]), 8)
        self.assertEqual(result["hands_played"], 1)
        self.assertTrue(result["capped"])
        self.assertFalse(result["won"])
        self.assertGreaterEqual(result["final_stack"], 0)

    def test_mocked_generation_writes_reports_and_resumes_without_reusing_seeds(self):
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.object(
            evolution, "policy_for", return_value=object()
        ), mock.patch.object(evolution, "play_tournament", side_effect=self._capped_tournament):
            runner = evolution.EvolutionRunner(temp_dir, self._config())
            with contextlib.redirect_stdout(io.StringIO()):
                first_state = runner.run(1)
            self.assertEqual(first_state["status"], "target_not_reached")
            self.assertEqual(first_state["completed_generations"], 1)
            self.assertEqual(len(first_state["active_population"]), 8)

            round_one_path = Path(temp_dir) / "round-0001.json"
            round_one = json.loads(round_one_path.read_text())
            evaluated = [row for row in round_one["bots"] if row["played"]]
            offspring = [row for row in round_one["bots"] if row["status"] == "offspring"]
            self.assertEqual(len(evaluated), 8)
            self.assertEqual(len(offspring), 3)
            self.assertTrue(all(row["played"] == 1 and row["won"] == 0 and row["capped"] == 1 for row in evaluated))
            self.assertTrue(any(row["status"] == "protected" for row in evaluated))
            self.assertTrue(any(row["status"] == "eliminated" for row in evaluated))
            self.assertTrue(any(row["offspring_ids"] for row in evaluated))
            self.assertEqual(len(round_one["validation"]), 3)
            self.assertFalse(round_one["confirmation"])
            self.assertTrue((Path(temp_dir) / "round-0001.csv").exists())
            self.assertTrue((Path(temp_dir) / "round-0001.md").exists())
            self.assertTrue((Path(temp_dir) / "index.html").exists())
            self.assertEqual(json.loads((Path(temp_dir) / "champion.json").read_text())["status"], "provisional")

            second_runner = evolution.EvolutionRunner(temp_dir, self._config(), resume=True)
            with contextlib.redirect_stdout(io.StringIO()):
                second_state = second_runner.run(1)
            self.assertEqual(second_state["completed_generations"], 2)
            self.assertEqual(second_state["seed_stream"]["counters"]["training"], 16)
            self.assertEqual(second_state["seed_stream"]["counters"]["validation"], 12)
            self.assertEqual(second_state["seed_stream"]["counters"]["confirmation"], 0)

            seed_sets = []
            for generation in (1, 2):
                report = json.loads((Path(temp_dir) / f"round-{generation:04d}.json").read_text())
                seeds = []
                for row in report["bots"]:
                    seeds.extend(match["seed"] for match in row.get("evaluations", []))
                for row in report["validation"]:
                    seeds.extend(match["seed"] for match in row["evaluations"])
                seed_sets.append(set(seeds))
            self.assertTrue(seed_sets[0].isdisjoint(seed_sets[1]))
            self.assertEqual(len(seed_sets[0]), 14)
            self.assertEqual(len(seed_sets[1]), 14)

            with self.assertRaisesRegex(ValueError, "incompatible"):
                evolution.EvolutionRunner(temp_dir, self._config(matches=2), resume=True)
            with mock.patch.object(evolution, "_code_fingerprint", return_value="0" * 64):
                with self.assertRaisesRegex(ValueError, "fingerprint"):
                    evolution.EvolutionRunner(temp_dir, self._config(), resume=True)

    def test_confirmation_promotes_only_after_spent_alpha_bound_clears_target(self):
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.object(
            evolution, "_execute_jobs", side_effect=self._all_winning_jobs
        ):
            runner = evolution.EvolutionRunner(temp_dir, self._config(validation_matches=1))
            with contextlib.redirect_stdout(io.StringIO()):
                state = runner.run(1)
            self.assertEqual(state["status"], "confirmed_target_reached")
            self.assertIsNotNone(state["champion"])
            confirmation = state["champion"]["confirmation"]
            self.assertEqual(confirmation["played"], 128)
            self.assertEqual(confirmation["won"], 128)
            self.assertGreater(confirmation["wilson_lower_bound"], 0.95)
            self.assertEqual(confirmation["alpha_spent"], 0.0125)
            champion = json.loads((Path(temp_dir) / "champion.json").read_text())
            self.assertEqual(champion["status"], "confirmed")
            self.assertEqual(champion["bot_id"], state["champion"]["bot_id"])
            report = json.loads((Path(temp_dir) / "round-0001.json").read_text())
            self.assertEqual(len(report["confirmation"]), 1)
            self.assertTrue(report["confirmation"][0]["gate_passed"])

    def test_small_tables_never_satisfy_the_eight_player_goal(self):
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.object(
            evolution, "_execute_jobs", side_effect=self._all_winning_jobs
        ), contextlib.redirect_stdout(io.StringIO()):
            runner = evolution.EvolutionRunner(temp_dir, self._config(players=2, validation_matches=1))
            state = runner.run(1)
            self.assertIsNone(state["champion"])
            self.assertEqual(state["confirmation_attempts"], 0)
            leader = json.loads((Path(temp_dir) / "champion.json").read_text())
            self.assertEqual(leader["players"], 2)
            self.assertFalse(leader["goal_eligible"])

    def test_same_strategy_opponents_remain_eligible_and_hero_has_its_own_seat(self):
        anchor = anchor_genomes()[0]
        config = evolution._validate_config(self._config(players=2))
        job = evolution._build_tournament_job(anchor, [anchor], 123, "validation", config)
        self.assertEqual(job["seat_bot_ids"], [anchor.bot_id, anchor.bot_id])
        self.assertIn(job["hero_seat"], (0, 1))

    def test_win_rate_guides_selection_before_tournament_points(self):
        rows = [{"bot_id": "consistent-places", "fitness": {"win_rate": 0.1, "mean_points": 7}},
                {"bot_id": "more-wins", "fitness": {"win_rate": 0.5, "mean_points": 5}}]
        self.assertEqual(evolution._rank(rows)[0]["bot_id"], "more-wins")

    def test_warm_seed_population_order_lineage_and_archive(self):
        imported = self._seed_genome("evo-initial-0000", parents=("legacy-parent-1", "legacy-parent-2"), generation=12)
        collision_seed = self._seed_genome("evo-g0001-0000", parents=("evo-initial-0000",), generation=4)
        fresh_collision_seed = self._seed_genome("evo-fresh-0000", parents=("legacy-parent-3",), generation=3)
        config = evolution._validate_config(self._config(
            population=9,
            seed_genomes=[imported, collision_seed, fresh_collision_seed],
        ))
        state = evolution._init_checkpoint(config, "test-fingerprint")

        active = state["active_population"]
        anchor_ids = [genome.bot_id for genome in anchor_genomes()]
        self.assertEqual(active[:5], anchor_ids)
        self.assertEqual(active[5:8], ["evo-initial-0000", "evo-g0001-0000", "evo-fresh-0000"])
        self.assertTrue(active[8].startswith("evo-fresh-"))
        self.assertNotIn(active[8], {imported["bot_id"], collision_seed["bot_id"], fresh_collision_seed["bot_id"]})
        self.assertEqual(len(set(active)), len(active))
        self.assertEqual(state["genomes"][imported["bot_id"]], imported)
        self.assertEqual(state["lineage"][imported["bot_id"]]["parents"], imported["parents"])
        self.assertEqual(state["lineage"][imported["bot_id"]]["generation"], imported["generation"])
        self.assertEqual(state["hall_of_fame"][:5], anchor_ids)
        self.assertIn(imported["bot_id"], state["hall_of_fame"])
        self.assertIn(collision_seed["bot_id"], state["hall_of_fame"])
        self.assertIn(fresh_collision_seed["bot_id"], state["hall_of_fame"])

        ranked_ids = [bot_id for bot_id in active if bot_id != state["protected_bot_id"]]
        ranked_ids = [bot_id for bot_id in ranked_ids if bot_id != imported["bot_id"]] + [imported["bot_id"]]
        ranked = [{
            "bot_id": bot_id,
            "fitness": {"win_rate": 0.0, "mean_points": 0.0, "mean_final_stack": 0.0, "invalid_rate": 0.0},
        } for bot_id in ranked_ids]
        runner = object.__new__(evolution.EvolutionRunner)
        runner.config = config
        runner.state = state
        _, _, status = runner._breed_next_population(1, ranked)
        self.assertEqual(status[imported["bot_id"]], "eliminated")
        self.assertIn(imported["bot_id"], state["hall_of_fame"])
        self.assertIn(imported["bot_id"], [evolution._id(genome) for genome in evolution._opponent_pool(state, "training")])
        self.assertEqual(state["genomes"][collision_seed["bot_id"]], collision_seed)
        self.assertIn("evo-g0001-0000-1", state["active_population"])
        self.assertEqual(state["lineage"][imported["bot_id"]]["generation"], 12)

    def test_seed_genome_validation_rejects_bad_ids_params_families_and_population(self):
        duplicate = self._seed_genome("same-id")
        with self.assertRaisesRegex(ValueError, "duplicate seed genome id"):
            evolution._validate_config(self._config(seed_genomes=[duplicate, duplicate]))

        anchor_conflict = self._seed_genome("anchor-fast")
        with self.assertRaisesRegex(ValueError, "conflicts with fixed anchor"):
            evolution._validate_config(self._config(seed_genomes=[anchor_conflict]))

        bad_params = self._seed_genome("bad-params")
        bad_params["params"]["opening_shift"] = 99.0
        with self.assertRaisesRegex(ValueError, "parameter"):
            evolution._validate_config(self._config(seed_genomes=[bad_params]))

        bad_family = self._seed_genome("bad-family")
        bad_family["family"] = "not-a-family"
        with self.assertRaisesRegex(ValueError, "family"):
            evolution._validate_config(self._config(seed_genomes=[bad_family]))

        with self.assertRaisesRegex(ValueError, "population must fit"):
            evolution._validate_config(self._config(population=6, seed_genomes=[
                self._seed_genome(f"seed-{index}") for index in range(2)
            ]))

    def test_adaptive_fraction_validation_and_fixed_pool_fingerprints(self):
        for value in (-0.01, 1.01, float("nan"), float("inf"), True, "0.5"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "adaptive_fraction"):
                evolution._validate_config(self._config(adaptive_fraction=value))
        self.assertEqual(evolution._validate_config(self._config())["adaptive_fraction"], 0.0)

        config_zero = evolution._validate_config(self._config(population=16, adaptive_fraction=0.0))
        config_half = evolution._validate_config(self._config(population=16, adaptive_fraction=0.5))
        state_zero = evolution._init_checkpoint(config_zero, "test-fingerprint")
        state_half = evolution._init_checkpoint(config_half, "test-fingerprint")
        self.assertEqual(state_zero["fixed_pool_fingerprints"], state_half["fixed_pool_fingerprints"])
        for key in ("training_opponents", "validation_population", "confirmation_population"):
            self.assertEqual(state_zero[key], state_half[key])
        zero_fresh = [state_zero["genomes"][bot_id] for bot_id in state_zero["active_population"][5:]]
        half_fresh = [state_half["genomes"][bot_id] for bot_id in state_half["active_population"][5:]]
        self.assertEqual(len(zero_fresh), len(half_fresh))
        self.assertTrue(all(row["bot_id"].startswith("evo-fresh-") for row in half_fresh))
        self.assertEqual(sum(row["family"] == "adaptive" for row in half_fresh), 6)
        self.assertTrue(all(a["params"] == b["params"] for a, b in zip(zero_fresh, half_fresh)))

    def test_adaptive_immigrants_keep_the_configured_family(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runner = evolution.EvolutionRunner(temp_dir, self._config(adaptive_fraction=1.0))
            ranked = [{"bot_id": bot_id, "fitness": {"win_rate": 0.1, "mean_points": 3}}
                      for bot_id in runner.state["active_population"]]
            next_ids, _, _ = runner._breed_next_population(1, ranked)
            immigrants = [runner.state["genomes"][bot_id] for bot_id in next_ids
                          if bot_id.startswith("evo-g") and not runner.state["genomes"][bot_id]["parents"]]
            self.assertTrue(immigrants)
            self.assertTrue(all(row["family"] == "adaptive" for row in immigrants))

    def test_evaluation_namespaces_change_match_seeds_and_preserve_opponents(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first = evolution.EvolutionRunner(Path(temp_dir) / "first", self._config(evaluation_namespace="v2"))
            second = evolution.EvolutionRunner(Path(temp_dir) / "second", self._config(evaluation_namespace="v3"))
            self.assertTrue(set(first._allocate_seeds("validation", 100)).isdisjoint(second._allocate_seeds("validation", 100)))
            self.assertEqual(first.state["fixed_pool_fingerprints"], second.state["fixed_pool_fingerprints"])

    def test_seed_file_snapshot_is_stored_and_content_changes_reject_resume(self):
        seed = self._seed_genome("file-import")
        with tempfile.TemporaryDirectory() as temp_dir:
            seed_path = Path(temp_dir) / "seeds.json"
            seed_path.write_text(json.dumps([seed]), encoding="utf-8")
            config = self._config(population=6, seed_genomes_path=str(seed_path))
            runner = evolution.EvolutionRunner(Path(temp_dir) / "run", config)
            checkpoint = json.loads((Path(temp_dir) / "run" / "checkpoint.json").read_text())
            self.assertEqual(checkpoint["config"]["seed_genomes"], [seed])
            self.assertEqual(checkpoint["config"]["seed_genomes_path"], str(seed_path.resolve()))

            evolution.EvolutionRunner(Path(temp_dir) / "run", config, resume=True)
            changed = copy.deepcopy(seed)
            changed["generation"] += 1
            seed_path.write_text(json.dumps([changed]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "incompatible"):
                evolution.EvolutionRunner(Path(temp_dir) / "run", config, resume=True)
            self.assertEqual(runner.state["config"]["seed_genomes"], [seed])

    def test_cli_exposes_v3_seed_and_adaptive_options(self):
        args = evolution.build_parser().parse_args([
            "run", "--adaptive-fraction", "0.5", "--seed-genomes", "warm-start.json",
        ])
        self.assertEqual(args.adaptive_fraction, 0.5)
        self.assertEqual(args.seed_genomes, "warm-start.json")

    def test_dependency_change_blocks_resume(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            evolution.EvolutionRunner(temp_dir, self._config())
            with mock.patch.object(evolution, "_dependency_versions", return_value={"pokerkit": "different"}):
                with self.assertRaisesRegex(ValueError, "fingerprint|dependency"):
                    evolution.EvolutionRunner(temp_dir, self._config(), resume=True)

    def test_interrupted_report_export_is_recovered_without_replaying_matches(self):
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.object(
            evolution, "_execute_jobs", side_effect=self._all_winning_jobs
        ), contextlib.redirect_stdout(io.StringIO()):
            runner = evolution.EvolutionRunner(temp_dir, self._config(validation_matches=1))
            with mock.patch.object(runner, "_write_generation_report", side_effect=OSError("interrupted")):
                with self.assertRaises(OSError):
                    runner.run(1)
            saved = json.loads((Path(temp_dir) / "checkpoint.json").read_text())
            self.assertEqual(saved["completed_generations"], 1)
            self.assertIn("pending_report", saved)
            self.assertFalse((Path(temp_dir) / "round-0001.json").exists())
            resumed = evolution.EvolutionRunner(temp_dir, self._config(validation_matches=1), resume=True)
            self.assertNotIn("pending_report", resumed.state)
            report = json.loads((Path(temp_dir) / "round-0001.json").read_text())
            self.assertEqual(report["status"], "confirmed_target_reached")
            self.assertEqual(resumed.state["seed_stream"]["counters"], saved["seed_stream"]["counters"])


if __name__ == "__main__":
    unittest.main()
