"""Synthetic public observations for legality and local latency checks."""

import random

from .cards import RANKS, SUITS


def observations(count=200, seed=8128):
    rng = random.Random(seed)
    deck = [r + s for r in RANKS for s in SUITS]
    for i in range(count):
        board_length = (0, 3, 4, 5)[i % 4]
        cards = rng.sample(deck, board_length + 2)
        bb = 20
        stack = rng.choice((60, 200, 500, 2000, 10000))
        current = rng.choice((0, bb, 2 * bb))
        call = min(stack, rng.choice((0, bb, 3 * bb, 10 * bb)))
        high = current + stack
        low = min(high, current + call + max(bb, call))
        legal = ["fold", "call"] if call else ["check"]
        if high > current + call:
            legal.append("raise")
        active = rng.randrange(2, 9)
        yield {
            "hole_cards": cards[:2], "board": cards[2:],
            "pot": max(current + call, rng.randrange(2, 100) * bb),
            "to_call": call, "stack": stack, "current_bet": current,
            "min_raise_to": low, "max_raise_to": high, "big_blind": bb,
            "position": rng.choice(("UTG", "MP", "CO", "BTN", "SB", "BB")),
            "players_active": active, "players_to_act": rng.randrange(active),
            "table_size": 8, "legal_actions": legal, "history": [],
            "hand_id": f"synthetic-{i}", "seed": rng.randrange(2**31),
        }
