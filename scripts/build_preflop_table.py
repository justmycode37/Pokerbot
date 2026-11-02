#!/usr/bin/env python3
"""Build the 169-class random-opponent Hold'em equity table offline.

This is a build-time utility. The runtime policy loads the resulting JSON and
does not call ``estimate_equity`` or sample cards.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pokerbot.cards import estimate_equity


RANKS = "23456789TJQKA"


def classes() -> list[tuple[str, tuple[str, str]]]:
    """Return one suit-equivalent representative for each of 169 classes."""
    result = []
    for high_index in range(12, -1, -1):
        high = RANKS[high_index]
        for low_index in range(high_index, -1, -1):
            low = RANKS[low_index]
            if high_index == low_index:
                result.append((high + low, (high + "s", high + "h")))
            else:
                result.append((high + low + "s", (high + "s", low + "s")))
                result.append((high + low + "o", (high + "s", low + "h")))
    return result


def build(samples: int, seed: int) -> dict:
    equities = {}
    for index, (name, hole) in enumerate(classes()):
        equities[name] = round(
            estimate_equity(
                hole,
                opponents=1,
                samples=samples,
                seed=seed + index,
            ),
            6,
        )
    return {
        "schema_version": 1,
        "variant": "no-limit-texas-holdem",
        "method": "uniform random opponent and board; cards.estimate_equity",
        "opponents": 1,
        "samples_per_class": samples,
        "base_seed": seed,
        "seed_schedule": "class_index_added_to_base_seed_in_list_order",
        "class_count": len(equities),
        "equity_vs_one_random_opponent": equities,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=260131)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "data" / "preflop_equity.json"
    )
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be positive")
    payload = build(args.samples, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "wrote %d classes at %d samples/class (base seed %d) to %s"
        % (payload["class_count"], args.samples, args.seed, args.output)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
