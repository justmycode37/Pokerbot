"""Preflop hand classes and a compact, offline generated equity lookup."""

from __future__ import annotations

import json
from pathlib import Path


_TABLE_PATH = Path(__file__).resolve().parent.parent / "data" / "preflop_equity.json"
_RANK_VALUE = {rank: value for value, rank in enumerate("23456789TJQKA", 2)}


def hand_class(hole_cards: tuple[str, str] | list[str]) -> str:
    """Return a canonical Hold'em class such as ``AA``, ``AKs`` or ``AKo``."""
    first, second = hole_cards
    high, low = sorted((first[0], second[0]), key=_RANK_VALUE.__getitem__, reverse=True)
    if high == low:
        return high + low
    return high + low + ("s" if first[1] == second[1] else "o")


def _analytic_fallback(class_name: str) -> float:
    """Conservative approximate equity if the optional generated file is absent."""
    high = "23456789TJQKA".index(class_name[0]) + 2
    low = "23456789TJQKA".index(class_name[1]) + 2
    pair = high == low
    suited = len(class_name) == 3 and class_name[2] == "s"
    gap = max(0, high - low - 1)
    score = 0.31 + (high - 2) * 0.019 + (low - 2) * 0.010
    if pair:
        score += 0.15 + (high - 2) * 0.004
    if suited:
        score += 0.025
    if not pair and gap == 0:
        score += 0.018
    elif gap == 1:
        score += 0.008
    elif gap >= 4:
        score -= 0.012
    return min(0.88, max(0.30, score))


def _load_table() -> dict[str, float]:
    try:
        payload = json.loads(_TABLE_PATH.read_text(encoding="utf-8"))
        values = payload["equity_vs_one_random_opponent"]
        if payload.get("variant") != "no-limit-texas-holdem":
            return {}
        return {
            str(hand): float(equity)
            for hand, equity in values.items()
            if 0.0 <= float(equity) <= 1.0
        }
    except (OSError, ValueError, TypeError, KeyError):
        return {}


_EQUITIES = _load_table()


def preflop_equity(hole_cards: tuple[str, str] | list[str]) -> float:
    """Estimated equity against one uniformly random Hold'em opponent."""
    class_name = hand_class(hole_cards)
    return _EQUITIES.get(class_name, _analytic_fallback(class_name))


def opening_threshold(position: str) -> float:
    """Approximate position-aware opening cutoff on the random-opponent scale."""
    return {
        "UTG": 0.625,
        "MP": 0.605,
        "CO": 0.575,
        "BTN": 0.545,
        "SB": 0.565,
        "BB": 0.615,
    }.get(position, 0.625)
