import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pokerbot import evolution
from pokerbot.evolution_strategies import anchor_genomes
from scripts import evolve_parallel


def _outcome_only(rows):
    latency_fields = {
        "latency_mean_ms", "latency_p95_ms", "latency_max_ms", "over_1ms", "runtime_ms",
    }
    return [
        {key: value for key, value in row.items() if key not in latency_fields}
        for row in rows
    ]


class ParallelEvolutionTests(unittest.TestCase):
    def _config(self, **overrides):
        config = {
            "players": 8,
            "population": 8,
            "matches": 1,
            "validation_matches": 2,
            "confirmation_matches": 128,
            "seed": 481516,
            "stacks": 2000,
            "big_blinds": (20, 40, 80, 160, 320, 640, 1280, 2560),
            "hands_per_level": 25,
            "max_hands": 12,
            "fixed_random_opponents": 7,
        }
        config.update(overrides)
        return config

    def _training_jobs(self, runner):
        state = runner.state
        training_pool = evolution._opponent_pool(state, "training")
        candidates = anchor_genomes()[:2]
        return [
            evolution._build_tournament_job(candidate, training_pool, seed, "training", runner.config)
            for candidate, seed in zip(candidates * 2, (2101, 2102, 2103, 2104))
        ]

    def test_cli_passes_target_and_archive_options_like_the_canonical_cli(self):
        argv = ["run", "--target-win-rate", "0.9", "--archive-checkpoint", "a.json",
                "--archive-checkpoint", "b.json", "--archive-policy-ids", "ids.json"]
        parallel = evolution.config_from_args(evolve_parallel.build_parser().parse_args(argv))
        canonical = evolution.config_from_args(evolution.build_parser().parse_args(argv))
        self.assertEqual(parallel, canonical)
        self.assertEqual(parallel["target_win_rate"], 0.9)
        self.assertEqual(parallel["archive_checkpoints"], ["a.json", "b.json"])
        captured = {}

        class Runner:
            def __init__(self, output_dir, config, **kwargs):
                captured.update(config)

            def run(self, generations):
                raise SystemExit(0)

        with mock.patch.object(evolve_parallel, "PersistentPoolRunner", Runner):
            with self.assertRaises(SystemExit):
                evolve_parallel.main(argv)
        self.assertEqual(captured["target_win_rate"], 0.9)
        self.assertEqual(captured["archive_checkpoints"], ["a.json", "b.json"])
        self.assertEqual(captured["archive_policy_ids_path"], "ids.json")

    def test_fixed_training_jobs_match_serial_canonical_parallel_and_accelerated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runner = evolve_parallel.PersistentPoolRunner(
                Path(temp_dir) / "accelerated", self._config(), workers=2, chunksize=2,
            )
            jobs = self._training_jobs(runner)

            serial = evolution._execute_jobs(jobs, workers=1)
            canonical_parallel = evolution._execute_jobs(jobs, workers=2)
            with runner._worker_pool():
                accelerated = runner.execute_jobs(jobs)

            expected_order = [(job["hero_id"], job["seed"]) for job in jobs]
            self.assertEqual([(row["bot_id"], row["seed"]) for row in accelerated], expected_order)
            self.assertEqual(_outcome_only(serial), _outcome_only(canonical_parallel))
            self.assertEqual(_outcome_only(serial), _outcome_only(accelerated))

    def test_exception_shuts_down_pool_and_clears_runner_reference(self):
        class FailingExecutor:
            instances = []

            def __init__(self, max_workers):
                self.max_workers = max_workers
                self.shutdown_call = None
                self.__class__.instances.append(self)

            def map(self, function, jobs, chunksize):
                raise RuntimeError("worker failed")

            def shutdown(self, *, wait, cancel_futures):
                self.shutdown_call = (wait, cancel_futures)

        with tempfile.TemporaryDirectory() as temp_dir:
            runner = evolve_parallel.PersistentPoolRunner(temp_dir, self._config(), workers=2)
            with mock.patch.object(evolve_parallel.concurrent.futures, "ProcessPoolExecutor", FailingExecutor):
                with self.assertRaisesRegex(RuntimeError, "worker failed"):
                    runner.run(1)

            self.assertEqual(len(FailingExecutor.instances), 1)
            self.assertEqual(FailingExecutor.instances[0].shutdown_call, (True, True))
            self.assertIsNone(runner._executor)

    def test_repeated_training_batches_reserve_fresh_seeds(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runner = evolve_parallel.PersistentPoolRunner(temp_dir, self._config(), workers=2)
            candidates = [
                evolution._from_dict(runner.state["genomes"][bot_id])
                for bot_id in runner.state["active_population"]
            ]
            first = runner._reserve_jobs(candidates, 1, "training", 1)
            second = runner._reserve_jobs(candidates, 1, "training", 2)
            first_seeds = {job["seed"] for job in first}
            second_seeds = {job["seed"] for job in second}

            self.assertEqual(len(first), 8)
            self.assertEqual(len(second), 8)
            self.assertTrue(first_seeds.isdisjoint(second_seeds))
            self.assertEqual(runner.state["seed_stream"]["counters"]["training"], 16)
            self.assertEqual(runner.state["seed_stream"]["counters"]["validation"], 0)
            self.assertEqual(runner.state["seed_stream"]["counters"]["confirmation"], 0)

    def test_resume_rejects_driver_settings_source_and_canonical_config_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self._config()
            first_runner = evolve_parallel.PersistentPoolRunner(
                temp_dir, config, workers=2, chunksize=4,
            )
            first_provenance_line = first_runner.provenance_path.read_text(encoding="utf-8").splitlines()[0]
            resumed = evolve_parallel.PersistentPoolRunner(
                temp_dir, config, resume=True, workers=2, chunksize=4,
            )
            provenance_lines = resumed.provenance_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(provenance_lines), 2)
            self.assertEqual(provenance_lines[0], first_provenance_line)

            with self.assertRaisesRegex(ValueError, "execution provenance"):
                evolve_parallel.PersistentPoolRunner(
                    temp_dir, config, resume=True, workers=2, chunksize=5,
                )
            with self.assertRaisesRegex(ValueError, "execution provenance"):
                evolve_parallel.PersistentPoolRunner(
                    temp_dir, config, resume=True, workers=3, chunksize=4,
                )
            with mock.patch.object(evolve_parallel, "_driver_source_hash", return_value="0" * 64):
                with self.assertRaisesRegex(ValueError, "execution provenance"):
                    evolve_parallel.PersistentPoolRunner(
                        temp_dir, config, resume=True, workers=2, chunksize=4,
                    )
            with self.assertRaisesRegex(ValueError, "provenance|incompatible"):
                evolve_parallel.PersistentPoolRunner(
                    temp_dir, self._config(matches=2), resume=True, workers=2, chunksize=4,
                )

    def test_resume_rejects_missing_provenance_and_chunksize_is_bounded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runner = evolve_parallel.PersistentPoolRunner(temp_dir, self._config())
            runner.provenance_path.unlink()
            with self.assertRaisesRegex(ValueError, "provenance file is missing"):
                evolve_parallel.PersistentPoolRunner(
                    temp_dir, self._config(), resume=True,
                )

        with self.assertRaisesRegex(ValueError, "chunksize"):
            evolve_parallel.PersistentPoolRunner(
                "/tmp/parallel-invalid-chunksize", self._config(), chunksize=0,
            )


if __name__ == "__main__":
    unittest.main()
