import contextlib
import io
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pokerbot import evolution
from pokerbot.evolution_strategies import anchor_genomes, new_random


class EvolutionTargetAndArchiveTests(unittest.TestCase):
    @staticmethod
    def _genome(bot_id: str, seed: int) -> dict:
        return new_random(random.Random(seed), bot_id).to_dict()

    @staticmethod
    def _write_checkpoint(path: Path, training: list[str], hof: list[str], genomes: dict[str, dict]) -> Path:
        path.write_text(json.dumps({
            "training_opponents": training,
            "hall_of_fame": hof,
            "genomes": genomes,
            # These heldout fields must not enter the imported projection.
            "validation_results": {"do_not_import": 1},
            "confirmation_results": {"do_not_import": 2},
            "history": [{"fitness": "do_not_import"}],
        }), encoding="utf-8")
        return path

    @staticmethod
    def _config(**overrides) -> dict:
        config = {
            "players": 8,
            "population": 8,
            "matches": 1,
            "validation_matches": 1,
            "confirmation_matches": 42,
            "seed": 20261103,
            "stacks": 2000,
            "big_blinds": (20, 40, 80, 160, 320, 640, 1280, 2560),
            "hands_per_level": 25,
            "max_hands": 200,
            "fixed_random_opponents": 7,
        }
        config.update(overrides)
        return config

    def _source_pair(self, root: Path) -> tuple[Path, Path, dict[str, dict], dict[str, dict]]:
        shared_a = self._genome("shared", 11)
        shared_b = self._genome("shared", 12)
        duplicate_a = self._genome("same-policy", 13)
        duplicate_b = dict(duplicate_a)
        duplicate_b["parents"] = ["other-lineage"]
        duplicate_b["generation"] = 9
        only_a = self._genome("only-a", 14)
        only_b = self._genome("only-b", 15)
        first = {"shared": shared_a, "same-policy": duplicate_a, "only-a": only_a}
        second = {"shared": shared_b, "same-policy": duplicate_b, "only-b": only_b}
        first_path = self._write_checkpoint(
            root / "first-checkpoint.json", ["shared", "same-policy", "only-a"],
            ["shared", "same-policy"], first,
        )
        second_path = self._write_checkpoint(
            root / "second-checkpoint.json", ["shared", "same-policy", "only-b"],
            ["shared"], second,
        )
        return first_path, second_path, first, second

    def test_archive_id_reused_by_this_runs_fixed_genome_gets_alias(self):
        config_raw = self._config()
        fixed = evolution._fixed_genome_phenotypes(
            config_raw["seed"], config_raw["fixed_random_opponents"], config_raw["players"]
        )
        self.assertIn("train-opponent-0000", fixed)
        # A prior run with another seed stored a different policy under the
        # same generated ID; the same policy under a shared ID keeps its ID.
        reused = self._genome("train-opponent-0000", 99)
        same = evolution._to_dict(evolution._make_random_genomes(
            config_raw["seed"], "training-opponents", 1, "train-opponent"
        )[0])
        self.assertNotEqual(evolution._effective_archive_phenotype(reused), fixed["train-opponent-0000"])
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = self._write_checkpoint(
                root / "prior.json", ["train-opponent-0000"], ["train-opponent-0000"],
                {"train-opponent-0000": reused},
            )
            config = evolution._validate_config(self._config(archive_checkpoints=[str(source)]))
            archive = config["training_archive"]
            alias = "train-opponent-0000@archive"
            self.assertEqual(archive["training_opponents"], [alias])
            self.assertEqual(archive["policy_ids"][alias], "train-opponent-0000")
            runner = evolution.EvolutionRunner(root / "run", config)
            state = runner.state
            self.assertIn(alias, state["training_opponents"])
            self.assertIn("train-opponent-0000", state["training_opponents"])
            self.assertEqual(
                evolution._effective_archive_phenotype(state["genomes"]["train-opponent-0000"]),
                fixed["train-opponent-0000"],
            )
            pool = evolution._opponent_pool(state, "training")
            archived = next(genome for genome in pool if genome.bot_id == alias)
            job = evolution._build_tournament_job(
                anchor_genomes()[0], [archived] * 7, 1, "training", config
            )
            self.assertEqual(job["policy_ids"][alias], "train-opponent-0000")
            self.assertEqual(state["validation_population"], evolution.EvolutionRunner(
                root / "baseline", evolution._validate_config(self._config())
            ).state["validation_population"])

            identical = self._write_checkpoint(
                root / "identical.json", ["train-opponent-0000"], [], {"train-opponent-0000": same},
            )
            config = evolution._validate_config(self._config(archive_checkpoints=[str(identical)]))
            self.assertEqual(config["training_archive"]["training_opponents"], ["train-opponent-0000"])

            # Two sources that agree on the reused-ID policy share one alias;
            # sources that disagree keep source-scoped aliases.
            again = self._write_checkpoint(
                root / "again.json", ["train-opponent-0000"], [], {"train-opponent-0000": dict(reused)},
            )
            config = evolution._validate_config(self._config(archive_checkpoints=[str(source), str(again)]))
            self.assertEqual(config["training_archive"]["training_opponents"], [alias])
            config = evolution._validate_config(self._config(archive_checkpoints=[str(source), str(identical)]))
            self.assertEqual(
                sorted(config["training_archive"]["training_opponents"]),
                ["train-opponent-0000@archive-0", "train-opponent-0000@archive-1"],
            )

    def test_sparse_and_explicit_default_params_share_one_archive_entry(self):
        from pokerbot.evolution_strategies import DEFAULT_PARAMS, Genome

        sparse = Genome(bot_id="shared-policy", family="evolved", params={}).to_dict()
        explicit = Genome(bot_id="shared-policy", family="evolved", params=dict(DEFAULT_PARAMS)).to_dict()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = [
                self._write_checkpoint(root / "sparse.json", ["shared-policy"], [], {"shared-policy": sparse}),
                self._write_checkpoint(root / "explicit.json", ["shared-policy"], [], {"shared-policy": explicit}),
            ]
            archive = evolution._archive_from_checkpoints([str(path) for path in paths])
        self.assertEqual(archive["training_opponents"], ["shared-policy"])

    def test_target_config_cli_and_finite_sample_minimum(self):
        self.assertEqual(evolution._validate_config({})["target_win_rate"], 0.95)
        self.assertEqual(evolution._validate_config({"target_win_rate": 0.90})["target_win_rate"], 0.90)
        self.assertEqual(evolution.minimum_all_successes_for_exact_bound(0.90, 0.0125), 42)
        self.assertEqual(evolution.minimum_all_successes_for_exact_bound(0.95, 0.0125), 86)
        args = evolution.build_parser().parse_args(["run", "--target-win-rate", "0.90"])
        self.assertEqual(args.target_win_rate, 0.90)
        self.assertEqual(evolution.build_parser().parse_args(["run"]).target_win_rate, 0.95)
        for value in (0, 1, float("nan"), float("inf"), True, "0.9"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "target_win_rate"):
                evolution._validate_config({"target_win_rate": value})
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            evolution.build_parser().parse_args(["run", "--target-win-rate", "1"])

    @staticmethod
    def _all_winning_evaluations(bot_id: str, count: int) -> list[dict]:
        return [{
            "bot_id": bot_id,
            "won": True,
            "lost": False,
            "capped": False,
            "points": 8.0,
            "final_stack": 16000,
            "finish": 1.0,
            "invalid_actions": 0,
            "decisions": 100,
            "latency_mean_ms": 0.1,
            "latency_p95_ms": 0.2,
            "latency_max_ms": 0.3,
            "over_1ms": 0,
            "runtime_ms": 1.0,
        } for _ in range(count)]

    def _exercise_confirmation_gate(self, root: Path, target: float) -> tuple[dict, dict | None]:
        config = evolution._validate_config(self._config(target_win_rate=target))
        runner = evolution.EvolutionRunner(root, config)
        candidate = anchor_genomes()[0]
        calls = 0

        def evaluate(_jobs, candidates, alpha_by_id=None):
            nonlocal calls
            calls += 1
            bot_id = candidates[0].bot_id
            if calls == 1:
                return {bot_id: {
                    "bot_id": bot_id, "played": 1, "won": 1, "win_rate": 1.0,
                    "invalid_actions": 0, "evaluations": [],
                }}
            return {bot_id: evolution._aggregate(
                bot_id, self._all_winning_evaluations(bot_id, 42), alpha_by_id[bot_id],
            )}

        with mock.patch.object(runner, "_evaluate_batch", side_effect=evaluate):
            _validation, confirmation, promoted = runner._test_candidates(1, [candidate])
        return (confirmation[0] if confirmation else {}), promoted

    def test_ninety_percent_target_uses_fresh_exact_confirmation_gate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result, promoted = self._exercise_confirmation_gate(Path(temp_dir) / "target-90", 0.90)
            self.assertIsNotNone(promoted)
            self.assertTrue(result["gate_passed"])
            self.assertEqual(result["played"], 42)
            self.assertGreater(result["gate_lower_bound"], 0.90)
            self.assertEqual(result["gate_alpha"], 0.0125)
            default_result, default_promoted = self._exercise_confirmation_gate(Path(temp_dir) / "target-95", 0.95)
            self.assertIsNone(default_promoted)
            self.assertFalse(default_result["gate_passed"])
            self.assertLess(default_result["gate_lower_bound"], 0.95)

    def test_archive_union_is_complete_deduplicated_and_source_scoped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first, second, _first_records, _second_records = self._source_pair(root)
            config = evolution._validate_config({"archive_checkpoints": [str(first), str(second)]})
            archive = config["training_archive"]
            self.assertEqual(archive["schema"], "pokerbot-training-archive-v1")
            self.assertEqual(set(archive["training_opponents"]), {
                "shared@archive-0", "same-policy", "only-a", "shared@archive-1", "only-b",
            })
            self.assertEqual(set(archive["hall_of_fame"]), {"shared@archive-0", "same-policy", "shared@archive-1"})
            self.assertEqual(len(archive["genomes"]), 5)
            self.assertEqual(archive["policy_ids"]["shared@archive-0"], "shared")
            self.assertEqual(archive["policy_ids"]["shared@archive-1"], "shared")
            self.assertEqual(len(archive["provenance"]["same-policy"]), 2)
            self.assertEqual(archive["provenance"]["same-policy"][0]["source_genome"]["generation"], 0)
            self.assertNotIn("history", archive)
            self.assertNotIn("confirmation_results", archive)
            self.assertTrue(evolution._verify_training_archive(archive))

            runner = evolution.EvolutionRunner(root / "run", config)
            self.assertTrue(set(archive["training_opponents"]).issubset(runner.state["training_opponents"]))
            self.assertTrue(set(archive["hall_of_fame"]).issubset(runner.state["hall_of_fame"]))
            self.assertFalse(set(archive["genomes"]) & set(runner.state["active_population"]))
            self.assertEqual(runner.state["training_archive_fingerprint"], archive["fingerprint"])
            self.assertEqual(runner.state["archive_provenance"], archive["provenance"])

    def test_archive_duplicate_membership_and_alias_conflicts_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            duplicate_path = self._write_checkpoint(
                root / "duplicate.json", ["shared", "shared"], [], {"shared": self._genome("shared", 21)},
            )
            with self.assertRaisesRegex(ValueError, "duplicate IDs"):
                evolution._validate_config({"archive_checkpoints": [str(duplicate_path)]})

            conflicting = self._genome("shared", 22)
            colliding_alias = self._genome("shared@archive-1", 23)
            first_path = self._write_checkpoint(root / "a.json", ["shared"], [], {"shared": self._genome("shared", 24)})
            second_path = self._write_checkpoint(
                root / "b.json", ["shared", "shared@archive-1"], [],
                {"shared": conflicting, "shared@archive-1": colliding_alias},
            )
            with self.assertRaisesRegex(ValueError, "conflicting archive policies remain under alias"):
                evolution._validate_config({"archive_checkpoints": [str(first_path), str(second_path)]})

            clean_first = self._write_checkpoint(
                root / "clean-first.json", ["shared"], [], {"shared": self._genome("shared", 31)},
            )
            clean_second = self._write_checkpoint(
                root / "clean-second.json", ["shared"], [], {"shared": self._genome("shared", 32)},
            )
            policy_path = root / "policy-ids.json"
            policy_path.write_text(json.dumps({
                "shared": "original-a",
                "shared@archive-0": "original-b",
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "conflicting original policy IDs"):
                evolution._validate_config({
                    "archive_checkpoints": [str(clean_first), str(clean_second)],
                    "archive_policy_ids_path": str(policy_path),
                })

    def test_deployment_factory_receives_original_policy_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first, second, _first_records, _second_records = self._source_pair(root)
            config = evolution._validate_config({
                "players": 2,
                "fixed_random_opponents": 1,
                "archive_checkpoints": [str(first), str(second)],
            })
            alias = "shared@archive-0"
            archived = evolution._from_dict(config["training_archive"]["genomes"][alias])
            job = evolution._build_tournament_job(anchor_genomes()[0], [archived], 47, "training", config)
            observed_ids = []

            def fake_policy(genome):
                observed_ids.append(genome.bot_id)
                return object()

            def fake_tournament(policies, **kwargs):
                seat = job["hero_seat"]
                return {
                    "winner": seat,
                    "capped": False,
                    "hands_played": 1,
                    "final_stacks": [1000, 0] if seat == 0 else [0, 1000],
                    "players": [
                        {"index": index, "finish": 1 if index == seat else 2, "points": 2 if index == seat else 1,
                         "final_stack": 1000 if index == seat else 0, "invalid_actions": 0, "decisions": 1}
                        for index in range(2)
                    ],
                }

            with mock.patch.object(evolution, "policy_for", side_effect=fake_policy), mock.patch.object(
                evolution, "play_tournament", side_effect=fake_tournament
            ):
                evolution._run_tournament_job(job)
            self.assertIn("shared", observed_ids)
            self.assertNotIn(alias, observed_ids)
            self.assertIn(alias, job["seat_bot_ids"])

    def test_archive_keeps_validation_confirmation_pools_and_resume_rejects_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first, second, _first_records, _second_records = self._source_pair(root)
            base = evolution.EvolutionRunner(root / "base", self._config())
            imported_config = self._config(archive_checkpoints=[str(first), str(second)])
            imported = evolution.EvolutionRunner(root / "imported", imported_config)
            for key in ("validation_population", "confirmation_population"):
                self.assertEqual(base.state[key], imported.state[key])
            for key in ("validation", "confirmation"):
                self.assertEqual(base.state["fixed_pool_fingerprints"][key], imported.state["fixed_pool_fingerprints"][key])

            heldout_only_change = json.loads(first.read_text(encoding="utf-8"))
            heldout_only_change["confirmation_results"] = {"ineligible": {"wins": 10**9}}
            first.write_text(json.dumps(heldout_only_change), encoding="utf-8")
            resumed = evolution.EvolutionRunner(root / "imported", imported_config, resume=True)
            self.assertEqual(resumed.state["training_archive_fingerprint"], imported.state["training_archive_fingerprint"])

            changed = json.loads(first.read_text(encoding="utf-8"))
            new_genome = self._genome("new-archive-member", 99)
            changed["training_opponents"].append(new_genome["bot_id"])
            changed["genomes"][new_genome["bot_id"]] = new_genome
            first.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "incompatible"):
                evolution.EvolutionRunner(root / "imported", imported_config, resume=True)


if __name__ == "__main__":
    unittest.main()
