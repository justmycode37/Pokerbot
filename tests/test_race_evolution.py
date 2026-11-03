from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from pokerbot import evolution
from pokerbot.evolution_strategies import Genome
from scripts import race_evolution


def _genome(bot_id: str, *, parents=(), generation=0, value=0.6) -> dict:
    return Genome(
        bot_id=bot_id,
        family="evolved",
        params={"call_frequency": value},
        parents=tuple(parents),
        generation=generation,
    ).to_dict()


def _checkpoint(genomes: list[dict], training_ids: list[str], hof_ids: list[str] | None = None) -> dict:
    return {
        "config": {
            "players": 8,
            "stacks": 2000,
            "big_blinds": list(evolution.DEFAULT_BIG_BLINDS),
            "hands_per_level": 25,
            "max_hands": 200,
            "payouts": None,
            "strict": True,
            "seed": 23,
            "evaluation_namespace": "training-run-label",
        },
        "training_opponents": training_ids,
        "hall_of_fame": training_ids[:2] if hof_ids is None else hof_ids,
        "genomes": {genome["bot_id"]: genome for genome in genomes},
        # These values must not be read, hashed, or used to select genomes.
        "validation_population": {"poison": "must not be read"},
        "confirmation_population": {"poison": "must not be read"},
        "validation_results": {"poison": "must not be read"},
        "confirmation_results": {"poison": "must not be read"},
        "history": {"poison": "must not be read"},
    }


def _write_json(path: Path, value) -> Path:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


class ProjectionTests(unittest.TestCase):
    def test_checkpoint_projection_never_reads_heldout_or_performance_fields(self):
        class GuardedCheckpoint(dict):
            def get(self, key, default=None):
                if key in {
                    "validation_population", "confirmation_population", "validation_results",
                    "confirmation_results", "history", "fitness", "champion",
                }:
                    raise AssertionError(f"forbidden checkpoint field read: {key}")
                return super().get(key, default)

        genome = _genome("pool-0")
        checkpoint = GuardedCheckpoint(_checkpoint([genome], training_ids=["pool-0"]))
        projected = race_evolution._project_checkpoint(checkpoint, "guarded")
        self.assertEqual(set(projected), {"source", "config", "training_opponents", "hall_of_fame", "genomes"})
        self.assertEqual(projected["training_opponents"], ["pool-0"])
        self.assertNotIn("evaluation_namespace", projected["config"])

    def test_preserves_union_and_records_same_id_lineage_provenance(self):
        first = _genome("shared", parents=("old-parent",), generation=2)
        second_shared = _genome("shared", parents=("new-parent",), generation=9)
        first_pool = [_genome(f"first-{index}") for index in range(7)] + [first]
        second_pool = [_genome(f"second-{index}") for index in range(7)] + [second_shared]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidates = _write_json(root / "candidates.json", [_genome("candidate")])
            checkpoint_a = _write_json(root / "a.json", _checkpoint(first_pool, [g["bot_id"] for g in first_pool], ["shared"]))
            checkpoint_b = _write_json(root / "b.json", _checkpoint(second_pool, [g["bot_id"] for g in second_pool], ["shared"]))
            seeds = _write_json(root / "seeds.json", [3, 8])
            inputs = race_evolution._assemble_inputs(candidates, [checkpoint_a, checkpoint_b], seeds)

        expected = {g["bot_id"] for g in first_pool + second_pool}
        self.assertEqual(set(inputs["opponent_ids"]), expected)
        self.assertEqual(len(inputs["opponent_genomes"]), len(expected))
        shared_sources = inputs["provenance"]["shared"]
        self.assertEqual({item["generation"] for item in shared_sources}, {2, 9})
        self.assertEqual({tuple(item["parents"]) for item in shared_sources}, {("old-parent",), ("new-parent",)})
        self.assertIn("complete_training_plus_hall_of_fame_sha256", inputs["opponent_pool_hashes"])

    def test_conflicting_phenotypes_under_an_id_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidates = _write_json(root / "candidates.json", [_genome("candidate")])
            first = [_genome(f"pool-{index}") for index in range(7)]
            second = [_genome(f"other-{index}") for index in range(7)]
            first[0] = _genome("shared")
            second[0] = _genome("shared", value=0.8)
            a = _write_json(root / "a.json", _checkpoint(first, [g["bot_id"] for g in first]))
            b = _write_json(root / "b.json", _checkpoint(second, [g["bot_id"] for g in second]))
            seeds = _write_json(root / "seeds.json", [1])
            with self.assertRaisesRegex(ValueError, "conflicting phenotypes under genome ID shared"):
                race_evolution._assemble_inputs(candidates, [a, b], seeds)


class PairedPlanTests(unittest.TestCase):
    def test_report_aliases_preserve_original_policy_ids_in_canonical_execution(self):
        opponents = [_genome(f"archive-{index}") for index in range(8)]
        inputs = {
            "candidates": [_genome("candidate-alias")],
            "opponent_genomes": opponents,
            "seeds": [1234],
            "config": {"players": 8},
            "policy_ids": {"candidate-alias": "original-shared-id", **{
                f"archive-{index}": "original-shared-id" for index in range(8)
            }},
        }
        job = race_evolution._build_ordered_jobs(inputs)[0]
        self.assertEqual(job["hero_id"], "candidate-alias")
        self.assertEqual(job["seat_bot_ids"][job["hero_seat"]], "candidate-alias")
        self.assertEqual([g["bot_id"] for g in job["genomes"]], ["original-shared-id"] * 8)
        self.assertEqual(job["policy_bot_ids"], ["original-shared-id"] * 8)
        self.assertNotEqual(job["seat_bot_ids"], job["policy_bot_ids"])

    def test_every_candidate_has_identical_paired_opponent_seats_and_clone_is_not_removed(self):
        candidates = [_genome("pool-0", value=0.5), _genome("challenger", value=0.7)]
        opponents = [_genome(f"pool-{index}", value=0.5 + index / 100) for index in range(7)]
        inputs = {
            "candidates": candidates,
            "opponent_genomes": opponents,
            "seeds": [1234, 5678],
            "config": {
                "players": 8, "stacks": 2000,
                "big_blinds": list(evolution.DEFAULT_BIG_BLINDS), "hands_per_level": 25,
                "max_hands": 200, "payouts": None, "strict": True,
            },
        }
        jobs = race_evolution._build_ordered_jobs(inputs)
        by_candidate = {}
        for job in jobs:
            by_candidate.setdefault(job["hero_id"], {})[job["seed"]] = job
        for seed in inputs["seeds"]:
            left, right = (by_candidate[genome["bot_id"]][seed] for genome in candidates)
            self.assertEqual(left["hero_seat"], right["hero_seat"])
            self.assertEqual(race_evolution._paired_signature(left), race_evolution._paired_signature(right))
            self.assertTrue(left["config"]["strict"])
            self.assertEqual(left["config"]["players"], 8)
            self.assertEqual(left["config"]["max_hands"], 200)
            self.assertIn("pool-0", [
                bot_id for index, bot_id in enumerate(left["seat_bot_ids"]) if index != left["hero_seat"]
            ])

    def test_canonical_evaluator_never_counts_a_capped_chip_lead_as_a_win(self):
        hero = _genome("hero")
        opponents = [_genome(f"opponent-{index}") for index in range(7)]
        config = {
            "players": 8, "stacks": 2000,
            "big_blinds": list(evolution.DEFAULT_BIG_BLINDS), "hands_per_level": 25,
            "max_hands": 200, "payouts": None, "strict": True,
        }
        job = evolution._build_tournament_job(
            evolution._from_dict(hero), [evolution._from_dict(row) for row in opponents], 100,
            race_evolution.COMPARISON_KIND, config,
        )
        fake_tournament = {
            "capped": True,
            "winner": job["hero_seat"],
            "hands_played": 200,
            "players": [{"index": job["hero_seat"], "final_stack": 100, "points": 10, "finish": 1}],
            "final_stacks": [100] * 8,
        }
        with mock.patch.object(evolution, "policy_for", return_value=object()), mock.patch.object(
            evolution, "play_tournament", return_value=fake_tournament,
        ) as play:
            result = evolution._run_tournament_job(job)
        self.assertFalse(result["won"])
        self.assertTrue(result["capped"])
        self.assertTrue(result["table_capped"])
        self.assertTrue(play.call_args.kwargs["strict"])


class RunTests(unittest.TestCase):
    def _inputs(self, root: Path):
        candidates = _write_json(root / "candidates.json", [_genome("candidate-a"), _genome("candidate-b", value=0.7)])
        opponents = [_genome(f"pool-{index}", value=0.5 + index / 20) for index in range(8)]
        checkpoint = _write_json(root / "checkpoint.json", _checkpoint(opponents, [g["bot_id"] for g in opponents]))
        seeds = _write_json(root / "seeds.json", [101, 202, 303])
        return candidates, checkpoint, seeds

    @staticmethod
    def _mock_evaluations(jobs, *, timing_offset=0):
        rows = []
        for index, job in enumerate(jobs):
            seed = int(job["seed"])
            candidate_a = job["hero_id"] == "candidate-a"
            capped = seed == 202
            won = candidate_a and seed == 101
            rows.append({
                "bot_id": job["hero_id"], "kind": race_evolution.COMPARISON_KIND, "seed": seed,
                "hero_seat": job["hero_seat"], "seat_bot_ids": list(job["seat_bot_ids"]),
                "winner_seat": job["hero_seat"] if won else None,
                "table_capped": capped, "capped": capped, "hands_played": 200,
                "won": won, "lost": not won and not capped, "final_stack": 1000 + int(candidate_a),
                "points": float(int(candidate_a) + index), "finish": 2.0 + int(candidate_a),
                "invalid_actions": 0, "decisions": 10, "latency_mean_ms": 0.1 + timing_offset,
                "latency_p95_ms": 0.2 + timing_offset, "latency_max_ms": 0.3 + timing_offset,
                "over_1ms": 0, "runtime_ms": 1.0 + timing_offset,
            })
        return rows

    def test_equal_sample_cap_denominator_reports_all_candidates_and_paired_bootstrap(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidates, checkpoint, seeds = self._inputs(root)
            output = root / "run"

            def evaluator(jobs, workers):
                self.assertEqual(workers, 2)
                self.assertTrue((output / "protocol.json").is_file())
                self.assertTrue((output / "jobs.json").is_file())
                self.assertTrue((output / "seeds.json").is_file())
                return self._mock_evaluations(jobs)

            with mock.patch.object(evolution, "_execute_jobs", side_effect=evaluator):
                result = race_evolution.run_comparison(
                    candidates, [checkpoint], seeds, output,
                    namespace="racer-equal-sample-test", workers=2,
                )
            self.assertTrue((output / "COMPLETE.json").is_file())
            self.assertEqual(json.loads((output / "status.json").read_text())["status"], "complete")
            self.assertEqual((output / "seeds.json").read_bytes(), seeds.read_bytes())
            self.assertEqual([row["played"] for row in result["results"]], [3, 3])
            self.assertEqual({row["status"] for row in result["results"]}, {"comparison_only"})
            first = next(row for row in result["results"] if row["bot_id"] == "candidate-a")
            self.assertEqual(first["won"], 1)
            self.assertEqual(first["table_caps"], 1)
            self.assertEqual(first["cap_survivors"], 1)
            self.assertAlmostEqual(first["win_rate"], 1 / 3)
            self.assertEqual(first["wilson_95"], evolution.wilson_interval(1, 3))
            self.assertEqual(len(result["paired_comparisons"]["comparisons"]), 2)
            self.assertEqual(len((output / "results.csv").read_text().splitlines()), 3)
            self.assertIn("comparison_only", (output / "report.md").read_text())
            self.assertEqual(json.loads((output / "jobs.json").read_text())["schema"], race_evolution.SCHEMA)

    def test_failure_leaves_run_incomplete_without_complete_marker(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidates, checkpoint, seeds = self._inputs(root)
            output = root / "failed-run"
            with mock.patch.object(evolution, "_execute_jobs", side_effect=RuntimeError("worker failed")):
                with self.assertRaisesRegex(RuntimeError, "worker failed"):
                    race_evolution.run_comparison(
                        candidates, [checkpoint], seeds, output, namespace="racer-failure-test",
                    )
            status = json.loads((output / "status.json").read_text())
            self.assertEqual(status["status"], "incomplete")
            self.assertEqual(status["stage"], "failed")
            self.assertIn("worker failed", status["error"])
            self.assertTrue((output / "protocol.json").is_file())
            self.assertTrue((output / "jobs.json").is_file())
            self.assertFalse((output / "COMPLETE.json").exists())
            self.assertFalse((output / "results.csv").exists())

    def test_alias_mapping_is_frozen_and_reported_without_changing_policy_sampling_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidates, checkpoint, seeds = self._inputs(root)
            mapping = _write_json(root / "policy-ids.json", {"candidate-a": "source-a", "pool-0": "source-pool-0"})
            output = root / "aliased-run"
            def evaluator(jobs, workers):
                first = jobs[0]
                self.assertEqual(first["hero_id"], "candidate-a")
                self.assertEqual(first["genomes"][first["hero_seat"]]["bot_id"], "source-a")
                return self._mock_evaluations(jobs)
            with mock.patch.object(evolution, "_execute_jobs", side_effect=evaluator):
                result = race_evolution.run_comparison(candidates, [checkpoint], seeds, output,
                    namespace="racer-alias-test", policy_ids_path=mapping)
            self.assertEqual(result["protocol"]["policy_ids"]["candidate-a"], "source-a")
            self.assertIsNotNone(result["protocol"]["inputs"]["policy_ids_file_sha256"])
            row = next(r for r in result["results"] if r["bot_id"] == "candidate-a")
            self.assertEqual(row["policy_bot_id"], "source-a")
            self.assertIn("Original policy ID", (output / "report.md").read_text())
            with self.assertRaisesRegex(ValueError, "unknown report ID"):
                race_evolution._assemble_inputs(candidates, [checkpoint], seeds,
                    _write_json(root / "unknown-mapping.json", {"missing": "source"}))

    def test_changed_source_during_evaluation_cannot_complete_a_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidates, checkpoint, seeds = self._inputs(root)
            output = root / "source-changed"
            with mock.patch.object(evolution, "_execute_jobs", side_effect=lambda jobs, workers: self._mock_evaluations(jobs)), mock.patch.object(
                race_evolution, "_source_fingerprint", side_effect=[{"sha256": "before"}, {"sha256": "after"}]
            ):
                with self.assertRaisesRegex(RuntimeError, "fingerprint changed"):
                    race_evolution.run_comparison(candidates, [checkpoint], seeds, output, namespace="racer-source-change")
            self.assertFalse((output / "COMPLETE.json").exists())
            self.assertEqual(json.loads((output / "status.json").read_text())["status"], "incomplete")

    def test_refuses_overwrite_and_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidates, checkpoint, seeds = self._inputs(root)
            output = root / "existing"
            output.mkdir()
            sentinel = output / "keep.txt"
            sentinel.write_text("existing run", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                race_evolution.run_comparison(
                    candidates, [checkpoint], seeds, output, namespace="racer-overwrite-test",
                )
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "existing run")
            with self.assertRaisesRegex(ValueError, "resume is unsupported"):
                race_evolution.run_comparison(
                    candidates, [checkpoint], seeds, root / "resume", namespace="racer-resume-test", resume=True,
                )

    def test_deterministic_order_and_paired_statistics_ignoring_timing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidates, checkpoint, seeds = self._inputs(root)
            outputs = [root / "run-a", root / "run-b"]
            call_count = 0

            def evaluator(jobs, workers):
                nonlocal call_count
                call_count += 1
                return self._mock_evaluations(jobs, timing_offset=float(call_count))

            for output in outputs:
                with mock.patch.object(evolution, "_execute_jobs", side_effect=evaluator):
                    race_evolution.run_comparison(
                        candidates, [checkpoint], seeds, output, namespace="racer-determinism-test",
                    )

            def strip_timing(value):
                if isinstance(value, dict):
                    return {
                        key: strip_timing(item) for key, item in value.items()
                        if key not in race_evolution.TIMING_FIELDS and key != "over_1ms"
                    }
                if isinstance(value, list):
                    return [strip_timing(item) for item in value]
                return value

            first = json.loads((outputs[0] / "results.json").read_text())
            second = json.loads((outputs[1] / "results.json").read_text())
            self.assertEqual(strip_timing(first), strip_timing(second))
            first_pairs = json.loads((outputs[0] / "paired-comparisons.json").read_text())
            second_pairs = json.loads((outputs[1] / "paired-comparisons.json").read_text())
            self.assertEqual(first_pairs, second_pairs)
            self.assertEqual([row["rank"] for row in first["candidate_results"]], [1, 2])

            sample = [1.0, -1.0, 0.5, -0.5]
            interval_a = race_evolution._bootstrap_interval(sample, 987)
            interval_b = race_evolution._bootstrap_interval(sample, 987)
            self.assertEqual(interval_a, interval_b)
            self.assertAlmostEqual(interval_a["mean"], 0.0)
            self.assertEqual(interval_a["n"], 4)
            self.assertIn("no multiple-test adjustment", interval_a["method"])


class CliTests(unittest.TestCase):
    def test_help_documents_training_only_worker_and_seed_inputs(self):
        parser = race_evolution.build_parser()
        help_text = parser.format_help()
        for expected in ("--candidates", "--checkpoint", "--seeds", "--namespace", "--workers", "comparison"):
            self.assertIn(expected, help_text)


if __name__ == "__main__":
    unittest.main()
