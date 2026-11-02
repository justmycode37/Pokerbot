"""Fast, dependency-free Hold'em policy for the local observation protocol.

The public tournament rules do not disclose the event variant or starter-kit
interface in advance. This module therefore makes a provisional Texas Hold'em
assumption and keeps all decisions inside the supplied, hero-only observation.
It uses a static preflop equity table and deterministic postflop heuristics; it
does not sample cards at runtime.
"""

from __future__ import annotations

from typing import Any

from .cards import rank_hand
from .preflop import hand_class, opening_threshold, preflop_equity
from .state import Observation
from .texture import suited_board_equity


_RANK_VALUE = {rank: value for value, rank in enumerate("23456789TJQKA", 2)}
_ACTION_ORDER = ("raise", "call", "check", "fold")


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _seed_roll(obs: Observation, salt: int) -> float:
    """Stable deterministic action mixer; no random-number sampling is used."""
    value = (obs.seed ^ (salt * 0x9E3779B9)) & 0xFFFFFFFF
    for card in obs.hole_cards + obs.board:
        code = _RANK_VALUE[card[0]] * 8 + "cdhs".index(card[1]) + 1
        value = ((value ^ code) * 0x01000193) & 0xFFFFFFFF
    value ^= value >> 16
    value = (value * 0x7FEB352D) & 0xFFFFFFFF
    value ^= value >> 15
    value = (value * 0x846CA68B) & 0xFFFFFFFF
    value ^= value >> 16
    return value / 4294967296.0


def _normalise(weights: dict[str, float], legal: frozenset[str]) -> dict[str, float]:
    kept = {action: max(0.0, weights.get(action, 0.0)) for action in _ACTION_ORDER if action in legal}
    total = sum(kept.values())
    if total <= 0.0:
        fallback = "check" if "check" in legal else "call" if "call" in legal else "fold"
        kept = {action: float(action == fallback) for action in kept}
        total = 1.0
    return {action: value / total for action, value in kept.items()}


def _select(probabilities: dict[str, float], obs: Observation, salt: int) -> str:
    roll = _seed_roll(obs, salt)
    cumulative = 0.0
    for action in _ACTION_ORDER:
        probability = probabilities.get(action, 0.0)
        cumulative += probability
        if roll < cumulative:
            return action
    return next(action for action in reversed(_ACTION_ORDER) if probabilities.get(action, 0.0) > 0.0)


def _history_actions(obs: Observation, street: str) -> list[dict[str, Any]]:
    actions = []
    for item in obs.history:
        if item.get("street", street) != street:
            continue
        actor = item.get("player")
        if obs.player_id is not None and actor == obs.player_id:
            continue
        actions.append(item)
    return actions


def _raise_count(obs: Observation, street: str) -> int:
    return sum(
        str(item.get("action", "")).lower() in {"raise", "bet", "all-in", "all_in"}
        for item in _history_actions(obs, street)
    )


def _preflop_entry_counts(obs: Observation) -> tuple[int, int]:
    """Count visible preflop entrants, excluding seats that have not acted."""
    last_by_player: dict[tuple[str, str], str] = {}
    anonymous_calls = 0
    anonymous_entries = 0
    for item in _history_actions(obs, "preflop"):
        action = str(item.get("action", "")).lower()
        if action not in {"call", "raise", "bet", "all-in", "all_in", "fold"}:
            continue
        actor = item.get("player")
        if actor is None:
            if action in {"call", "raise", "bet", "all-in", "all_in"}:
                anonymous_entries += 1
                anonymous_calls += int(action == "call")
            continue
        last_by_player[(type(actor).__name__, str(actor))] = action
    entered = [
        action for action in last_by_player.values()
        if action in {"call", "raise", "bet", "all-in", "all_in"}
    ]
    entered_count = len(entered) + anonymous_entries
    limper_count = sum(action == "call" for action in entered) + anonymous_calls
    return entered_count, limper_count


def _raise_target(
    obs: Observation,
    *,
    strength: float,
    preflop: bool,
    aggression: int = 0,
    unopened: bool = False,
) -> int:
    """Choose a legal total street bet (the engine's raise amount convention)."""
    if preflop:
        effective_bb = (obs.stack + obs.to_call) / obs.big_blind
        if effective_bb <= 10:
            return obs.max_raise_to
        if unopened or obs.to_call == 0:
            target = max(obs.min_raise_to, round(2.25 * obs.big_blind))
        else:
            call_total = obs.current_bet + obs.to_call
            multiplier = 3.0 if aggression <= 1 else 2.3
            target = max(obs.min_raise_to, round(call_total * multiplier))
        return obs.raise_to(target)

    effective_pot = max(obs.big_blind, obs.contestable_pot)
    if obs.to_call == 0:
        fraction = 0.38 if strength < 0.78 else 0.55
        if obs.stack <= effective_pot * 0.7:
            return obs.max_raise_to
        target = obs.current_bet + max(obs.big_blind, round(effective_pot * fraction))
    else:
        call_total = obs.current_bet + obs.to_call
        fraction = 0.62 if strength < 0.82 else 0.82
        if obs.stack <= (obs.contestable_pot + obs.to_call) * 0.65:
            return obs.max_raise_to
        extra = max(obs.to_call, round((obs.contestable_pot + obs.to_call) * fraction))
        target = call_total + extra
    return obs.raise_to(target)


def _preflop_decision(obs: Observation) -> tuple[dict[str, float], int, dict[str, Any]]:
    equity = preflop_equity(obs.hole_cards)
    name = hand_class(obs.hole_cards)
    raises = _raise_count(obs, "preflop")
    entered_opponents, limpers = _preflop_entry_counts(obs)
    highest_street_bet = obs.current_bet + obs.to_call
    if raises > 0 or highest_street_bet > obs.big_blind:
        situation = "raised"
        aggression = max(1, raises)
    elif entered_opponents:
        situation = "limped"
        aggression = 0
    else:
        situation = "unopened"
        aggression = 0
    # If history was truncated but the price is above the big blind, treat the
    # observed price as at least one voluntary raise.
    if situation == "raised" and aggression == 0:
        aggression = 1
    effective_bb = (obs.stack + obs.to_call) / obs.big_blind
    multiway_discount = 0.035 * max(0, entered_opponents - 1)
    diagnostics: dict[str, Any] = {
        "policy": "fast-heuristic-v3",
        "variant_assumption": "no-limit-texas-holdem",
        "street": obs.street,
        "preflop_situation": situation,
        "hand_class": name,
        "preflop_equity_vs_random": round(equity, 4),
        "effective_stack_bb": round(effective_bb, 2),
        "opponents_in_pot": entered_opponents,
        "players_waiting": obs.players_to_act,
        "highest_street_bet": highest_street_bet,
    }
    raise_amount = 0

    if obs.position == "BB" and obs.to_call == 0:
        # The big blind already owns its option. Check weak hands for free;
        # isolate actual limpers only with a clear value hand.
        if limpers:
            if limpers and equity >= 0.72 and "raise" in obs.legal_actions:
                raise_amount = _raise_target(obs, strength=equity, preflop=True)
                weights = {"raise": 0.84, "check": 0.16}
                diagnostics["reason"] = "value raise over limpers"
            else:
                weights = {"check": 1.0}
                diagnostics["reason"] = "free big-blind check"
        else:
            weights = {"check": 1.0}
            diagnostics["reason"] = "free big-blind check"
    elif situation == "unopened":
        threshold = opening_threshold(obs.position)
        # Seats yet to act affect open strength, but are not opponents who have
        # entered the pot and therefore receive no multiway equity discount.
        threshold += 0.004 * min(5, max(0, obs.players_to_act - 1))
        if effective_bb <= 6:
            threshold -= 0.045
        elif effective_bb <= 10:
            threshold -= 0.025
        elif effective_bb <= 16:
            threshold -= 0.01
        diagnostics["open_threshold"] = round(threshold, 4)
        if equity >= threshold and "raise" in obs.legal_actions:
            raise_amount = _raise_target(
                obs, strength=equity, preflop=True, unopened=True
            )
            if name in {"AA", "KK"}:
                # Premium pairs never take the fold side of an unopened mix.
                weights = {"raise": 1.0}
            else:
                margin = equity - threshold
                raise_probability = _clamp(0.78 + margin * 1.5, 0.78, 0.98)
                weights = {"raise": raise_probability, "fold": 1.0 - raise_probability}
            diagnostics["reason"] = "unopened raise first in"
        elif "fold" in obs.legal_actions:
            weights = {"fold": 1.0}
            diagnostics["reason"] = "fold below unopened raise cutoff"
        elif "call" in obs.legal_actions:
            weights = {"call": 1.0}
            diagnostics["reason"] = "call forced by legal actions"
        else:
            weights = {"check": 1.0}
            diagnostics["reason"] = "check forced by legal actions"
    else:
        # The table is against a random hand. Discount it for the stronger
        # range represented by a raise, but keep limped pots distinct.
        if aggression == 0:
            range_discount = 0.015
        elif aggression == 1:
            range_discount = 0.065
        else:
            range_discount = 0.13
        range_discount += multiway_discount
        if obs.position in {"UTG", "MP", "SB"}:
            range_discount += 0.015
        elif obs.position in {"BTN", "BB"}:
            range_discount -= 0.005
        adjusted_equity = _clamp(equity - range_discount)
        margin = 0.025 + 0.025 * aggression + 0.02 * max(0, entered_opponents - 1)
        if obs.position == "BB":
            margin -= 0.015
        if obs.to_call >= obs.stack:
            margin -= 0.015
        if obs.position == "BB":
            call_floor = 0.42
        elif obs.position in {"UTG", "MP", "SB"}:
            call_floor = 0.50
        else:
            call_floor = 0.48
        call_cutoff = max(obs.pot_odds + margin, call_floor + 0.045 * (aggression > 1))
        diagnostics.update({
            "aggression_level": aggression,
            "entered_opponents": entered_opponents,
            "estimated_equity_after_range_adjustment": round(adjusted_equity, 4),
            "pot_odds": round(obs.pot_odds, 4),
            "continue_threshold": round(call_cutoff, 4),
        })
        can_call = "call" in obs.legal_actions
        can_raise = "raise" in obs.legal_actions
        short_stack_cutoff = 0.56 + (0.12 if aggression > 1 else 0.0)
        value_reraise_cutoff = 0.70 + (0.07 if aggression > 1 else 0.0)
        short_stack = effective_bb <= 10
        should_reraise = adjusted_equity >= (short_stack_cutoff if short_stack else value_reraise_cutoff)

        if can_raise and should_reraise:
            raise_amount = _raise_target(obs, strength=adjusted_equity, preflop=True, aggression=aggression)
            raise_probability = 0.70 if short_stack else 0.56
            if name in {"AA", "KK"}:
                raise_probability = 1.0
            weights = {"raise": raise_probability, "call": 1.0 - raise_probability}
            if situation == "limped":
                diagnostics["reason"] = "isolate limpers"
            else:
                diagnostics["reason"] = "short-stack value jam" if short_stack else "value re-raise"
        elif can_call and adjusted_equity >= call_cutoff:
            weights = {"call": 1.0}
            diagnostics["reason"] = "pot-odds and range threshold met"
        elif can_call and "fold" not in obs.legal_actions:
            weights = {"call": 1.0}
            diagnostics["reason"] = "call forced by legal actions"
        else:
            weights = {"fold": 1.0}
            diagnostics["reason"] = "fold below continue threshold"

    probabilities = _normalise(weights, obs.legal_actions)
    if "raise" not in obs.legal_actions:
        raise_amount = 0
    diagnostics["raise_amount"] = raise_amount
    return probabilities, raise_amount, diagnostics


def _straight_outs(known_cards: tuple[str, ...]) -> int:
    ranks = {_RANK_VALUE[card[0]] for card in known_cards}
    card_counts: dict[int, int] = {}
    for card in known_cards:
        rank = _RANK_VALUE[card[0]]
        card_counts[rank] = card_counts.get(rank, 0) + 1
    rank_sets = [set(range(low, low + 5)) for low in range(2, 11)]
    rank_sets.append({14, 2, 3, 4, 5})
    outs = 0
    for rank in range(2, 15):
        if rank in ranks:
            continue
        augmented = ranks | {rank}
        if any(run.issubset(augmented) for run in rank_sets):
            outs += max(0, 4 - card_counts.get(rank, 0))
    return outs


def _draw_outs(obs: Observation, category: int) -> tuple[int, int, int]:
    if len(obs.board) >= 5 or category >= 5:
        return 0, 0, 0
    known = obs.hole_cards + obs.board
    suit_counts = {suit: sum(card[1] == suit for card in known) for suit in "cdhs"}
    flush_outs = 0
    if max(suit_counts.values()) == 4:
        draw_suit = max(suit_counts, key=suit_counts.get)
        # At least one of the four known suit cards must be in hero's hand.
        if any(card[1] == draw_suit for card in obs.hole_cards):
            flush_outs = 13 - suit_counts[draw_suit]
    straight_outs = _straight_outs(known) if category < 4 else 0
    total_outs = min(15, flush_outs + straight_outs)
    future = 5 - len(obs.board)
    remaining = max(1, 52 - len(known))
    hit_probability = 0.0
    if total_outs:
        miss = 1.0
        for draw_index in range(future):
            miss *= 1.0 - min(total_outs, remaining - draw_index) / max(1, remaining - draw_index)
        hit_probability = 1.0 - miss
    return flush_outs, straight_outs, min(0.25, hit_probability * 0.42)


def _board_is_connected(board: tuple[str, ...]) -> bool:
    ranks = {_RANK_VALUE[card[0]] for card in board}
    for low in range(2, 11):
        if len(ranks.intersection(range(low, low + 5))) >= 3:
            return True
    return len(ranks.intersection({14, 2, 3, 4, 5})) >= 3


def _postflop_equity(obs: Observation) -> tuple[float, dict[str, Any]]:
    cards = obs.hole_cards + obs.board
    rank = rank_hand(cards)
    category = rank[0]
    board_ranks = {_RANK_VALUE[card[0]] for card in obs.board}
    highest_board = max(board_ranks)
    hole_ranks = [_RANK_VALUE[card[0]] for card in obs.hole_cards]
    board_suits = {suit: sum(card[1] == suit for card in obs.board) for suit in "cdhs"}
    all_suits = {suit: sum(card[1] == suit for card in cards) for suit in "cdhs"}
    board_pair = len(board_ranks) < len(obs.board)
    connected = _board_is_connected(obs.board)
    max_board_suit = max(board_suits.values())
    flush_outs, straight_outs, draw_equity = _draw_outs(obs, category)

    board_play = False
    exact_shared_board_tie = False
    base = 0.20
    if len(obs.board) == 5 and rank == rank_hand(obs.board):
        board_play = True
        if rank == (8, 14):
            # A royal flush on the board is unbeatable by any private cards.
            exact_shared_board_tie = True
            base = 1.0 / obs.players_active
        else:
            base = 1.0 / obs.players_active
            # A shared straight or lower board hand can still be overtaken by
            # a better private-card combination.
            base = max(0.05, base - 0.04)
    elif category == 0:
        overcards = sum(value > highest_board for value in hole_ranks)
        base = 0.22 + 0.035 * overcards
        if min(hole_ranks) >= highest_board:
            base += 0.025
    elif category == 1:
        pair_rank = rank[1]
        if hole_ranks[0] == hole_ranks[1]:
            if pair_rank > highest_board:
                base = 0.66
            elif pair_rank == highest_board:
                base = 0.62
            else:
                base = 0.46
        elif any(value == highest_board for value in hole_ranks):
            base = 0.61
        elif any(value in board_ranks for value in hole_ranks):
            base = 0.48
        else:
            # Pair is already on the board; hero's private cards mainly supply
            # kickers and do not make a meaningful made-hand advantage.
            base = 0.39 if rank[1] == highest_board else 0.34
        kicker_values = [value for value in hole_ranks if value != pair_rank]
        if kicker_values:
            base += 0.012 if max(kicker_values) >= 13 else -0.008
    elif category == 2:
        board_only_two_pair = board_pair and not any(value in board_ranks for value in hole_ranks) and hole_ranks[0] != hole_ranks[1]
        base = 0.40 if board_only_two_pair else 0.65
    elif category == 3:
        board_only_trips = any(
            sum(_RANK_VALUE[card[0]] == board_rank for card in obs.board) >= 3
            for board_rank in board_ranks
        )
        base = 0.66 if board_only_trips else 0.78
    elif category == 4:
        base = 0.79
    elif category == 5:
        base = 0.84
    elif category == 6:
        base = 0.92
    elif category == 7:
        base = 0.975
    else:
        base = 0.995

    texture_penalty = 0.0
    if category <= 2 and board_pair:
        texture_penalty += 0.025
    if category <= 2 and connected:
        texture_penalty += 0.025
    if category <= 2 and max_board_suit == 2 and max(all_suits.values()) < 4:
        texture_penalty += 0.035
    if category <= 2 and max_board_suit >= 3 and max(all_suits.values()) < 4:
        texture_penalty += 0.055

    if exact_shared_board_tie:
        texture_penalty = 0.0
        multiway_penalty = 0.0
        equity = base
    else:
        multiway_penalty = min(0.22, max(0, obs.players_active - 2) * 0.045)
        equity = _clamp(base + draw_equity - texture_penalty - multiway_penalty)
    suited_equity = suited_board_equity(obs)
    equity_model = "hand_draw_texture_heuristic"
    exact_unbeatable_hand = False
    if suited_equity is not None:
        equity = suited_equity
        # This calculation already accounts for opponents and suit blockers.
        texture_penalty = multiway_penalty = 0.0
        equity_model = "exact_uniform_suited_river" if len(obs.board) == 5 else "conservative_suited_turn_floor"
        exact_unbeatable_hand = equity == 1.0
    return equity, {
        "made_hand_category": category,
        "draw_outs": flush_outs + straight_outs,
        "flush_draw_outs": flush_outs,
        "straight_draw_outs": straight_outs,
        "board_connected": connected,
        "board_paired": board_pair,
        "board_play": board_play,
        "exact_shared_board_tie": exact_shared_board_tie,
        "exact_unbeatable_hand": exact_unbeatable_hand,
        "equity_model": equity_model,
        "texture_penalty": round(texture_penalty, 4),
        "multiway_penalty": round(multiway_penalty, 4),
    }


def _postflop_decision(obs: Observation) -> tuple[dict[str, float], int, dict[str, Any]]:
    equity, detail = _postflop_equity(obs)
    history = _history_actions(obs, obs.street)
    aggression = sum(str(item.get("action", "")).lower() in {"raise", "bet", "all-in", "all_in"} for item in history)
    pressure_discount = 0.0
    if obs.to_call:
        pressure_discount += 0.035
        size_ratio = obs.to_call / max(1, obs.contestable_pot)
        if size_ratio >= 0.65:
            pressure_discount += 0.045
        if aggression:
            pressure_discount += min(0.07, 0.035 * aggression)
    if detail["exact_shared_board_tie"] or detail["exact_unbeatable_hand"]:
        pressure_discount = 0.0
        adjusted_equity = equity
    else:
        adjusted_equity = _clamp(equity - pressure_discount)
    raise_amount = 0
    diagnostics: dict[str, Any] = {
        "policy": "fast-heuristic-v3",
        "variant_assumption": "no-limit-texas-holdem",
        "street": obs.street,
        "estimated_equity": round(adjusted_equity, 4),
        "raw_hand_draw_estimate": round(equity, 4),
        "pot_odds": round(obs.pot_odds, 4),
        "pressure_discount": round(pressure_discount, 4),
        "aggression_level": aggression,
        "opponents_in_pot": obs.players_active - 1,
        **detail,
    }

    if obs.to_call > 0:
        if detail["exact_shared_board_tie"] or detail["exact_unbeatable_hand"]:
            continue_threshold = obs.pot_odds
        else:
            margin = 0.02 + 0.015 * max(0, obs.players_active - 2)
            if obs.to_call >= obs.stack:
                margin -= 0.015
            continue_threshold = max(0.0, obs.pot_odds + margin)
        can_call = "call" in obs.legal_actions
        can_raise = "raise" in obs.legal_actions
        raise_probability = 0.0
        if (can_raise and not detail["board_play"] and adjusted_equity >= max(0.73, continue_threshold + 0.18)):
            raise_probability = _clamp(0.30 + (adjusted_equity - 0.73) * 1.5, 0.30, 0.62)
        elif (
            can_raise and not detail["board_play"] and obs.players_active == 2
            and obs.position in {"CO", "BTN"} and detail["draw_outs"] >= 8
            and aggression == 0 and adjusted_equity >= continue_threshold
        ):
            # A restrained semi-bluff mix; the action itself is chosen by a
            # stable per-observation hash so replay remains reproducible.
            raise_probability = 0.08

        if can_call and adjusted_equity >= continue_threshold:
            weights = {"raise": raise_probability, "call": 1.0 - raise_probability}
            diagnostics["reason"] = "continue by pot odds" if not raise_probability else "value or semi-bluff raise mix"
        elif can_call and "fold" not in obs.legal_actions:
            weights = {"call": 1.0}
            diagnostics["reason"] = "call forced by legal actions"
        elif can_raise and raise_probability > 0.0:
            weights = {"raise": raise_probability, "fold": 1.0 - raise_probability}
            diagnostics["reason"] = "raise or fold without a legal call"
        else:
            weights = {"fold": 1.0}
            diagnostics["reason"] = "fold below pot-odds threshold"
        diagnostics["continue_threshold"] = round(continue_threshold, 4)
        if can_raise and raise_probability > 0.0:
            raise_amount = _raise_target(obs, strength=adjusted_equity, preflop=False)
    else:
        can_raise = "raise" in obs.legal_actions
        raise_probability = 0.0
        if can_raise and not detail["board_play"]:
            if adjusted_equity >= 0.72:
                raise_probability = _clamp(0.42 + (adjusted_equity - 0.72) * 1.25, 0.42, 0.78)
            elif adjusted_equity >= 0.62:
                raise_probability = 0.20
            elif (
                obs.players_active == 2 and obs.position in {"CO", "BTN"}
                and aggression == 0 and not detail["board_paired"] and not detail["board_connected"]
            ):
                raise_probability = 0.06
        if can_raise:
            weights = {"raise": raise_probability, "check": 1.0 - raise_probability}
        else:
            weights = {"check": 1.0}
        diagnostics["reason"] = "value bet or small bluff mix" if raise_probability else "check"
        if can_raise and raise_probability > 0.0:
            raise_amount = _raise_target(obs, strength=adjusted_equity, preflop=False)

    probabilities = _normalise(weights, obs.legal_actions)
    if "raise" not in obs.legal_actions:
        raise_amount = 0
    diagnostics["raise_amount"] = raise_amount
    return probabilities, raise_amount, diagnostics


def decide(raw: dict) -> dict:
    """Return a legal action, total raise size, probabilities, and diagnostics.

    Raises use the protocol's **total street bet** convention. Invalid input is
    rejected by :meth:`Observation.from_dict` so adapters can surface protocol
    errors consistently.
    """
    obs = Observation.from_dict(raw)
    if obs.street == "preflop":
        probabilities, raise_amount, diagnostics = _preflop_decision(obs)
        salt = 101
    else:
        probabilities, raise_amount, diagnostics = _postflop_decision(obs)
        salt = 211 + len(obs.board)
    action = _select(probabilities, obs, salt)
    if action not in obs.legal_actions:
        # Defensive invariant if legal-action conventions expand later.
        action = "check" if "check" in obs.legal_actions else "call" if "call" in obs.legal_actions else "fold"
    return {
        "action": action,
        "amount": raise_amount if action == "raise" else 0,
        "probabilities": probabilities,
        "raise_amount": raise_amount,
        "diagnostics": diagnostics,
    }
