"""Texas Hold'em card parsing, hand ranking, and Monte Carlo equity.

Cards are written as a rank followed by a suit (for example ``As`` or
``10h``). Ranks are ``23456789TJQKA`` and suits are ``cdhs``. ``rank_hand``
accepts five to seven distinct cards and returns a lexicographically
comparable tuple; the first value is the category (0 for high card through 8
for straight flush).

``estimate_equity`` samples unknown cards uniformly from the remaining deck.
It does not accept weighted opponent ranges yet: ``opponent_ranges`` must be
``None``. The result is the hero's average pot share, so a tie among *n*
players contributes ``1 / n`` to that sample.
"""

from __future__ import annotations

import random
from numbers import Integral
from typing import Optional, Sequence, Tuple


RANKS = "23456789TJQKA"
SUITS = "cdhs"
_RANK_VALUE = {rank: value for value, rank in enumerate(RANKS, start=2)}
_DECK = tuple(rank + suit for rank in RANKS for suit in SUITS)


def normalize_card(card: str) -> str:
    """Return a canonical card code, such as ``"As"`` or ``"Th"``.

    Rank and suit letters are case-insensitive. The common ``10`` spelling is
    accepted and normalized to ``T``. Surrounding whitespace is ignored.
    """
    if not isinstance(card, str):
        raise TypeError("card must be a string")

    value = card.strip()
    if len(value) == 3 and value[:2].lower() == "10":
        rank, suit = "T", value[2].lower()
    elif len(value) == 2:
        rank, suit = value[0].upper(), value[1].lower()
    else:
        raise ValueError("card must be a rank and suit, such as 'As' or '10h'")

    if rank not in RANKS or suit not in SUITS:
        raise ValueError("card must use a rank in 23456789TJQKA and suit in cdhs")
    return rank + suit


def _normalize_cards(
    cards: Sequence[str], *, label: str, minimum: int, maximum: int
) -> Tuple[str, ...]:
    if isinstance(cards, (str, bytes)) or not isinstance(cards, Sequence):
        raise TypeError("%s must be a sequence of card strings" % label)
    if not minimum <= len(cards) <= maximum:
        if minimum == maximum:
            raise ValueError("%s must contain exactly %d cards" % (label, minimum))
        raise ValueError(
            "%s must contain between %d and %d cards"
            % (label, minimum, maximum)
        )

    normalized = tuple(normalize_card(card) for card in cards)
    if len(set(normalized)) != len(normalized):
        raise ValueError("%s contains duplicate cards" % label)
    return normalized


def _straight_high(rank_mask: int) -> int:
    """Return the high rank of the best straight in a rank bit mask, or 0."""
    for high in range(14, 5, -1):
        needed = 0b11111 << (high - 4)
        if rank_mask & needed == needed:
            return high
    # A-2-3-4-5 (the ace is low only in this one straight).
    wheel = (1 << 14) | (1 << 2) | (1 << 3) | (1 << 4) | (1 << 5)
    return 5 if rank_mask & wheel == wheel else 0


def _evaluate_normalized(cards: Sequence[str]) -> Tuple[int, ...]:
    """Evaluate already-canonical, already-validated five-to-seven cards."""
    counts = [0] * 15
    suit_masks = {suit: 0 for suit in SUITS}
    rank_mask = 0
    for card in cards:
        rank = _RANK_VALUE[card[0]]
        suit = card[1]
        counts[rank] += 1
        rank_mask |= 1 << rank
        suit_masks[suit] |= 1 << rank

    # Straight flush.
    for suit_mask in suit_masks.values():
        straight_high = _straight_high(suit_mask)
        if straight_high:
            return (8, straight_high)

    ranks_by_count = sorted(
        (rank for rank in range(2, 15) if counts[rank]),
        key=lambda rank: (counts[rank], rank),
        reverse=True,
    )

    # Four of a kind.
    quads = next((rank for rank in ranks_by_count if counts[rank] == 4), 0)
    if quads:
        kicker = max(rank for rank in range(2, 15) if rank != quads and counts[rank])
        return (7, quads, kicker)

    # Full house. A second three-of-a-kind can supply the pair.
    trips = sorted((rank for rank in ranks_by_count if counts[rank] >= 3), reverse=True)
    if trips:
        pair_ranks = [rank for rank in ranks_by_count if rank != trips[0] and counts[rank] >= 2]
        if pair_ranks:
            return (6, trips[0], max(pair_ranks))

    # Flush: keep the best five ranks, even when six or seven cards share a suit.
    flushes = []
    for suit_mask in suit_masks.values():
        if suit_mask.bit_count() >= 5:
            flushes.append(
                tuple(
                    rank
                    for rank in range(14, 1, -1)
                    if suit_mask & (1 << rank)
                )[:5]
            )
    if flushes:
        return (5,) + max(flushes)

    # Straight.
    straight_high = _straight_high(rank_mask)
    if straight_high:
        return (4, straight_high)

    # Three of a kind.
    if trips:
        triple = trips[0]
        kickers = sorted(
            (rank for rank in range(2, 15) if rank != triple and counts[rank]),
            reverse=True,
        )
        return (3, triple) + tuple(kickers[:2])

    pairs = sorted((rank for rank in range(2, 15) if counts[rank] == 2), reverse=True)
    if len(pairs) >= 2:
        kicker = max(
            rank for rank in range(2, 15) if rank not in pairs[:2] and counts[rank]
        )
        return (2, pairs[0], pairs[1], kicker)
    if pairs:
        pair = pairs[0]
        kickers = sorted(
            (rank for rank in range(2, 15) if rank != pair and counts[rank]),
            reverse=True,
        )
        return (1, pair) + tuple(kickers[:3])

    return (0,) + tuple(
        sorted((rank for rank in range(2, 15) if counts[rank]), reverse=True)[:5]
    )


def rank_hand(cards: Sequence[str]) -> Tuple[int, ...]:
    """Rank a five-to-seven-card poker hand; higher tuples always win.

    The category values are high card 0, pair 1, two pair 2, three of a kind
    3, straight 4, flush 5, full house 6, four of a kind 7, and straight flush
    8. Tiebreak ranks follow each category in descending comparison order.
    """
    normalized = _normalize_cards(cards, label="cards", minimum=5, maximum=7)
    return _evaluate_normalized(normalized)


def estimate_equity(
    hole_cards: Sequence[str],
    board: Sequence[str] = (),
    *,
    opponents: int = 1,
    samples: int = 1000,
    seed: int = 0,
    opponent_ranges: Optional[object] = None,
) -> float:
    """Estimate Hold'em showdown equity by uniformly sampling unknown cards.

    ``hole_cards`` must contain two cards, ``board`` zero to five, and
    ``opponents`` one to seven. Each sample deals all opponents' hole cards
    and any missing community cards from the remaining 52-card deck without
    replacement. ``opponent_ranges`` is reserved for a future range API and
    must currently be ``None``.
    """
    hole = _normalize_cards(hole_cards, label="hole_cards", minimum=2, maximum=2)
    community = _normalize_cards(board, label="board", minimum=0, maximum=5)
    if set(hole).intersection(community):
        raise ValueError("hole_cards and board contain duplicate cards")

    if isinstance(opponents, bool) or not isinstance(opponents, Integral):
        raise TypeError("opponents must be an integer from 1 through 7")
    opponents = int(opponents)
    if not 1 <= opponents <= 7:
        raise ValueError("opponents must be from 1 through 7")

    if isinstance(samples, bool) or not isinstance(samples, Integral):
        raise TypeError("samples must be a positive integer")
    samples = int(samples)
    if samples <= 0:
        raise ValueError("samples must be a positive integer")

    if isinstance(seed, bool) or not isinstance(seed, Integral):
        raise TypeError("seed must be an integer")
    seed = int(seed)

    if opponent_ranges is not None:
        raise ValueError("opponent_ranges is not supported; pass None")

    known = set(hole + community)
    remaining = [card for card in _DECK if card not in known]
    cards_to_draw = 2 * opponents + 5 - len(community)
    rng = random.Random(seed)
    equity_total = 0.0

    for _ in range(samples):
        dealt = rng.sample(remaining, cards_to_draw)
        final_board = community + tuple(dealt[2 * opponents :])
        hero_rank = _evaluate_normalized(hole + final_board)
        best_rank = hero_rank
        best_count = 1
        hero_is_winning = True

        for index in range(opponents):
            opponent_hole = tuple(dealt[2 * index : 2 * index + 2])
            opponent_rank = _evaluate_normalized(opponent_hole + final_board)
            if opponent_rank > best_rank:
                best_rank = opponent_rank
                best_count = 1
                hero_is_winning = False
            elif opponent_rank == best_rank:
                best_count += 1

        if hero_is_winning:
            equity_total += 1.0 / best_count

    return equity_total / samples
