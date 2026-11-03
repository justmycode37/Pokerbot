#!/usr/bin/env python3
"""Optional persistent-process-pool driver for canonical evolution runs.

This module deliberately delegates all population, seed, checkpoint, report,
and target-confirmation behavior to :mod:`pokerbot.evolution`. It changes only
how already-reserved tournament jobs are scheduled.
"""

from __future__ import annotations

import argparse
import concurrent.futures
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pokerbot import evolution  # noqa: E402


PROVENANCE_SCHEMA = "pokerbot-evolution-parallel-execution-v1"
PROVENANCE_FILENAME = "parallel-execution-provenance.jsonl"
MAX_CHUNKSIZE = 64


def _driver_source_hash() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _configuration_hash(config: dict[str, Any]) -> str:
    material = json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _read_provenance(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"parallel resume rejected: cannot read execution provenance: {exc}") from exc
    if not lines:
        raise ValueError("parallel resume rejected: execution provenance is empty")
    for line_number, line in enumerate(lines, start=1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"parallel resume rejected: invalid provenance JSON on line {line_number}"
            ) from exc
        if not isinstance(record, dict) or record.get("schema") != PROVENANCE_SCHEMA:
            raise ValueError(f"parallel resume rejected: unsupported provenance record on line {line_number}")
        records.append(record)
    return records


def _append_provenance(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
    # Append and fsync each invocation record. Existing provenance is never
    # rewritten, including after an interrupted run.
    with path.open("a", encoding="utf-8", newline="") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())


class PersistentPoolRunner(evolution.EvolutionRunner):
    """Canonical evolution runner with one scoped pool per ``run`` call."""

    def __init__(
        self,
        output_dir: str | Path,
        config: dict[str, Any] | None = None,
        *,
        resume: bool = False,
        workers: int = 2,
        chunksize: int = 4,
    ) -> None:
        self.workers = int(workers)
        if self.workers < 1:
            raise ValueError("workers must be at least 1")
        self.chunksize = int(chunksize)
        if not 1 <= self.chunksize <= MAX_CHUNKSIZE:
            raise ValueError(f"chunksize must be between 1 and {MAX_CHUNKSIZE}")

        self.output_dir = Path(output_dir).expanduser().resolve()
        self.provenance_path = self.output_dir / PROVENANCE_FILENAME
        validated_config = evolution._validate_config(config or {})
        self._driver_hash = _driver_source_hash()
        self._config_hash = _configuration_hash(validated_config)
        checkpoint_path = self.output_dir / "checkpoint.json"

        if resume:
            if not checkpoint_path.exists():
                raise FileNotFoundError(f"cannot resume: {checkpoint_path} does not exist")
            if not self.provenance_path.exists():
                raise ValueError("parallel resume rejected: execution provenance file is missing")
            for record in _read_provenance(self.provenance_path):
                expected = {
                    "driver_source_sha256": self._driver_hash,
                    "workers": self.workers,
                    "chunksize": self.chunksize,
                    "config_sha256": self._config_hash,
                }
                if any(record.get(key) != value for key, value in expected.items()):
                    raise ValueError(
                        "parallel resume rejected: driver source, worker count, chunksize, or config "
                        "differs from execution provenance"
                    )
        elif self.provenance_path.exists() and not checkpoint_path.exists():
            raise ValueError(
                "cannot start a fresh parallel run: provenance exists without its checkpoint"
            )

        # The canonical runner owns checkpoint compatibility and initialization.
        super().__init__(self.output_dir, config, resume=resume, workers=self.workers)
        self._executor: concurrent.futures.ProcessPoolExecutor | None = None
        _append_provenance(self.provenance_path, {
            "schema": PROVENANCE_SCHEMA,
            "event": "run_start",
            "started_at_utc": evolution._utc_now(),
            "driver_source_sha256": self._driver_hash,
            "config_sha256": self._config_hash,
            "workers": self.workers,
            "chunksize": self.chunksize,
            "python_version": sys.version.split()[0],
            "executor": "concurrent.futures.ProcessPoolExecutor.map",
            "result_order": "input order",
            "provenance_path": str(self.provenance_path),
        })

    @contextmanager
    def _worker_pool(self) -> Iterator[None]:
        if self._executor is not None:
            raise RuntimeError("parallel worker pool is already active")
        if self.workers > 1:
            executor = concurrent.futures.ProcessPoolExecutor(max_workers=self.workers)
            self._executor = executor
        else:
            executor = None
        try:
            yield
        finally:
            self._executor = None
            if executor is not None:
                # Explicitly cancel queued work and wait for running workers on
                # both success and failure paths before releasing the pool.
                executor.shutdown(wait=True, cancel_futures=True)

    def execute_jobs(self, jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self.workers <= 1:
            return evolution._execute_jobs(jobs, 1)
        if self._executor is None:
            raise RuntimeError("parallel jobs must run inside the scoped worker pool")
        # ProcessPoolExecutor.map preserves input order; chunksize affects only
        # transport batching and is capped when the batch itself is smaller.
        return list(self._executor.map(
            evolution._run_tournament_job,
            jobs,
            chunksize=min(self.chunksize, max(1, len(jobs))),
        ))

    def _evaluate_batch(
        self,
        jobs: list[dict[str, Any]],
        candidates: list[Any],
        alpha_by_id: dict[str, float] | None = None,
    ) -> dict[str, dict[str, Any]]:
        results = self.execute_jobs(jobs)
        by_id: dict[str, list[dict[str, Any]]] = {evolution._id(genome): [] for genome in candidates}
        for result in results:
            by_id[result["bot_id"]].append(result)
        return {
            bot_id: evolution._aggregate(
                bot_id, evaluations, None if alpha_by_id is None else alpha_by_id[bot_id]
            )
            for bot_id, evaluations in by_id.items()
        }

    def run(self, generations: int) -> dict[str, Any]:
        with self._worker_pool():
            return super().run(generations)


def _chunksize(value: str) -> int:
    try:
        result = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("chunksize must be an integer") from exc
    if not 1 <= result <= MAX_CHUNKSIZE:
        raise argparse.ArgumentTypeError(f"chunksize must be between 1 and {MAX_CHUNKSIZE}")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = evolution.build_parser()
    subparsers = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )
    run_parser = subparsers.choices["run"]
    run_parser.set_defaults(workers=2)
    run_parser.add_argument(
        "--chunksize", type=_chunksize, default=4,
        help=f"bounded ProcessPoolExecutor transport batch size (1..{MAX_CHUNKSIZE})",
    )
    run_parser.description = "Run or resume canonical evolution with a scoped persistent process pool."
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = {
        "players": args.players, "population": args.population, "matches": args.matches,
        "validation_matches": args.validation_matches, "confirmation_matches": args.confirmation_matches,
        "seed": args.seed, "stacks": args.stacks, "big_blinds": args.big_blinds,
        "hands_per_level": args.hands_per_level, "max_hands": args.max_hands,
        "payouts": args.payouts, "strict": True,
        "adaptive_fraction": args.adaptive_fraction, "seed_genomes_path": args.seed_genomes,
        "evaluation_namespace": args.evaluation_namespace,
    }
    runner = PersistentPoolRunner(
        args.output_dir, config, resume=args.resume,
        workers=args.workers, chunksize=args.chunksize,
    )
    state = runner.run(args.generations)
    print(json.dumps({
        "event": "chunk_complete", "status": state["status"],
        "completed_generations": state["completed_generations"],
        "requested_chunk_generations": args.generations,
        "target_not_reached": state["champion"] is None,
        "output_dir": str(runner.output_dir),
        "summary": str(runner.output_dir / "summary.json"),
        "champion": str(runner.output_dir / "champion.json"),
        "checkpoint": str(runner.checkpoint_path),
        "provenance": str(runner.provenance_path),
        "workers": runner.workers,
        "chunksize": runner.chunksize,
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
