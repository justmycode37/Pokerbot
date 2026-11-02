"""Reproducible local commands; no external submissions or live poker."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path


def policy(name, samples=1000, model_path=None):
    if name == "imitation":
        if not model_path:
            raise ValueError("imitation policy needs --model pointing to a trained JSON model")
        from .imitation import decide_with_model
        model = json.loads(Path(model_path).read_text())
        return lambda state: decide_with_model(state, model)
    if name == "fast":
        from .fast import decide
        return decide
    if name in ("mc-range", "mc-uniform"):
        from .strategy import decide
        return lambda state: decide(state, samples=samples, use_ranges=name == "mc-range")
    from . import simulation
    return getattr(simulation, name.replace("-", "_"))


def write_result(value, output=None):
    payload = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)


def profile_policy(decide, count=1000, seed=8128):
    from .scenarios import observations
    states = list(observations(count, seed))
    for state in states[:20]:
        decide(state)
    timings = []
    by_street = {0: [], 3: [], 4: [], 5: []}
    invalid = 0
    for state in states:
        start = time.perf_counter_ns()
        result = decide(state)
        elapsed = (time.perf_counter_ns() - start) / 1000
        timings.append(elapsed)
        by_street[len(state["board"])].append(elapsed)
        if result["action"] not in state["legal_actions"]:
            invalid += 1
        elif result["action"] == "raise" and not (
                type(result.get("amount")) is int
                and state["min_raise_to"] <= result["amount"] <= state["max_raise_to"]):
            invalid += 1

    def summary(values):
        ordered = sorted(values)
        def quantile(p):
            return ordered[min(len(ordered) - 1, max(0, math.ceil(p * len(ordered)) - 1))]
        return {"count": len(ordered), "median_us": quantile(0.5),
                "p95_us": quantile(0.95), "p99_us": quantile(0.99),
                "max_us": ordered[-1], "over_1ms_count": sum(t > 1000 for t in ordered)}
    return {"count": count, "seed": seed, "latency": summary(timings),
            "by_board_length": {str(k): summary(v) for k, v in by_street.items() if v},
            "invalid_actions": invalid,
            "caveat": "Warm local Python calls on synthetic observations; excludes SDK overhead and does not certify the event sandbox."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("decide", "compare-ivey", "review-ivey", "benchmark", "profile"):
        p = sub.add_parser(name)
        p.add_argument("--policy", choices=("fast", "mc-range", "mc-uniform", "imitation"), default="fast")
        p.add_argument("--model", help="Trained JSON model for --policy imitation")
        p.add_argument("--samples", type=int, default=1000)
        if name != "decide":
            p.add_argument("--output")
        if name in ("compare-ivey", "review-ivey"):
            p.add_argument("--data")
            p.add_argument("--sizing-tolerance", type=int, default=0)
            p.add_argument("--include-reconstructed", action="store_true")
            p.add_argument("--include-verified-video", action="store_true")
            p.add_argument("--include-public-reports", action="store_true")
        if name == "review-ivey":
            p.add_argument("--include-video", action="store_true")
        if name == "benchmark":
            p.add_argument("--opponent", choices=("calling-station", "tight-passive", "random-legal"), default="calling-station")
            p.add_argument("--players", type=int, default=8)
            p.add_argument("--hands", type=int, default=800)
            p.add_argument("--seed", type=int, default=20261031)
        if name == "profile":
            p.add_argument("--count", type=int, default=1000)
            p.add_argument("--seed", type=int, default=8128)
    args = parser.parse_args(argv)
    if args.samples <= 0:
        parser.error("--samples must be positive")
    try:
        decide = policy(args.policy, args.samples, args.model)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    if args.command == "decide":
        errors = 0
        for index, line in enumerate(sys.stdin, 1):
            if not line.strip():
                continue
            try:
                result = decide(json.loads(line))
            except (ValueError, TypeError, KeyError) as exc:
                result = {"error": str(exc), "line": index}
                errors += 1
            print(json.dumps(result, allow_nan=False), flush=True)
        return int(bool(errors))
    if args.command in ("compare-ivey", "review-ivey"):
        from . import ivey
        from .benchmarks import load_ivey_corpus
        decisions, load_report = load_ivey_corpus(args.data, include_reconstructed=args.include_reconstructed,
                                               include_verified_video=args.include_verified_video,
                                               include_public_reports=args.include_public_reports)
        if args.command == "review-ivey":
            from .review import review_packet, packet_markdown, write_packet
            if args.include_video:
                from .benchmarks import load_video_reviews
                full_sources = {r["source"].split("&")[0] for r in decisions}
                decisions.extend(r for r in load_video_reviews() if r["source"].split("&")[0] not in full_sources)
            packet = review_packet(decisions, decide, policy_name=args.policy)
            if args.output:
                write_packet(packet, args.output)
            else:
                print(packet_markdown(packet))
            return 0
        result = ivey.compare_decisions(decisions, decide, sizing_tolerance=args.sizing_tolerance)
        result.update({"policy": args.policy, "load_report": load_report,
                       "goal_gt99_all_ivey_decisions_proven": False})
        result["by_format_and_evidence"] = {
            f"{kind}/{tier}": ivey.compare_decisions(
                [r for r in decisions if (r["format"], r["evidence_tier"]) == (kind, tier)],
                decide, sizing_tolerance=args.sizing_tolerance)
            for kind, tier in sorted({(r["format"], r["evidence_tier"]) for r in decisions})}
    elif args.command == "benchmark":
        if not 2 <= args.players <= 8 or args.hands < args.players:
            parser.error("benchmark needs 2-8 players and at least one full seat rotation")
        from .simulation import benchmark
        result = benchmark(decide, [policy(args.opponent)] * (args.players - 1),
                           hands=args.hands, seed=args.seed)
        result.update({"policy": args.policy, "opponent": args.opponent,
                       "benchmark_kind": "local_cash_reset_not_official_tournament"})
    else:
        if args.count < 4:
            parser.error("--count must be at least four")
        result = profile_policy(decide, args.count, args.seed)
        result["policy"] = args.policy
    write_result(result, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
