"""Resumable, deterministic evolutionary tournament runner.

Each candidate is the sole hero in its own full-table tournament. Training,
validation, and final confirmation use separate seed streams and opponent
pools. A checkpoint reserves seeds before a tournament batch is launched, so
restarting an interrupted generation cannot accidentally reuse those seeds.

The Wilson intervals describe match-level outright wins conditional on the
stored opponent pool. Fresh-sample exact binomial confirmation uses an alpha-spending schedule
whose total one-sided error budget is at most 2.5% across all confirmation
attempts. This controls repeated checking across generations and candidates;
it does not remove the usual assumption that independently seeded matches are
Bernoulli trials under the configured simulator and opponent pool.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import html
from importlib.metadata import PackageNotFoundError, version
import json
import math
import os
import platform
import random
import sys
import tempfile
import time
from pathlib import Path
from statistics import NormalDist
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT_SCHEMA = "pokerbot-evolution-checkpoint-v1"
REPORT_SCHEMA = "pokerbot-evolution-round-v1"
TARGET_WIN_RATE = 0.95
CONFIRMATION_ALPHA_BUDGET = 0.025
VALIDATION_ALPHA_BUDGET = 0.025
DEFAULT_BIG_BLINDS = (20, 40, 80, 160, 320, 640, 1280, 2560)
DEFAULT_PAYOUTS: tuple[float, ...] | None = None
FIXED_RANDOM_OPPONENTS = 16
VALIDATION_LEADERS = 3


# These wrappers deliberately import the sibling APIs at call time. This lets
# reports and unit tests load before optional simulator dependencies are
# installed, while keeping the runtime contract explicit.
def play_tournament(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .tournament import play_tournament as implementation

    return implementation(*args, **kwargs)


def new_random(*args: Any, **kwargs: Any) -> Any:
    from .evolution_strategies import new_random as implementation

    return implementation(*args, **kwargs)


def breed(*args: Any, **kwargs: Any) -> Any:
    from .evolution_strategies import breed as implementation

    return implementation(*args, **kwargs)


def policy_for(*args: Any, **kwargs: Any) -> Any:
    from .evolution_strategies import policy_for as implementation

    return implementation(*args, **kwargs)


def anchor_genomes(*args: Any, **kwargs: Any) -> Any:
    from .evolution_strategies import anchor_genomes as implementation

    return implementation(*args, **kwargs)


def _genome_class() -> Any:
    from .evolution_strategies import Genome

    return Genome


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
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


def _write_json(path: Path, value: Any) -> None:
    _atomic_write(path, json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def _seed_value(master_seed: int, domain: str, counter: int) -> int:
    material = f"pokerbot-evolution-seed-v1\0{int(master_seed)}\0{domain}\0{int(counter)}".encode()
    # Keep seeds in the positive range accepted by common simulator RNGs.
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big") & ((1 << 63) - 1)


def _fingerprint_files() -> dict[str, str]:
    files: list[Path] = []
    package = ROOT / "pokerbot"
    if package.exists():
        files.extend(path for path in package.rglob("*.py") if "__pycache__" not in path.parts)
        files.extend(path for path in (package / "models").rglob("*") if path.is_file())
    # Public equity lookup is an input used by the frozen saved strategy.
    equity = ROOT / "data" / "preflop_equity.json"
    if equity.is_file():
        files.append(equity)
    result: dict[str, str] = {}
    for path in sorted(set(files)):
        name = path.relative_to(ROOT).as_posix()
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _code_fingerprint() -> str:
    payload = {"files": _fingerprint_files(), "python": platform.python_version(),
               "dependencies": _dependency_versions()}
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


def _dependency_versions() -> dict[str, str]:
    try:
        return {"pokerkit": version("pokerkit")}
    except PackageNotFoundError:
        return {"pokerkit": "not-installed"}


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _json_object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _archive_phenotype(genome: dict[str, Any]) -> str:
    # A bot ID salts some policy behavior. This comparison only decides whether
    # two source records need different archive aliases; policy IDs are mapped
    # back separately before a policy factory is called.
    return _canonical_json({"family": genome["family"], "params": genome["params"]})


def _effective_archive_phenotype(genome: dict[str, Any]) -> str:
    """Phenotype after family defaults, so sparse and explicit-default params match.

    Used only to decide archive aliasing. Resume integrity checks keep the
    stricter byte-level ``_archive_phenotype`` comparison.
    """
    from .evolution_strategies import _genes

    parsed = _from_dict(genome)
    return _canonical_json({"family": parsed.family, "params": _genes(parsed)})


def _archive_projection(raw: Any, source: str) -> dict[str, Any]:
    """Read only training/HOF membership and referenced genomes from a checkpoint."""
    if not isinstance(raw, dict):
        raise ValueError(f"archive checkpoint {source} must contain a JSON object")
    training_ids = raw.get("training_opponents")
    hof_ids = raw.get("hall_of_fame")
    registry = raw.get("genomes")
    for label, ids in (("training_opponents", training_ids), ("hall_of_fame", hof_ids)):
        if not isinstance(ids, list) or any(not isinstance(bot_id, str) or not bot_id.strip() for bot_id in ids):
            raise ValueError(f"archive checkpoint {source} {label} must be a list of nonempty IDs")
        if len(ids) != len(set(ids)):
            raise ValueError(f"archive checkpoint {source} {label} contains duplicate IDs")
    if not isinstance(registry, dict):
        raise ValueError(f"archive checkpoint {source} genomes must be an object")

    referenced = list(dict.fromkeys([*training_ids, *hof_ids]))
    genomes: dict[str, dict[str, Any]] = {}
    expected_fields = {"bot_id", "family", "params", "parents", "generation"}
    for bot_id in referenced:
        if bot_id not in registry:
            raise ValueError(f"archive checkpoint {source} references missing genome {bot_id}")
        raw_genome = registry[bot_id]
        if not isinstance(raw_genome, dict) or set(raw_genome) != expected_fields:
            raise ValueError(f"archive checkpoint {source} genome {bot_id} must use canonical Genome.to_dict fields")
        genome = _from_dict(raw_genome)
        canonical = _to_dict(genome)
        if _canonical_json(canonical) != _canonical_json(raw_genome) or _id(genome) != bot_id:
            raise ValueError(f"archive checkpoint {source} genome registry key does not match canonical genome {bot_id}")
        genomes[bot_id] = canonical
    return {
        "training_opponents": list(training_ids),
        "hall_of_fame": list(hof_ids),
        "genomes": genomes,
    }


def _archive_from_checkpoints(
    paths_raw: Any,
    policy_ids_path_raw: Any = None,
    reserved_phenotypes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Freeze a source-scoped, deduplicated union of training/HOF policies.

    Only membership and referenced Genome.to_dict records are projected from
    each checkpoint. Fitness, validation, confirmation, and history fields are
    never copied into the archive snapshot. ``reserved_phenotypes`` maps this
    run's fixed genome IDs to their phenotypes; an archived policy that reuses
    such an ID for a different policy gets a source-scoped alias, and its
    original ID is restored before the policy is constructed.
    """
    if paths_raw is None:
        paths_raw = []
    if not isinstance(paths_raw, (list, tuple)):
        raise ValueError("archive_checkpoints must be a list of checkpoint paths")
    if not paths_raw:
        if policy_ids_path_raw is not None:
            raise ValueError("archive_policy_ids_path requires at least one archive checkpoint")
        empty: dict[str, Any] = {
            "schema": "pokerbot-training-archive-v1",
            "sources": [],
            "training_opponents": [],
            "hall_of_fame": [],
            "genomes": {},
            "policy_ids": {},
            "provenance": {},
            "policy_ids_source": None,
        }
        return _seal_training_archive(empty)

    paths: list[Path] = []
    for raw_path in paths_raw:
        if not isinstance(raw_path, (str, os.PathLike)) or not str(raw_path).strip():
            raise ValueError("archive checkpoint paths must be nonempty paths")
        paths.append(Path(raw_path).expanduser().resolve())
    if len(set(paths)) != len(paths):
        raise ValueError("archive checkpoint paths must be unique")

    policy_ids: dict[str, str] = {}
    policy_ids_source: dict[str, Any] | None = None
    supplied_policy_ids: dict[str, str] = {}
    if policy_ids_path_raw is not None:
        if not isinstance(policy_ids_path_raw, (str, os.PathLike)) or not str(policy_ids_path_raw).strip():
            raise ValueError("archive_policy_ids_path must be a nonempty path")
        policy_path = Path(policy_ids_path_raw).expanduser().resolve()
        try:
            policy_bytes = policy_path.read_bytes()
            parsed_policy_ids = json.loads(policy_bytes, object_pairs_hook=_json_object_without_duplicates)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"could not read archive policy IDs from {policy_path}: {exc}") from exc
        if not isinstance(parsed_policy_ids, dict) or not parsed_policy_ids:
            raise ValueError("archive policy IDs must be a nonempty alias-to-original-ID object")
        for alias, original_id in parsed_policy_ids.items():
            if not isinstance(alias, str) or not alias.strip() or not isinstance(original_id, str) or not original_id.strip():
                raise ValueError("archive policy ID aliases and original IDs must be nonempty strings")
            supplied_policy_ids[alias] = original_id
        policy_ids_source = {"path": str(policy_path), "sha256": hashlib.sha256(policy_bytes).hexdigest()}

    projections: list[dict[str, Any]] = []
    sources: list[dict[str, str]] = []
    for path in paths:
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_json_object_without_duplicates)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"could not read archive checkpoint {path}: {exc}") from exc
        projection = _archive_projection(parsed, str(path))
        projections.append(projection)
        sources.append({"path": str(path), "projection_sha256": _sha256_json(projection)})

    phenotypes_by_id: dict[str, set[str]] = {}
    for projection in projections:
        for bot_id, genome in projection["genomes"].items():
            phenotypes_by_id.setdefault(bot_id, set()).add(_effective_archive_phenotype(genome))
    conflicts = {bot_id for bot_id, phenotypes in phenotypes_by_id.items() if len(phenotypes) > 1}
    # Earlier runs may reuse generated IDs (for example ``train-opponent-0000``)
    # for policies that differ from this run's fixed genomes of the same ID.
    # If every source agrees on that policy, it gets one shared alias so it is
    # not duplicated in the training pool.
    reserved_conflicts = set()
    for bot_id, phenotypes in phenotypes_by_id.items():
        reserved = (reserved_phenotypes or {}).get(bot_id)
        if reserved is not None and phenotypes != {reserved} and bot_id not in conflicts:
            reserved_conflicts.add(bot_id)

    # Build a stable per-source mapping. Conflicting IDs are namespaced by
    # source index; identical policies retain their original archive ID.
    source_aliases: list[dict[str, str]] = []
    for source_index, projection in enumerate(projections):
        aliases = {}
        for bot_id in projection["genomes"]:
            if bot_id in conflicts:
                aliases[bot_id] = f"{bot_id}@archive-{source_index}"
            elif bot_id in reserved_conflicts:
                aliases[bot_id] = f"{bot_id}@archive"
            else:
                aliases[bot_id] = bot_id
        source_aliases.append(aliases)

    registry: dict[str, dict[str, Any]] = {}
    archive_training_ids: list[str] = []
    archive_hof_ids: list[str] = []
    provenance: dict[str, list[dict[str, Any]]] = {}
    identity_origins: dict[str, str] = {}
    for source_index, projection in enumerate(projections):
        aliases = source_aliases[source_index]
        source = sources[source_index]
        source_path = source["path"]
        source_digest = source["projection_sha256"]
        for pool_name, pool_ids, union_ids in (
            ("training_opponents", projection["training_opponents"], archive_training_ids),
            ("hall_of_fame", projection["hall_of_fame"], archive_hof_ids),
        ):
            for source_bot_id in pool_ids:
                alias = aliases[source_bot_id]
                if alias not in union_ids:
                    union_ids.append(alias)
        for source_bot_id, source_genome in projection["genomes"].items():
            alias = aliases[source_bot_id]
            aliased = dict(source_genome)
            aliased["bot_id"] = alias
            aliased["parents"] = [aliases.get(parent, parent) for parent in source_genome["parents"]]
            current = registry.get(alias)
            if current is not None and _effective_archive_phenotype(current) != _effective_archive_phenotype(aliased):
                raise ValueError(f"conflicting archive policies remain under alias {alias}")
            if current is None:
                registry[alias] = aliased
            alias_identity = supplied_policy_ids.get(alias)
            source_identity = supplied_policy_ids.get(source_bot_id)
            if alias_identity is not None and source_identity is not None and alias_identity != source_identity:
                raise ValueError(f"conflicting original policy IDs supplied for archive alias {alias}")
            source_original_id = alias_identity or source_identity or source_bot_id
            previous_identity = identity_origins.get(alias)
            if previous_identity is not None and previous_identity != source_original_id:
                raise ValueError(f"conflicting original policy IDs supplied for archive alias {alias}")
            identity_origins[alias] = source_original_id
            record = {
                "source": source_path,
                "source_projection_sha256": source_digest,
                "source_bot_id": source_bot_id,
                "source_genome": source_genome,
                "source_pools": [pool for pool, ids in (
                    ("training_opponents", projection["training_opponents"]),
                    ("hall_of_fame", projection["hall_of_fame"]),
                ) if source_bot_id in ids],
            }
            provenance.setdefault(alias, []).append(record)

    known_ids = set(registry) | {bot_id for projection in projections for bot_id in projection["genomes"]}
    unknown_map_keys = set(supplied_policy_ids) - known_ids
    if unknown_map_keys:
        raise ValueError(f"archive policy IDs reference unknown aliases: {', '.join(sorted(unknown_map_keys))}")
    policy_ids.update(identity_origins)
    archive = {
        "schema": "pokerbot-training-archive-v1",
        "sources": sources,
        "training_opponents": archive_training_ids,
        "hall_of_fame": archive_hof_ids,
        "genomes": registry,
        "policy_ids": policy_ids,
        "provenance": provenance,
        "policy_ids_source": policy_ids_source,
    }
    return _seal_training_archive(archive)


def _seal_training_archive(archive: dict[str, Any]) -> dict[str, Any]:
    result = dict(archive)
    result["provenance_sha256"] = _sha256_json(result["provenance"])
    result["content_sha256"] = _sha256_json({
        key: value for key, value in result.items() if key not in {"content_sha256", "provenance_sha256", "fingerprint"}
    })
    result["fingerprint"] = _sha256_json({
        "content_sha256": result["content_sha256"],
        "provenance_sha256": result["provenance_sha256"],
        "sources": result["sources"],
        "policy_ids_source": result["policy_ids_source"],
    })
    return result


def _verify_training_archive(archive: dict[str, Any]) -> bool:
    try:
        return _seal_training_archive({
            key: value for key, value in archive.items()
            if key not in {"content_sha256", "provenance_sha256", "fingerprint"}
        }) == archive
    except (KeyError, TypeError, ValueError):
        return False


def _validate_config(raw: dict[str, Any]) -> dict[str, Any]:
    evaluation_namespace = raw.get("evaluation_namespace", "")
    if not isinstance(evaluation_namespace, str) or len(evaluation_namespace) > 128:
        raise ValueError("evaluation_namespace must be a string of at most 128 characters")
    adaptive_fraction_raw = raw.get("adaptive_fraction", 0.0)
    if isinstance(adaptive_fraction_raw, bool) or not isinstance(adaptive_fraction_raw, (int, float)):
        raise ValueError("adaptive_fraction must be a finite number between 0 and 1")
    adaptive_fraction = float(adaptive_fraction_raw)
    if not math.isfinite(adaptive_fraction) or not 0.0 <= adaptive_fraction <= 1.0:
        raise ValueError("adaptive_fraction must be a finite number between 0 and 1")

    seed_genomes_path_raw = raw.get("seed_genomes_path")
    seed_genomes_path: str | None = None
    seed_genomes_raw = raw.get("seed_genomes")
    if seed_genomes_path_raw is not None:
        if not isinstance(seed_genomes_path_raw, (str, os.PathLike)) or not str(seed_genomes_path_raw).strip():
            raise ValueError("seed_genomes_path must be a nonempty path")
        seed_genomes_path = str(Path(seed_genomes_path_raw).expanduser().resolve())
        try:
            path_genomes = json.loads(Path(seed_genomes_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"could not read seed genomes from {seed_genomes_path}: {exc}") from exc
        path_snapshot = _validate_seed_genomes(path_genomes)
        if seed_genomes_raw is not None:
            supplied_snapshot = _validate_seed_genomes(seed_genomes_raw)
            if _canonical_json(path_snapshot) != _canonical_json(supplied_snapshot):
                raise ValueError("seed genome file content differs from the supplied seed genome snapshot")
        seed_genomes = path_snapshot
    else:
        seed_genomes = _validate_seed_genomes([] if seed_genomes_raw is None else seed_genomes_raw)

    target_raw = raw.get("target_win_rate", TARGET_WIN_RATE)
    if isinstance(target_raw, bool) or not isinstance(target_raw, (int, float)):
        raise ValueError("target_win_rate must be a finite probability strictly between 0 and 1")
    target_win_rate = float(target_raw)
    if not math.isfinite(target_win_rate) or not 0.0 < target_win_rate < 1.0:
        raise ValueError("target_win_rate must be a finite probability strictly between 0 and 1")
    archive = _archive_from_checkpoints(
        raw.get("archive_checkpoints", []),
        raw.get("archive_policy_ids_path"),
        _fixed_genome_phenotypes(
            int(raw.get("seed", 20261102)),
            int(raw.get("fixed_random_opponents", FIXED_RANDOM_OPPONENTS)),
            int(raw.get("players", 8)),
        ) if raw.get("archive_checkpoints") else None,
    )

    config = {
        "players": int(raw.get("players", 8)),
        "population": int(raw.get("population", 8)),
        "matches": int(raw.get("matches", 8)),
        "validation_matches": int(raw.get("validation_matches", 32)),
        "confirmation_matches": int(raw.get("confirmation_matches", 128)),
        "seed": int(raw.get("seed", 20261102)),
        "stacks": int(raw.get("stacks", 2000)),
        "big_blinds": [int(value) for value in raw.get("big_blinds", DEFAULT_BIG_BLINDS)],
        "hands_per_level": int(raw.get("hands_per_level", 25)),
        "max_hands": int(raw.get("max_hands", 200)),
        "payouts": None if raw.get("payouts") is None else [float(value) for value in raw["payouts"]],
        "strict": bool(raw.get("strict", True)),
        "validation_leaders": int(raw.get("validation_leaders", VALIDATION_LEADERS)),
        "fixed_random_opponents": int(raw.get("fixed_random_opponents", FIXED_RANDOM_OPPONENTS)),
        "target_win_rate": target_win_rate,
        "adaptive_fraction": adaptive_fraction,
        "evaluation_namespace": evaluation_namespace,
        # Store the canonical genome content with the checkpoint. The path is
        # retained as provenance and is reread on resume, so edits cannot be
        # accepted silently.
        "seed_genomes_path": seed_genomes_path,
        "seed_genomes": seed_genomes,
        # The complete projected training/HOF archive is frozen into config;
        # source files are reread and reprojected on resume.
        "archive_checkpoints": [source["path"] for source in archive["sources"]],
        "archive_policy_ids_path": None if archive["policy_ids_source"] is None else archive["policy_ids_source"]["path"],
        "training_archive": archive,
    }
    if not 2 <= config["players"] <= 8:
        raise ValueError("players must be between 2 and 8 (the default is a full 8-player table)")
    if config["population"] < 5 + len(config["seed_genomes"]):
        raise ValueError("population must fit the five fixed anchors and all imported seed genomes")
    for key in ("matches", "validation_matches", "confirmation_matches", "stacks", "hands_per_level", "max_hands"):
        if config[key] <= 0:
            raise ValueError(f"{key} must be positive")
    if config["seed"] < 0:
        raise ValueError("seed must be non-negative")
    if not config["big_blinds"] or any(value <= 0 for value in config["big_blinds"]):
        raise ValueError("big_blinds must contain positive values")
    if config["validation_leaders"] <= 0:
        raise ValueError("validation_leaders must be positive")
    if config["fixed_random_opponents"] < config["players"] - 1:
        raise ValueError("fixed_random_opponents must be at least players - 1")
    if config["archive_checkpoints"] and not archive["training_opponents"] and not archive["hall_of_fame"]:
        raise ValueError("archive checkpoints must contain at least one training or hall-of-fame genome")
    return config


def _fixed_genome_phenotypes(seed: int, fixed_random_opponents: int, players: int) -> dict[str, str]:
    """Return phenotypes of the fixed anchors and generated pools for one run."""
    anchors = _deduplicated_genomes(anchor_genomes())
    training_count = max(fixed_random_opponents, players - 1, 0)
    fixed = anchors + _make_random_genomes(seed, "training-opponents", training_count, "train-opponent")
    fixed += _make_random_genomes(seed, "validation-pool", max(fixed_random_opponents, 0), "validation-opponent")
    fixed += _make_random_genomes(seed, "confirmation-pool", max(fixed_random_opponents, 0), "confirmation-opponent")
    return {_id(genome): _effective_archive_phenotype(_to_dict(genome)) for genome in fixed}


def _validate_seed_genomes(raw_genomes: Any) -> list[dict[str, Any]]:
    """Validate and copy a canonical list of imported Genome.to_dict objects."""
    if not isinstance(raw_genomes, list):
        raise ValueError("seed genomes must be a JSON list")
    snapshots: list[dict[str, Any]] = []
    seen: set[str] = set()
    anchor_ids = {_id(genome) for genome in _deduplicated_genomes(anchor_genomes())}
    expected_fields = {"bot_id", "family", "params", "parents", "generation"}
    for index, raw in enumerate(raw_genomes):
        if not isinstance(raw, dict):
            raise ValueError(f"seed genome at index {index} must be an object")
        if set(raw) != expected_fields:
            raise ValueError(f"seed genome at index {index} must use the canonical Genome.to_dict fields")
        genome = _from_dict(raw)
        snapshot = _to_dict(genome)
        if _canonical_json(snapshot) != _canonical_json(raw):
            raise ValueError(f"seed genome at index {index} is not a canonical Genome.to_dict object")
        bot_id = _id(genome)
        if bot_id in seen:
            raise ValueError(f"duplicate seed genome id: {bot_id}")
        if bot_id in anchor_ids:
            raise ValueError(f"seed genome id conflicts with fixed anchor: {bot_id}")
        seen.add(bot_id)
        snapshots.append(snapshot)
    return snapshots


def wilson_interval(wins: int, trials: int, confidence: float = 0.95) -> list[float] | None:
    """Two-sided Wilson score interval, inclusive of capped/non-win trials."""
    if trials <= 0:
        return None
    if not 0 <= wins <= trials:
        raise ValueError("wins must be between zero and trials")
    z = NormalDist().inv_cdf(0.5 + confidence / 2)
    p = wins / trials
    z2 = z * z
    denom = 1 + z2 / trials
    center = (p + z2 / (2 * trials)) / denom
    margin = z * math.sqrt((p * (1 - p) / trials) + (z2 / (4 * trials * trials))) / denom
    return [max(0.0, center - margin), min(1.0, center + margin)]


def wilson_lower_bound(wins: int, trials: int, alpha: float) -> float | None:
    """One-sided Wilson lower score bound at the supplied one-sided alpha."""
    if trials <= 0:
        return None
    if not 0 <= wins <= trials:
        raise ValueError("wins must be between zero and trials")
    if not 0.0 < alpha < 0.5:
        raise ValueError("alpha must be between 0 and 0.5")
    z = NormalDist().inv_cdf(1.0 - alpha)
    p = wins / trials
    z2 = z * z
    denom = 1.0 + z2 / trials
    center = p + z2 / (2.0 * trials)
    margin = z * math.sqrt((p * (1.0 - p) / trials) + z2 / (4.0 * trials * trials))
    return max(0.0, (center - margin) / denom)


def minimum_all_successes_for_bound(target: float, alpha: float) -> int:
    """Smallest all-win sample whose one-sided Wilson lower bound exceeds target."""
    if not 0.0 < target < 1.0 or not 0.0 < alpha < 0.5:
        raise ValueError("target and alpha must be probabilities")
    z = NormalDist().inv_cdf(1.0 - alpha)
    n = max(1, math.floor((target * z * z) / (1.0 - target)) + 1)
    while wilson_lower_bound(n, n, alpha) <= target:
        n += 1
    while n > 1 and wilson_lower_bound(n - 1, n - 1, alpha) > target:
        n -= 1
    return n


def exact_lower_bound(wins: int, trials: int, alpha: float) -> float | None:
    """One-sided Clopper–Pearson bound, inverted from the binomial upper tail."""
    if type(wins) is not int or type(trials) is not int or not 0 <= wins <= trials:
        raise ValueError("wins and trials must be integers with 0 <= wins <= trials")
    if not 0 < alpha < 0.5:
        raise ValueError("alpha must be between zero and 0.5")
    if trials == 0:
        return None
    if wins == 0:
        return 0.0
    if wins == trials:
        return math.exp(math.log(alpha) / trials)
    coefficients = [math.lgamma(trials + 1) - math.lgamma(k + 1)
                    - math.lgamma(trials - k + 1) for k in range(wins, trials + 1)]

    def log_tail(probability: float) -> float:
        terms = [coefficient + k * math.log(probability)
                 + (trials - k) * math.log1p(-probability)
                 for k, coefficient in zip(range(wins, trials + 1), coefficients)]
        largest = max(terms)
        return largest + math.log(math.fsum(math.exp(term - largest) for term in terms))

    low, high = 0.0, wins / trials
    for _ in range(64):
        midpoint = (low + high) / 2
        if log_tail(midpoint) < math.log(alpha):
            low = midpoint
        else:
            high = midpoint
    return low


def minimum_all_successes_for_exact_bound(target: float, alpha: float) -> int:
    """Smallest fresh all-win sample whose exact lower bound exceeds target."""
    if not math.isfinite(target) or not 0.0 < target < 1.0 or not math.isfinite(alpha) or not 0.0 < alpha < 0.5:
        raise ValueError("target and alpha must be finite probabilities")
    return math.floor(math.log(alpha) / math.log(target)) + 1


def _one_sided_alpha(budget: float, attempt_index: int) -> float:
    # Telescoping spending sums to budget, without geometric underflow during
    # long searches. Each confirmation tests only its new independent sample.
    return budget / ((attempt_index + 1) * (attempt_index + 2))


def _to_dict(genome: Any) -> dict[str, Any]:
    return genome.to_dict()


def _from_dict(raw: dict[str, Any]) -> Any:
    return _genome_class().from_dict(raw)


def _id(genome: Any) -> str:
    return str(genome.bot_id)


def _protected_anchor(genomes: list[Any]) -> Any:
    for genome in genomes:
        identity = (str(getattr(genome, "bot_id", "")) + " " + str(getattr(genome, "family", ""))).lower().replace("-", "_")
        if "saved" in identity and ("baseline" in identity or "bot" in identity or "saved" == getattr(genome, "family", "")):
            return genome
    for genome in genomes:
        identity = (str(getattr(genome, "bot_id", "")) + " " + str(getattr(genome, "family", ""))).lower()
        if "saved" in identity:
            return genome
    raise ValueError("anchor_genomes() must include the immutable saved baseline")


def _make_random_genomes(master_seed: int, domain: str, count: int, prefix: str, generation: int = 0) -> list[Any]:
    result = []
    for index in range(count):
        rng = random.Random(_seed_value(master_seed, domain, index))
        result.append(new_random(rng, f"{prefix}-{index:04d}", generation=generation))
    return result


def _available_genome_id(prefix: str, index: int, reserved_ids: set[str]) -> str:
    base = f"{prefix}-{index:04d}"
    candidate = base
    collision = 1
    while candidate in reserved_ids:
        candidate = f"{base}-{collision}"
        collision += 1
    reserved_ids.add(candidate)
    return candidate


def _make_initial_active_random_genomes(
    master_seed: int,
    count: int,
    prefix: str,
    reserved_ids: set[str],
    adaptive_fraction: float,
) -> list[Any]:
    result = []
    adaptive_count = int(math.floor(adaptive_fraction * count + 0.5))
    adaptive_rng = random.Random(_seed_value(master_seed, "initial-active-family", 0))
    adaptive_indices = set(adaptive_rng.sample(range(count), adaptive_count))
    for index in range(count):
        bot_id = _available_genome_id(prefix, index, reserved_ids)
        rng = random.Random(_seed_value(master_seed, "initial-active", index))
        genome = new_random(rng, bot_id, generation=0)
        # Family choice has an independent seed domain so changing this V3
        # option cannot change the sampled genes or any fixed opponent pool.
        if index in adaptive_indices:
            raw = _to_dict(genome)
            raw["family"] = "adaptive"
            genome = _genome_class().from_dict(raw)
        result.append(genome)
    return result


def _deduplicated_genomes(genomes: Iterable[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for genome in genomes:
        bot_id = _id(genome)
        if bot_id not in seen:
            result.append(genome)
            seen.add(bot_id)
    return result


def _init_checkpoint(config: dict[str, Any], code_fingerprint: str) -> dict[str, Any]:
    anchors = _deduplicated_genomes(anchor_genomes())
    if len(anchors) < 5:
        raise ValueError("anchor_genomes() must provide the saved, fast, calling-station, tight, and random anchors")
    protected = _protected_anchor(anchors)
    seed_genomes = [_from_dict(raw) for raw in config["seed_genomes"]]
    archive = config["training_archive"]
    archive_genomes = [_from_dict(archive["genomes"][bot_id]) for bot_id in archive["genomes"]]
    if len(anchors) + len(seed_genomes) > config["population"]:
        raise ValueError(
            f"population={config['population']} cannot hold all {len(anchors)} fixed anchors "
            f"and {len(seed_genomes)} imported seed genomes"
        )
    training_random_count = max(config["fixed_random_opponents"], config["players"] - 1)
    training_opponents = anchors + _make_random_genomes(
        config["seed"], "training-opponents", training_random_count, "train-opponent", generation=0
    )
    archive_by_id = {_id(genome): genome for genome in archive_genomes}
    fixed_genomes = anchors + training_opponents[len(anchors):]
    fixed_genomes += _make_random_genomes(
        config["seed"], "validation-pool", config["fixed_random_opponents"], "validation-opponent", generation=0
    )
    fixed_genomes += _make_random_genomes(
        config["seed"], "confirmation-pool", config["fixed_random_opponents"], "confirmation-opponent", generation=0
    )
    fixed_by_id = {_id(genome): genome for genome in fixed_genomes}
    for bot_id, genome in archive_by_id.items():
        existing = fixed_by_id.get(bot_id)
        if existing is not None and _archive_phenotype(_to_dict(existing)) != _archive_phenotype(_to_dict(genome)):
            raise ValueError(f"archive genome ID conflicts with a fixed genome: {bot_id}")
    training_opponents = _deduplicated_genomes(
        training_opponents + [archive_by_id[bot_id] for bot_id in archive["training_opponents"]]
    )
    validation_population = anchors + _make_random_genomes(
        config["seed"], "validation-pool", config["fixed_random_opponents"], "validation-opponent", generation=0
    )
    confirmation_population = anchors + _make_random_genomes(
        config["seed"], "confirmation-pool", config["fixed_random_opponents"], "confirmation-opponent", generation=0
    )

    fixed_registry_ids = {
        _id(genome) for genome in anchors + training_opponents + validation_population + confirmation_population
    }
    for genome in seed_genomes:
        if _id(genome) in fixed_registry_ids or _id(genome) in archive_by_id:
            raise ValueError(f"seed genome id conflicts with a fixed or archived genome: {_id(genome)}")

    active = list(anchors) + seed_genomes
    reserved_ids = fixed_registry_ids | {_id(genome) for genome in seed_genomes} | set(archive_by_id)
    fresh_prefix = "evo-fresh" if seed_genomes or config["adaptive_fraction"] > 0.0 else "evo-initial"
    active.extend(_make_initial_active_random_genomes(
        config["seed"], config["population"] - len(active), fresh_prefix, reserved_ids,
        config["adaptive_fraction"],
    ))
    all_genomes = _deduplicated_genomes(
        active + training_opponents + validation_population + confirmation_population + archive_genomes
    )
    return {
        "schema": CHECKPOINT_SCHEMA,
        "created_at_utc": _utc_now(),
        "updated_at_utc": _utc_now(),
        "python_version": platform.python_version(),
        "dependency_versions": _dependency_versions(),
        "source_file_sha256": _fingerprint_files(),
        "code_fingerprint": code_fingerprint,
        "config": config,
        "completed_generations": 0,
        "status": "running",
        "protected_bot_id": _id(protected),
        "active_population": [_id(genome) for genome in active],
        "genomes": {_id(genome): _to_dict(genome) for genome in all_genomes},
        "lineage": {_id(genome): {
            "bot_id": _id(genome), "family": str(genome.family), "parents": list(genome.parents),
            "generation": int(genome.generation), "params": dict(genome.params),
        } for genome in all_genomes},
        "training_opponents": [_id(genome) for genome in training_opponents],
        "validation_population": [_id(genome) for genome in validation_population],
        "confirmation_population": [_id(genome) for genome in confirmation_population],
        "fixed_pool_fingerprints": {
            "training": hashlib.sha256(_canonical_json([_to_dict(g) for g in training_opponents]).encode()).hexdigest(),
            "validation": hashlib.sha256(_canonical_json([_to_dict(g) for g in validation_population]).encode()).hexdigest(),
            "confirmation": hashlib.sha256(_canonical_json([_to_dict(g) for g in confirmation_population]).encode()).hexdigest(),
        },
        # Imported policies remain available as training opponents even when
        # eliminated from the active population.
        "hall_of_fame": list(dict.fromkeys(
            [_id(genome) for genome in anchors + seed_genomes] + list(archive["hall_of_fame"])
        )),
        "training_archive_fingerprint": archive["fingerprint"],
        "training_archive_fingerprints": {
            "fingerprint": archive["fingerprint"],
            "content_sha256": archive["content_sha256"],
            "provenance_sha256": archive["provenance_sha256"],
            "sources": archive["sources"],
            "policy_ids_source": archive["policy_ids_source"],
        },
        "archive_provenance": archive["provenance"],
        "archive_policy_ids": archive["policy_ids"],
        "hall_of_fame_fitness": {},
        "seed_stream": {
            "algorithm": "sha256-counter-v1",
            "master_seed": config["seed"],
            "evaluation_namespace": config["evaluation_namespace"],
            "domains": ["training", "validation", "confirmation"],
            "counters": {"training": 0, "validation": 0, "confirmation": 0},
            "reserved_evaluations": [],
        },
        "validation_attempts": 0,
        "confirmation_attempts": 0,
        "confirmation_results": {},
        "history": [],
        "inflight": None,
        "champion": None,
        "provisional_champion": _id(protected),
    }


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _player_for_seat(result: dict[str, Any], seat: int) -> dict[str, Any]:
    for player in result.get("players", []):
        if int(player.get("index", -1)) == seat:
            return player
    players = result.get("players", [])
    if seat < len(players):
        return players[seat]
    return {}


def _float_or_none(value: Any) -> float | None:
    return None if value is None else float(value)


def _run_tournament_job(job: dict[str, Any]) -> dict[str, Any]:
    # Policies mix using their public observation seed. Never seed a shared
    # policy-accessible RNG with the private deal seed.
    policy_ids = job.get("policy_ids", {})
    genomes = []
    for raw in job["genomes"]:
        deployed = dict(raw)
        deployed["bot_id"] = policy_ids.get(deployed["bot_id"], deployed["bot_id"])
        genomes.append(_from_dict(deployed))
    policies = [policy_for(genome) for genome in genomes]
    config = job["config"]
    started = time.perf_counter()
    result = play_tournament(
        policies,
        seed=int(job["seed"]),
        stacks=config["stacks"],
        big_blinds=tuple(config["big_blinds"]),
        hands_per_level=config["hands_per_level"],
        max_hands=config["max_hands"],
        payouts=None if config["payouts"] is None else tuple(config["payouts"]),
        strict=config["strict"],
        trace=False,
    )
    runtime_ms = (time.perf_counter() - started) * 1000.0
    hero_seat = int(job["hero_seat"])
    hero = _player_for_seat(result, hero_seat)
    capped = bool(result.get("capped", False))
    winner = result.get("winner")
    won = winner is not None and int(winner) == hero_seat and not capped
    final_stacks = result.get("final_stacks", [])
    fallback_stack = final_stacks[hero_seat] if hero_seat < len(final_stacks) else 0
    final_stack = int(hero.get("final_stack", fallback_stack))
    return {
        "bot_id": job["hero_id"],
        "kind": job["kind"],
        "seed": int(job["seed"]),
        "hero_seat": hero_seat,
        "seat_bot_ids": list(job["seat_bot_ids"]),
        "winner_seat": winner,
        "table_capped": capped,
        "capped": bool(capped and final_stack > 0),
        "hands_played": int(result.get("hands_played", 0)),
        "won": bool(won),
        "lost": bool(not won and final_stack <= 0),
        "final_stack": final_stack,
        "points": float(hero.get("points", 0.0) or 0.0),
        "finish": _float_or_none(hero.get("finish")),
        "invalid_actions": int(hero.get("invalid_actions", 0) or 0),
        "decisions": int(hero.get("decisions", 0) or 0),
        "latency_mean_ms": _float_or_none(hero.get("latency_mean_ms")),
        "latency_p95_ms": _float_or_none(hero.get("latency_p95_ms")),
        "latency_max_ms": _float_or_none(hero.get("latency_max_ms")),
        "over_1ms": int(hero.get("over_1ms", 0) or 0),
        "runtime_ms": runtime_ms,
    }


def _execute_jobs(jobs: list[dict[str, Any]], workers: int) -> list[dict[str, Any]]:
    if workers <= 1:
        return [_run_tournament_job(job) for job in jobs]
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(_run_tournament_job, jobs, chunksize=1))


def _aggregate(bot_id: str, evaluations: list[dict[str, Any]], alpha: float | None = None) -> dict[str, Any]:
    count = len(evaluations)
    wins = sum(bool(row["won"]) for row in evaluations)
    capped = sum(bool(row["capped"]) for row in evaluations)
    lost = sum(bool(row["lost"]) for row in evaluations)
    points = [float(row["points"]) for row in evaluations]
    stacks = [int(row["final_stack"]) for row in evaluations]
    finishes = [float(row["finish"]) for row in evaluations if row.get("finish") is not None]
    invalid = sum(int(row["invalid_actions"]) for row in evaluations)
    decisions = sum(int(row["decisions"]) for row in evaluations)

    def mean(items: list[float] | list[int]) -> float | None:
        return None if not items else sum(items) / len(items)

    latency_rows = [row for row in evaluations if row.get("latency_mean_ms") is not None]
    timed_decisions = sum(row["decisions"] for row in latency_rows)
    lat_mean = (sum(float(row["latency_mean_ms"]) * row["decisions"] for row in latency_rows)
                / timed_decisions if timed_decisions else None)
    lat_p95 = max((float(row["latency_p95_ms"]) for row in latency_rows
                   if row.get("latency_p95_ms") is not None), default=None)
    lat_max = max((float(row["latency_max_ms"]) for row in evaluations if row.get("latency_max_ms") is not None), default=None)
    rate = wins / count if count else None
    score = {
        "mean_points": mean(points),
        "win_rate": rate,
        "mean_final_stack": mean(stacks),
        "mean_finish": mean(finishes),
        "invalid_actions": invalid,
        "decisions": decisions,
        "invalid_rate": invalid / decisions if decisions else 0.0,
    }
    return {
        "bot_id": bot_id,
        "played": count,
        "won": wins,
        "lost": lost,
        "capped": capped,
        "win_rate": rate,
        "wilson_95": wilson_interval(wins, count),
        "wilson_lower_bound": wilson_lower_bound(wins, count, alpha) if alpha is not None and count else None,
        "exact_lower_bound": exact_lower_bound(wins, count, alpha) if alpha is not None and count else None,
        "alpha": alpha,
        "mean_points": score["mean_points"],
        "mean_finish": score["mean_finish"],
        "mean_final_stack": score["mean_final_stack"],
        "invalid_actions": invalid,
        "decisions": decisions,
        "invalid_rate": score["invalid_rate"],
        "latency_mean_ms": lat_mean,
        "latency_p95_ms": lat_p95,
        "latency_p95_method": "maximum per-match policy-call p95, not pooled p95",
        "latency_max_ms": lat_max,
        "over_1ms": sum(int(row["over_1ms"]) for row in evaluations),
        "runtime_mean_ms": mean([float(row["runtime_ms"]) for row in evaluations]),
        "fitness": score,
        "evaluations": evaluations,
    }


def _rank_key(row: dict[str, Any]) -> tuple[float, float, float, float, str]:
    fitness = row["fitness"]
    return (
        float(fitness.get("win_rate") or 0.0),
        float(fitness.get("mean_points") or 0.0),
        float(fitness.get("mean_final_stack") or 0.0),
        -float(fitness.get("invalid_rate") or 0.0),
        str(row["bot_id"]),
    )


def _rank(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Stable bot-id ordering resolves exact ties and never depends on dict order.
    return sorted(rows, key=lambda row: (
        -_rank_key(row)[0], -_rank_key(row)[1], -_rank_key(row)[2], -_rank_key(row)[3], row["bot_id"]
    ))


def _opponent_pool(state: dict[str, Any], kind: str) -> list[Any]:
    if kind == "training":
        ids = list(state["training_opponents"])
        ids.extend(state["hall_of_fame"])
    elif kind == "validation":
        ids = list(state["validation_population"])
    elif kind == "confirmation":
        ids = list(state["confirmation_population"])
    else:
        raise ValueError(f"unknown evaluation kind: {kind}")
    return _deduplicated_genomes(_from_dict(state["genomes"][bot_id]) for bot_id in ids)


def _build_tournament_job(candidate: Any, opponents: list[Any], seed: int, kind: str, config: dict[str, Any]) -> dict[str, Any]:
    rng = random.Random(seed)
    # Fixed opponents remain eligible for every hero, including a copy of the
    # same strategy. Removing the hero would give fixed anchors easier pools.
    eligible = list(opponents)
    needed = config["players"] - 1
    if len(eligible) < needed:
        raise ValueError(f"{kind} opponent pool has {len(eligible)} unique bots; need {needed}")
    selected = rng.sample(eligible, needed)
    roles = [(True, candidate), *((False, genome) for genome in selected)]
    rng.shuffle(roles)
    hero_seat = next(index for index, (is_hero, _) in enumerate(roles) if is_hero)
    seated = [genome for _, genome in roles]
    seat_bot_ids = [_id(genome) for genome in seated]
    archive_policy_ids = config.get("training_archive", {}).get("policy_ids", {})
    runtime_config = {key: value for key, value in config.items() if key != "training_archive"}
    return {
        "genomes": [_to_dict(genome) for genome in seated],
        "seat_bot_ids": seat_bot_ids,
        "policy_ids": {bot_id: archive_policy_ids[bot_id] for bot_id in seat_bot_ids if bot_id in archive_policy_ids},
        "hero_id": _id(candidate),
        "hero_seat": hero_seat,
        "seed": int(seed),
        "kind": kind,
        "config": runtime_config,
    }


class EvolutionRunner:
    """Run one or more generations and atomically maintain the audit bundle."""

    def __init__(self, output_dir: str | Path, config: dict[str, Any] | None = None, *, resume: bool = False, workers: int = 1) -> None:
        self.output_dir = Path(output_dir).resolve()
        self.checkpoint_path = self.output_dir / "checkpoint.json"
        self.workers = max(1, int(workers))
        self.config = _validate_config(config or {})
        self.code_fingerprint = _code_fingerprint()
        if resume:
            if not self.checkpoint_path.exists():
                raise FileNotFoundError(f"cannot resume: {self.checkpoint_path} does not exist")
            self.state = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            self._verify_checkpoint()
            pending_report = self.state.pop("pending_report", None)
            if pending_report is not None:
                self._write_generation_report(pending_report)
            # An in-flight generation is retried as a whole with fresh seed
            # counters. The already completed generations remain committed.
            self.state["inflight"] = None
            self._save_checkpoint()
        else:
            if self.checkpoint_path.exists():
                raise FileExistsError(f"checkpoint exists at {self.checkpoint_path}; pass --resume to continue")
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self.state = _init_checkpoint(self.config, self.code_fingerprint)
            self._save_checkpoint()
        self._write_common_artifacts()

    def _verify_checkpoint(self) -> None:
        state = self.state
        if state.get("schema") != CHECKPOINT_SCHEMA:
            raise ValueError("unsupported evolution checkpoint schema")
        if state.get("config") != self.config:
            raise ValueError("resume configuration is incompatible with checkpoint; use the same population, seeds, and match settings")
        if state.get("code_fingerprint") != self.code_fingerprint:
            raise ValueError("resume rejected: project code or frozen model fingerprint changed")
        if state.get("python_version") != platform.python_version():
            raise ValueError("resume rejected: Python version differs from checkpoint")
        if state.get("dependency_versions") != _dependency_versions():
            raise ValueError("resume rejected: simulator dependency version differs from checkpoint")
        archive = self.config["training_archive"]
        if not _verify_training_archive(archive):
            raise ValueError("resume rejected: frozen training archive fingerprint is invalid")
        if state.get("training_archive_fingerprint") != archive["fingerprint"]:
            raise ValueError("resume rejected: training archive fingerprint differs from checkpoint")
        expected_archive_fingerprints = {
            "fingerprint": archive["fingerprint"],
            "content_sha256": archive["content_sha256"],
            "provenance_sha256": archive["provenance_sha256"],
            "sources": archive["sources"],
            "policy_ids_source": archive["policy_ids_source"],
        }
        if state.get("training_archive_fingerprints") != expected_archive_fingerprints:
            raise ValueError("resume rejected: archived source fingerprints differ from checkpoint")
        if state.get("archive_provenance") != archive["provenance"]:
            raise ValueError("resume rejected: archived lineage or provenance differs from checkpoint")
        if state.get("archive_policy_ids") != archive["policy_ids"]:
            raise ValueError("resume rejected: archived policy identity mapping differs from checkpoint")
        for bot_id, genome in archive["genomes"].items():
            persisted = state.get("genomes", {}).get(bot_id)
            if (persisted is None or persisted.get("bot_id") != bot_id
                    or _archive_phenotype(persisted) != _archive_phenotype(genome)):
                raise ValueError(f"resume rejected: archived genome {bot_id} differs from checkpoint")
        if not set(archive["training_opponents"]).issubset(state.get("training_opponents", [])):
            raise ValueError("resume rejected: archived training opponent membership differs from checkpoint")
        if not set(archive["hall_of_fame"]).issubset(state.get("hall_of_fame", [])):
            raise ValueError("resume rejected: archived hall-of-fame membership differs from checkpoint")
        if state.get("seed_stream", {}).get("master_seed") != self.config["seed"]:
            raise ValueError("resume rejected: seed stream does not match config")
        keys = {
            "training": "training_opponents",
            "validation": "validation_population",
            "confirmation": "confirmation_population",
        }
        for key, state_key in keys.items():
            raw_pool = [state.get("genomes", {}).get(bot_id) for bot_id in state.get(state_key, [])]
            actual = hashlib.sha256(_canonical_json(raw_pool).encode()).hexdigest()
            if actual != state.get("fixed_pool_fingerprints", {}).get(key):
                raise ValueError(f"resume rejected: persisted fixed {key} pool was changed")

    def _save_checkpoint(self) -> None:
        self.state["updated_at_utc"] = _utc_now()
        _write_json(self.checkpoint_path, self.state)

    def _allocate_seeds(self, domain: str, count: int) -> list[int]:
        counters = self.state["seed_stream"]["counters"]
        start = int(counters[domain])
        namespace = self.config["evaluation_namespace"]
        seed_domain = f"{namespace}:{domain}" if namespace else domain
        seeds = [_seed_value(self.config["seed"], seed_domain, start + offset) for offset in range(count)]
        counters[domain] = start + count
        return seeds

    def _reserve_jobs(self, candidates: list[Any], matches_per_candidate: int, domain: str, generation: int) -> list[dict[str, Any]]:
        pool = _opponent_pool(self.state, domain)
        jobs: list[dict[str, Any]] = []
        count = len(candidates) * matches_per_candidate
        seeds = iter(self._allocate_seeds(domain, count))
        for candidate in candidates:
            for _ in range(matches_per_candidate):
                seed = next(seeds)
                job = _build_tournament_job(candidate, pool, seed, domain, self.config)
                job["generation"] = generation
                jobs.append(job)
        self.state["inflight"] = {
            "generation": generation,
            "phase": domain,
            "reserved_seed_count": count,
            "reserved_seed_range_end": self.state["seed_stream"]["counters"][domain],
        }
        self.state["seed_stream"]["reserved_evaluations"].append({
            "generation": generation,
            "domain": domain,
            "count": count,
            "counter_end": self.state["seed_stream"]["counters"][domain],
        })
        # Seed reservations reach disk before a worker can start consuming one.
        self._save_checkpoint()
        return jobs

    def _evaluate_batch(self, jobs: list[dict[str, Any]], candidates: list[Any], alpha_by_id: dict[str, float] | None = None) -> dict[str, dict[str, Any]]:
        results = _execute_jobs(jobs, self.workers)
        by_id: dict[str, list[dict[str, Any]]] = {_id(genome): [] for genome in candidates}
        for result in results:
            by_id[result["bot_id"]].append(result)
        return {
            bot_id: _aggregate(bot_id, evaluations, None if alpha_by_id is None else alpha_by_id[bot_id])
            for bot_id, evaluations in by_id.items()
        }

    def _register_genome(self, genome: Any) -> None:
        bot_id = _id(genome)
        self.state["genomes"][bot_id] = _to_dict(genome)
        self.state["lineage"][bot_id] = {
            "bot_id": bot_id, "family": str(genome.family), "parents": list(genome.parents),
            "generation": int(genome.generation), "params": dict(genome.params),
        }

    def _breed_next_population(self, generation: int, ranked: list[dict[str, Any]]) -> tuple[list[str], dict[str, list[str]], dict[str, str]]:
        population_ids = list(self.state["active_population"])
        protected_id = self.state["protected_bot_id"]
        ranked_ids = [row["bot_id"] for row in ranked]
        nonprotected = [bot_id for bot_id in ranked_ids if bot_id != protected_id]
        survivor_count = max(1, math.ceil(len(nonprotected) / 2))
        survivor_ids = nonprotected[:survivor_count]
        next_ids = [protected_id, *survivor_ids]
        offspring_by_parent: dict[str, list[str]] = {bot_id: [] for bot_id in population_ids}
        status = {
            bot_id: "protected" if bot_id == protected_id else ("survived" if bot_id in survivor_ids else "eliminated")
            for bot_id in population_ids
        }
        parent_genomes = [_from_dict(self.state["genomes"][bot_id]) for bot_id in survivor_ids]
        rng = random.Random(_seed_value(self.config["seed"], "genetics", generation))
        offspring_count = self.config["population"] - len(next_ids)
        reserved_ids = set(self.state["genomes"])
        offspring_prefix = f"evo-g{generation:04d}"
        for index in range(offspring_count):
            bot_id = _available_genome_id(offspring_prefix, index, reserved_ids)
            # One in four slots is a fresh immigrant. Other slots use the
            # sibling breed API, which performs parameter mutation and optional
            # crossover; fixed anchors remain intact in the genome ledger.
            if (index + 1) % 4 == 0 or index == offspring_count - 1 or not parent_genomes:
                child = new_random(rng, bot_id, generation=generation)
                family_rng = random.Random(_seed_value(
                    self.config["seed"], "immigrant-family",
                    generation * self.config["population"] + index,
                ))
                if family_rng.random() < self.config["adaptive_fraction"]:
                    raw = child.to_dict()
                    raw["family"] = "adaptive"
                    child = _from_dict(raw)
            else:
                parent = rng.choice(parent_genomes)
                other_choices = [item for item in parent_genomes if _id(item) != _id(parent)]
                other = rng.choice(other_choices) if other_choices else None
                child = breed(parent, other, rng, bot_id, generation)
            self._register_genome(child)
            next_ids.append(_id(child))
            for parent_id in tuple(getattr(child, "parents", ())):
                offspring_by_parent.setdefault(parent_id, []).append(_id(child))

        # Preserve the champion archive monotonically; all prior entries stay
        # available to future opponent sampling.
        hof = self.state["hall_of_fame"]
        additions = 0
        hof_additions_per_generation = max(1, math.ceil(self.config["population"] / 4))
        for row in ranked:
            if row["bot_id"] != protected_id and row["bot_id"] not in hof:
                hof.append(row["bot_id"])
                self.state["hall_of_fame_fitness"][row["bot_id"]] = row["fitness"]
                additions += 1
                if additions >= hof_additions_per_generation:
                    break
        self.state["active_population"] = next_ids
        return next_ids, offspring_by_parent, status

    def _test_candidates(self, generation: int, leaders: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
        validation_alpha_by_id: dict[str, float] = {}
        validation_indexes: dict[str, int] = {}
        for genome in leaders:
            index = int(self.state["validation_attempts"])
            self.state["validation_attempts"] = index + 1
            validation_indexes[_id(genome)] = index
            validation_alpha_by_id[_id(genome)] = _one_sided_alpha(VALIDATION_ALPHA_BUDGET, index)
        validation_jobs = self._reserve_jobs(leaders, self.config["validation_matches"], "validation", generation)
        validation = self._evaluate_batch(validation_jobs, leaders, validation_alpha_by_id)
        validation_rows: list[dict[str, Any]] = []
        confirm_candidates: list[Any] = []
        for genome in leaders:
            row = validation[_id(genome)]
            row["attempt"] = validation_indexes[_id(genome)] + 1
            row["gate_passed"] = bool(self.config["players"] == 8
                                      and row["win_rate"] is not None
                                      and row["win_rate"] > self.config["target_win_rate"]
                                      and row["invalid_actions"] == 0)
            validation_rows.append(row)
            if row["gate_passed"]:
                confirm_candidates.append(genome)

        confirmation_rows: list[dict[str, Any]] = []
        promoted: dict[str, Any] | None = None
        # Candidates are checked in training-rank order. Stop as soon as one
        # passes its independent confirmation, which is the only early-stop
        # condition permitted for a run.
        for genome in confirm_candidates:
            bot_id = _id(genome)
            global_index = int(self.state["confirmation_attempts"])
            self.state["confirmation_attempts"] = global_index + 1
            alpha = _one_sided_alpha(CONFIRMATION_ALPHA_BUDGET, global_index)
            confirmation_jobs = self._reserve_jobs(
                [genome], self.config["confirmation_matches"], "confirmation", generation
            )
            attempt = self._evaluate_batch(confirmation_jobs, [genome], {bot_id: alpha})[bot_id]
            previous = self.state["confirmation_results"].get(bot_id, {"evaluations": [], "alpha_spent": 0.0, "attempts": []})
            previous["evaluations"].extend(attempt["evaluations"])
            previous["alpha_spent"] += alpha
            previous["attempts"].append({
                "attempt": global_index + 1,
                "alpha": alpha,
                "played": attempt["played"],
                "won": attempt["won"],
                "win_rate": attempt["win_rate"],
                "wilson_95": attempt["wilson_95"],
            })
            self.state["confirmation_results"][bot_id] = previous
            cumulative = _aggregate(bot_id, previous["evaluations"], previous["alpha_spent"])
            cumulative["attempt"] = global_index + 1
            cumulative["attempt_alpha"] = alpha
            cumulative["alpha_spent"] = previous["alpha_spent"]
            cumulative["attempts"] = previous["attempts"]
            cumulative["attempt_result"] = attempt
            cumulative["gate_lower_bound"] = attempt["exact_lower_bound"]
            cumulative["gate_alpha"] = alpha
            cumulative["gate_passed"] = bool(
                attempt["exact_lower_bound"] is not None
                and attempt["exact_lower_bound"] > self.config["target_win_rate"]
                and self.config["players"] == 8
                and attempt["invalid_actions"] == 0
            )
            confirmation_rows.append(cumulative)
            if cumulative["gate_passed"]:
                promoted = {
                    "bot_id": bot_id,
                    "genome": self.state["genomes"][bot_id],
                    "confirmed_at_generation": generation,
                    "target_win_rate": self.config["target_win_rate"],
                    "confirmation": cumulative,
                }
                break
        return validation_rows, confirmation_rows, promoted

    def run(self, generations: int) -> dict[str, Any]:
        if generations <= 0:
            raise ValueError("generations chunk must be positive")
        self.state["status"] = "running"
        self._save_checkpoint()
        for _ in range(generations):
            if self.state.get("champion"):
                break
            generation = int(self.state["completed_generations"]) + 1
            current = [_from_dict(self.state["genomes"][bot_id]) for bot_id in self.state["active_population"]]
            training_jobs = self._reserve_jobs(current, self.config["matches"], "training", generation)
            training = self._evaluate_batch(training_jobs, current)
            ranked = _rank(list(training.values()))
            for rank, row in enumerate(ranked, start=1):
                row["rank"] = rank
            leader_count = min(self.config["validation_leaders"], len(ranked))
            leaders = [_from_dict(self.state["genomes"][row["bot_id"]]) for row in ranked[:leader_count]]
            validation_rows, confirmation_rows, promoted = self._test_candidates(generation, leaders)
            next_population, offspring_by_parent, bot_status = self._breed_next_population(generation, ranked)
            self.state["provisional_champion"] = ranked[0]["bot_id"] if ranked else self.state["protected_bot_id"]
            if promoted is not None:
                self.state["champion"] = promoted
                self.state["status"] = "confirmed_target_reached"

            bots: list[dict[str, Any]] = []
            for row in ranked:
                genome_raw = self.state["genomes"][row["bot_id"]]
                bots.append({
                    **row,
                    "parents": list(genome_raw.get("parents", [])),
                    "family": genome_raw.get("family"),
                    "params": genome_raw.get("params", {}),
                    "status": bot_status[row["bot_id"]],
                    "offspring_ids": offspring_by_parent.get(row["bot_id"], []),
                })
            for bot_id in next_population:
                if bot_id in training:
                    continue
                raw = self.state["genomes"][bot_id]
                bots.append({
                    "bot_id": bot_id, "parents": list(raw.get("parents", [])), "family": raw.get("family"),
                    "params": raw.get("params", {}), "rank": None, "fitness": None, "played": 0, "won": 0,
                    "lost": 0, "capped": 0, "win_rate": None, "wilson_95": None, "mean_points": None,
                    "mean_finish": None, "mean_final_stack": None, "invalid_actions": 0, "decisions": 0,
                    "latency_mean_ms": None, "latency_p95_ms": None, "latency_max_ms": None, "over_1ms": 0,
                    "runtime_mean_ms": None, "status": "offspring", "offspring_ids": [], "evaluations": [],
                })
            validation_by_id = {row["bot_id"]: row for row in validation_rows}
            confirmation_by_id = {row["bot_id"]: row for row in confirmation_rows}
            for row in bots:
                if row["bot_id"] in validation_by_id:
                    row["validation"] = validation_by_id[row["bot_id"]]
                if row["bot_id"] in confirmation_by_id:
                    row["confirmation"] = confirmation_by_id[row["bot_id"]]

            generation_summary = {
                "generation": generation,
                "created_at_utc": _utc_now(),
                "training_match_count": sum(row["played"] for row in training.values()),
                "best_training_bot_id": ranked[0]["bot_id"] if ranked else None,
                "best_training_win_rate": ranked[0]["win_rate"] if ranked else None,
                "best_training_mean_points": ranked[0]["mean_points"] if ranked else None,
                "validation_gate_passes": sum(bool(row["gate_passed"]) for row in validation_rows),
                "confirmation_attempts": len(confirmation_rows),
                "confirmed_target_reached": promoted is not None,
                "active_population": list(next_population),
                "training_seed_counter": self.state["seed_stream"]["counters"]["training"],
                "validation_seed_counter": self.state["seed_stream"]["counters"]["validation"],
                "confirmation_seed_counter": self.state["seed_stream"]["counters"]["confirmation"],
            }
            self.state["history"].append(generation_summary)
            self.state["completed_generations"] = generation
            self.state["inflight"] = None
            report = {
                "schema": REPORT_SCHEMA,
                "generation": generation,
                "created_at_utc": generation_summary["created_at_utc"],
                "status": "confirmed_target_reached" if promoted else "target_not_reached",
                "target_win_rate": self.config["target_win_rate"],
                "config": self.config,
                "code_fingerprint": self.code_fingerprint,
                "seed_stream": json.loads(json.dumps(self.state["seed_stream"])),
                "validation_population": self.state["validation_population"],
                "confirmation_population": self.state["confirmation_population"],
                "bots": bots,
                "training_ranked_bot_ids": [row["bot_id"] for row in ranked],
                "validation": validation_rows,
                "confirmation": confirmation_rows,
                "generation_summary": generation_summary,
                "fitness_rule": "Lexicographic: outright win rate, mean tournament points, mean final chips, then fewer invalid actions per decision.",
                "win_rule": "Only a non-capped tournament result naming this hero as the sole-survivor winner is a win. Capped/unfinished tables remain in the denominator.",
                "confidence_method": {
                    "descriptive_interval": "Two-sided 95% Wilson score interval for each reported win rate.",
                    "confirmation_gate": "The fresh confirmation sample's one-sided exact binomial lower bound must exceed target; telescoping alpha spending has total budget at most 0.025 across candidates and attempts. Cumulative results are descriptive only.",
                    "validation_gate": "Validation is a gate only: observed outright-win rate must exceed target. It never ranks or breeds candidates.",
                    "finite_sample_limit": (
                        f"At the first confirmation alpha={_one_sided_alpha(CONFIRMATION_ALPHA_BUDGET, 0):.6g}, "
                        f"an all-win fresh sample needs at least "
                        f"{minimum_all_successes_for_exact_bound(self.config['target_win_rate'], _one_sided_alpha(CONFIRMATION_ALPHA_BUDGET, 0))} "
                        f"matches for an exact binomial lower bound above target {self.config['target_win_rate']:.3f}; "
                        "later confirmation attempts can require more."
                    ),
                    "interpretation": "Match-level Wilson inference is conditional on the fixed opponent pool and assumes independently seeded match outcomes under the configured simulator.",
                },
                "limits": [
                    "Validation and confirmation opponents are independently generated, fixed pools that include all fixed anchors.",
                    "Training, validation, and confirmation use disjoint deterministic seed domains; checkpoint reservations are durable before evaluation starts.",
                    "Training fitness and validation gates do not use confirmation outcomes for breeding or training ranks.",
                ],
            }
            # Commit the generation plus a durable export journal first.
            # Resume republishes this report if interrupted during export.
            self.state["pending_report"] = report
            self._save_checkpoint()
            self._write_generation_report(report)
            self._write_common_artifacts()
            self.state.pop("pending_report", None)
            self._save_checkpoint()
            print(json.dumps({
                "event": "generation_complete", "generation": generation, "status": report["status"],
                "report_paths": self._report_paths(generation),
                "bot_results": [{
                    "bot_id": row["bot_id"], "rank": row.get("rank"), "played": row.get("played", 0),
                    "won": row.get("won", 0), "lost": row.get("lost", 0), "capped": row.get("capped", 0),
                    "win_rate": row.get("win_rate"), "mean_points": row.get("mean_points"), "status": row.get("status"),
                } for row in bots],
            }, sort_keys=True), flush=True)
            if promoted is not None:
                break

        if self.state.get("champion"):
            self.state["status"] = "confirmed_target_reached"
        else:
            self.state["status"] = "target_not_reached"
        self._write_common_artifacts()
        self._save_checkpoint()
        return self.state

    def _report_paths(self, generation: int) -> dict[str, str]:
        stem = f"round-{generation:04d}"
        return {
            "json": str(self.output_dir / f"{stem}.json"),
            "csv": str(self.output_dir / f"{stem}.csv"),
            "markdown": str(self.output_dir / f"{stem}.md"),
            "checkpoint": str(self.checkpoint_path),
            "summary": str(self.output_dir / "summary.json"),
            "history": str(self.output_dir / "history.json"),
            "html": str(self.output_dir / "index.html"),
            "champion": str(self.output_dir / "champion.json"),
        }

    def _write_generation_report(self, report: dict[str, Any]) -> None:
        generation = int(report["generation"])
        stem = f"round-{generation:04d}"
        _write_json(self.output_dir / f"{stem}.json", report)
        fields = [
            "bot_id", "rank", "parents", "family", "params", "fitness", "played", "won", "lost", "capped",
            "win_rate", "wilson_95", "mean_points", "mean_finish", "mean_final_stack", "invalid_actions",
            "decisions", "invalid_rate", "latency_mean_ms", "latency_p95_ms", "latency_max_ms", "over_1ms",
            "runtime_mean_ms", "status", "offspring_ids",
        ]
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=self.output_dir, delete=False) as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for row in report["bots"]:
                writer.writerow({key: json.dumps(row.get(key), sort_keys=True) if isinstance(row.get(key), (list, dict)) else row.get(key) for key in fields})
            stream.flush()
            os.fsync(stream.fileno())
            temporary = stream.name
        os.replace(temporary, self.output_dir / f"{stem}.csv")
        lines = [
            f"# Evolution round {generation:04d}", "",
            f"Status: **{report['status']}**  ",
            f"Target: >{report['target_win_rate']:.3f} outright wins per full-table match.",
            "",
            "Capped and unfinished matches count as non-wins. Rank uses training outcomes only; validation is a promotion gate.",
            "",
            "| Rank | Bot | Family | Points | Win rate | 95% Wilson | Played | Won | Lost | Capped | Invalid | Status | Offspring |",
            "|---:|---|---|---:|---:|---|---:|---:|---:|---:|---:|---|---|",
        ]
        for row in report["bots"]:
            interval = row.get("wilson_95")
            interval_text = "—" if interval is None else f"{interval[0]:.3f}–{interval[1]:.3f}"
            points_text = "—" if row.get("mean_points") is None else f"{row['mean_points']:.4f}"
            rate_text = "—" if row.get("win_rate") is None else f"{row['win_rate']:.3f}"
            lines.append(
                f"| {row.get('rank', '—')} | {row['bot_id']} | {row.get('family', '')} | {points_text} | {rate_text} | {interval_text} | "
                f"{row.get('played', 0)} | {row.get('won', 0)} | {row.get('lost', 0)} | {row.get('capped', 0)} | "
                f"{row.get('invalid_actions', 0)} | {row.get('status', '')} | {', '.join(row.get('offspring_ids', [])) or '—'} |"
            )
        lines.extend(["", "## Validation gate", ""])
        if not report["validation"]:
            lines.append("No candidates were tested.")
        else:
            for row in report["validation"]:
                interval = row.get("wilson_95")
                interval_text = "—" if interval is None else f"{interval[0]:.3f}–{interval[1]:.3f}"
                lines.append(f"- {row['bot_id']}: {row['won']}/{row['played']} wins ({row['win_rate']:.3f}); Wilson 95% {interval_text}; gate {'passed' if row['gate_passed'] else 'not passed'}.")
        lines.extend(["", "## Confirmation", ""])
        if not report["confirmation"]:
            lines.append("No candidate passed the validation gate in this round.")
        else:
            for row in report["confirmation"]:
                lower = row.get("gate_lower_bound")
                lower_text = "—" if lower is None else f"{lower:.4f}"
                lines.append(f"- {row['bot_id']}: cumulative {row['won']}/{row['played']} wins (descriptive); fresh-sample exact lower bound {lower_text} at alpha {row['gate_alpha']:.6g}; {'confirmed' if row['gate_passed'] else 'not confirmed'}.")
        _atomic_write(self.output_dir / f"{stem}.md", "\n".join(lines) + "\n")

    def _write_common_artifacts(self) -> None:
        champion = self.state.get("champion")
        provisional_id = self.state.get("provisional_champion") or self.state["protected_bot_id"]
        bot_id = champion["bot_id"] if champion else provisional_id
        genome = self.state["genomes"][bot_id]
        champion_payload = {
            "schema": "pokerbot-evolution-champion-v1",
            "status": "confirmed" if champion else "provisional",
            "bot_id": bot_id,
            "players": self.config["players"],
            "variant": "no-limit-texas-holdem",
            "goal_eligible": self.config["players"] == 8,
            "dependency_versions": self.state["dependency_versions"],
            "genome": genome,
            "target_win_rate": self.config["target_win_rate"],
            "confirmation": champion.get("confirmation") if champion else None,
            "policy_load_hint": "from pokerbot.evolution_strategies import Genome, policy_for; policy = policy_for(Genome.from_dict(champion['genome']))",
        }
        _write_json(self.output_dir / "champion.json", champion_payload)
        last_generation = self.state["history"][-1] if self.state["history"] else None
        summary = {
            "schema": "pokerbot-evolution-summary-v1",
            "status": self.state.get("status", "running"),
            "completed_generations": self.state["completed_generations"],
            "target_win_rate": self.config["target_win_rate"],
            "champion": champion_payload,
            "last_generation": last_generation,
            "config": self.config,
            "code_fingerprint": self.state["code_fingerprint"],
            "seed_stream": self.state["seed_stream"],
            "statistical_method": {
                "confirmation_alpha_budget": CONFIRMATION_ALPHA_BUDGET,
                "confirmation_alpha_spending": "alpha_i = budget / ((i+1)*(i+2)) across all fresh candidate confirmation attempts; total spend is at most 0.025.",
                "confirmation_rule": "Promote only when a fresh sample's one-sided exact binomial lower bound is strictly above target. Cumulative results are descriptive.",
                "all_successes_at_first_confirmation_attempt_minimum": minimum_all_successes_for_exact_bound(
                    self.config["target_win_rate"], _one_sided_alpha(CONFIRMATION_ALPHA_BUDGET, 0)
                ),
                "interpretation": "Match outcomes are conditional on the persisted opponent pools and assume independently seeded Bernoulli matches. Wilson intervals are descriptive; promotion uses an exact binomial bound on new confirmation matches.",
            },
            "history_path": "history.json",
            "checkpoint_path": "checkpoint.json",
        }
        _write_json(self.output_dir / "summary.json", summary)
        _write_json(self.output_dir / "history.json", {
            "schema": "pokerbot-evolution-history-v1",
            "history": self.state["history"],
            "confirmation_results": self.state["confirmation_results"],
            "hall_of_fame": self.state["hall_of_fame"],
            "lineage": self.state["lineage"],
        })
        self._write_html(summary)

    def _write_html(self, summary: dict[str, Any]) -> None:
        history = self.state["history"]
        rates = [row.get("best_training_win_rate") for row in history]
        points = [row.get("best_training_mean_points") for row in history]
        html_doc = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pokerbot evolutionary playground</title>
<style>
body{{font:16px/1.5 system-ui,sans-serif;max-width:1100px;margin:36px auto;padding:0 22px;color:#1c2430;background:#f4f6f8}}
h1,h2{{line-height:1.2}} .card{{background:#fff;border:1px solid #d8dee6;border-radius:12px;padding:20px;margin:18px 0;box-shadow:0 2px 8px #17212b0d}}
.status{{display:inline-block;padding:4px 10px;border-radius:999px;background:#e9eef5;font-weight:650}} svg{{width:100%;height:auto;overflow:visible}}
.grid{{stroke:#dce2e9;stroke-width:1}} .series{{fill:none;stroke:#2764ae;stroke-width:3}} .dot{{fill:#2764ae}} .muted{{color:#576579}} code{{overflow-wrap:anywhere}}
</style></head><body>
<h1>Pokerbot evolutionary playground</h1>
<p class="status">{html.escape(str(summary['status']))}</p>
<p class="muted">Completed {summary['completed_generations']} generations · target &gt;{summary['target_win_rate']:.3f} outright wins per match</p>
<section class="card"><h2>Best training win rate by generation</h2>{_chart_svg(rates, "Win rate", 0.0, 1.0)}</section>
<section class="card"><h2>Best training mean points</h2>{_chart_svg(points, "Mean points")}</section>
<section class="card"><h2>Champion policy</h2><p><strong>{html.escape(str(summary['champion']['bot_id']))}</strong> · {html.escape(str(summary['champion']['status']))}</p>
<p class="muted">{html.escape(str(summary['champion']['policy_load_hint']))}</p>
<p>Machine-readable files: <a href="summary.json">summary</a>, <a href="history.json">history</a>, <a href="champion.json">champion genome</a>, <a href="checkpoint.json">checkpoint</a>.</p></section>
<section class="card"><h2>Interpretation</h2><p>Each candidate's training results come from separate full-table matches. Capped tables count as non-wins. Validation gates candidates; only confirmation can promote a champion.</p>
<p class="muted">{html.escape(summary['statistical_method']['interpretation'])} Repeated confirmation attempts use alpha spending, with a total one-sided budget of 0.025.</p></section>
</body></html>'''
        _atomic_write(self.output_dir / "index.html", html_doc)


def _chart_svg(values: list[Any], label: str, low: float | None = None, high: float | None = None) -> str:
    points = [None if value is None else float(value) for value in values]
    valid = [value for value in points if value is not None and math.isfinite(value)]
    width, height, left, right, top, bottom = 760, 300, 65, 20, 24, 46
    plot_width = width - left - right
    plot_height = height - top - bottom
    if not valid:
        return f'<p class="muted">No {html.escape(label.lower())} values yet.</p>'
    lower = min(valid) if low is None else low
    upper = max(valid) if high is None else high
    if lower == upper:
        pad = max(1.0, abs(lower) * 0.1)
        lower -= pad
        upper += pad
    else:
        pad = (upper - lower) * 0.08
        lower = lower if low is not None else lower - pad
        upper = upper if high is not None else upper + pad
    xy = []
    for index, value in enumerate(points):
        if value is None:
            xy.append(None)
        else:
            x = left + (plot_width * index / max(1, len(points) - 1))
            y = top + plot_height * (upper - value) / (upper - lower)
            xy.append((x, y))
    lines = []
    for tick in range(5):
        y = top + plot_height * tick / 4
        tick_value = upper - (upper - lower) * tick / 4
        lines.append(f'<line class="grid" x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}"/><text x="4" y="{y+4:.1f}" font-size="12">{tick_value:.3g}</text>')
    segments = []
    current = []
    dots = []
    for index, item in enumerate(xy):
        if item is None:
            if current:
                segments.append(" ".join(f"{x:.1f},{y:.1f}" for x, y in current))
                current = []
            continue
        current.append(item)
        dots.append(f'<circle class="dot" cx="{item[0]:.1f}" cy="{item[1]:.1f}" r="4"><title>Generation {index+1}: {points[index]:.4g}</title></circle>')
    if current:
        segments.append(" ".join(f"{x:.1f},{y:.1f}" for x, y in current))
    polylines = "".join(f'<polyline class="series" points="{segment}"/>' for segment in segments)
    xlabels = "" if len(points) > 24 else "".join(
        f'<text x="{(left + plot_width * i / max(1, len(points)-1)):.1f}" y="{height-12}" text-anchor="middle" font-size="11">{i+1}</text>'
        for i in range(len(points))
    )
    return f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(label)} by generation">{"".join(lines)}{polylines}{"".join(dots)}{xlabels}</svg>'


def _parse_int_csv(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part.strip()) for part in value.split(",") if part.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected comma-separated integers") from exc


def _parse_float_csv(value: str) -> tuple[float, ...]:
    try:
        return tuple(float(part.strip()) for part in value.split(",") if part.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected comma-separated numbers") from exc


def _parse_probability(value: str) -> float:
    try:
        probability = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a finite probability strictly between 0 and 1") from exc
    if not math.isfinite(probability) or not 0.0 < probability < 1.0:
        raise argparse.ArgumentTypeError("expected a finite probability strictly between 0 and 1")
    return probability


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run or resume the pokerbot evolutionary playground.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="run a chunk of generations")
    run_parser.add_argument("--output-dir", default="reports/evolution-v1")
    run_parser.add_argument("--population", type=int, default=8)
    run_parser.add_argument("--generations", type=int, default=1, help="number of generations in this chunk")
    run_parser.add_argument("--matches", type=int, default=8, help="training matches per active bot per generation")
    run_parser.add_argument("--validation-matches", type=int, default=32)
    run_parser.add_argument("--confirmation-matches", type=int, default=128)
    run_parser.add_argument("--target-win-rate", type=_parse_probability, default=TARGET_WIN_RATE,
                            help="required outright full-table win rate; default: 0.95")
    run_parser.add_argument("--seed", type=int, default=20261102)
    run_parser.add_argument("--evaluation-namespace", default="",
                            help="separate match seed streams across experiments without changing fixed opponents")
    run_parser.add_argument("--adaptive-fraction", type=float, default=0.0,
                            help="fraction of fresh initial active genomes and immigrants using the adaptive policy family")
    run_parser.add_argument("--seed-genomes", default=None,
                            help="JSON file containing a list of canonical Genome.to_dict seed genomes")
    run_parser.add_argument("--archive-checkpoint", action="append", default=[],
                            help="checkpoint to import as training/HOF opponents; repeat to union complete archives")
    run_parser.add_argument("--archive-policy-ids", default=None,
                            help="optional JSON mapping archive aliases to original policy IDs")
    run_parser.add_argument("--workers", type=int, default=1)
    run_parser.add_argument("--players", type=int, default=8)
    run_parser.add_argument("--stacks", type=int, default=2000)
    run_parser.add_argument("--big-blinds", type=_parse_int_csv, default=DEFAULT_BIG_BLINDS)
    run_parser.add_argument("--hands-per-level", type=int, default=25)
    run_parser.add_argument("--max-hands", type=int, default=200)
    run_parser.add_argument("--payouts", type=_parse_float_csv, default=None)
    run_parser.add_argument("--resume", action="store_true", help="continue the saved checkpoint")
    return parser


def config_from_args(args: argparse.Namespace) -> dict[str, Any]:
    """Build the raw run config from parsed ``run`` arguments.

    Shared by every CLI driver so options such as ``--target-win-rate`` and
    ``--archive-checkpoint`` cannot be silently dropped by one of them.
    """
    return {
        "players": args.players, "population": args.population, "matches": args.matches,
        "validation_matches": args.validation_matches, "confirmation_matches": args.confirmation_matches,
        "seed": args.seed, "stacks": args.stacks, "big_blinds": args.big_blinds,
        "hands_per_level": args.hands_per_level, "max_hands": args.max_hands,
        "payouts": args.payouts, "strict": True,
        "adaptive_fraction": args.adaptive_fraction, "seed_genomes_path": args.seed_genomes,
        "evaluation_namespace": args.evaluation_namespace,
        "target_win_rate": args.target_win_rate,
        "archive_checkpoints": args.archive_checkpoint,
        "archive_policy_ids_path": args.archive_policy_ids,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = config_from_args(args)
    runner = EvolutionRunner(args.output_dir, config, resume=args.resume, workers=args.workers)
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
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
