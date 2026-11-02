"""Compare fast hand-strength estimates with independent uniform-card MC.

This is diagnostic calibration on synthetic observations, not human action
imitation, an opponent-range model, or an official playing-strength result.
"""

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pokerbot.cards import estimate_equity
from pokerbot.fast import _postflop_equity
from pokerbot.scenarios import observations
from pokerbot.state import Observation


def calibrate(count=256, samples=1000, seed=7319):
    rows = []
    groups = defaultdict(list)
    for raw in observations(count * 2, seed):
        obs = Observation.from_dict(raw)
        if not obs.board:
            continue
        estimate, details = _postflop_equity(obs)
        reference = estimate_equity(obs.hole_cards, obs.board,
                                    opponents=obs.players_active - 1,
                                    samples=samples, seed=obs.seed)
        row = {"hole_cards": list(obs.hole_cards), "board": list(obs.board),
               "players_active": obs.players_active,
               "fast": estimate, "mc_uniform": reference,
               "error": estimate - reference, "category": details["made_hand_category"]}
        rows.append(row)
        groups[obs.street].append(row["error"])
        if len(rows) == count:
            break
    def summary(errors):
        return {"count": len(errors), "bias": statistics.fmean(errors),
                "mae": statistics.fmean(abs(e) for e in errors),
                "rmse": statistics.fmean(e * e for e in errors) ** 0.5}
    return {"seed": seed, "samples_per_observation": samples,
            "overall": summary([r["error"] for r in rows]),
            "by_street": {name: summary(errors) for name, errors in groups.items()},
            "largest_errors": sorted(rows, key=lambda r: abs(r["error"]), reverse=True)[:20],
            "caveat": "Synthetic random-card observations and uniform opponent cards; not Ivey actions or tournament performance."}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--count", type=int, default=256)
    p.add_argument("--samples", type=int, default=1000)
    p.add_argument("--seed", type=int, default=7319)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    if args.count <= 0 or args.samples <= 0:
        p.error("count and samples must be positive")
    Path(args.output).write_text(json.dumps(calibrate(args.count, args.samples, args.seed), indent=2) + "\n")
