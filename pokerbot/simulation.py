"""Reproducible local NLHE simulation for policy evaluation.

This module is a local testing model. It does not implement, certify, or
represent the official Sequoia tournament or its sandbox.
"""

from __future__ import annotations

import hashlib
import math
import random
import statistics
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from typing import Any

from .cards import RANKS, SUITS
from .state import Observation


Policy = Callable[[dict[str, Any]], dict[str, Any]]
_ACTION_ORDER = ("fold", "check", "call", "raise")
_AUTOMATION_NAMES = (
    "ANTE_POSTING",
    "BET_COLLECTION",
    "BLIND_OR_STRADDLE_POSTING",
    "HOLE_CARDS_SHOWING_OR_MUCKING",
    "RUNOUT_COUNT_SELECTION",
    "HAND_KILLING",
    "CHIPS_PUSHING",
    "CHIPS_PULLING",
)


class InvalidActionError(ValueError):
    """Raised when a policy returns an action outside its observation."""

    def __init__(self, detail: dict[str, Any]):
        self.detail = detail
        super().__init__(
            f"invalid action from {detail['player_id']}: {detail['reason']}"
        )


def _require_int(value: Any, name: str, *, minimum: int) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _require_seed(seed: Any) -> int:
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    return seed


def _domain_seed(seed: int, purpose: str, *parts: object) -> int:
    """Derive a stable seed in a separate pseudorandom domain."""
    material = "\0".join(
        ("pokerbot-local-v1", str(seed), purpose, *(str(p) for p in parts))
    )
    return int.from_bytes(hashlib.sha256(material.encode("utf-8")).digest()[:8], "big")


def _positions(player_count: int) -> list[str]:
    """Return positions for PokerKit's seat order (seat 0 is the small blind)."""
    if player_count == 2:
        return ["BB", "BTN"]
    if player_count == 3:
        return ["SB", "BB", "BTN"]

    button = player_count - 1
    positions = [""] * player_count
    positions[button] = "BTN"
    positions[0] = "SB"
    positions[1] = "BB"
    positions[2] = "UTG"
    if player_count >= 5:
        positions[player_count - 2] = "CO"
        for seat in range(3, player_count - 2):
            positions[seat] = "MP"
    return positions


def _street(board_size: int) -> str:
    return {0: "preflop", 3: "flop", 4: "turn", 5: "river"}[board_size]


def _contestable_pot(state: Any, hero: int) -> int:
    """Return committed chips hero can contest by calling the current bet.

    Contribution tiers include folded players' money. A tier is counted only
    when hero can reach it after calling and at least one other live player
    could also reach it. This excludes unreachable side pots and an unmatched
    top contribution.
    """
    contributions = [max(0, -payoff) for payoff in state.payoffs]
    call_amount = state.checking_or_calling_amount
    if call_amount is None:
        call_amount = 0
    hero_limit = contributions[hero] + call_amount
    opponent_limits = [
        contributions[i] + state.stacks[i]
        for i in state.player_indices
        if i != hero and state.statuses[i]
    ]
    if not state.statuses[hero] or not opponent_limits:
        return 0

    total = 0
    previous = 0
    boundaries = set(contributions)
    boundaries.add(hero_limit)
    boundaries.update(opponent_limits)
    for level in sorted(value for value in boundaries if value > 0):
        if level <= previous:
            continue
        layer_size = (level - previous) * sum(value >= level for value in contributions)
        if hero_limit >= level and any(limit >= level for limit in opponent_limits):
            total += layer_size
        previous = level
    return min(total, state.total_pot_amount)


def _observation(
    state: Any,
    seat: int,
    positions: Sequence[str],
    seed: int,
    decision_number: int,
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    board = [repr(card) for cards in state.board_cards for card in cards]
    hero_cards = [repr(card) for card in state.hole_cards[seat]]
    current_bet = state.bets[seat]
    call_amount = state.checking_or_calling_amount
    if call_amount is None:
        call_amount = 0

    legal = []
    if call_amount > 0 and state.can_fold():
        legal.append("fold")
    if state.can_check_or_call():
        legal.append("check" if call_amount == 0 else "call")
    min_raise_to = state.min_completion_betting_or_raising_to_amount
    max_raise_to = state.max_completion_betting_or_raising_to_amount
    if min_raise_to is not None and max_raise_to is not None:
        legal.append("raise")

    public_history = [dict(action) for action in history]
    result = {
        "hole_cards": hero_cards,
        "board": board,
        "pot": state.total_pot_amount,
        "to_call": min(call_amount, state.stacks[seat]),
        "stack": state.stacks[seat],
        "current_bet": current_bet,
        "min_raise_to": min_raise_to if min_raise_to is not None else 0,
        "max_raise_to": max_raise_to if max_raise_to is not None else 0,
        "big_blind": state.blinds_or_straddles[1],
        "position": positions[seat],
        "players_active": sum(state.statuses),
        "players_to_act": max(0, len(state.actor_indices) - 1),
        "legal_actions": [action for action in _ACTION_ORDER if action in legal],
        "street": _street(len(board)),
        "seed": _domain_seed(seed, "policy", seat, decision_number),
        "history": public_history,
        "player_id": f"p{seat}",
        "contestable_pot": _contestable_pot(state, seat),
        "table_size": state.player_count,
    }
    # Run the same public protocol validator used by the strategy boundary.
    Observation.from_dict(result)
    return result


def _invalid_reason(
    decision: Any, observation: Mapping[str, Any], state: Any
) -> str | None:
    if not isinstance(decision, Mapping):
        return "policy output must be a decision object"
    action = decision.get("action")
    if not isinstance(action, str):
        return "decision must contain a string action"
    if action not in observation["legal_actions"]:
        return f"{action!r} is not legal; legal actions are {observation['legal_actions']}"
    if action == "raise":
        amount = decision.get("amount")
        if type(amount) is not int:
            return "raise decision must contain an integer total street bet in amount"
        if not observation["min_raise_to"] <= amount <= observation["max_raise_to"]:
            return (
                f"raise amount {amount} is outside street-total bounds "
                f"[{observation['min_raise_to']}, {observation['max_raise_to']}]"
            )
        if not state.can_complete_bet_or_raise_to(amount):
            return f"PokerKit rejected raise-to amount {amount}"
    return None


def _fallback_action(observation: Mapping[str, Any]) -> dict[str, Any]:
    legal = observation["legal_actions"]
    if "check" in legal:
        return {"action": "check"}
    if "fold" in legal:
        return {"action": "fold"}
    return {"action": "call"}


def _deal_board_or_burn(state: Any, deck: Sequence[str], cursor: int) -> int:
    """Advance one pending community-card operation using the fixed deck."""
    if state.card_burning_status:
        if cursor >= len(deck):
            raise RuntimeError("predealt deck exhausted before burn")
        state.burn_card(deck[cursor])
        return cursor + 1

    count = state.board_dealing_count
    if count is not None:
        if count <= 0 or cursor + count > len(deck):
            raise RuntimeError("invalid or exhausted board-dealing request")
        state.deal_board("".join(deck[cursor : cursor + count]))
        return cursor + count
    return cursor


def _play_hand(
    policies: Sequence[Policy],
    *,
    seed: int,
    stacks: int | Sequence[int],
    big_blind: int,
    strict: bool,
    include_trace: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(policies, Sequence) or isinstance(policies, (str, bytes)):
        raise TypeError("policies must be a sequence of callables")
    player_count = len(policies)
    if not 2 <= player_count <= 8:
        raise ValueError("policies must contain between 2 and 8 players")
    if any(not callable(policy) for policy in policies):
        raise TypeError("every policy must be callable")
    _require_seed(seed)
    _require_int(big_blind, "big_blind", minimum=1)
    if type(stacks) is int:
        starting_stacks = [
            _require_int(stacks, "stacks", minimum=1) for _ in policies
        ]
    elif isinstance(stacks, Sequence) and not isinstance(stacks, (str, bytes)):
        if len(stacks) != player_count:
            raise ValueError("stack sequence length must match the number of policies")
        starting_stacks = [
            _require_int(value, f"stacks[{index}]", minimum=1)
            for index, value in enumerate(stacks)
        ]
    else:
        raise TypeError("stacks must be an integer or a sequence of integers")

    try:
        from pokerkit import Automation, Mode, NoLimitTexasHoldem
    except ImportError as exc:  # pragma: no cover - depends on installation
        raise RuntimeError(
            "the local simulator requires the optional dependency; "
            "install with `pip install '.[evaluation]'`"
        ) from exc

    automations = tuple(getattr(Automation, name) for name in _AUTOMATION_NAMES)
    small_blind = max(1, big_blind // 2)
    state = NoLimitTexasHoldem.create_state(
        automations,
        False,
        0,
        (small_blind, big_blind),
        big_blind,
        tuple(starting_stacks),
        player_count,
        mode=Mode.CASH_GAME,
    )

    # The only card stream visible to PokerKit is supplied by this private
    # predeal. Policies receive a separate, domain-derived sampling seed.
    deck = [rank + suit for rank in RANKS for suit in SUITS]
    random.Random(seed).shuffle(deck)
    cursor = 0
    for _round in range(2):
        for seat in range(player_count):
            state.deal_hole(deck[cursor], player_index=seat)
            cursor += 1

    positions = _positions(player_count)
    history: list[dict[str, Any]] = []
    public_actions: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    invalid_actions: list[dict[str, Any]] = []
    policy_metrics: list[dict[str, Any]] = []
    decision_numbers = [0] * player_count

    while state.status:
        seat = state.actor_index
        if seat is None:
            before = (state.street_index, state.card_burning_status,
                      state.board_dealing_count, len(state.operations))
            cursor = _deal_board_or_burn(state, deck, cursor)
            after = (state.street_index, state.card_burning_status,
                     state.board_dealing_count, len(state.operations))
            if before == after:
                raise RuntimeError(
                    "PokerKit has no actor or pending card operation while the hand is active"
                )
            continue

        observation = _observation(
            state, seat, positions, seed, decision_numbers[seat], history
        )
        decision_numbers[seat] += 1
        policy_observation = deepcopy(observation)
        started = time.perf_counter_ns()
        raw_decision = policies[seat](policy_observation)
        elapsed_ns = time.perf_counter_ns() - started
        reason = _invalid_reason(raw_decision, observation, state)
        if reason is not None:
            detail = {
                "player_id": f"p{seat}",
                "action": raw_decision.get("action") if isinstance(raw_decision, Mapping) else None,
                "reason": reason,
                "fallback": None,
            }
            if strict:
                raise InvalidActionError(detail)
            decision = _fallback_action(observation)
            detail["fallback"] = dict(decision)
            invalid_actions.append(detail)
        else:
            decision = {"action": raw_decision["action"]}
            if decision["action"] == "raise":
                decision["amount"] = raw_decision["amount"]

        before_bet = state.bets[seat]
        action_name = decision["action"]
        if action_name == "fold":
            operation = state.fold()
            target = before_bet
            added = 0
        elif action_name in ("check", "call"):
            operation = state.check_or_call()
            # PokerKit may collect street bets immediately after the final
            # call, so capture the street-total target before collection.
            target = before_bet + operation.amount
            added = operation.amount
        else:
            target = decision["amount"]
            operation = state.complete_bet_or_raise_to(target)
            added = target - before_bet

        public_action = {
            "street": observation["street"],
            "player": f"p{seat}",
            "position": positions[seat],
            "action": action_name,
            "amount": target,
            "added": added,
        }
        history.append(public_action)
        public_actions.append(dict(public_action))
        trace.append({
            "observation": observation,
            "decision": dict(decision),
            "action": dict(public_action),
        })
        policy_metrics.append({
            "seat": seat,
            "legal_action_count": len(observation["legal_actions"]),
            "latency_ns": elapsed_ns,
        })

    if state.status:
        raise RuntimeError("PokerKit did not settle the hand")
    final_stacks = list(state.stacks)
    payoffs = [final - initial for final, initial in zip(final_stacks, starting_stacks)]
    if sum(final_stacks) != sum(starting_stacks) or sum(payoffs) != 0:
        raise RuntimeError("chip conservation failed in PokerKit settlement")

    result: dict[str, Any] = {
        "payoffs": payoffs,
        "stacks": final_stacks,
        "actions": public_actions,
        "invalid_actions": invalid_actions,
        "big_blind": big_blind,
        "table_size": player_count,
    }
    if include_trace:
        result["trace"] = trace
    return result, policy_metrics


def play_hand(
    policies: Sequence[Policy],
    *,
    seed: int = 0,
    stacks: int | Sequence[int] = 2000,
    big_blind: int = 20,
    strict: bool = True,
    trace: bool = False,
) -> dict[str, Any]:
    """Play one local cash-reset hand with two through eight policy callables.

    ``policies`` are in PokerKit seat order; each receives one observation
    dictionary and returns a decision dictionary. ``stacks`` can be one
    common starting stack or one stack per seat. ``trace=True`` includes each
    exact policy observation and normalized decision. Illegal decisions raise
    :class:`InvalidActionError` by default; ``strict=False`` records them and
    visibly falls back to check, then fold, then call.
    """
    result, _ = _play_hand(
        policies,
        seed=seed,
        stacks=stacks,
        big_blind=big_blind,
        strict=strict,
        include_trace=trace,
    )
    return result


def calling_station(observation: dict[str, Any]) -> dict[str, Any]:
    """Call every bet and otherwise check; never raise or fold."""
    return {"action": "call" if observation["to_call"] else "check"}


def tight_passive(observation: dict[str, Any]) -> dict[str, Any]:
    """Small illustrative preflop-range and low-price calling baseline."""
    if observation["to_call"] == 0:
        return {"action": "check"}
    if observation["street"] == "preflop":
        ranks = {rank: value for value, rank in enumerate(RANKS, start=2)}
        first, second = observation["hole_cards"]
        high, low = sorted((ranks[first[0]], ranks[second[0]]), reverse=True)
        suited = first[1] == second[1]
        pair = high == low
        playable = pair and high >= 8
        playable |= high >= 12 and low >= 10
        playable |= suited and high >= 11 and low >= 9
        if playable and observation["to_call"] <= observation["big_blind"]:
            return {"action": "call"}
    elif observation["to_call"] <= max(
        1, min(observation["big_blind"], observation["contestable_pot"] // 10)
    ):
        return {"action": "call"}
    return {"action": "fold"}


def random_legal(observation: dict[str, Any]) -> dict[str, Any]:
    """Choose a legal action reproducibly from the observation's public seed."""
    rng = random.Random(observation["seed"])
    action = rng.choice(observation["legal_actions"])
    if action == "raise":
        return {
            "action": "raise",
            "amount": rng.randint(
                observation["min_raise_to"], observation["max_raise_to"]
            ),
        }
    return {"action": action}


def _quantile(values: Sequence[int], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * probability
    low = math.floor(index)
    high = math.ceil(index)
    if low == high:
        return float(ordered[low])
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def _decision_summary(metrics: Sequence[dict[str, int]]) -> dict[str, Any]:
    legal_counts = [item["legal_action_count"] for item in metrics]
    latencies = [item["latency_ns"] for item in metrics]
    histogram = Counter(legal_counts)
    latency_ms = [value / 1_000_000 for value in latencies]
    return {
        "count": len(metrics),
        "legal_action_count": {
            "mean": statistics.fmean(legal_counts) if legal_counts else None,
            "distribution": {str(key): histogram[key] for key in sorted(histogram)},
        },
        "latency_ms": {
            "mean": statistics.fmean(latency_ms) if latency_ms else None,
            "p50": _quantile(latencies, 0.50) / 1_000_000 if latencies else None,
            "p95": _quantile(latencies, 0.95) / 1_000_000 if latencies else None,
            "p99": _quantile(latencies, 0.99) / 1_000_000 if latencies else None,
            "max": max(latency_ms) if latency_ms else None,
        },
    }


def benchmark(
    hero_policy: Policy,
    opponents: list[Policy],
    *,
    hands: int = 100,
    seed: int = 0,
    stacks: int | Sequence[int] = 2000,
    big_blind: int = 20,
    strict: bool = True,
) -> dict[str, Any]:
    """Evaluate a policy against opponents using duplicate-deal seat rotations.

    ``hands`` is the requested number of hand runs. The count rounds up to a
    whole block of one run per seat, so every duplicate deal gives the hero
    every table position. Policies rotate while PokerKit's same shuffled deck
    is reused within the block. Uncertainty is the standard error across
    duplicate-deal block means, in bb/100.
    """
    if not callable(hero_policy):
        raise TypeError("hero_policy must be callable")
    if not isinstance(opponents, list) or any(not callable(p) for p in opponents):
        raise TypeError("opponents must be a list of callable policies")
    if not 1 <= len(opponents) <= 7:
        raise ValueError("opponents must contain between 1 and 7 policies")
    _require_int(hands, "hands", minimum=1)
    _require_seed(seed)
    _require_int(big_blind, "big_blind", minimum=1)
    all_policies = [hero_policy, *opponents]
    player_count = len(all_policies)
    blocks = math.ceil(hands / player_count)
    block_values: list[float] = []
    all_payoffs: list[int] = []
    hero_metrics: list[dict[str, int]] = []
    invalid_count = 0
    hero_invalid_count = 0

    for block in range(blocks):
        deal_seed = _domain_seed(seed, "benchmark-deal", block)
        block_payoffs = []
        for hero_seat in range(player_count):
            seat_policies = [
                all_policies[(seat - hero_seat) % player_count]
                for seat in range(player_count)
            ]
            hand_result, metrics = _play_hand(
                seat_policies,
                seed=deal_seed,
                stacks=stacks,
                big_blind=big_blind,
                strict=strict,
                include_trace=False,
            )
            block_payoffs.append(hand_result["payoffs"][hero_seat])
            all_payoffs.append(hand_result["payoffs"][hero_seat])
            hero_metrics.extend(item for item in metrics if item["seat"] == hero_seat)
            invalid_count += len(hand_result["invalid_actions"])
            hero_invalid_count += sum(
                item["player_id"] == f"p{hero_seat}"
                for item in hand_result["invalid_actions"]
            )
        block_values.append(
            statistics.fmean(block_payoffs) / big_blind * 100
        )

    total_hands = blocks * player_count
    net_bb100 = sum(all_payoffs) / (total_hands * big_blind) * 100
    standard_error = (
        statistics.stdev(block_values) / math.sqrt(len(block_values))
        if len(block_values) > 1
        else None
    )
    return {
        "hero_net_bb_per_100": net_bb100,
        "uncertainty": {
            "method": "standard error across duplicate-deal block means",
            "blocks": len(block_values),
            "standard_error_bb_per_100": standard_error,
            "ci95_bb_per_100": (
                [net_bb100 - 1.96 * standard_error, net_bb100 + 1.96 * standard_error]
                if standard_error is not None
                else None
            ),
            "block_means_bb_per_100": block_values,
        },
        "hands_requested": hands,
        "hands_played": total_hands,
        "players": player_count,
        "big_blind": big_blind,
        "invalid_actions": invalid_count,
        "hero_invalid_actions": hero_invalid_count,
        "hero_decisions": _decision_summary(hero_metrics),
    }
