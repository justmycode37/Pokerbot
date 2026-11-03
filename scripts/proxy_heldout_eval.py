"""Evaluate genomes on a fixed proxy of the heldout opponent distribution.

The canonical validation and confirmation pools are the five fixed anchors plus
``fixed_random_opponents`` genomes drawn with ``new_random`` from their own seed
domains. This proxy pool uses the same construction and table sampling, but
with separate seed domains, so development never reads heldout outcomes.

Usage::

    .venv/bin/python scripts/proxy_heldout_eval.py CANDIDATES.json \
        --matches 256 --workers 2 --output OUT.json

``CANDIDATES.json`` is a list of canonical genome dicts (``bot_id``, ``family``,
``params``...). Every candidate plays the same seeded tables (same opponents,
seats and deals), so differences between candidates are paired.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pokerbot import evolution  # noqa: E402
from pokerbot.evolution_strategies import anchor_genomes  # noqa: E402

PROXY_MASTER_SEED = 20261103
PROXY_POOL_DOMAIN = "proxy-heldout-pool-v1"
PROXY_EVAL_DOMAIN = "proxy-heldout-eval-v1"


def proxy_pool(config: dict, pool_domain: str = PROXY_POOL_DOMAIN) -> list:
    anchors = evolution._deduplicated_genomes(anchor_genomes())
    if pool_domain in {"validation-pool", "confirmation-pool"}:
        raise ValueError("proxy pools must not reuse the canonical heldout seed domains")
    randoms = evolution._make_random_genomes(
        PROXY_MASTER_SEED, pool_domain, config["fixed_random_opponents"], "proxy-opponent"
    )
    return anchors + randoms


def wilson(wins: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def evaluate(candidates: list[dict], matches: int, workers: int, eval_domain: str = PROXY_EVAL_DOMAIN,
             seed_offset: int = 0, pool_domain: str = PROXY_POOL_DOMAIN) -> dict:
    config = evolution._validate_config({})
    pool = proxy_pool(config, pool_domain)
    pool_ids = {evolution._id(g) for g in pool}
    genomes = [evolution._from_dict(raw) for raw in candidates]
    for genome in genomes:
        if evolution._id(genome) in pool_ids:
            raise ValueError(f"candidate id collides with proxy pool: {evolution._id(genome)}")
    jobs = []
    for genome in genomes:
        for index in range(seed_offset, seed_offset + matches):
            seed = evolution._seed_value(PROXY_MASTER_SEED, eval_domain, index)
            jobs.append(evolution._build_tournament_job(genome, pool, seed, "validation", config))
    rows = evolution._execute_jobs(jobs, workers)
    summary = []
    for genome in genomes:
        mine = [row for row in rows if row["bot_id"] == evolution._id(genome)]
        wins = sum(row["won"] for row in mine)
        low, high = wilson(wins, len(mine))
        summary.append({
            "bot_id": evolution._id(genome),
            "family": genome.family,
            "played": len(mine),
            "won": wins,
            "win_rate": wins / len(mine) if mine else None,
            "wilson95": [low, high],
            "busted": sum(row["lost"] for row in mine),
            "capped_non_wins": sum(row["table_capped"] and not row["won"] for row in mine),
            "mean_points": sum(row["points"] for row in mine) / max(1, len(mine)),
            "invalid_actions": sum(row["invalid_actions"] for row in mine),
            "decisions": sum(row["decisions"] for row in mine),
        })
    return {
        "estimand": "outright 8-player table wins vs proxy heldout pool (anchors + new_random genomes); capped tables are non-wins",
        "proxy_master_seed": PROXY_MASTER_SEED,
        "pool_domain": pool_domain,
        "eval_domain": eval_domain,
        "seed_offset": seed_offset,
        "pool_ids": sorted(pool_ids),
        "config": {k: v for k, v in config.items() if k != "training_archive"},
        "summary": sorted(summary, key=lambda r: -r["won"]),
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("candidates", type=Path)
    parser.add_argument("--matches", type=int, default=128)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--eval-domain", default=PROXY_EVAL_DOMAIN,
                        help="use a fresh domain for confirmation-style re-tests of a selected candidate")
    parser.add_argument("--seed-offset", type=int, default=0)
    parser.add_argument("--pool-domain", default=PROXY_POOL_DOMAIN,
                        help="draw a different proxy opponent pool to check for overfitting to one pool")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    candidates = json.loads(args.candidates.read_text())
    result = evaluate(candidates, args.matches, args.workers, args.eval_domain, args.seed_offset, args.pool_domain)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    for row in result["summary"]:
        print(f"{row['bot_id']:<40} {row['family']:<22} {row['won']:>4}/{row['played']:<4} "
              f"{row['win_rate']:.3f}  [{row['wilson95'][0]:.3f}, {row['wilson95'][1]:.3f}]  "
              f"invalid={row['invalid_actions']}")


if __name__ == "__main__":
    main()
