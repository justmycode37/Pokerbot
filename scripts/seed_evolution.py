#!/usr/bin/env python3
"""Build a deterministic, training-only seed proposal for evolution-next.

The checked-in proposal is frozen to V4 rounds 1--6. Only each report's
training ``bots`` rows and the fields in TRAINING_FIELDS enter selection.
Validation and confirmation sections are intentionally projected away before
any sorting or genotype analysis.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from pokerbot.evolution_strategies import DEFAULT_PARAMS, PARAMETER_BOUNDS, Genome


ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "reports"
SOURCE_DIR = REPORTS_DIR / "evolution-v4"
SELECTION_ROUND = 6
PROPOSAL_SEED = 20261102
GENERATED_ON = "2026-11-02"
SCHEMA = "pokerbot-evolution-next-seed-proposal-v1"

TRAINING_FIELDS = (
    "bot_id", "family", "params", "parents", "played", "won", "rank", "status",
)
SOURCE_ROUNDS = tuple(range(1, 7))

# These hashes freeze the exact training report inputs used for this proposal.
# They are checked before JSON parsing so a changed V4 report cannot silently
# alter the candidate set.
FROZEN_SOURCE_SHA256 = {
    "round-0001.json": "44badea6b767be2bdc497de02f0bf7272a66a5cbb4bfa3185bee01e558a548ab",
    "round-0002.json": "877e64f575c56c2b3798476d012bdc7e5656549fc9ea9366584f3e3122e9f668",
    "round-0003.json": "054762d2ad795829349766d9c6302859309276936cd38d90d358d619bb75b5dd",
    "round-0004.json": "23d450850097d6041f2cd1cf0b3034f62c48a2964669ba9a52a4c72beba75ded",
    "round-0005.json": "d46a8844e527cf1b7a702c1d84d7292e9188d66ba460f38c2312691ae12b29cb",
    "round-0006.json": "4ca38aadeb7a36de64e2e18ad04b610a8a7059898ebef2a1fa6f53f4adf34fb7",
}

# Baseline runner fingerprints for the recommended config. Keep these as
# integration checks only: they are neither read as genomes nor used in
# candidate selection or mutation.
EXPECTED_FIXED_POOL_HASHES = {
    "training": "9ccd82b00482fe46c25b27221ba68c0f7c4f4c0fe484b94c0ce9e3104ae7c714",
    "validation": "da7c046010060560cbcc29e4198fb7669e8e190bcc1977626ae32ee5995a22d4",
    "confirmation": "77616d50a436b840053dd5479a78f115eefd823db9e3b1d477b09f3b0466a7f9",
}

VARIANTS_PER_FAMILY = 2
ELITE_COUNT = 4
ELITE_POOL_LIMIT = 8
MUTATED_PARAMETER_COUNT = 3


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def project_training_report(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Copy only allowed training row fields; ignore every other report field."""
    rows = report.get("bots")
    if not isinstance(rows, list):
        raise ValueError("round report must contain a training bots list")
    projected: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ValueError(f"training bot row {index} must be an object")
        projected.append({field: row[field] for field in TRAINING_FIELDS if field in row})
    return projected


def load_training_rounds(
    round_paths: Sequence[tuple[int, Path]],
    *,
    expected_hashes: Mapping[str, str] | None = None,
) -> tuple[dict[int, list[dict[str, Any]]], dict[str, str]]:
    """Read each report once, hash its bytes, then project training rows only."""
    rounds: dict[int, list[dict[str, Any]]] = {}
    hashes: dict[str, str] = {}
    for round_number, path in round_paths:
        raw = path.read_bytes()
        digest = _sha256(raw)
        hashes[path.name] = digest
        expected = None if expected_hashes is None else expected_hashes.get(path.name)
        if expected is not None and digest != expected:
            raise ValueError(f"frozen source hash mismatch for {path.name}: {digest}")

        # JSON parsing happens only after the hash is recorded. The parsed
        # report is immediately reduced to the allowlisted training fields.
        parsed = json.loads(raw)
        if not isinstance(parsed, Mapping):
            raise ValueError(f"{path.name} must contain a JSON object")
        rounds[round_number] = project_training_report(parsed)
        del parsed, raw
    return rounds, hashes


def _effective_genes(params: Mapping[str, float]) -> dict[str, float]:
    genes = dict(DEFAULT_PARAMS)
    genes.update({key: float(value) for key, value in params.items()})
    return genes


def _normalized_genotype_distance(first: Mapping[str, Any], second: Mapping[str, Any]) -> float:
    left = _effective_genes(first["params"])
    right = _effective_genes(second["params"])
    distances = [
        abs(left[name] - right[name]) / (high - low)
        for name, (low, high) in PARAMETER_BOUNDS.items()
    ]
    return sum(distances) / len(distances)


def _validate_training_candidate(row: Mapping[str, Any]) -> Genome:
    required = {"bot_id", "family", "params", "parents", "played", "rank", "status"}
    missing = required - set(row)
    if missing:
        raise ValueError(f"training row missing required fields: {', '.join(sorted(missing))}")
    if row["family"] not in {"evolved", "adaptive"}:
        raise ValueError("elite candidate must use the evolved or adaptive family")
    if type(row["rank"]) is not int or row["rank"] < 1:
        raise ValueError("elite candidate rank must be a positive within-round integer")
    if type(row["played"]) is not int or row["played"] <= 0:
        raise ValueError("elite candidate must have played training matches")
    genome = Genome(
        bot_id=row["bot_id"],
        family=row["family"],
        params=row["params"],
        parents=row["parents"],
        # Source row projection intentionally excludes generation. Imported
        # genomes begin at generation zero in the versioned successor.
        generation=0,
    )
    return genome


def _select_elites(round_rows: Sequence[Mapping[str, Any]]) -> tuple[list[Genome], list[dict[str, Any]]]:
    eligible: list[tuple[Mapping[str, Any], Genome]] = []
    for row in round_rows:
        if (
            row.get("family") in {"evolved", "adaptive"}
            and type(row.get("played")) is int
            and row["played"] > 0
            and type(row.get("rank")) is int
            and row["rank"] > 0
        ):
            eligible.append((row, _validate_training_candidate(row)))
    eligible.sort(key=lambda pair: (pair[0]["rank"], pair[0]["bot_id"]))
    elite_pool = eligible[:ELITE_POOL_LIMIT]
    if len(elite_pool) < ELITE_COUNT:
        raise ValueError(f"Round {SELECTION_ROUND} has fewer than {ELITE_COUNT} eligible candidates")

    # Select within-round top-half candidates. Start with the best rank, then
    # greedily maximize minimum normalized L1 distance while balancing the
    # four controls to two evolved and two adaptive candidates. Rank and ID
    # break exact distance ties.
    first = elite_pool[0]
    selected: list[tuple[Mapping[str, Any], Genome]] = [first]
    family_counts = Counter({first[1].family: 1})
    distances: dict[str, float | None] = {first[1].bot_id: None}
    while len(selected) < ELITE_COUNT:
        allowed = [pair for pair in elite_pool if pair not in selected and family_counts[pair[1].family] < VARIANTS_PER_FAMILY]
        if not allowed:
            raise ValueError("Round 6 top-eight pool cannot supply two elites from each candidate family")
        ranked = []
        for pair in allowed:
            distance = min(_normalized_genotype_distance(pair[0], chosen[0]) for chosen in selected)
            ranked.append((pair, distance))
        ranked.sort(key=lambda item: (-item[1], item[0][0]["rank"], item[0][0]["bot_id"]))
        chosen, distance = ranked[0]
        selected.append(chosen)
        family_counts[chosen[1].family] += 1
        distances[chosen[1].bot_id] = distance

    selection_details = []
    for row, genome in selected:
        selection_details.append({
            "bot_id": genome.bot_id,
            "family": genome.family,
            "source_round": SELECTION_ROUND,
            "within_round_training_rank": row["rank"],
            "played": row["played"],
            "won": row.get("won"),
            "status": row["status"],
            "source_parents": list(genome.parents),
            "minimum_normalized_distance_to_prior_elites": distances[genome.bot_id],
            "params_sha256": _sha256(_canonical_json(dict(genome.params)).encode("utf-8")),
        })
    return [genome for _, genome in selected], selection_details


def _mutate_parameters(parent: Genome, seed: int) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    rng = random.Random(seed)
    params = _effective_genes(parent.params)
    changed: dict[str, dict[str, float]] = {}
    names = sorted(PARAMETER_BOUNDS)
    for name in rng.sample(names, k=MUTATED_PARAMETER_COUNT):
        low, high = PARAMETER_BOUNDS[name]
        previous = params[name]
        direction = -1.0 if rng.getrandbits(1) else 1.0
        delta = rng.uniform(0.04, 0.12) * (high - low) * direction
        proposed = round(min(high, max(low, previous + delta)), 6)
        if proposed == previous:
            proposed = round(min(high, max(low, previous - delta)), 6)
        if proposed == previous:
            proposed = round(high if previous != high else low, 6)
        if not low <= proposed <= high or proposed == previous:
            raise ValueError(f"could not make a bounded nonzero mutation for {name}")
        params[name] = proposed
        changed[name] = {
            "before": round(previous, 6),
            "after": proposed,
            "delta": round(proposed - previous, 6),
        }
    return params, changed


def _genotype_key(genome: Genome) -> tuple[tuple[str, float], ...]:
    return tuple(sorted((name, float(value)) for name, value in _effective_genes(genome.params).items()))


def _build_variants(elites: Sequence[Genome]) -> tuple[list[Genome], list[dict[str, Any]]]:
    by_family: dict[str, list[Genome]] = {"evolved": [], "adaptive": []}
    for elite in elites:
        by_family[elite.family].append(elite)
    if any(len(by_family[family]) != VARIANTS_PER_FAMILY for family in by_family):
        raise ValueError("exactly two selected elites per family are required for variant coverage")

    used_genotypes = {_genotype_key(elite) for elite in elites}
    variants: list[Genome] = []
    details: list[dict[str, Any]] = []
    variant_index = 0
    for family in ("evolved", "adaptive"):
        for parent in by_family[family]:
            attempt = 0
            while True:
                mutation_seed = PROPOSAL_SEED + 100 * (variant_index + 1) + attempt
                params, changes = _mutate_parameters(parent, mutation_seed)
                candidate = Genome(
                    bot_id=f"evolution-next-g0000-variant-{variant_index + 1:02d}-{family}",
                    family=family,
                    params=params,
                    parents=(parent.bot_id,),
                    generation=0,
                )
                key = _genotype_key(candidate)
                if key not in used_genotypes:
                    break
                attempt += 1
                if attempt > 100:
                    raise ValueError("deterministic mutation could not find a unique genotype")
            used_genotypes.add(key)
            variants.append(candidate)
            details.append({
                "bot_id": candidate.bot_id,
                "family": candidate.family,
                "parent_ids": list(candidate.parents),
                "mutation_seed": mutation_seed,
                "retry_index": attempt,
                "changed_parameters": changes,
                "label": "exploration hypothesis; no measured improvement claim",
            })
            variant_index += 1
    return variants, details


def generate_proposal(rounds: Mapping[int, Sequence[Mapping[str, Any]]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return canonical seed genomes and training-only selection metadata."""
    if SELECTION_ROUND not in rounds:
        raise ValueError(f"training rows for selection round {SELECTION_ROUND} are required")
    elites, elite_details = _select_elites(rounds[SELECTION_ROUND])
    variants, variant_details = _build_variants(elites)
    genomes = elites + variants
    ids = [genome.bot_id for genome in genomes]
    genotypes = [_genotype_key(genome) for genome in genomes]
    if len(ids) != len(set(ids)):
        raise ValueError("proposal contains duplicate bot IDs")
    if len(genotypes) != len(set(genotypes)):
        raise ValueError("proposal contains duplicate genotypes")
    if len(genomes) != 8:
        raise ValueError("proposal must contain four exact controls and four variants")

    seed_genomes = [genome.to_dict() for genome in genomes]
    metadata = {
        "selection_round": SELECTION_ROUND,
        "selection_rule": (
            "Filter Round 6 training rows to played evolved/adaptive genomes with an integer within-round rank; "
            "take ranks 1–8, start with rank 1, then greedily maximize minimum mean normalized L1 distance "
            "over all PARAMETER_BOUNDS genes while enforcing two elites per family. Ties use lower rank then bot_id. "
            "No win rates or outcomes are pooled across rounds."
        ),
        "elite_pool_ids_in_rank_order": [
            row["bot_id"] for row in sorted(
                (r for r in rounds[SELECTION_ROUND]
                 if r.get("family") in {"evolved", "adaptive"}
                 and type(r.get("played")) is int and r["played"] > 0
                 and type(r.get("rank")) is int and r["rank"] > 0),
                key=lambda row: (row["rank"], row["bot_id"]),
            )[:ELITE_POOL_LIMIT]
        ],
        "exact_elites": elite_details,
        "variants": variant_details,
        "candidate_family_counts": dict(sorted(Counter(g.family for g in genomes).items())),
        "candidate_labels": {
            "exact_controls": "Four unchanged Round 6 training genomes; rank-selected and genotype-diversified controls.",
            "variants": "Four bounded, deterministically seeded perturbations; exploratory hypotheses without measured results.",
        },
    }
    return seed_genomes, metadata


def _file_hashes(paths: Sequence[Path]) -> dict[str, str]:
    hashes = {}
    for path in paths:
        hashes[path.relative_to(ROOT).as_posix()] = _sha256(path.read_bytes())
    return dict(sorted(hashes.items()))


def _json_text(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _render_audit_markdown(manifest: Mapping[str, Any]) -> str:
    selection = manifest["proposal"]
    lines = [
        "# Evolution-next seed proposal audit",
        "",
        f"Generated from frozen V4 training reports on {GENERATED_ON}.",
        "",
        "## Source snapshot",
        "",
        "The source is frozen at completed V4 rounds 1–6. Each report was read once; its SHA-256 was recorded before parsing, then only `bots` training rows and the allowlisted fields were retained. Nested validation and confirmation data were discarded before candidate analysis.",
        "",
    ]
    for entry in manifest["source_reports"]:
        lines.append(f"- Round {entry['round']}: `{entry['path']}` — `{entry['sha256']}`")
    lines.extend([
        "",
        "## Training-only selection",
        "",
        selection["selection_rule"],
        "",
        "The ranking is local to Round 6. The selection does not pool win rates across changing archive pools and excludes reference-family genomes.",
        "",
        "| Exact control | Family | Round 6 training rank | Played | Won | Status | Parents | Min distance to prior elites |",
        "|---|---|---:|---:|---:|---|---|---:|",
    ])
    for elite in selection["exact_elites"]:
        distance = elite["minimum_normalized_distance_to_prior_elites"]
        shown_distance = "—" if distance is None else f"{distance:.6f}"
        lines.append(
            f"| `{elite['bot_id']}` | {elite['family']} | {elite['within_round_training_rank']} | "
            f"{elite['played']} | {elite['won']} | {elite['status']} | "
            f"{', '.join(f'`{parent}`' for parent in elite['source_parents']) or '—'} | {shown_distance} |"
        )
    lines.extend([
        "",
        "The four controls preserve the source IDs, family, parameter values, and source parent lists. Their imported generation is set to 0 for the new run.",
        "",
        "## Exploratory variants",
        "",
        "Variants are perturbation hypotheses, not measured improvements. No tournament was launched to evaluate them.",
        "",
        "| Variant | Family | Parent | Mutation seed | Changed parameters (`before → after`) |",
        "|---|---|---|---:|---|",
    ])
    for variant in selection["variants"]:
        changes = ", ".join(
            f"{name} ({values['before']} → {values['after']})"
            for name, values in variant["changed_parameters"].items()
        )
        lines.append(
            f"| `{variant['bot_id']}` | {variant['family']} | `{variant['parent_ids'][0]}` | "
            f"{variant['mutation_seed']} | {changes} |"
        )
    lines.extend([
        "",
        "Each variant mutates three distinct bounded genes from one selected elite. The seed and each before/after value are recorded in the manifest.",
        "",
        "## Successor configuration",
        "",
        "```sh",
        manifest["recommended_run"]["command"],
        "```",
        "",
        "The proposal fits population 16 with five fixed anchors (13 occupied slots, 3 remaining). The new evaluation namespace is `evolution-next-20261102-seed-v1`.",
        "",
        "Fixed-pool hashes below are integration checks only. They do not enter the selection rule or mutation process; no fixed pool genome data is included in this proposal.",
        "",
        "| Fixed pool | Expected SHA-256 |",
        "|---|---|",
    ])
    for name, digest in manifest["integration_checks"]["expected_fixed_pool_hashes"].items():
        lines.append(f"| {name} | `{digest}` |")
    lines.extend([
        "",
        "## Limits",
        "",
        "Round 6 training ranks describe the V4 training archive only. They do not establish independent performance, and the four variants have no measured result. All validation and confirmation outcomes were excluded from candidate selection.",
        "",
        f"Seed file SHA-256: `{manifest['seed_file']['sha256']}`.",
        "",
    ])
    return "\n".join(lines)


def build_artifacts() -> dict[str, str]:
    paths = [(number, SOURCE_DIR / f"round-{number:04d}.json") for number in SOURCE_ROUNDS]
    rounds, source_hashes = load_training_rounds(paths, expected_hashes=FROZEN_SOURCE_SHA256)
    seed_genomes, proposal = generate_proposal(rounds)
    seed_text = _json_text(seed_genomes)
    seed_hash = _sha256(seed_text.encode("utf-8"))

    seed_path = REPORTS_DIR / "evolution-next-seeds.json"
    manifest_path = REPORTS_DIR / "evolution-next-seeds-manifest.json"
    audit_json_path = REPORTS_DIR / "evolution-audits" / "next-seeds-20261102.json"
    audit_md_path = REPORTS_DIR / "evolution-audits" / "next-seeds-20261102.md"

    code_paths = [
        ROOT / "scripts" / "seed_evolution.py",
        ROOT / "pokerbot" / "evolution.py",
        ROOT / "pokerbot" / "evolution_strategies.py",
        ROOT / "pokerbot" / "evolution_adaptive.py",
        SOURCE_DIR / "source" / "pokerbot" / "evolution.py",
        SOURCE_DIR / "source" / "pokerbot" / "evolution_strategies.py",
        SOURCE_DIR / "source" / "pokerbot" / "evolution_adaptive.py",
    ]
    source_reports = [
        {"round": number, "path": f"reports/evolution-v4/round-{number:04d}.json", "sha256": source_hashes[f"round-{number:04d}.json"]}
        for number in SOURCE_ROUNDS
    ]
    run_namespace = "evolution-next-20261102-seed-v1"
    run_args = [
        ".venv/bin/python -m pokerbot.evolution run",
        "--output-dir reports/evolution-next-20261102",
        "--population 16",
        "--generations 2",
        "--matches 128",
        "--validation-matches 128",
        "--confirmation-matches 512",
        "--players 8",
        "--seed 20261102",
        "--workers 4",
        "--adaptive-fraction 0.5",
        f"--evaluation-namespace {run_namespace}",
        "--seed-genomes reports/evolution-next-seeds.json",
    ]
    recommended_run = {
        "population": 16,
        "generations_per_chunk": 2,
        "workers": 4,
        "adaptive_fraction": 0.5,
        "training_matches": 128,
        "validation_matches": 128,
        "confirmation_matches": 512,
        "players": 8,
        "format": "unchanged eight-player full-table format",
        "seed": PROPOSAL_SEED,
        "evaluation_namespace": run_namespace,
        "seed_genomes_path": "reports/evolution-next-seeds.json",
        "population_capacity": {"fixed_anchors": 5, "seed_genomes": len(seed_genomes), "occupied": 5 + len(seed_genomes), "available": 16 - 5 - len(seed_genomes)},
        "command": " \\\n  ".join(run_args),
    }
    manifest = {
        "schema": SCHEMA,
        "generated_on": GENERATED_ON,
        "source_snapshot": "V4 completed rounds 1–6; Round 7 is intentionally excluded.",
        "source_reports": source_reports,
        "loaded_training_fields": list(TRAINING_FIELDS),
        "source_code_sha256": _file_hashes(code_paths),
        "proposal": proposal,
        "seed_file": {
            "path": "reports/evolution-next-seeds.json",
            "sha256": seed_hash,
            "serialization": "canonical Genome.to_dict objects in a JSON list",
            "genome_count": len(seed_genomes),
        },
        "candidate_families": proposal["candidate_family_counts"],
        "recommended_run": recommended_run,
        "integration_checks": {
            "expected_fixed_pool_hashes": EXPECTED_FIXED_POOL_HASHES,
            "integration_only": True,
            "used_for_selection_or_mutation": False,
            "note": "Compare these fixed fingerprints when wiring the successor runner; no fixed pool genomes or outcomes are included here.",
        },
        "limitations": [
            "Only Round 6 within-round training ranks were used to order the candidate pool; win rates were not pooled across rounds.",
            "The four variants are exploration hypotheses and have no measured improvement claim.",
            "Validation and confirmation outcomes were excluded before analysis.",
            "The seed proposal does not change or weaken any evaluation pool.",
        ],
    }
    audit = {
        "schema": SCHEMA + "-audit-v1",
        "generated_on": GENERATED_ON,
        "source_reports": source_reports,
        "selection_and_mutation": proposal,
        "seed_file": manifest["seed_file"],
        "expected_fixed_pool_hashes_integration_only": EXPECTED_FIXED_POOL_HASHES,
        "recommended_run": recommended_run,
        "claim": "Variants are exploratory hypotheses; no measured improvement is claimed.",
    }

    audit_json_path.parent.mkdir(parents=True, exist_ok=True)
    seed_path.write_text(seed_text, encoding="utf-8")
    manifest_path.write_text(_json_text(manifest), encoding="utf-8")
    audit_json_path.write_text(_json_text(audit), encoding="utf-8")
    audit_md_path.write_text(_render_audit_markdown(manifest), encoding="utf-8")
    return {
        "seed_file": str(seed_path.relative_to(ROOT)),
        "manifest": str(manifest_path.relative_to(ROOT)),
        "audit_json": str(audit_json_path.relative_to(ROOT)),
        "audit_markdown": str(audit_md_path.relative_to(ROOT)),
        "seed_file_sha256": seed_hash,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    print(json.dumps(build_artifacts(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
