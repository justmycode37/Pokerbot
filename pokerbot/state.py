"""Validate the public, hero-only observation at the strategy boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .cards import normalize_card

STREETS = {0: "preflop", 3: "flop", 4: "turn", 5: "river"}
ACTIONS = frozenset({"fold", "check", "call", "raise"})
POSITIONS = frozenset({"UTG", "MP", "CO", "BTN", "SB", "BB"})


@dataclass(frozen=True)
class Observation:
    hole_cards: tuple[str, str]
    board: tuple[str, ...]
    pot: int
    to_call: int
    stack: int
    current_bet: int
    min_raise_to: int
    max_raise_to: int
    big_blind: int
    position: str
    players_active: int
    players_to_act: int
    legal_actions: frozenset[str]
    street: str
    seed: int
    history: tuple[dict, ...]
    player_id: str | int | None = None
    contestable_pot: int = 0
    table_size: int = 8

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Observation":
        if not isinstance(raw, Mapping):
            raise ValueError("observation must be an object")

        def integer(key: str, default=None, minimum=0) -> int:
            value = raw.get(key, default)
            if type(value) is not int or value < minimum:
                raise ValueError(f"{key} must be an integer >= {minimum}")
            return value

        hole = raw.get("hole_cards")
        board = raw.get("board")
        if not isinstance(hole, (list, tuple)) or len(hole) != 2:
            raise ValueError("hole_cards must contain exactly two cards")
        if not isinstance(board, (list, tuple)) or len(board) not in STREETS:
            raise ValueError("board must contain 0, 3, 4, or 5 cards")
        hole = tuple(normalize_card(card) for card in hole)
        board = tuple(normalize_card(card) for card in board)
        if len(set(hole + board)) != len(hole + board):
            raise ValueError("known cards must be distinct")
        street = STREETS[len(board)]
        if raw.get("street", street) != street:
            raise ValueError("street disagrees with board length")
        position = raw.get("position")
        if position not in POSITIONS:
            raise ValueError("unrecognized position")
        legal = raw.get("legal_actions")
        if (not isinstance(legal, (list, tuple)) or not legal
                or any(not isinstance(a, str) or a not in ACTIONS for a in legal)):
            raise ValueError("legal_actions must be a nonempty list of known actions")
        legal = frozenset(legal)
        stack = integer("stack", minimum=1)
        to_call = integer("to_call")
        if to_call > stack:
            raise ValueError("to_call must be capped by remaining stack")
        if ("check" in legal and to_call) or ("call" in legal and not to_call):
            raise ValueError("check/call legality disagrees with to_call")
        if not legal.intersection({"check", "call", "fold"}):
            raise ValueError("at least one passive action must be legal")
        current = integer("current_bet")
        low = integer("min_raise_to", 0)
        high = integer("max_raise_to", 0)
        if "raise" in legal and not current + to_call < low <= high <= current + stack:
            raise ValueError("raise bounds must be legal total street bets")
        pot = integer("pot")
        contestable = integer("contestable_pot", pot)
        if contestable > pot:
            raise ValueError("contestable_pot cannot exceed pot")
        active = integer("players_active", minimum=2)
        table_size = integer("table_size", max(8, active), minimum=2)
        if not active <= table_size <= 8:
            raise ValueError("require 2 <= players_active <= table_size <= 8")
        to_act = integer("players_to_act", active - 1)
        if to_act >= active:
            raise ValueError("players_to_act must exclude hero")
        history = raw.get("history", [])
        if not isinstance(history, (list, tuple)) or any(not isinstance(h, dict) for h in history):
            raise ValueError("history must be a list of public action objects")
        # Whitelist visible action fields. Outcomes/labels cannot reach the policy.
        visible_history = tuple({k: h[k] for k in ("street", "player", "action", "amount", "added", "position") if k in h} for h in history)
        player_id = raw.get("player_id")
        if player_id is not None and type(player_id) not in (str, int):
            raise ValueError("player_id must be a string or integer")
        seed = raw.get("seed", 0)
        if type(seed) is not int:
            raise ValueError("seed must be an integer")
        return cls(hole, board, pot, to_call, stack, current, low, high,
                   integer("big_blind", minimum=1), position, active, to_act,
                   legal, street, seed, visible_history, player_id,
                   contestable, table_size)

    @property
    def pot_odds(self) -> float:
        return self.to_call / max(1, self.contestable_pot + self.to_call)

    def raise_to(self, target: float) -> int:
        return max(self.min_raise_to, min(self.max_raise_to, round(target)))
