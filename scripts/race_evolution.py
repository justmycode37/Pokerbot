#!/usr/bin/env python3
"""Training-only, equal-sample comparisons using the canonical tournament evaluator.

This is an experimental comparison tool. It does not promote a candidate or
change the canonical evolutionary runner. Every candidate is evaluated on the
same supplied seeds, sampled opponent identities, seats, and deal streams.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import random
import sys
import tempfile
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pokerbot import evolution  # noqa: E402


SCHEMA = "pokerbot-evolution-racer-v1"
COMPARISON_KIND = "comparison_only"
ENGINE_DOMAINS = {"training", "validation", "confirmation"}
BOOTSTRAP_REPLICATES = 2_000
BOOTSTRAP_CONFIDENCE = 0.95
GENOME_FIELDS = {"bot_id", "family", "params", "parents", "generation"}
CONFIG_FIELDS = ("players", "stacks", "big_blinds", "hands_per_level", "max_hands", "payouts", "strict")
CSV_FIELDS = (
    "rank", "status", "bot_id", "policy_bot_id", "generation", "parents", "family", "params", "provenance", "played", "won", "lost",
    "cap_survivors", "table_caps", "win_rate", "wilson_95_low", "wilson_95_high",
    "mean_points", "mean_finish", "mean_final_stack", "invalid_actions", "decisions",
    "invalid_rate", "latency_mean_ms", "latency_p95_ms", "latency_max_ms", "over_1ms",
)
TIMING_FIELDS = {"runtime_ms", "runtime_mean_ms", "latency_mean_ms", "latency_p95_ms", "latency_max_ms"}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _write_json(path: Path, value: Any) -> bytes:
    encoded = _json_bytes(value)
    _atomic_write_bytes(path, encoded)
    return encoded


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid non-finite JSON number: {value}")


def _load_json(path: Path) -> tuple[Any, bytes]:
    raw = path.read_bytes()
    try:
        return json.loads(raw, parse_constant=_reject_json_constant), raw
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"could not read JSON from {path}: {exc}") from exc


def _normalized_genome(raw: Any, label: str, *, require_canonical: bool = False) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError(f"{label} must be a genome object")
    if require_canonical and set(raw) != GENOME_FIELDS:
        raise ValueError(f"{label} must use the canonical Genome.to_dict fields")
    genome = evolution._from_dict(dict(raw))
    record = evolution._to_dict(genome)
    if require_canonical and _canonical_json(record) != _canonical_json(dict(raw)):
        raise ValueError(f"{label} is not a canonical Genome.to_dict object")
    return record


def _phenotype(genome: Mapping[str, Any]) -> str:
    # IDs salt deployed policy randomness, so identity is part of evaluation
    # behavior even though this conflict check defines phenotype as family+genes.
    return _canonical_json({"family": genome["family"], "params": genome["params"]})


def _project_checkpoint(raw: Mapping[str, Any], source_label: str) -> dict[str, Any]:
    """Project only training config, training/HOF IDs, and referenced genomes.

    Validation, confirmation, fitness, history, and report fields are not read.
    """
    if not isinstance(raw, Mapping):
        raise ValueError(f"checkpoint {source_label} must be a JSON object")
    config_raw = raw.get("config", {})
    if not isinstance(config_raw, Mapping):
        raise ValueError(f"checkpoint {source_label} config must be an object")
    config = {key: config_raw[key] for key in CONFIG_FIELDS if key in config_raw}

    training_ids = raw.get("training_opponents")
    hof_ids = raw.get("hall_of_fame")
    registry = raw.get("genomes")
    for label, ids in (("training_opponents", training_ids), ("hall_of_fame", hof_ids)):
        if not isinstance(ids, list) or any(not isinstance(bot_id, str) or not bot_id.strip() for bot_id in ids):
            raise ValueError(f"checkpoint {source_label} {label} must be a list of nonempty IDs")
    if not isinstance(registry, Mapping):
        raise ValueError(f"checkpoint {source_label} genomes must be an object")

    referenced = list(dict.fromkeys([*training_ids, *hof_ids]))
    genomes: dict[str, dict[str, Any]] = {}
    for bot_id in referenced:
        if bot_id not in registry:
            raise ValueError(f"checkpoint {source_label} references missing genome {bot_id}")
        genome = _normalized_genome(registry[bot_id], f"checkpoint {source_label} genome {bot_id}")
        if genome["bot_id"] != bot_id:
            raise ValueError(f"checkpoint {source_label} genome registry key does not match {bot_id}")
        genomes[bot_id] = genome

    return {
        "source": source_label,
        "config": config,
        "training_opponents": list(training_ids),
        "hall_of_fame": list(hof_ids),
        "genomes": genomes,
    }


def _projected_checkpoint_file(path: Path) -> tuple[dict[str, Any], str]:
    parsed, _raw_bytes = _load_json(path)
    if not isinstance(parsed, Mapping):
        raise ValueError(f"checkpoint {path} must contain a JSON object")
    projected = _project_checkpoint(parsed, str(path))
    # Hash only the allowlisted projection. Checkpoint performance and held-out
    # fields do not influence source identity, the pool, or any score.
    digest_payload = {key: value for key, value in projected.items() if key != "source"}
    return projected, _sha256(_canonical_json(digest_payload).encode("utf-8"))


def _project_candidates(path: Path) -> tuple[list[dict[str, Any]], bytes]:
    parsed, raw_bytes = _load_json(path)
    if not isinstance(parsed, list) or not parsed:
        raise ValueError("candidate genomes file must contain a nonempty JSON list")
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(parsed):
        genome = _normalized_genome(raw, f"candidate at index {index}", require_canonical=True)
        if genome["bot_id"] in seen:
            raise ValueError(f"duplicate candidate ID: {genome['bot_id']}")
        seen.add(genome["bot_id"])
        candidates.append(genome)
    return candidates, raw_bytes


def _project_seeds(path: Path) -> tuple[list[int], bytes]:
    parsed, raw_bytes = _load_json(path)
    if not isinstance(parsed, list) or not parsed:
        raise ValueError("seed file must contain a nonempty JSON list of integer seeds")
    seeds: list[int] = []
    for index, seed in enumerate(parsed):
        if type(seed) is not int or not 0 <= seed < (1 << 63):
            raise ValueError(f"seed at index {index} must be an integer in [0, 2**63)")
        seeds.append(seed)
    if len(set(seeds)) != len(seeds):
        raise ValueError("seed file contains duplicate values; the supplied seed list is used unchanged")
    return seeds, raw_bytes


def _validate_namespace(namespace: str) -> None:
    if not namespace or namespace != namespace.strip() or len(namespace) > 128:
        raise ValueError("namespace must be a nonempty trimmed string of at most 128 characters")
    if namespace in ENGINE_DOMAINS or not namespace.startswith("racer-"):
        raise ValueError("namespace must be a fresh racer-* label, distinct from engine training/validation/confirmation domains")


def _simulation_config(projected_checkpoints: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    expected = {
        "players": 8,
        "stacks": 2000,
        "big_blinds": list(evolution.DEFAULT_BIG_BLINDS),
        "hands_per_level": 25,
        "max_hands": 200,
        "payouts": None,
        "strict": True,
    }
    snapshots: list[dict[str, Any]] = []
    for checkpoint in projected_checkpoints:
        source_config = checkpoint["config"]
        config = dict(expected)
        for key in CONFIG_FIELDS:
            if key in source_config:
                config[key] = source_config[key]
        for key, required in (("players", 8), ("max_hands", 200)):
            if type(config[key]) is not int:
                raise ValueError(f"checkpoint {checkpoint['source']} config {key} must be an integer")
            if config[key] != required:
                if key == "players":
                    raise ValueError(f"checkpoint {checkpoint['source']} is not configured for full eight-player tables")
                raise ValueError(f"checkpoint {checkpoint['source']} does not use the required 200-hand cap")
        if type(config["stacks"]) is not int or type(config["hands_per_level"]) is not int:
            raise ValueError(f"checkpoint {checkpoint['source']} stack and level settings must be integers")
        if not isinstance(config["big_blinds"], list) or any(type(value) is not int for value in config["big_blinds"]):
            raise ValueError(f"checkpoint {checkpoint['source']} big_blinds must be a list of integers")
        if type(config["strict"]) is not bool:
            raise ValueError(f"checkpoint {checkpoint['source']} strict must be a boolean")
        if config["payouts"] is not None:
            if not isinstance(config["payouts"], list) or any(
                isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value))
                for value in config["payouts"]
            ):
                raise ValueError(f"checkpoint {checkpoint['source']} payouts must be finite numbers or null")
            config["payouts"] = [float(value) for value in config["payouts"]]
        config["players"] = 8
        config["max_hands"] = 200
        if not config["strict"]:
            raise ValueError(f"checkpoint {checkpoint['source']} does not use strict legal actions")
        if config["stacks"] <= 0 or config["hands_per_level"] <= 0 or not config["big_blinds"] or any(x <= 0 for x in config["big_blinds"]):
            raise ValueError(f"checkpoint {checkpoint['source']} has invalid training table settings")
        snapshots.append(config)
    if not snapshots:
        return expected
    canonical = _canonical_json(snapshots[0])
    if any(_canonical_json(config) != canonical for config in snapshots[1:]):
        raise ValueError("checkpoint inputs have conflicting training table configurations")
    return snapshots[0]


def _register_genome(
    registry: dict[str, dict[str, Any]],
    provenance: dict[str, list[dict[str, Any]]],
    raw_genome: Mapping[str, Any],
    origin: dict[str, Any],
) -> None:
    bot_id = str(raw_genome["bot_id"])
    current = registry.get(bot_id)
    if current is not None and _phenotype(current) != _phenotype(raw_genome):
        raise ValueError(f"conflicting phenotypes under genome ID {bot_id}")
    if current is None:
        registry[bot_id] = dict(raw_genome)
    # Same-ID family/params duplicates with changed parent or generation are
    # retained as explicit provenance, while one stable policy record is used.
    if origin not in provenance.setdefault(bot_id, []):
        provenance[bot_id].append(origin)


def _assemble_inputs(
    candidate_path: Path,
    checkpoint_paths: Sequence[Path],
    seed_path: Path,
    policy_ids_path: Path | None = None,
) -> dict[str, Any]:
    candidates, candidate_bytes = _project_candidates(candidate_path)
    seeds, seed_bytes = _project_seeds(seed_path)
    projected_checkpoints: list[dict[str, Any]] = []
    checkpoint_hashes: list[dict[str, str]] = []
    for path in checkpoint_paths:
        projected, digest = _projected_checkpoint_file(path)
        projected_checkpoints.append(projected)
        checkpoint_hashes.append({"path": str(path), "projected_sha256": digest})

    config = _simulation_config(projected_checkpoints)
    registry: dict[str, dict[str, Any]] = {}
    provenance: dict[str, list[dict[str, Any]]] = {}
    training_ids: set[str] = set()
    hof_ids: set[str] = set()
    for checkpoint in projected_checkpoints:
        source = checkpoint["source"]
        for bot_id in checkpoint["training_opponents"]:
            training_ids.add(bot_id)
            genome = checkpoint["genomes"][bot_id]
            _register_genome(registry, provenance, genome, {
                "source_type": "checkpoint", "source": source, "pool": "training_opponents",
                "parents": list(genome["parents"]), "generation": genome["generation"],
            })
        for bot_id in checkpoint["hall_of_fame"]:
            hof_ids.add(bot_id)
            genome = checkpoint["genomes"][bot_id]
            _register_genome(registry, provenance, genome, {
                "source_type": "checkpoint", "source": source, "pool": "hall_of_fame",
                "parents": list(genome["parents"]), "generation": genome["generation"],
            })
    for genome in candidates:
        _register_genome(registry, provenance, genome, {
            "source_type": "candidate_file", "source": str(candidate_path),
            "parents": list(genome["parents"]), "generation": genome["generation"],
        })

    opponent_ids = sorted(training_ids | hof_ids)
    if len(opponent_ids) < 7:
        raise ValueError(f"training plus hall-of-fame union has {len(opponent_ids)} unique IDs; need at least 7")
    opponent_genomes = [registry[bot_id] for bot_id in opponent_ids]
    training_genomes = [registry[bot_id] for bot_id in sorted(training_ids)]
    hof_genomes = [registry[bot_id] for bot_id in sorted(hof_ids)]
    policy_ids: dict[str, str] = {}
    policy_ids_hash = None
    if policy_ids_path is not None:
        raw_policy_ids, policy_ids_bytes = _load_json(policy_ids_path)
        if not isinstance(raw_policy_ids, dict) or not raw_policy_ids:
            raise ValueError("policy IDs file must be a nonempty report-ID to original-policy-ID object")
        for report_id, policy_id in raw_policy_ids.items():
            if report_id not in registry:
                raise ValueError(f"policy IDs file references unknown report ID {report_id}")
            if not isinstance(policy_id, str) or not policy_id.strip():
                raise ValueError(f"original policy ID for {report_id} must be a nonempty string")
            policy_ids[report_id] = policy_id
        policy_ids_hash = _sha256(policy_ids_bytes)
    candidate_details = []
    for genome in candidates:
        candidate_details.append({**genome, "policy_bot_id": policy_ids.get(genome["bot_id"], genome["bot_id"]),
                                  "provenance": provenance[genome["bot_id"]]})

    return {
        "candidates": candidates,
        "candidate_details": candidate_details,
        "seeds": seeds,
        "seed_bytes": seed_bytes,
        "candidate_bytes": candidate_bytes,
        "checkpoint_projections": projected_checkpoints,
        "checkpoint_hashes": checkpoint_hashes,
        "config": config,
        "provenance": provenance,
        "opponent_ids": opponent_ids,
        "opponent_genomes": opponent_genomes,
        "training_ids": sorted(training_ids),
        "training_genomes": training_genomes,
        "hall_of_fame_ids": sorted(hof_ids),
        "hall_of_fame_genomes": hof_genomes,
        "opponent_pool_hashes": {
            "training_opponents_sha256": _sha256(_canonical_json(training_genomes).encode("utf-8")),
            "hall_of_fame_sha256": _sha256(_canonical_json(hof_genomes).encode("utf-8")),
            "complete_training_plus_hall_of_fame_sha256": _sha256(_canonical_json(opponent_genomes).encode("utf-8")),
        },
        "candidate_pool_sha256": _sha256(_canonical_json(candidates).encode("utf-8")),
        "seed_file_sha256": _sha256(seed_bytes),
        "candidate_file_sha256": _sha256(candidate_bytes),
        "policy_ids": policy_ids,
        "policy_ids_file_sha256": policy_ids_hash,
    }


def _paired_signature(job: Mapping[str, Any]) -> tuple[Any, ...]:
    seat = int(job["hero_seat"])
    opponents = tuple((index, bot_id) for index, bot_id in enumerate(job["seat_bot_ids"]) if index != seat)
    return int(job["seed"]), seat, opponents


def _build_ordered_jobs(inputs: Mapping[str, Any]) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    candidates = inputs["candidates"]
    opponent_genomes = [evolution._from_dict(raw) for raw in inputs["opponent_genomes"]]
    for candidate_index, candidate_raw in enumerate(candidates):
        candidate = evolution._from_dict(candidate_raw)
        for seed_index, seed in enumerate(inputs["seeds"]):
            job = evolution._build_tournament_job(
                candidate, opponent_genomes, seed, COMPARISON_KIND, dict(inputs["config"]),
            )
            job["candidate_index"] = candidate_index
            job["seed_index"] = seed_index
            # Report aliases disambiguate independent runs. The canonical
            # adapter constructs policies from these records, so restore each
            # original policy ID before execution to preserve its action salt.
            policy_ids = inputs.get("policy_ids", {})
            for raw_genome in job["genomes"]:
                raw_genome["bot_id"] = policy_ids.get(raw_genome["bot_id"], raw_genome["bot_id"])
            job["policy_bot_ids"] = [raw["bot_id"] for raw in job["genomes"]]
            jobs.append(job)

    reference: dict[int, tuple[Any, ...]] = {}
    for job in jobs:
        seed_index = int(job["seed_index"])
        signature = _paired_signature(job)
        if seed_index in reference and signature != reference[seed_index]:
            raise AssertionError("canonical job builder produced an unpaired seat/opponent plan")
        reference[seed_index] = signature
    return jobs


def _mean(values: Sequence[float | int]) -> float | None:
    return None if not values else math.fsum(float(value) for value in values) / len(values)


def _aggregate_candidate(candidate: Mapping[str, Any], evaluations: list[dict[str, Any]], provenance: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    aggregate = evolution._aggregate(str(candidate["bot_id"]), evaluations)
    row = {
        **{key: candidate[key] for key in ("bot_id", "family", "params", "parents", "generation")},
        "provenance": [dict(item) for item in provenance],
        "played": aggregate["played"],
        "won": aggregate["won"],
        "lost": aggregate["lost"],
        "cap_survivors": aggregate["capped"],
        "table_caps": sum(bool(item.get("table_capped")) for item in evaluations),
        "win_rate": aggregate["win_rate"],
        "wilson_95": aggregate["wilson_95"],
        "mean_points": aggregate["mean_points"],
        "mean_finish": aggregate["mean_finish"],
        "mean_final_stack": aggregate["mean_final_stack"],
        "invalid_actions": aggregate["invalid_actions"],
        "decisions": aggregate["decisions"],
        "invalid_rate": aggregate["invalid_rate"],
        "latency_mean_ms": aggregate["latency_mean_ms"],
        "latency_p95_ms": aggregate["latency_p95_ms"],
        "latency_p95_method": aggregate["latency_p95_method"],
        "latency_max_ms": aggregate["latency_max_ms"],
        "over_1ms": aggregate["over_1ms"],
        "runtime_mean_ms": aggregate["runtime_mean_ms"],
        "evaluations": evaluations,
        "status": COMPARISON_KIND,
    }
    if row["played"] != len(evaluations) or row["played"] == 0:
        raise ValueError(f"candidate {candidate['bot_id']} did not receive the full equal sample")
    return row


def _rank_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(rows, key=lambda row: (
        -(row["win_rate"] if row["win_rate"] is not None else 0.0),
        -(row["mean_points"] if row["mean_points"] is not None else 0.0),
        -(row["mean_final_stack"] if row["mean_final_stack"] is not None else 0.0),
        row["invalid_rate"],
        row["bot_id"],
    ))
    for rank, row in enumerate(ranked, start=1):
        row["rank"] = rank
    return ranked


def _percentile(sorted_values: Sequence[float], probability: float) -> float:
    if not sorted_values:
        raise ValueError("cannot compute a percentile from no observations")
    position = (len(sorted_values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(sorted_values[lower])
    fraction = position - lower
    return float(sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction)


def _bootstrap_interval(values: Sequence[float], bootstrap_seed: int, replicates: int = BOOTSTRAP_REPLICATES) -> dict[str, Any]:
    if not values:
        return {"n": 0, "mean": None, "interval_95": None, "replicates": replicates}
    rng = random.Random(bootstrap_seed)
    sample_size = len(values)
    means = [
        math.fsum(values[rng.randrange(sample_size)] for _ in range(sample_size)) / sample_size
        for _ in range(replicates)
    ]
    means.sort()
    return {
        "n": sample_size,
        "mean": _mean(values),
        "interval_95": [_percentile(means, 0.025), _percentile(means, 0.975)],
        "replicates": replicates,
        "method": "descriptive paired percentile bootstrap; no multiple-test adjustment",
    }


def _bootstrap_seed(namespace: str, candidate_id: str, reference_id: str, metric: str) -> int:
    material = "\0".join((namespace, candidate_id, reference_id, metric)).encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def _paired_comparisons(
    rows_by_id: Mapping[str, Mapping[str, Any]],
    reference_id: str,
    namespace: str,
    seed_order: Sequence[int],
) -> dict[str, Any]:
    if reference_id not in rows_by_id:
        raise ValueError(f"reference candidate ID not found: {reference_id}")
    reference = rows_by_id[reference_id]
    reference_by_seed = {int(row["seed"]): row for row in reference["evaluations"]}
    comparison_results: list[dict[str, Any]] = []
    for candidate_id in sorted(rows_by_id):
        candidate = rows_by_id[candidate_id]
        candidate_by_seed = {int(row["seed"]): row for row in candidate["evaluations"]}
        if set(candidate_by_seed) != set(reference_by_seed) or set(candidate_by_seed) != set(seed_order):
            raise ValueError("paired comparison requires identical seeds for every candidate")
        deltas: list[dict[str, Any]] = []
        metric_values: dict[str, list[float]] = {"win": [], "points": [], "finish": [], "final_stack": []}
        for seed in seed_order:
            candidate_match = candidate_by_seed[seed]
            reference_match = reference_by_seed[seed]
            win_delta = float(bool(candidate_match["won"])) - float(bool(reference_match["won"]))
            points_delta = float(candidate_match["points"]) - float(reference_match["points"])
            stack_delta = float(candidate_match["final_stack"]) - float(reference_match["final_stack"])
            c_finish = candidate_match.get("finish")
            r_finish = reference_match.get("finish")
            finish_delta = None if c_finish is None or r_finish is None else float(c_finish) - float(r_finish)
            metric_values["win"].append(win_delta)
            metric_values["points"].append(points_delta)
            metric_values["final_stack"].append(stack_delta)
            if finish_delta is not None:
                metric_values["finish"].append(finish_delta)
            deltas.append({
                "seed": seed,
                "candidate_won": bool(candidate_match["won"]),
                "reference_won": bool(reference_match["won"]),
                "win_delta": win_delta,
                "candidate_points": float(candidate_match["points"]),
                "reference_points": float(reference_match["points"]),
                "points_delta": points_delta,
                "candidate_finish": c_finish,
                "reference_finish": r_finish,
                "finish_delta": finish_delta,
                "candidate_final_stack": int(candidate_match["final_stack"]),
                "reference_final_stack": int(reference_match["final_stack"]),
                "final_stack_delta": stack_delta,
            })
        intervals = {
            metric: _bootstrap_interval(
                values, _bootstrap_seed(namespace, candidate_id, reference_id, metric),
            )
            for metric, values in metric_values.items()
        }
        comparison_results.append({
            "candidate_id": candidate_id,
            "reference_id": reference_id,
            "paired_per_seed_differences": deltas,
            "paired_bootstrap": intervals,
        })
    return {
        "reference_id": reference_id,
        "confidence": BOOTSTRAP_CONFIDENCE,
        "interpretation": "Descriptive paired intervals only; no multiple-test-adjusted superiority or target claim.",
        "comparisons": comparison_results,
    }


def _csv_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    from io import StringIO

    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        interval = row["wilson_95"] or [None, None]
        writer.writerow({
            "rank": row["rank"], "status": row["status"], "bot_id": row["bot_id"],
            "policy_bot_id": row["policy_bot_id"], "generation": row["generation"],
            "parents": _canonical_json(row["parents"]), "family": row["family"],
            "params": _canonical_json(row["params"]), "provenance": _canonical_json(row["provenance"]),
            "played": row["played"], "won": row["won"],
            "lost": row["lost"], "cap_survivors": row["cap_survivors"], "table_caps": row["table_caps"],
            "win_rate": row["win_rate"], "wilson_95_low": interval[0], "wilson_95_high": interval[1],
            "mean_points": row["mean_points"], "mean_finish": row["mean_finish"],
            "mean_final_stack": row["mean_final_stack"], "invalid_actions": row["invalid_actions"],
            "decisions": row["decisions"], "invalid_rate": row["invalid_rate"],
            "latency_mean_ms": row["latency_mean_ms"], "latency_p95_ms": row["latency_p95_ms"],
            "latency_max_ms": row["latency_max_ms"], "over_1ms": row["over_1ms"],
        })
    return stream.getvalue().encode("utf-8")


def _markdown_report(protocol: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], paired: Mapping[str, Any]) -> bytes:
    lines = [
        "# Evolution candidate comparison (training only)",
        "",
        "**Status: comparison_only.** This is an experimental equal-sample comparison, not a promotion gate, superiority claim, or target test.",
        "",
        f"- Namespace: `{protocol['namespace']}`",
        f"- Seeds: {protocol['sample_size']} supplied unchanged; SHA-256 `{protocol['inputs']['seed_file_sha256']}`",
        f"- Opponent pool: {protocol['opponent_pool']['unique_ids']} complete training + HOF IDs; SHA-256 `{protocol['opponent_pool']['hashes']['complete_training_plus_hall_of_fame_sha256']}`",
        f"- Reference for paired differences: `{paired['reference_id']}`",
        f"- Source fingerprint: `{protocol['source_fingerprint']['sha256']}`",
        "",
        "Every candidate receives the same seeded opponent IDs, seats, and deal stream. All matches use eight players, strict legal actions, and a 200-hand cap. Any capped table is a non-win even when the hero has the chip lead; win rate uses every played table as its denominator.",
        "",
        "| Rank | Candidate | Original policy ID | Generation | Family | Parents | Parameters | Played | Won | Lost | Cap survivors | Table caps | Win rate | Wilson 95% | Mean points | Mean finish | Mean chips | Invalid actions / decisions | Invalid rate | Latency mean / p95 / max ms | Status |",
        "|---:|---|---|---:|---|---|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---|---:|---|---|",
    ]
    for row in rows:
        interval = row["wilson_95"]
        interval_text = "—" if interval is None else f"{interval[0]:.4f}–{interval[1]:.4f}"
        lines.append(
            f"| {row['rank']} | `{row['bot_id']}` | `{row['policy_bot_id']}` | {row['generation']} | {row['family']} | "
            f"{', '.join(f'`{parent}`' for parent in row['parents']) or '—'} | `{_canonical_json(row['params'])}` | "
            f"{row['played']} | {row['won']} | {row['lost']} | {row['cap_survivors']} | {row['table_caps']} | "
            f"{row['win_rate']:.4f} | {interval_text} | "
            f"{row['mean_points']:.4f} | {row['mean_finish'] if row['mean_finish'] is not None else '—'} | "
            f"{row['mean_final_stack']:.2f} | {row['invalid_actions']} / {row['decisions']} | {row['invalid_rate']:.6f} | "
            f"{row['latency_mean_ms'] if row['latency_mean_ms'] is not None else '—'} / "
            f"{row['latency_p95_ms'] if row['latency_p95_ms'] is not None else '—'} / "
            f"{row['latency_max_ms'] if row['latency_max_ms'] is not None else '—'} | comparison_only |"
        )
    lines.extend([
        "",
        "## Paired differences",
        "",
        f"Intervals are descriptive paired percentile-bootstrap intervals ({BOOTSTRAP_REPLICATES} resamples, nominal 95%). No multiple-test adjustment or target claim is made. Candidate IDs affect deployed policy randomness, so paired effects do not isolate gene changes.",
        "",
        "| Candidate | Reference | Win-rate difference | 95% interval | Mean points difference | 95% interval |",
        "|---|---|---:|---|---:|---|",
    ])
    for comparison in paired["comparisons"]:
        intervals = comparison["paired_bootstrap"]
        win = intervals["win"]
        points = intervals["points"]
        win_ci = "—" if win["interval_95"] is None else f"{win['interval_95'][0]:.4f}–{win['interval_95'][1]:.4f}"
        points_ci = "—" if points["interval_95"] is None else f"{points['interval_95'][0]:.4f}–{points['interval_95'][1]:.4f}"
        lines.append(
            f"| `{comparison['candidate_id']}` | `{comparison['reference_id']}` | {win['mean']:.4f} | {win_ci} | "
            f"{points['mean']:.4f} | {points_ci} |"
        )
    lines.extend([
        "",
        "## Limits",
        "",
        "Equal-sample rankings remain noisy at finite sample sizes. Changing the training + HOF source pool changes the estimand. Candidate IDs also influence policy randomness, so this paired design does not isolate gene effects. These training-only results do not replace held-out evaluation; independent held-out evaluation is still required before any performance or promotion decision.",
        "",
    ])
    return "\n".join(lines).encode("utf-8")


def _source_fingerprint() -> dict[str, Any]:
    package_files = evolution._fingerprint_files()
    script_digest = _sha256(Path(__file__).read_bytes())
    dependencies = evolution._dependency_versions()
    fingerprint_payload = {
        "canonical_evolution_code_fingerprint": evolution._code_fingerprint(),
        "racer_script_sha256": script_digest,
        "pokerbot_files": package_files,
        "dependencies": dependencies,
        "python_version": sys.version.split()[0],
    }
    return {
        **fingerprint_payload,
        "sha256": _sha256(_canonical_json(fingerprint_payload).encode("utf-8")),
    }


def _protocol(inputs: Mapping[str, Any], namespace: str, reference_id: str | None, workers: int) -> dict[str, Any]:
    source = _source_fingerprint()
    candidates = inputs["candidate_details"]
    resolved_reference = reference_id or candidates[0]["bot_id"]
    if resolved_reference not in {candidate["bot_id"] for candidate in candidates}:
        raise ValueError(f"reference candidate ID not found: {resolved_reference}")
    return {
        "schema": SCHEMA,
        "status": "comparison_only",
        "purpose": "training-only equal-sample candidate comparison; not a promotion gate",
        "namespace": namespace,
        "seed_domain_note": "Fresh racer namespace supplied by the operator; seeds are used exactly as supplied and are not drawn from engine training/validation/confirmation counters.",
        "sample_size": len(inputs["seeds"]),
        "seeds": list(inputs["seeds"]),
        "simulation_config": dict(inputs["config"]),
        "workers": workers,
        "candidate_order": [candidate["bot_id"] for candidate in candidates],
        "candidates": candidates,
        "reference_candidate_id": resolved_reference,
        "inputs": {
            "candidate_file_sha256": inputs["candidate_file_sha256"],
            "candidate_pool_sha256": inputs["candidate_pool_sha256"],
            "seed_file_sha256": inputs["seed_file_sha256"],
            "checkpoint_projections": inputs["checkpoint_hashes"],
            "policy_ids_file_sha256": inputs["policy_ids_file_sha256"],
        },
        "policy_ids": dict(inputs["policy_ids"]),
        "policy_id_note": "Report aliases identify archived records; canonical policies use the recorded original policy IDs, preserving action sampling.",
        "opponent_pool": {
            "unique_ids": len(inputs["opponent_ids"]),
            "training_opponent_ids": inputs["training_ids"],
            "hall_of_fame_ids": inputs["hall_of_fame_ids"],
            "complete_union_ids": inputs["opponent_ids"],
            "genomes": [
                {**genome, "policy_bot_id": inputs["policy_ids"].get(genome["bot_id"], genome["bot_id"]),
                 "provenance": inputs["provenance"][genome["bot_id"]]}
                for genome in inputs["opponent_genomes"]
            ],
            "hashes": inputs["opponent_pool_hashes"],
        },
        "source_fingerprint": source,
        "statistics": {
            "win_rate_interval": "two-sided Wilson 95%; every played table including capped tables is in the denominator",
            "paired_bootstrap_replicates": BOOTSTRAP_REPLICATES,
            "paired_bootstrap_confidence": BOOTSTRAP_CONFIDENCE,
            "multiple_testing": "none; intervals are descriptive, with no superiority or target claim",
        },
        "interpretation_limits": [
            "Equal-sample rankings remain noisy.",
            "Changing the source opponent pool changes the estimand.",
            "Candidate IDs influence deployed policy randomness; paired effects do not isolate gene changes.",
            "Held-out evaluation remains required.",
        ],
    }


def run_comparison(
    candidate_path: str | Path,
    checkpoint_paths: Sequence[str | Path],
    seed_path: str | Path,
    output_dir: str | Path,
    *,
    namespace: str,
    workers: int = 1,
    reference_id: str | None = None,
    resume: bool = False,
    policy_ids_path: str | Path | None = None,
) -> dict[str, Any]:
    if resume:
        raise ValueError("resume is unsupported in racer v1; use a new output directory and a frozen protocol")
    _validate_namespace(namespace)
    if type(workers) is not int or workers < 1:
        raise ValueError("workers must be at least 1")
    if not checkpoint_paths:
        raise ValueError("at least one checkpoint input is required")
    run_dir = Path(output_dir).expanduser().resolve()
    if run_dir.exists():
        raise FileExistsError(f"run directory already exists: {run_dir}")

    inputs = _assemble_inputs(
        Path(candidate_path).expanduser().resolve(),
        [Path(path).expanduser().resolve() for path in checkpoint_paths],
        Path(seed_path).expanduser().resolve(),
        None if policy_ids_path is None else Path(policy_ids_path).expanduser().resolve(),
    )
    protocol = _protocol(inputs, namespace, reference_id, workers)
    jobs = _build_ordered_jobs(inputs)

    run_dir.parent.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(exist_ok=False)
    status_path = run_dir / "status.json"
    marker_path = run_dir / "COMPLETE.json"
    _write_json(status_path, {"status": "incomplete", "stage": "freezing_protocol_and_jobs"})
    try:
        protocol_bytes = _write_json(run_dir / "protocol.json", protocol)
        jobs_bytes = _write_json(run_dir / "jobs.json", {"schema": SCHEMA, "ordered_jobs": jobs})
        _atomic_write_bytes(run_dir / "seeds.json", inputs["seed_bytes"])
        _write_json(status_path, {"status": "incomplete", "stage": "simulation_not_started"})

        # The full protocol, exact input seed bytes, and complete ordered jobs
        # are on disk before the first call into the canonical evaluator.
        _write_json(status_path, {"status": "running", "stage": "canonical_evaluation"})
        evaluations = evolution._execute_jobs(jobs, workers)
        if _source_fingerprint() != protocol["source_fingerprint"]:
            raise RuntimeError("source or dependency fingerprint changed during evaluation")
        if len(evaluations) != len(jobs):
            raise RuntimeError(f"canonical evaluator returned {len(evaluations)} results for {len(jobs)} jobs")
        expected_order = [(job["hero_id"], int(job["seed"])) for job in jobs]
        expected_jobs = set(expected_order)
        observed_order = [(str(row["bot_id"]), int(row["seed"])) for row in evaluations]
        observed_jobs = set(observed_order)
        if observed_jobs != expected_jobs or len(observed_jobs) != len(evaluations):
            raise RuntimeError("canonical evaluator results do not match the frozen ordered jobs")
        result_by_job = {
            (str(row["bot_id"]), int(row["seed"])): row for row in evaluations
        }
        evaluations = [result_by_job[key] for key in expected_order]

        by_id: dict[str, list[dict[str, Any]]] = {candidate["bot_id"]: [] for candidate in inputs["candidates"]}
        for result in evaluations:
            by_id[result["bot_id"]].append(result)
        candidate_rows = [
            _aggregate_candidate(candidate, by_id[candidate["bot_id"]], inputs["provenance"][candidate["bot_id"]])
            for candidate in inputs["candidates"]
        ]
        for row in candidate_rows:
            row["policy_bot_id"] = inputs["policy_ids"].get(row["bot_id"], row["bot_id"])
        ranked_rows = _rank_rows(candidate_rows)
        rows_by_id = {row["bot_id"]: row for row in ranked_rows}
        paired = _paired_comparisons(
            rows_by_id, protocol["reference_candidate_id"], namespace, inputs["seeds"],
        )
        results_payload = {
            "schema": SCHEMA,
            "status": "comparison_only",
            "namespace": namespace,
            "protocol_sha256": _sha256(protocol_bytes),
            "jobs_sha256": _sha256(jobs_bytes),
            "candidate_results": ranked_rows,
        }
        results_bytes = _write_json(run_dir / "results.json", results_payload)
        paired_bytes = _write_json(run_dir / "paired-comparisons.json", paired)
        csv_bytes = _csv_bytes(ranked_rows)
        _atomic_write_bytes(run_dir / "results.csv", csv_bytes)
        markdown_bytes = _markdown_report(protocol, ranked_rows, paired)
        _atomic_write_bytes(run_dir / "report.md", markdown_bytes)

        _write_json(status_path, {"status": "complete", "stage": "reports_written", "result_count": len(evaluations)})
        _write_json(marker_path, {
            "status": "complete",
            "classification": COMPARISON_KIND,
            "protocol_sha256": _sha256(protocol_bytes),
            "jobs_sha256": _sha256(jobs_bytes),
            "results_sha256": _sha256(results_bytes),
            "paired_comparisons_sha256": _sha256(paired_bytes),
            "csv_sha256": _sha256(csv_bytes),
            "markdown_sha256": _sha256(markdown_bytes),
            "seed_file_sha256": inputs["seed_file_sha256"],
        })
        return {"protocol": protocol, "results": ranked_rows, "paired_comparisons": paired, "output_dir": run_dir}
    except BaseException as exc:
        try:
            _write_json(status_path, {
                "status": "incomplete",
                "stage": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
            })
        except BaseException:
            pass
        raise


def _positive_workers(value: str) -> int:
    try:
        result = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("workers must be an integer") from exc
    if result < 1:
        raise argparse.ArgumentTypeError("workers must be at least 1")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", required=True, help="JSON list of canonical Genome.to_dict candidate objects")
    parser.add_argument("--checkpoint", action="append", nargs="+", required=True,
                        help="checkpoint JSON input; repeat this option or pass several paths after it")
    parser.add_argument("--seeds", required=True, help="unchanged JSON list of fresh integer seeds")
    parser.add_argument("--namespace", required=True, help="fresh one-use namespace label beginning with racer-")
    parser.add_argument("--output-dir", required=True, help="new run directory; existing directories are refused")
    parser.add_argument("--workers", type=_positive_workers, default=1, help="canonical evaluator worker processes (default: 1)")
    parser.add_argument("--reference-id", help="candidate ID for paired differences (default: first candidate in input order)")
    parser.add_argument("--policy-ids", help="optional JSON mapping report aliases to original policy IDs; preserves ID-dependent action sampling across archived runs")
    parser.add_argument("--resume", action="store_true", help="unsupported in racer v1; always refused safely")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    checkpoint_paths = [Path(path) for group in args.checkpoint for path in group]
    try:
        run = run_comparison(
            args.candidates, checkpoint_paths, args.seeds, args.output_dir,
            namespace=args.namespace, workers=args.workers,
            reference_id=args.reference_id, resume=args.resume,
            policy_ids_path=args.policy_ids,
        )
    except Exception as exc:
        print(f"racer failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "status": "comparison_only",
        "candidate_count": len(run["results"]),
        "sample_size_per_candidate": run["protocol"]["sample_size"],
        "output_dir": str(run["output_dir"]),
        "complete_marker": str(run["output_dir"] / "COMPLETE.json"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
