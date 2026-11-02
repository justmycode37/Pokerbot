"""Exact river and conservative turn equity for unpaired four/five-suit boards.

The supported cases have a made flush.  On an unpaired river board with four
or five cards of one suit, every opponent hand that can tie or beat that flush
is determined by zero, one, or two cards of that suit.  The remaining cards
can therefore be counted combinatorially without sampling.
"""

from __future__ import annotations

from functools import lru_cache
from math import comb

from .cards import RANKS, SUITS
from .state import Observation


_RANK_VALUE = {rank: value for value, rank in enumerate(RANKS, start=2)}
_FULL_RANK_MASK = sum(1 << value for value in range(2, 15))
_DECK = tuple(rank + suit for rank in RANKS for suit in SUITS)
_STRAIGHT_WINDOWS = tuple(
    (high, sum(1 << rank for rank in range(high - 4, high + 1)))
    for high in range(14, 5, -1)
) + ((5, (1 << 14) | (1 << 2) | (1 << 3) | (1 << 4) | (1 << 5)),)


def _straight_high(rank_mask: int) -> int:
    for high, window in _STRAIGHT_WINDOWS:
        if rank_mask & window == window:
            return high
    return 0


@lru_cache(maxsize=4096)
def _suited_hand_rank(rank_mask: int) -> tuple[int, ...]:
    """Rank a guaranteed flush from the ranks available in one suit."""
    straight = _straight_high(rank_mask)
    if straight:
        return (8, straight)
    high_cards = []
    for rank in range(14, 1, -1):
        if rank_mask & (1 << rank):
            high_cards.append(rank)
            if len(high_cards) == 5:
                break
    return (5, *high_cards)


def _status(rank: tuple[int, ...], hero_rank: tuple[int, ...]) -> int:
    """Return -1 for losing, 0 for tying, and 1 for beating the hero."""
    return (rank > hero_rank) - (rank < hero_rank)


def _river_exact(
    hole_cards: tuple[str, str], board: tuple[str, ...], opponents: int
) -> float:
    """Exact uniform-card equity for a supported unpaired river board."""
    known = set(hole_cards + board)
    suit_counts = {suit: sum(card[1] == suit for card in board) for suit in SUITS}
    suit = max(suit_counts, key=suit_counts.get)
    board_suit_ranks = sum(
        1 << _RANK_VALUE[card[0]] for card in board if card[1] == suit
    )
    hero_suit_ranks = board_suit_ranks | sum(
        1 << _RANK_VALUE[card[0]] for card in hole_cards if card[1] == suit
    )
    hero_rank = _suited_hand_rank(hero_suit_ranks)

    known_suited_mask = board_suit_ranks | sum(
        1 << _RANK_VALUE[card[0]] for card in hole_cards if card[1] == suit
    )
    remaining_ranks = [
        rank for rank in range(2, 15) if not known_suited_mask & (1 << rank)
    ]
    suited_count = len(remaining_ranks)

    # On a five-suited board, an opponent with no private card of that suit
    # plays the board flush.  On a four-suited board their hand is below hero's
    # flush, even if their other cards make a pair, two pair, or a straight.
    if suit_counts[suit] == 5:
        board_rank = _suited_hand_rank(board_suit_ranks)
        empty_status = _status(board_rank, hero_rank)
    else:
        empty_status = -1

    one_status = []
    for rank in remaining_ranks:
        one_status.append(
            _status(_suited_hand_rank(board_suit_ranks | (1 << rank)), hero_rank)
        )
    pair_status = [[-1] * suited_count for _ in range(suited_count)]
    for first in range(suited_count):
        for second in range(first + 1, suited_count):
            pair_mask = (
                board_suit_ranks
                | (1 << remaining_ranks[first])
                | (1 << remaining_ranks[second])
            )
            straight = _straight_high(pair_mask)
            if straight:
                pair_status[first][second] = _status((8, straight), hero_rank)
            else:
                # Without a straight flush, the higher of the two private
                # suited cards determines the best flush comparison.
                pair_status[first][second] = one_status[second]

    # First exclude every single suited card that beats hero. Conditional on
    # their absence, only an opponent holding a particular two-card straight
    # flush completion can still win. Count those pair events with
    # inclusion-exclusion rather than enumerating every opponent's deal.
    total_unknown = 52 - len(known)
    bad_cards = sum(status > 0 for status in one_status)
    safe_count = total_unknown - bad_cards
    if safe_count < 2 * opponents:
        return 0.0
    no_bad_card = comb(safe_count, 2 * opponents) / comb(total_unknown, 2 * opponents)
    safe_mask = sum(1 << i for i, status in enumerate(one_status) if status <= 0)
    adjacency = [0] * suited_count
    for first in range(suited_count):
        for second in range(first + 1, suited_count):
            if safe_mask & (1 << first) and safe_mask & (1 << second) and pair_status[first][second] > 0:
                adjacency[first] |= 1 << second
                adjacency[second] |= 1 << first

    @lru_cache(maxsize=None)
    def matching_counts(mask: int) -> tuple[int, ...]:
        # Intersections of forbidden pair events are possible only for disjoint
        # pairs assigned to different opponents. Return graph matching counts
        # by number of edges; a shared physical card cannot be dealt twice.
        if not mask:
            return (1,)
        bit = mask & -mask
        vertex = bit.bit_length() - 1
        rest = mask ^ bit
        counts = list(matching_counts(rest))
        neighbors = adjacency[vertex] & rest
        while neighbors:
            other = neighbors & -neighbors
            subcounts = matching_counts(rest ^ other)
            if len(counts) < len(subcounts) + 1:
                counts.extend([0] * (len(subcounts) + 1 - len(counts)))
            for size, value in enumerate(subcounts):
                counts[size + 1] += value
            neighbors ^= other
        return tuple(counts)

    counts = matching_counts(safe_mask)
    no_bad_pair = 1.0
    coefficient = 1.0
    for size in range(1, min(opponents, len(counts) - 1) + 1):
        # (opponents)_size / product(C(safe_count - 2*k, 2))
        coefficient *= (opponents - size + 1) / comb(safe_count - 2 * (size - 1), 2)
        no_bad_pair += (-1 if size % 2 else 1) * counts[size] * coefficient
    share_divisor = opponents + 1 if empty_status == 0 else 1
    return min(1.0, max(0.0, no_bad_card * no_bad_pair / share_divisor))


def _safe_river_floor_from_masks(
    board_suit_ranks: int,
    hole_suit_ranks: int,
    suited_board_count: int,
    opponents: int,
) -> float:
    """A lower bound for one final river, using precomputed suit rank masks."""
    hero_suit_ranks = board_suit_ranks | hole_suit_ranks
    hero_rank = _suited_hand_rank(hero_suit_ranks)
    remaining_suit_mask = _FULL_RANK_MASK & ~hero_suit_ranks
    poison_mask = 0
    bits = remaining_suit_mask
    while bits:
        bit = bits & -bits
        if _status(_suited_hand_rank(board_suit_ranks | bit), hero_rank) >= 0:
            poison_mask |= bit
        bits ^= bit

    # A two-card straight flush may beat hero even when neither card would
    # produce a competitive flush alone.  Exclude both cards in that case.
    for high, window in _STRAIGHT_WINDOWS:
        straight_rank = (8, high)
        if straight_rank <= hero_rank:
            continue
        missing = window & ~board_suit_ranks
        if missing.bit_count() == 2 and missing & remaining_suit_mask == missing:
            poison_mask |= missing

    poison_count = poison_mask.bit_count()
    opponent_cards = opponents * 2
    if 45 - poison_count < opponent_cards:
        return 0.0
    no_poison = comb(45 - poison_count, opponent_cards) / comb(45, opponent_cards)

    if suited_board_count == 5 and _suited_hand_rank(board_suit_ranks) == hero_rank:
        # Opponents without a dangerous suit card can all play the same board
        # flush.  Assume every opponent ties for a safe lower bound.
        return no_poison / (opponents + 1)
    return no_poison


def suited_board_equity(obs: Observation) -> float | None:
    """Estimate uniform-card equity on made-flush four/five-suit textures.

    River observations are exact for unpaired five-card boards with exactly
    four or five public cards of one suit, provided hero also has a flush.
    A four-card turn board returns a conservative lower bound for a low flush
    whose private suited ranks are all below the public suited ranks, or for a
    made straight flush.  Paired river runouts contribute zero for a flush;
    for a straight flush they are counted because full houses and quads cannot
    beat it. Unsupported textures return ``None`` so callers can keep their
    existing estimate.
    """
    if not isinstance(obs, Observation) or not 2 <= obs.players_active <= 8:
        return None
    if len(obs.board) not in (4, 5):
        return None
    if len(set(obs.hole_cards + obs.board)) != len(obs.hole_cards + obs.board):
        return None
    if len(set(card[0] for card in obs.board)) != len(obs.board):
        return None

    board_suits = {suit: sum(card[1] == suit for card in obs.board) for suit in SUITS}
    dominant_suit = max(board_suits, key=board_suits.get)
    count = board_suits[dominant_suit]
    if (len(obs.board) == 5 and count not in (4, 5)) or (
        len(obs.board) == 4 and count != 4
    ):
        return None
    hero_suit_mask = sum(
        1 << _RANK_VALUE[card[0]]
        for card in obs.board + obs.hole_cards
        if card[1] == dominant_suit
    )
    if hero_suit_mask.bit_count() < 5:
        return None
    hero_is_straight_flush = _suited_hand_rank(hero_suit_mask)[0] == 8
    opponents = obs.players_active - 1

    if len(obs.board) == 5:
        return _river_exact(obs.hole_cards, obs.board, opponents)

    known = set(obs.hole_cards + obs.board)
    board_ranks = {card[0] for card in obs.board}
    board_suit_ranks = sum(
        1 << _RANK_VALUE[card[0]] for card in obs.board if card[1] == dominant_suit
    )
    hole_suit_ranks = sum(
        1 << _RANK_VALUE[card[0]] for card in obs.hole_cards if card[1] == dominant_suit
    )
    if not hero_is_straight_flush:
        private_suit_ranks = hero_suit_mask & ~board_suit_ranks
        lowest_public_suit_rank = (board_suit_ranks & -board_suit_ranks).bit_length() - 1
        if private_suit_ranks.bit_length() - 1 >= lowest_public_suit_rank:
            # Higher turn flushes can keep substantial equity on paired river
            # runouts; the low-flush bound intentionally discards those cases.
            return None
    possible_rivers = [card for card in _DECK if card not in known]
    floor_total = 0.0
    off_suit_count = 0
    for river in possible_rivers:
        if river[1] == dominant_suit:
            river_mask = 1 << _RANK_VALUE[river[0]]
            floor_total += _safe_river_floor_from_masks(
                board_suit_ranks | river_mask,
                hole_suit_ranks,
                5,
                opponents,
            )
        elif river[0] not in board_ranks or hero_is_straight_flush:
            # Every unpaired off-suit river leaves the same four public suit
            # cards and removes one non-suited card from the unknown deck.
            # For a made straight flush, paired boards can also be counted:
            # full houses and quads cannot beat category eight.
            off_suit_count += 1
    if off_suit_count:
        floor_total += off_suit_count * _safe_river_floor_from_masks(
            board_suit_ranks,
            hole_suit_ranks,
            4,
            opponents,
        )
    return floor_total / len(possible_rivers)
