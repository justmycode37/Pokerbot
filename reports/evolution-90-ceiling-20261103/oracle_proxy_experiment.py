#!/usr/bin/env python3
"""Non-canonical hole-card oracle harness for the evolution-90 proxy pools.

This harness copies no canonical engine code and modifies no project source.
It temporarily wraps the engine's observation function in this process to add
the already-dealt hole cards and current tournament stacks. A filtered policy
passes that private payload only to the designated oracle hero. Opponents and
the saved reference receive the unchanged public observation.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import itertools
import json
import math
import random
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pokerbot import evolution, simulation
from pokerbot.cards import RANKS, SUITS, rank_hand
from pokerbot.evolution_strategies import Genome
from scripts.proxy_heldout_eval import (
    PROXY_MASTER_SEED,
    proxy_pool,
    wilson,
)

DECK = tuple(rank + suit for rank in RANKS for suit in SUITS)
MODES = ("saved-reference", "hole-chip-ev", "hole-leader-aware")
HOLE_ORACLE_ID = "ceiling-hole-oracle"


def install_cheat_observation() -> None:
    """Attach engine-private card and stack data for the designated wrapper."""
    current = simulation._observation
    if getattr(current, "_ceiling_cheat_wrapper", False):
        return

    def observation_with_cheat(state, seat, positions, seed, decision_number, history):
        raw = current(state, seat, positions, seed, decision_number, history)
        raw["_oracle_holes_by_engine_seat"] = [
            [repr(card) for card in hand] for hand in state.hole_cards
        ]
        # During a hand payoffs are the negative committed chips, so adding
        # them back to remaining stacks recovers each live seat's hand-start
        # tournament stack, including its posted blind.
        raw["_oracle_start_stacks_by_engine_seat"] = [
            int(stack - payoff) for stack, payoff in zip(state.stacks, state.payoffs)
        ]
        return raw

    observation_with_cheat._ceiling_cheat_wrapper = True
    simulation._observation = observation_with_cheat


class OracleAccessFilter:
    """Keep engine-private fields visible only to the oracle hero policy."""

    def __init__(self, policy, allow_oracle_data: bool):
        self.policy = policy
        self.allow_oracle_data = allow_oracle_data

    def reset(self):
        reset = getattr(self.policy, "reset", None)
        if callable(reset):
            reset()

    def __call__(self, observation: dict[str, Any]) -> dict[str, Any]:
        if not self.allow_oracle_data:
            clean = dict(observation)
            clean.pop("_oracle_holes_by_engine_seat", None)
            clean.pop("_oracle_start_stacks_by_engine_seat", None)
            return self.policy(clean)
        seat_ids = list(observation["table_player_ids"])
        holes = observation["_oracle_holes_by_engine_seat"]
        stacks = observation["_oracle_start_stacks_by_engine_seat"]
        folded = {
            str(action["player"])
            for action in observation["history"]
            if action.get("action") == "fold" and action.get("player") is not None
        }
        clean = dict(observation)
        clean.pop("_oracle_holes_by_engine_seat", None)
        clean.pop("_oracle_start_stacks_by_engine_seat", None)
        clean["oracle_holes_by_player"] = {
            player_id: list(cards) for player_id, cards in zip(seat_ids, holes)
            if player_id not in folded
        }
        if getattr(self.policy, "mode", None) == "hole-leader-aware":
            clean["oracle_start_stacks_by_player"] = {
                player_id: int(stack) for player_id, stack in zip(seat_ids, stacks)
            }
        return self.policy(clean)


class HoleCardOracle:
    """Greedy chip-EV oracle; actual holes, current cards, legal sizing only."""

    def __init__(self, mode: str):
        self.mode = mode
        self.equity_cache: dict[tuple, float] = {}
        self.equity_samples = 128
        self.exact_runout_limit = 1500

    def reset(self):
        self.equity_cache.clear()

    def _equity(self, hero_hole, board, villains) -> float:
        key = (
            tuple(sorted(hero_hole)), tuple(board),
            tuple(sorted(tuple(sorted(hand)) for hand in villains)),
        )
        cached = self.equity_cache.get(key)
        if cached is not None:
            return cached
        known = set(hero_hole) | set(board)
        for hand in villains:
            known.update(hand)
        remaining = [card for card in DECK if card not in known]
        missing = 5 - len(board)
        runout_count = math.comb(len(remaining), missing)
        exact = runout_count <= self.exact_runout_limit
        if exact:
            runouts = itertools.combinations(remaining, missing)
            count = runout_count
        else:
            digest = hashlib.sha256(repr(key).encode("utf-8")).digest()
            rng = random.Random(int.from_bytes(digest[:8], "big"))
            count = self.equity_samples
            runouts = (rng.sample(remaining, missing) for _ in range(count))

        share_total = 0.0
        hero_cards = tuple(hero_hole)
        villain_cards = [tuple(hand) for hand in villains]
        for runout in runouts:
            final_board = tuple(board) + tuple(runout)
            hero_rank = rank_hand(hero_cards + final_board)
            ranks = [hero_rank]
            ranks.extend(rank_hand(hand + final_board) for hand in villain_cards)
            best = max(ranks)
            if hero_rank == best:
                share_total += 1.0 / sum(rank == best for rank in ranks)
        equity = share_total / count
        self.equity_cache[key] = equity
        return equity

    def __call__(self, observation: dict[str, Any]) -> dict[str, Any]:
        hero_id = str(observation["player_id"])
        table_ids = list(observation["table_player_ids"])
        all_holes = observation["oracle_holes_by_player"]
        folded = {
            str(action["player"])
            for action in observation["history"]
            if action.get("action") == "fold" and action.get("player") is not None
        }
        villain_ids = [
            player_id for player_id in table_ids
            if player_id != hero_id and player_id not in folded
        ]
        villains = [tuple(all_holes[player_id]) for player_id in villain_ids]
        equity = self._equity(
            tuple(observation["hole_cards"]), tuple(observation["board"]), villains
        )

        legal = set(observation["legal_actions"])
        to_call = int(observation["to_call"])
        stack = int(observation["stack"])
        blind = int(observation["big_blind"])
        pot = int(observation["contestable_pot"])
        active = max(2, len(villain_ids) + 1)
        call_price = to_call / max(1, pot + to_call)

        leader = False
        if self.mode == "hole-leader-aware":
            starting = observation["oracle_start_stacks_by_player"]
            hero_start = int(starting[hero_id])
            opponent_starts = [int(starting[player_id]) for player_id in villain_ids]
            leader = bool(opponent_starts and hero_start > max(opponent_starts))

        if to_call:
            # Calls use the true multiway equity versus the opponents who have
            # not folded. In a large lead, require a stronger edge before
            # risking a substantial fraction of the hand-start stack.
            required = call_price
            if leader:
                start = int(observation["oracle_start_stacks_by_player"][hero_id])
                high_variance_call = to_call >= max(2 * blind, 0.25 * start)
                if high_variance_call:
                    required = max(required + 0.08, 0.70)
            if "fold" in legal and equity + 1e-9 < required:
                return {"action": "fold"}

            raise_allowed = "raise" in legal
            if raise_allowed and equity >= max(call_price + 0.28, 0.72):
                amount_to_call = to_call
                if stack <= 8 * blind or equity >= 0.88:
                    target = int(observation["max_raise_to"])
                else:
                    target = int(observation["current_bet"]) + max(
                        2 * amount_to_call, int(0.65 * max(1, pot))
                    )
                target = max(int(observation["min_raise_to"]), min(
                    int(observation["max_raise_to"]), target
                ))
                return {"action": "raise", "amount": target}
            if "call" in legal:
                return {"action": "call"}
            return {"action": "check"}

        if "raise" not in legal or not villains:
            return {"action": "check" if "check" in legal else "call"}

        # Betting with >1/N equity has positive chip value if all N active
        # opponents call; any folds add immediate value. Increase sizing with
        # a larger actual-hand edge, and jam very strong short-stack spots.
        threshold = 1.0 / active + 0.025
        if equity < threshold:
            return {"action": "check" if "check" in legal else "call"}
        if stack <= 8 * blind and equity >= max(threshold, 0.24):
            target = int(observation["max_raise_to"])
        elif equity >= 0.86 and not leader:
            target = int(observation["max_raise_to"])
        elif equity >= 0.70:
            target = int(observation["current_bet"]) + max(blind, int(0.85 * max(1, pot)))
        elif equity >= 0.48:
            target = int(observation["current_bet"]) + max(blind, int(0.55 * max(1, pot)))
        else:
            target = int(observation["current_bet"]) + max(blind, int(0.30 * max(1, pot)))
        target = max(int(observation["min_raise_to"]), min(
            int(observation["max_raise_to"]), target
        ))
        return {"action": "raise", "amount": target}


def run_one(task: dict[str, Any]) -> dict[str, Any]:
    install_cheat_observation()
    mode = task["mode"]
    job = task["job"]
    hero_seat = int(job["hero_seat"])
    genomes = [evolution._from_dict(raw) for raw in job["genomes"]]
    policies = []
    for seat, genome in enumerate(genomes):
        if seat == hero_seat and mode in {"hole-chip-ev", "hole-leader-aware"}:
            policy = HoleCardOracle(mode)
            policies.append(OracleAccessFilter(policy, True))
        elif seat == hero_seat:
            # The pool-builder placeholder is only for seat/opponent sampling;
            # the paired hero reference is always the canonical saved policy.
            saved = Genome("ceiling-saved-reference", family="saved")
            policies.append(OracleAccessFilter(evolution.policy_for(saved), False))
        else:
            policies.append(OracleAccessFilter(evolution.policy_for(genome), False))

    started = time.perf_counter()
    result = evolution.play_tournament(
        policies,
        seed=int(job["seed"]),
        stacks=job["config"]["stacks"],
        big_blinds=tuple(job["config"]["big_blinds"]),
        hands_per_level=job["config"]["hands_per_level"],
        max_hands=job["config"]["max_hands"],
        payouts=None if job["config"]["payouts"] is None else tuple(job["config"]["payouts"]),
        strict=True,
        trace=True,
    )
    elapsed = time.perf_counter() - started
    trace = result["trace"]
    reached_hu = any(
        sum(stack > 0 for stack in row["end_stacks"]) == 2
        and row["end_stacks"][hero_seat] > 0
        for row in trace
    )
    bust_row = next((row for row in trace if row["end_stacks"][hero_seat] == 0), None)
    hero = result["players"][hero_seat]
    won = result["winner"] == hero_seat and not result["capped"]
    return {
        "mode": mode,
        "pool_domain": task["pool_domain"],
        "eval_domain": task["eval_domain"],
        "index": task["index"],
        "seed": int(job["seed"]),
        "hero_seat": hero_seat,
        "seat_bot_ids": list(job["seat_bot_ids"]),
        "won": bool(won),
        "capped": bool(result["capped"]),
        "busted": int(hero["final_stack"]) == 0,
        "heads_up_reached": bool(reached_hu),
        "heads_up_converted": bool(reached_hu and won),
        "bust_hand": int(bust_row["hand"]) if bust_row else None,
        "bust_big_blind": int(bust_row["big_blind_amount"]) if bust_row else None,
        "hands_played": int(result["hands_played"]),
        "invalid_actions": int(hero["invalid_actions"]),
        "chip_conservation": sum(result["final_stacks"]) == sum(result["config"]["starting_stacks"]),
        "runtime_seconds": elapsed,
    }


def make_tasks(pool_domain: str, eval_domain: str, matches: int) -> list[dict[str, Any]]:
    config = evolution._validate_config({})
    pool = proxy_pool(config, pool_domain)
    placeholder = Genome(HOLE_ORACLE_ID, family="saved")
    tasks = []
    for index in range(matches):
        seed = evolution._seed_value(PROXY_MASTER_SEED, eval_domain, index)
        job = evolution._build_tournament_job(placeholder, pool, seed, "proxy-ceiling", config)
        for mode in MODES:
            tasks.append({
                "mode": mode,
                "pool_domain": pool_domain,
                "eval_domain": eval_domain,
                "index": index,
                "job": job,
            })
    return tasks


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summaries = []
    for mode in MODES:
        mine = [row for row in rows if row["mode"] == mode]
        n = len(mine)
        wins = sum(row["won"] for row in mine)
        low, high = wilson(wins, n)
        reached = [row for row in mine if row["heads_up_reached"]]
        busted = [row for row in mine if row["busted"]]
        bust_stages: dict[str, int] = {}
        for row in busted:
            bb = row["bust_big_blind"]
            stage = "unknown" if bb is None else str(bb)
            bust_stages[stage] = bust_stages.get(stage, 0) + 1
        summaries.append({
            "mode": mode,
            "played": n,
            "wins": wins,
            "win_rate": wins / n if n else None,
            "wilson95": [low, high],
            "heads_up_entry_count": len(reached),
            "heads_up_entry_rate": len(reached) / n if n else None,
            "heads_up_conversion_count": sum(row["heads_up_converted"] for row in reached),
            "heads_up_conversion_rate": (
                sum(row["heads_up_converted"] for row in reached) / len(reached) if reached else None
            ),
            "bust_count": len(busted),
            "bust_rate": len(busted) / n if n else None,
            "bust_big_blind_counts": dict(sorted(bust_stages.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else -1)),
            "busts_at_bb_ge_160": sum(row["bust_big_blind"] is not None and row["bust_big_blind"] >= 160 for row in busted),
            "capped_non_wins": sum(row["capped"] and not row["won"] for row in mine),
            "invalid_actions": sum(row["invalid_actions"] for row in mine),
            "chip_conservation_failures": sum(not row["chip_conservation"] for row in mine),
            "mean_runtime_seconds": sum(row["runtime_seconds"] for row in mine) / max(1, n),
        })
    return {"summaries": summaries}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--matches", type=int, default=256, help="tables per mode per pool; use 256 for the report")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--output", type=Path, default=ROOT / "reports/evolution-90-ceiling-20261103/oracle-summary.json")
    parser.add_argument("--smoke", action="store_true", help="use 2 tables per mode and pool to check the harness")
    args = parser.parse_args()
    if args.workers < 1 or args.workers > 2:
        parser.error("workers must be between 1 and 2")
    matches = 2 if args.smoke else args.matches
    if not args.smoke and matches < 256:
        parser.error("the report run requires at least 256 tables per mode per pool")

    all_rows = []
    pool_eval_pairs = [
        ("proxy-heldout-pool-v1", "proxy-heldout-eval-v1"),
        ("proxy-heldout-pool-v2", "proxy-heldout-eval-v2"),
    ]
    for pool_domain, eval_domain in pool_eval_pairs:
        tasks = make_tasks(pool_domain, eval_domain, matches)
        print(f"Running {len(tasks)} paired tables for {pool_domain}/{eval_domain} with {args.workers} worker(s)", flush=True)
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as executor:
            for index, row in enumerate(executor.map(run_one, tasks, chunksize=1), 1):
                all_rows.append(row)
                if index % 16 == 0 or index == len(tasks):
                    print(f"  {pool_domain}: {index}/{len(tasks)} completed", flush=True)

    result = {
        "schema": "pokerbot-evolution-90-hole-oracle-v1",
        "protocol": {
            "proxy_master_seed": PROXY_MASTER_SEED,
            "matches_per_mode_per_pool": matches,
            "modes": list(MODES),
            "pool_eval_pairs": [list(pair) for pair in pool_eval_pairs],
            "pool_construction": "five fixed anchors plus 16 new_random genomes; each job sampled 7 opponents using evolution._build_tournament_job",
            "table_config": {
                "players": 8, "starting_stack": 2000,
                "big_blinds": [20, 40, 80, 160, 320, 640, 1280, 2560],
                "hands_per_level": 25, "max_hands": 200,
                "capped_tables_are_wins": False,
            },
            "oracle_information": "actual current hole cards of every non-folded opponent; no future board cards; folded hole cards are hidden from policy and treated as unknown for equity runouts",
            "leader_aware_stack_information": "the leader-aware variant additionally receives all current tournament stack sizes; this is visible at a physical poker table but is not part of the canonical hero-only observation",
            "equity_method": "exact when remaining board runouts <=1500; otherwise 128 deterministic Monte Carlo runouts per unique hand/board/opponent-hole state; multiway pot shares use split-pot equity",
            "policy_variants": {
                "hole-chip-ev": "call/fold uses true multiway equity versus actual live hands and current contestable-pot odds; aggressive value sizing by equity and stack/blind depth",
                "hole-leader-aware": "same oracle information and equity, but when currently sole chip leader requires at least 70% equity (and 8 points above pot odds) to call a large commitment of at least 25% of hand-start stack",
                "saved-reference": "canonical saved policy, paired on identical sampled opponents, seat, and deal",
            },
            "canonical_source_modified": False,
            "canonical_validation_or_confirmation_domains_or_results_read": False,
        },
        **summarize(all_rows),
        "rows": all_rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result["summaries"], indent=2), flush=True)
    print(f"wrote {args.output}", flush=True)


if __name__ == "__main__":
    main()
