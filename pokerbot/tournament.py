"""Reusable local no-limit hold'em tournament simulation.

This is an illustrative local tournament wrapper around :mod:`simulation`; it
does not represent any official event rules. The button follows a moving-button
rule on the permanent original-seat ring: after each hand it advances clockwise
to the next player with chips, skipping eliminated seats. There is no dead
button. For a multiway-to-heads-up transition where the button busts and the
prior big blind survives, that big blind takes the heads-up button to avoid a
back-to-back big blind. In heads-up play the button is the small blind and is
dealt in engine seat order ``[BB, BTN/SB]``; multiway engine order is
``[SB, BB, ..., BTN]``.
"""

from __future__ import annotations

import hashlib
import math
import statistics
from collections.abc import Sequence
from functools import lru_cache
from numbers import Real
from typing import Any

from .simulation import Policy, _play_hand


DEFAULT_BIG_BLINDS = (20, 40, 80, 160, 320, 640, 1280, 2560)


def _require_integer(value: Any, name: str, minimum: int) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a finite number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _validate_payouts(payouts: Sequence[Real], expected_length: int | None = None) -> list[float]:
    if isinstance(payouts, (str, bytes)) or not isinstance(payouts, Sequence):
        raise TypeError("payouts must be a sequence of finite numbers")
    if expected_length is not None and len(payouts) != expected_length:
        raise ValueError("payouts length must match the number of players")
    values = [_number(value, f"payouts[{index}]") for index, value in enumerate(payouts)]
    if any(value < 0 for value in values):
        raise ValueError("payouts must be nonnegative")
    if any(left < right for left, right in zip(values, values[1:])):
        raise ValueError("payouts must be nonincreasing")
    if not math.isfinite(sum(values)):
        raise ValueError("total payouts must be finite")
    return values


def _icm_details(
    stacks: Sequence[Real], payouts: Sequence[Real]
) -> tuple[list[float], list[float]]:
    """Return ICM expected payouts and expected places for positive stacks."""
    if isinstance(stacks, (str, bytes)) or not isinstance(stacks, Sequence) or not stacks:
        raise TypeError("stacks must be a nonempty sequence of positive numbers")
    stack_values = [_number(value, f"stacks[{index}]") for index, value in enumerate(stacks)]
    if any(value <= 0 for value in stack_values):
        raise ValueError("ICM stacks must all be positive")
    payout_values = _validate_payouts(payouts)
    if len(payout_values) > len(stack_values):
        raise ValueError("payouts cannot contain more places than there are stacks")

    player_count = len(stack_values)

    @lru_cache(maxsize=None)
    def solve(remaining_mask: int) -> tuple[tuple[float, ...], tuple[float, ...]]:
        if remaining_mask == 0:
            return (0.0,) * player_count, (0.0,) * player_count
        remaining = [
            index for index in range(player_count) if remaining_mask & (1 << index)
        ]
        place = player_count - len(remaining) + 1
        # Normalize separately in each subproblem: globally scaling can lose
        # tiny stacks that become relevant after a much larger stack finishes.
        scale = max(stack_values[index] for index in remaining)
        normalized = {index: stack_values[index] / scale for index in remaining}
        total = math.fsum(normalized.values())
        equities = [0.0] * player_count
        expected_finish = [0.0] * player_count
        for index in remaining:
            probability = normalized[index] / total
            future_equities, future_finish = solve(remaining_mask ^ (1 << index))
            if place <= len(payout_values):
                equities[index] += probability * payout_values[place - 1]
            expected_finish[index] += probability * place
            for other in remaining:
                if other != index:
                    equities[other] += probability * future_equities[other]
                    expected_finish[other] += probability * future_finish[other]
        return tuple(equities), tuple(expected_finish)

    equities, expected_finish = solve((1 << player_count) - 1)
    return list(equities), list(expected_finish)


def icm_equities(stacks: Sequence[Real], payouts: Sequence[Real]) -> list[float]:
    """Return each player's exact independent-chip-model expected payout.

    ``stacks`` must contain positive chip counts. ``payouts`` is ordered from
    first place downward; it can be shorter than the field, in which case
    places below its length pay zero. With the tournament's 2–8-player limit,
    exhaustive ICM enumeration is small and exact up to floating-point sums.
    """
    return _icm_details(stacks, payouts)[0]


class _TournamentPolicy:
    """Translate engine-local seat IDs into stable anonymous tournament IDs."""

    __slots__ = ("policy", "original_index", "seat_order", "hand_index", "action_prices")

    def __init__(self, policy: Policy, original_index: int, seat_order: Sequence[int], *, hand_index: int = 0, action_prices: dict[int, int] | None = None):
        self.policy = policy
        self.original_index = original_index
        self.seat_order = tuple(seat_order)
        self.hand_index = hand_index
        self.action_prices = {} if action_prices is None else action_prices

    def __call__(self, observation: dict[str, Any]) -> dict[str, Any]:
        # Record only this actor's public price. A price is shared with other
        # policies only after its corresponding action enters public history.
        self.action_prices[len(observation["history"])] = observation["to_call"]
        translated = dict(observation)
        translated["player_id"] = f"p{self.original_index}"
        translated["hand_index"] = self.hand_index
        translated["table_player_ids"] = [f"p{index}" for index in self.seat_order]
        history = []
        for action_index, action in enumerate(observation["history"]):
            item = dict(action)
            if action_index in self.action_prices:
                item["to_call"] = self.action_prices[action_index]
            engine_player = item.get("player")
            if isinstance(engine_player, str) and engine_player.startswith("p"):
                try:
                    engine_seat = int(engine_player[1:])
                except ValueError:
                    engine_seat = -1
                if 0 <= engine_seat < len(self.seat_order):
                    item["player"] = f"p{self.seat_order[engine_seat]}"
            history.append(item)
        translated["history"] = history
        return self.policy(translated)


def _next_live_after(seat: int, stacks: Sequence[int]) -> int:
    count = len(stacks)
    for distance in range(1, count + 1):
        candidate = (seat + distance) % count
        if stacks[candidate] > 0:
            return candidate
    raise RuntimeError("cannot advance the button without a live player")


def _seat_order(button: int, stacks: Sequence[int]) -> list[int]:
    """Produce ``[SB, BB, ..., BTN]`` or heads-up ``[BB, BTN/SB]``."""
    live_count = sum(stack > 0 for stack in stacks)
    if live_count < 2:
        raise ValueError("a hand needs at least two players with chips")
    if stacks[button] <= 0:
        raise RuntimeError("the button must be assigned to a live player")
    clockwise = [
        (button + distance) % len(stacks)
        for distance in range(1, len(stacks) + 1)
        if stacks[(button + distance) % len(stacks)] > 0
    ]
    if live_count == 2:
        return [next(seat for seat in clockwise if seat != button), button]
    return clockwise


def _hand_seed(seed: int, hand_number: int) -> int:
    material = f"pokerbot-tournament-v1\0{seed}\0{hand_number}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def _engine_player_to_original(player_id: Any, seat_order: Sequence[int]) -> int | None:
    if not isinstance(player_id, str) or not player_id.startswith("p"):
        return None
    try:
        seat = int(player_id[1:])
    except ValueError:
        return None
    if not 0 <= seat < len(seat_order):
        return None
    return seat_order[seat]


def _elimination_points(
    indices: Sequence[int],
    start_stacks: Sequence[int],
    finish: list[float | None],
    points: list[float | None],
    next_worst_place: int,
    payouts: Sequence[float],
) -> int:
    """Assign simultaneous eliminations bottom-up, splitting exact stack ties."""
    # Allocate from the worst remaining place upward, so lower entering stacks
    # receive the worse rank when several players bust in one hand.
    ordered = sorted(indices, key=lambda index: start_stacks[index])
    cursor = next_worst_place
    offset = 0
    while offset < len(ordered):
        tied_stack = start_stacks[ordered[offset]]
        end = offset + 1
        while end < len(ordered) and start_stacks[ordered[end]] == tied_stack:
            end += 1
        tied = ordered[offset:end]
        occupied_places = list(range(cursor - len(tied) + 1, cursor + 1))
        mean_place = sum(occupied_places) / len(occupied_places)
        mean_points = sum(payouts[place - 1] for place in occupied_places) / len(occupied_places)
        for index in tied:
            finish[index] = float(mean_place)
            points[index] = float(mean_points)
        cursor -= len(tied)
        offset = end
    return cursor


def play_tournament(
    policies: Sequence[Policy],
    *,
    seed: int = 0,
    stacks: int | Sequence[int] = 2000,
    big_blinds: Sequence[int] = DEFAULT_BIG_BLINDS,
    hands_per_level: int = 25,
    max_hands: int = 200,
    payouts: Sequence[Real] | None = None,
    strict: bool = True,
    trace: bool = False,
) -> dict[str, Any]:
    """Play a reproducible local NLHE tournament with two through eight bots.

    Policies are ordered by permanent original index. At each hand they are
    seated according to the current moving button on that original-seat ring;
    each call to the hand engine creates fresh PokerKit table state. If a
    policy object has a zero-argument ``reset()`` hook, it is called once before
    the tournament starts.

    The default 20/40 doubling schedule and descending ``N..1`` points are
    illustrative. Public rules announce 10/20 starting blinds increasing every
    25 hands, while the event variant and payout schedule may differ. Pass
    explicit ``big_blinds`` and ``payouts`` for a different scenario.

    ``finish`` is a one-based place, with equal-stack simultaneous eliminations
    sharing their occupied places. If hand-capped, survivors receive exact ICM
    expected places and payout points for the remaining top places. ``points``
    are payouts (not chips); ``final_stacks`` always conserve starting chips.
    Latency p95 uses nearest-rank; wall-clock latency metrics naturally vary
    between otherwise reproducible runs.
    """
    if not isinstance(policies, Sequence) or isinstance(policies, (str, bytes)):
        raise TypeError("policies must be a sequence of callables")
    player_count = len(policies)
    if not 2 <= player_count <= 8:
        raise ValueError("policies must contain between 2 and 8 players")
    if any(not callable(policy) for policy in policies):
        raise TypeError("every policy must be callable")
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    if type(strict) is not bool or type(trace) is not bool:
        raise TypeError("strict and trace must be booleans")
    hands_per_level = _require_integer(hands_per_level, "hands_per_level", 1)
    max_hands = _require_integer(max_hands, "max_hands", 1)

    if type(stacks) is int:
        initial_stacks = [_require_integer(stacks, "stacks", 1)] * player_count
    elif isinstance(stacks, Sequence) and not isinstance(stacks, (str, bytes)):
        if len(stacks) != player_count:
            raise ValueError("stack sequence length must match the number of policies")
        initial_stacks = [
            _require_integer(value, f"stacks[{index}]", 1)
            for index, value in enumerate(stacks)
        ]
    else:
        raise TypeError("stacks must be a positive integer or a sequence of positive integers")

    if (
        isinstance(big_blinds, (str, bytes))
        or not isinstance(big_blinds, Sequence)
        or not big_blinds
    ):
        raise TypeError("big_blinds must be a nonempty sequence of positive integers")
    blind_schedule = [
        _require_integer(value, f"big_blinds[{index}]", 1)
        for index, value in enumerate(big_blinds)
    ]
    if any(left >= right for left, right in zip(blind_schedule, blind_schedule[1:])):
        raise ValueError("big_blinds must be strictly increasing")

    payouts_were_defaulted = payouts is None
    payout_values = (
        [float(place) for place in range(player_count, 0, -1)]
        if payouts is None
        else _validate_payouts(payouts, player_count)
    )

    reset_policy_ids: set[int] = set()
    for policy in policies:
        if id(policy) in reset_policy_ids:
            continue
        reset_policy_ids.add(id(policy))
        reset = getattr(policy, "reset", None)
        if callable(reset):
            reset()

    current_stacks = list(initial_stacks)
    finish: list[float | None] = [None] * player_count
    points: list[float | None] = [None] * player_count
    metrics = [{"decisions": 0, "latencies_ns": [], "invalid_actions": 0}
               for _ in range(player_count)]
    trace_rows: list[dict[str, Any]] = []
    hands_played = 0
    invalid_total = 0
    next_worst_place = player_count
    button = player_count - 1

    while sum(stack > 0 for stack in current_stacks) > 1 and hands_played < max_hands:
        seat_order = _seat_order(button, current_stacks)
        active_count = len(seat_order)
        big_blind = blind_schedule[min(hands_played // hands_per_level, len(blind_schedule) - 1)]
        small_blind = max(1, big_blind // 2)
        hand_starts = list(current_stacks)
        engine_stacks = [hand_starts[index] for index in seat_order]
        action_prices: dict[int, int] = {}
        hand_policies = [
            _TournamentPolicy(policies[index], index, seat_order, hand_index=hands_played, action_prices=action_prices)
            for index in seat_order
        ]
        hand_result, policy_metrics = _play_hand(
            hand_policies,
            seed=_hand_seed(seed, hands_played),
            stacks=engine_stacks,
            big_blind=big_blind,
            strict=strict,
            include_trace=False,
        )
        engine_final = hand_result["stacks"]
        if len(engine_final) != active_count:
            raise RuntimeError("hand engine returned the wrong number of stacks")
        engine_payoffs = hand_result.get("payoffs")
        if not isinstance(engine_payoffs, Sequence) or len(engine_payoffs) != active_count:
            raise RuntimeError("hand engine returned the wrong number of payoffs")
        for seat, original_index in enumerate(seat_order):
            current_stacks[original_index] = _require_integer(
                engine_final[seat], f"hand result stacks[{seat}]", 0
            )
            if engine_payoffs[seat] != engine_final[seat] - engine_stacks[seat]:
                raise RuntimeError("hand engine payoff does not match its settled stack")
        if sum(current_stacks) != sum(initial_stacks):
            raise RuntimeError("tournament chip conservation failed after a hand")
        if sum(hand_result.get("payoffs", ())) != 0:
            raise RuntimeError("hand engine returned nonconserving payoffs")

        for item in policy_metrics:
            seat = item.get("seat")
            if type(seat) is not int or not 0 <= seat < active_count:
                raise RuntimeError("hand engine returned invalid policy metrics seat")
            player_metrics = metrics[seat_order[seat]]
            player_metrics["decisions"] += 1
            latency = item.get("latency_ns")
            if type(latency) is int and latency >= 0:
                player_metrics["latencies_ns"].append(latency)

        hand_invalid = hand_result.get("invalid_actions", [])
        invalid_total += len(hand_invalid)
        for item in hand_invalid:
            original_index = _engine_player_to_original(item.get("player_id"), seat_order)
            if original_index is not None:
                metrics[original_index]["invalid_actions"] += 1

        busted = [index for index in seat_order if current_stacks[index] == 0]
        if busted:
            next_worst_place = _elimination_points(
                busted, hand_starts, finish, points, next_worst_place, payout_values
            )

        hands_played += 1
        if trace:
            actions = []
            for action_index, action in enumerate(hand_result.get("actions", [])):
                translated_action = dict(action)
                if action_index in action_prices:
                    translated_action["to_call"] = action_prices[action_index]
                original_index = _engine_player_to_original(action.get("player"), seat_order)
                if original_index is not None:
                    translated_action["player"] = f"p{original_index}"
                actions.append(translated_action)
            trace_rows.append({
                "hand": hands_played,
                "button": button,
                "small_blind": button if active_count == 2 else seat_order[0],
                "big_blind_player": seat_order[0] if active_count == 2 else seat_order[1],
                "small_blind_amount": small_blind,
                "big_blind_amount": big_blind,
                "seat_order": list(seat_order),
                "start_stacks": hand_starts,
                "end_stacks": list(current_stacks),
                "actions": actions,
            })

        if sum(stack > 0 for stack in current_stacks) > 1:
            live_count = sum(stack > 0 for stack in current_stacks)
            next_button = _next_live_after(button, current_stacks)
            if (
                active_count > 2
                and live_count == 2
                and current_stacks[button] == 0
                and current_stacks[seat_order[1]] > 0
            ):
                # If the prior button busts while the prior BB survives into
                # heads-up, make that BB the next BTN/SB instead of posting BB
                # twice. Other blind eliminations follow the moving ring.
                next_button = seat_order[1]
            button = next_button

    live = [index for index, stack in enumerate(current_stacks) if stack > 0]
    winner: int | None = None
    capped = len(live) > 1 and hands_played >= max_hands
    if len(live) == 1:
        winner = live[0]
        if next_worst_place != 1:
            raise RuntimeError("elimination ranks did not leave first place for the winner")
        finish[winner] = 1.0
        points[winner] = payout_values[0]
    elif live:
        if next_worst_place != len(live):
            raise RuntimeError("elimination ranks did not leave the top places for survivors")
        live_equities, live_finishes = _icm_details(
            [current_stacks[index] for index in live],
            payout_values[:len(live)],
        )
        for offset_index, original_index in enumerate(live):
            points[original_index] = live_equities[offset_index]
            finish[original_index] = live_finishes[offset_index]
    else:
        raise RuntimeError("chip conservation left no live player")

    if any(value is None for value in finish) or any(value is None for value in points):
        raise RuntimeError("tournament ranking did not assign every player's result")
    finished = [float(value) for value in finish]
    awarded = [float(value) for value in points]
    if not math.isclose(sum(awarded), sum(payout_values), rel_tol=1e-10, abs_tol=1e-9):
        raise RuntimeError("tournament points conservation failed")
    if not math.isclose(
        sum(finished), player_count * (player_count + 1) / 2,
        rel_tol=1e-10, abs_tol=1e-9,
    ):
        raise RuntimeError("expected finish ranks do not conserve place positions")
    if sum(current_stacks) != sum(initial_stacks):
        raise RuntimeError("final tournament chip conservation failed")

    players = []
    for index in range(player_count):
        latencies = metrics[index]["latencies_ns"]
        p95_ns = (
            sorted(latencies)[max(0, math.ceil(0.95 * len(latencies)) - 1)]
            if latencies else None
        )
        players.append({
            "index": index,
            "finish": finished[index],
            "points": awarded[index],
            "final_stack": current_stacks[index],
            "won": winner == index,
            "invalid_actions": metrics[index]["invalid_actions"],
            "decisions": metrics[index]["decisions"],
            "latency_mean_ms": statistics.fmean(latencies) / 1_000_000 if latencies else None,
            "latency_p95_ms": p95_ns / 1_000_000 if p95_ns is not None else None,
            "latency_max_ms": max(latencies) / 1_000_000 if latencies else None,
            "over_1ms": sum(value > 1_000_000 for value in latencies),
        })

    result = {
        "winner": winner,
        "capped": capped,
        "hands_played": hands_played,
        "final_stacks": current_stacks,
        "players": players,
        "invalid_actions": invalid_total,
        "seed": seed,
        "config": {
            "starting_stacks": initial_stacks,
            "big_blinds": blind_schedule,
            "hands_per_level": hands_per_level,
            "max_hands": max_hands,
            "payouts": payout_values,
            "payouts_defaulted": payouts_were_defaulted,
            "strict": strict,
            "button_rule": (
                "moving button; next live original seat clockwise; no dead button; "
                "if the prior BTN busts into heads-up and prior BB survives, "
                "that BB becomes BTN/SB"
            ),
            "heads_up_seats": "[BB, BTN/SB]",
            "multiway_seats": "[SB, BB, ..., BTN]",
            "payout_caveat": (
                "Default descending N-to-1 points are illustrative, not official payouts."
            ),
            "blind_schedule_caveat": (
                "Default 20/40 doubling levels are illustrative. Public rules announce "
                "10/20 starting blinds increasing every 25 hands; the event variant "
                "and payout schedule may differ."
            ),
        },
    }
    if trace:
        result["trace"] = trace_rows
    return result
