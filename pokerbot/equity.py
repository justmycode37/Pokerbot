"""Offline weighted-range equity, with explicit sampling assumptions.

Ranges are independent weighted distributions over two-card combinations,
conditioned jointly on card disjointness. They are modeling assumptions, not
knowledge of an opponent's actual cards or a solver-derived strategy.
"""

from __future__ import annotations

import random
from functools import lru_cache
from itertools import combinations
from typing import Sequence

from .cards import RANKS, SUITS, _evaluate_normalized, estimate_equity, normalize_card

DECK = tuple(r + s for r in RANKS for s in SUITS)


def hand_class(hole: Sequence[str]) -> str:
    a, b = sorted(hole, key=lambda c: RANKS.index(c[0]), reverse=True)
    return a[0] + b[0] + ("" if a[0] == b[0] else "s" if a[1] == b[1] else "o")


@lru_cache(maxsize=1)
def broad_opening_range() -> tuple[tuple[tuple[str, str], float], ...]:
    """A transparent illustrative range; not fitted to any Ivey hand."""
    weighted = []
    for hole in combinations(DECK, 2):
        a, b = sorted((RANKS.index(c[0]) + 2 for c in hole), reverse=True)
        suited = hole[0][1] == hole[1][1]
        premium = a == b and a >= 9 or a >= 13 and b >= 11 or a == 14 and b >= 10
        playable = a == b or a == 14 or suited and (a >= 10 and b >= 7 or a - b <= 2 and b >= 5) or a >= 12 and b >= 10
        # Nonzero weak-hand mass deliberately expresses model uncertainty.
        weighted.append((hole, 1.0 if premium else 0.45 if playable else 0.04))
    return tuple(weighted)


def weighted_equity(hole_cards, board=(), *, ranges, samples=1000, seed=0):
    """Return fractional showdown equity against explicit weighted ranges.

    Each range is a sequence of ((card1, card2), positive_weight). A whole
    opponent deal is rejected if cards collide, so no player's range is
    privileged by sequential resampling. Board runouts are then uniform.
    """
    hole = tuple(normalize_card(c) for c in hole_cards)
    board = tuple(normalize_card(c) for c in board)
    if len(hole) != 2 or len(board) not in (0, 3, 4, 5) or len(set(hole + board)) != len(hole + board):
        raise ValueError("require distinct hero cards and a valid Hold'em board")
    if type(samples) is not int or samples <= 0 or not 1 <= len(ranges) <= 7:
        raise ValueError("require positive samples and 1-7 opponent ranges")
    known = set(hole + board)
    populations, weights = [], []
    for distribution in ranges:
        population, mass = [], []
        for cards, weight in distribution:
            cards = tuple(normalize_card(c) for c in cards)
            if len(cards) != 2 or len(set(cards)) != 2:
                raise ValueError("range entries require two distinct cards")
            if not isinstance(weight, (float, int)) or not 0 < weight < float("inf"):
                raise ValueError("range weights must be positive finite numbers")
            if not known.intersection(cards):
                population.append(cards)
                mass.append(float(weight))
        if not population:
            raise ValueError("opponent range has no unblocked hands")
        populations.append(population)
        weights.append(mass)
    rng = random.Random(seed)
    # Bulk independent draws avoid recomputing cumulative weights per sample.
    pool_size = max(128, samples * 2)
    pools = [rng.choices(p, weights=w, k=pool_size) for p, w in zip(populations, weights)]
    cursor = 0
    total = 0.0
    attempts = 0
    accepted = 0
    while accepted < samples:
        attempts += 1
        if attempts > max(10000, samples * 100):
            raise ValueError("ranges have insufficient jointly compatible card assignments")
        if cursor == pool_size:
            pools = [rng.choices(p, weights=w, k=pool_size) for p, w in zip(populations, weights)]
            cursor = 0
        hands = [pool[cursor] for pool in pools]
        cursor += 1
        flat = [c for hand in hands for c in hand]
        if len(set(flat)) != len(flat):
            continue
        used = known.union(flat)
        runout = board + tuple(rng.sample([c for c in DECK if c not in used], 5 - len(board)))
        ranks = [_evaluate_normalized(hole + runout)]
        ranks.extend(_evaluate_normalized(hand + runout) for hand in hands)
        best = max(ranks)
        total += (1.0 / ranks.count(best)) if ranks[0] == best else 0.0
        accepted += 1
    return total / samples


def estimate_for_observation(obs, *, samples=1000, use_ranges=True) -> tuple[float, str]:
    if not use_ranges:
        return estimate_equity(obs.hole_cards, obs.board, opponents=obs.players_active - 1,
                               samples=samples, seed=obs.seed), "uniform_unknown_cards"
    # Conservative modeling: only preflop aggression changes the prior. There
    # is no claim that this simple likelihood models a particular opponent.
    preflop_raises = [h for h in obs.history if h.get("street") == "preflop"
                      and h.get("action") == "raise"
                      and (obs.player_id is None or h.get("player") != obs.player_id)]
    if not preflop_raises:
        return estimate_for_observation(obs, samples=samples, use_ranges=False)
    ranges = [broad_opening_range()] * (obs.players_active - 1)
    return weighted_equity(obs.hole_cards, obs.board, ranges=ranges,
                           samples=samples, seed=obs.seed), "illustrative_opening_ranges"
