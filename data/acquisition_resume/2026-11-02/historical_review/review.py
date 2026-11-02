#!/usr/bin/env python3
"""Independently source-review Triton 2023-2024 converter candidates.

Reads the archived raw batch and current converter outputs. Writes only the
parent review lane. It does not fit, score, admit, or split candidates.
"""
from __future__ import annotations
import copy
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BATCH = ROOT / "data/acquisition_resume/2026-11-01/triton_2023_2024"
PRIOR_REVIEW = ROOT / "data/acquisition_resume/2026-11-01/triton_2023_2024_review"
OUT = ROOT / "data/acquisition_resume/2026-11-02/historical_review"
EVENT_OUT = OUT / "conversionoutputs/by-tournament"
sys.path.insert(0, str(ROOT))
from pokerbot.corpus import validate_rows

HERO = "3970ce21-3d14-4bdc-97ca-98df8220d040"
FORCED_DEAD = {"ante", "small_ante", "big_ante"}
FORCED_LIVE = {"small_blind", "big_blind", "straddle"}
FORCED = FORCED_DEAD | FORCED_LIVE
BETTING = {"raise", "call", "bet", "all_in", "check", "fold"}
CANONICAL_SEPARATORS = (",", ":")

def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def canonical_sha(value) -> str:
    return sha_bytes(json.dumps(value, sort_keys=True, separators=CANONICAL_SEPARATORS,
                                ensure_ascii=False, allow_nan=False).encode("utf-8"))

def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))

def card(raw: str) -> str:
    if not isinstance(raw, str) or not raw.startswith("CARD_") or len(raw) != 7:
        raise ValueError(f"unsupported source card {raw!r}")
    code = raw[5:]
    return ("T" if code[:1] == "10" else code[0].upper()) + code[-1].lower()

def position_labels(n: int) -> list[str]:
    # Frozen position labels follow PokerKit's seat order; heads-up is [BB, BTN].
    if n == 2:
        return ["BB", "BTN"]
    if n == 3:
        return ["SB", "BB", "BTN"]
    labels = [""] * n
    labels[0], labels[1], labels[2], labels[-1] = "SB", "BB", "UTG", "BTN"
    if n >= 5:
        labels[-2] = "CO"
        for i in range(3, n - 2):
            labels[i] = "MP"
    return labels

def source_actions(hand):
    result = []
    flat = 0
    for ri, round_row in enumerate(hand["rounds"]):
        for ai, action in enumerate(round_row["actions"]):
            result.append((flat, ri, ai, round_row, action))
            flat += 1
    return result

def locate_flat(hand, index):
    for flat, ri, ai, round_row, action in source_actions(hand):
        if flat == index:
            return ri, ai, round_row, action
    raise ValueError(f"source action index {index} is outside raw prefix")

def find_episode(node, episode_id):
    if isinstance(node, dict):
        if node.get("episodeId") == episode_id and isinstance(node.get("tournament"), dict):
            return node
        for value in node.values():
            found = find_episode(value, episode_id)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = find_episode(value, episode_id)
            if found is not None:
                return found
    return None

def find_tournament_uuid(node, event_id):
    if isinstance(node, dict):
        if node.get("uuid") == event_id:
            return node
        for value in node.values():
            found = find_tournament_uuid(value, event_id)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = find_tournament_uuid(value, event_id)
            if found is not None:
                return found
    return None

def contestable(contributions, stacks, active, hero, call_amount, total_pot, dead_antes):
    """Independent dead-ante-plus-live-tier contestable-pot calculation."""
    hero_limit = contributions[hero] + call_amount
    opponent_limits = [contributions[i] + stacks[i] for i in range(len(stacks))
                       if i != hero and active[i]]
    if not active[hero] or not opponent_limits:
        return 0
    boundaries = set(contributions) | {hero_limit} | set(opponent_limits)
    result = 0
    previous = 0
    for level in sorted(x for x in boundaries if x > 0):
        layer = (level - previous) * sum(value >= level for value in contributions)
        if hero_limit >= level and any(limit >= level for limit in opponent_limits):
            result += layer
        previous = level
    return min(dead_antes + result, total_pot)

def full_hand_accounting(hand):
    players = {p["userId"]: p for p in hand["players"]}
    paid = Counter()
    for _, _, _, _, action in source_actions(hand):
        if action["type"] in FORCED | {"raise", "call", "bet", "all_in"}:
            paid[action["userId"]] += action["amount"]
    contributed = Counter()
    payouts = Counter()
    total = 0
    if not hand.get("pots"):
        return False, {"reason": "missing_terminal_pots"}
    for pot in hand["pots"]:
        amount = pot["totalAmount"]
        pot_players = Counter()
        for e in pot["potPlayers"]:
            pot_players[e["userId"]] += e["amount"]
            contributed[e["userId"]] += e["amount"]
        hi = pot["hi"]
        side_players = Counter()
        award_total = 0
        for e in hi["sidePlayers"]:
            side_players[e["userId"]] += e["amount"]
            payouts[e["userId"]] += e["winAmount"]
            award_total += e["winAmount"]
        if sum(pot_players.values()) != amount or hi["totalAmount"] != amount:
            return False, {"reason": "terminal_pot_contribution_total_mismatch"}
        if pot_players != side_players:
            return False, {"reason": "terminal_pot_attribution_mismatch"}
        if award_total != amount:
            return False, {"reason": "terminal_pot_awards_do_not_sum_to_total"}
        total += amount
    if contributed != paid:
        return False, {"reason": "terminal_pots_vs_action_payments_mismatch"}
    if total != sum(paid.values()):
        return False, {"reason": "terminal_pot_total_vs_payments_mismatch"}
    for user_id, p in players.items():
        if p["startChips"] - paid[user_id] + payouts[user_id] != p["endChips"]:
            return False, {"reason": "terminal_stack_reconciliation_mismatch", "user_id": user_id}
    if sum(p["startChips"] for p in players.values()) != sum(p["endChips"] for p in players.values()):
        return False, {"reason": "terminal_table_chip_total_mismatch"}
    return True, {"players": len(players), "terminal_pots": len(hand["pots"]),
                  "total_contributed": total, "action_payments_reconciled": True,
                  "stacks_reconciled": True}

def verify_candidate(row, hand, manifest_action, hand_manifest_row, request_info,
                     episode_infos, event_id):
    checks = {}
    issues = []
    def check(name, condition, detail=None):
        checks[name] = bool(condition)
        if not condition:
            issues.append(name if detail is None else f"{name}: {detail}")

    hid = hand["handId"]
    n = len(hand["players"])
    raw_file = BATCH / hand_manifest_row["source_response_paths"][0]
    response_bytes = raw_file.read_bytes()
    raw_response_sha = sha_bytes(response_bytes)
    canon_payload_sha = canonical_sha(hand)
    req_path = BATCH / request_info["request_path"]
    req_bytes = req_path.read_bytes()
    request_body = json.loads(req_bytes)
    req_sha = sha_bytes(req_bytes)
    query_sha = sha_bytes(request_body["query"].encode("utf-8"))
    check("official_response_request_query_and_payload_hashes",
          raw_response_sha == request_info["response_sha256"]
          == hand_manifest_row["source_response_hashes"][0]
          and query_sha == request_info["query_sha256"]
          and request_body.get("variables") == request_info.get("variables")
          and request_info.get("variables", {}).get("handId") == hid
          and request_info.get("variables", {}).get("episodeId") == episode_infos[0]["episode_id"]
          and row.get("source_capture_sha256") == raw_response_sha
          and row.get("source_request_sha256") == req_sha
          and row.get("source_query_sha256") == query_sha
          and row.get("source_request_variables") == request_info.get("variables")
          and row.get("source_request_operation_name") == "GetHand"
          and row.get("source_request_episode_id") == episode_infos[0]["episode_id"]
          and Path(row.get("source_capture_path", "")).resolve() == raw_file.resolve()
          and Path(row.get("source_request_path", "")).resolve() == req_path.resolve()
          and row.get("source_payload_sha256") == canon_payload_sha)

    ri = manifest_action["original_round_index"]
    ai = manifest_action["original_action_index"]
    flat = row["source_action_index"]
    raw_ri, raw_ai, round_row, current = locate_flat(hand, flat)
    expected_canonical = f"{hid}:{ri}:{ai}"
    stable_key = f"triton:{hid}:round:{ri}:action:{ai}"
    check("canonical_hand_and_source_location",
          ri == raw_ri and ai == raw_ai
          and (hid, ri, ai) == (manifest_action["raw_hand_id"], manifest_action["original_round_index"], manifest_action["original_action_index"])
          and manifest_action["canonical_decision_id"] == expected_canonical
          and row.get("source_decision_id") == f"triton:{hid}:action:{flat}"
          and row.get("stable_source_decision_key") == stable_key
          and row.get("source_round_index") == ri
          and row.get("source_round_action_index") == ai
          and row.get("source_action_index") == flat
          and row.get("source_action_count") == len(source_actions(hand)))

    hero_row = next((p for p in hand["players"] if p.get("userId") == HERO or (p.get("user") or {}).get("uuid") == HERO), None)
    known = hero_row is not None and isinstance(hero_row.get("pocketCards"), list) and len(hero_row["pocketCards"]) == 2 and all(hero_row["pocketCards"])
    hero_cards = [card(x) for x in hero_row["pocketCards"]] if known else []
    check("hero_cards_known_and_matching",
          known and manifest_action["hero_cards_status"] == "known_two_cards"
          and row["state"].get("hole_cards") == hero_cards
          and len(set(hero_cards)) == 2)

    by_id = {p["userId"]: p for p in hand["players"]}
    capacity = hand["noOfSeats"]
    seats = {p["userId"]: p["seatNo"] for p in hand["players"]}
    seat_owner = {p["seatNo"]: p["userId"] for p in hand["players"]}
    forced = [(a["type"], a["userId"], a["amount"]) for _, _, _, _, a in source_actions(hand) if a["type"] in FORCED]
    sb = [u for kind, u, _ in forced if kind == "small_blind"]
    bb = [u for kind, u, _ in forced if kind == "big_blind"]
    sb_amount = sum(amount for kind, _, amount in forced if kind == "small_blind")
    bb_amount = sum(amount for kind, _, amount in forced if kind == "big_blind")
    live_forced_source_order = [(kind, actor) for kind, actor, _ in forced if kind in FORCED_LIVE]
    antes_by_id = Counter()
    live_by_id = Counter()
    for kind, actor, amount in forced:
        if kind in FORCED_DEAD:
            antes_by_id[actor] += amount
        else:
            live_by_id[actor] += amount
    forced_order_ok = len(sb) == 1 and len(bb) == 1 and sb[0] != bb[0]
    ordered_ids = []
    button_ok = False
    if forced_order_ok:
        sb_seat = seats[sb[0]]
        if n == 2:
            ordered_ids = [bb[0], sb[0]]
        else:
            ordered_ids = [p["userId"] for p in sorted(hand["players"], key=lambda p: (p["seatNo"] - sb_seat) % capacity)]
        dealer_id = seat_owner.get(hand.get("dealerSeatNo"))
        if n == 2:
            button_ok = (ordered_ids == [bb[0], sb[0]]
                         and dealer_id == sb[0]
                         and hand.get("dealerSeatNo") == sb_seat)
        else:
            button_ok = (ordered_ids[0] == sb[0] and ordered_ids[1] == bb[0]
                         and dealer_id is not None and ordered_ids[-1] == dealer_id)
    straddlers = {actor for kind, actor, _ in forced if kind == "straddle"}
    expected_live_forced_order = [("small_blind", sb[0]), ("big_blind", bb[0])] if forced_order_ok else []
    expected_live_forced_order.extend(("straddle", actor) for actor in ordered_ids[2:] if actor in straddlers)
    forced_prefix_order_ok = True
    betting_seen = False
    for _, _, _, source_round, source_action in source_actions(hand):
        kind = source_action["type"]
        if kind in FORCED:
            if source_round["name"].lower().replace("preflop", "pre_flop") != "pre_flop" or betting_seen:
                forced_prefix_order_ok = False
        else:
            betting_seen = True
    forced_order_ok = forced_order_ok and live_forced_source_order == expected_live_forced_order and forced_prefix_order_ok
    check("actual_small_big_blinds_and_antes_in_source_array_order",
          forced_order_ok
          and sb_amount <= hand["blindLevel"]["smallBlind"]
          and bb_amount <= hand["blindLevel"]["bigBlind"]
          and all(antes_by_id[u] + live_by_id[u] <= by_id[u]["startChips"] for u in by_id)
          and row["source_actual_player_count"] == n
          and row["source_physical_capacity"] == capacity)
    check("button_order_verified_from_occupied_dealer_seat",
          forced_order_ok and button_ok
          and row["session_id"] == f"triton:tournament:{event_id}")

    # Replay only the source prefix before the candidate action with an exact chip ledger.
    stacks = {u: by_id[u]["startChips"] for u in ordered_ids}
    contributions = Counter()
    dead_antes = 0
    street_bets = Counter()
    active = {u: True for u in ordered_ids}
    history = []
    max_bet = 0
    for kind, actor, amount in forced:
        stacks[actor] -= amount
        if kind in FORCED_DEAD:
            dead_antes += amount
        else:
            contributions[actor] += amount
            street_bets[actor] += amount
            max_bet = max(max_bet, street_bets[actor])
    current_street = 0
    last_full_raise = max([hand["blindLevel"]["bigBlind"]] + [x[2] for x in forced if x[0] in FORCED_LIVE])
    last_acted_bet = {u: None for u in ordered_ids}
    raise_right = {u: True for u in ordered_ids}
    prior_rows = [(f, rix, aix, rd, a) for f, rix, aix, rd, a in source_actions(hand) if f < flat]
    timeline_monotone = True
    prev_ts = None
    for _, _, _, _, a in source_actions(hand):
        t = a.get("timestamp")
        if prev_ts is not None and t < prev_ts:
            timeline_monotone = False
        prev_ts = t

    for _, prior_ri, prior_ai, prior_round, a in prior_rows:
        kind, actor = a["type"], a["userId"]
        if kind in FORCED:
            continue
        if prior_ri != current_street:
            current_street = prior_ri
            street_bets = Counter()
            max_bet = 0
            last_full_raise = hand["blindLevel"]["bigBlind"]
            last_acted_bet = {u: None for u in ordered_ids}
            raise_right = {u: active[u] for u in ordered_ids}
        before = street_bets[actor]
        added = a.get("amount", 0)
        due = max_bet - before
        if kind == "fold":
            active[actor] = False
            hist_action = "fold"
            target = before
        elif kind == "check":
            hist_action = "check"
            target = before
            raise_right[actor] = False
            last_acted_bet[actor] = max_bet
        elif kind == "call" or (kind == "all_in" and before + added <= max_bet):
            hist_action = "call"
            target = before + added
            raise_right[actor] = False
            last_acted_bet[actor] = max_bet
        elif kind in {"raise", "bet", "all_in"}:
            hist_action = "raise"
            target = before + added
            increase = target - max_bet
            old_max_bet = max_bet
            max_bet = max(max_bet, target)
            if increase >= last_full_raise:
                last_full_raise = increase
                for other in ordered_ids:
                    if other != actor and active[other]:
                        raise_right[other] = True
            else:
                for other in ordered_ids:
                    acted_at = last_acted_bet[other]
                    if other != actor and active[other] and acted_at is not None and max_bet - acted_at >= last_full_raise:
                        raise_right[other] = True
            raise_right[actor] = False
            last_acted_bet[actor] = target
        else:
            raise ValueError(f"unsupported source action in prefix: {kind}")
        history.append({"street": {"pre_flop": "preflop", "flop": "flop", "turn": "turn", "river": "river"}[prior_round["name"].lower().replace("preflop", "pre_flop")],
                        "player": f"p{ordered_ids.index(actor)}",
                        "position": position_labels(n)[ordered_ids.index(actor)],
                        "action": hist_action, "amount": target,
                        "added": 0 if hist_action in {"fold", "check"} else added})
        if added:
            stacks[actor] -= added
            contributions[actor] += added
            street_bets[actor] += added
        if stacks[actor] < 0:
            issues.append("prefix_stack_below_zero")

    # Reset street ledger to the current source round when there were no earlier actions there.
    if current_street != ri:
        street_bets = Counter()
        max_bet = 0
        last_full_raise = hand["blindLevel"]["bigBlind"]
        last_acted_bet = {u: None for u in ordered_ids}
        raise_right = {u: active[u] for u in ordered_ids}
    hero = current["userId"]
    hero_index = ordered_ids.index(hero) if hero in ordered_ids else -1
    current_before = street_bets[hero]
    due_raw = max_bet - current_before
    call_amount = min(due_raw, stacks.get(hero, 0))
    total_pot = dead_antes + sum(contributions.values())
    expected_action = current["type"]
    if expected_action == "all_in":
        expected_action = "call" if current_before + current["amount"] <= max_bet else "raise"
    elif expected_action in {"bet", "raise"}:
        expected_action = "raise"
    expected = {"action": expected_action}
    if expected_action == "raise":
        expected["amount"] = current_before + current["amount"]

    state = row["state"]
    max_raise = current_before + stacks.get(hero, 0)
    min_full_raise = max_bet + last_full_raise if max_bet else hand["blindLevel"]["bigBlind"]
    # When the acting stack cannot reach a full raise, PokerKit exposes the
    # only legal short all-in target as both the minimum and maximum.
    opponent_can_match = any(u != hero and active.get(u, False) and stacks.get(u, 0) > 0 for u in ordered_ids)
    can_raise_from_raw = (raise_right.get(hero, False) and active.get(hero, False)
                          and opponent_can_match and max_raise > max_bet)
    min_raise = min(min_full_raise, max_raise) if can_raise_from_raw else 0
    max_raise_bound = max_raise if can_raise_from_raw else 0
    legal_shape = state.get("legal_actions", [])
    legal_expected = ("call" if due_raw > 0 else "check")
    prefix_history_ok = state.get("history") == history
    source_call_amount_ok = not (current["type"] == "call" or (current["type"] == "all_in" and expected_action == "call")) or current.get("amount") == call_amount
    check("incremental_amounts_and_raw_action_mapping",
          current.get("userId") == HERO
          and manifest_action["actor_user_id"] == HERO
          and manifest_action["action_type"] == current["type"]
          and expected == row["expected"]
          and source_call_amount_ok
          and (expected_action != "raise" or min_raise <= expected["amount"] <= max_raise))
    independent_contestable = contestable([contributions[u] for u in ordered_ids],
            [stacks[u] for u in ordered_ids], [active[u] for u in ordered_ids], hero_index, call_amount, total_pot, dead_antes)
    prefix_check = row.get("source_prefix_pot_check") or {}
    check("source_prefix_pot_helper_crosscheck_including_dead_antes",
          prefix_check == {"pot": total_pot, "to_call": call_amount,
                           "contestable_pot": independent_contestable, "dead_antes": dead_antes})
    check("preaction_stack_call_pot_and_eligible_pot",
          state.get("stack") == stacks.get(hero)
          and state.get("current_bet") == current_before
          and state.get("to_call") == call_amount
          and state.get("pot") == total_pot
          and state.get("contestable_pot") == independent_contestable)
    legal_base = (["fold"] if due_raw > 0 else []) + (["call"] if due_raw > 0 else ["check"])
    legal_base = [x for x in ("fold", "check", "call") if x in legal_base]
    bounds_in_row = (state.get("min_raise_to", 0), state.get("max_raise_to", 0))
    raise_advertised = "raise" in legal_shape
    bounds_ok = bounds_in_row == (min_raise, max_raise_bound)
    expected_legal = sorted(legal_base + (["raise"] if can_raise_from_raw else []))
    check("raw_prefix_history_current_action_cut_and_actor_order",
          prefix_history_ok
          and state.get("player_id") == f"p{hero_index}"
          and state.get("players_active") == sum(active.values())
          and state.get("table_size") == n
          and state.get("position") == position_labels(n)[hero_index]
          and row.get("source_action_index") == flat
          and expected_action in legal_shape)
    check("preaction_legal_actions_and_raise_bounds",
          legal_shape == expected_legal and raise_advertised == can_raise_from_raw
          and bounds_ok and (expected_action != "raise" or raise_advertised))

    # Board state is determined by revealed source cards and each current action timestamp.
    target_time = current["timestamp"]
    expected_board = []
    board_ready = True
    for board_ri, board_round in enumerate(hand["rounds"]):
        name = board_round["name"].lower().replace("preflop", "pre_flop")
        if name == "pre_flop":
            continue
        if board_ri > ri:
            break
        if name == "flop":
            reveal_times = board_round.get("communityCardTimestamps", [])
            if len(reveal_times) != 3 or target_time < max(reveal_times):
                board_ready = False
                break
            expected_board.extend(card(x) for x in board_round.get("communityCards", []))
        elif name in {"turn", "river"}:
            reveal_time = board_round.get("communityCardTimestamp")
            if not isinstance(reveal_time, int) or target_time < reveal_time:
                board_ready = False
                break
            expected_board.append(card(board_round["communityCard"]))
    check("board_readiness_and_public_cards", board_ready and state.get("board") == expected_board
          and timeline_monotone and current["timestamp"] >= (max(round_row.get("communityCardTimestamps", [0])) if round_row["name"].lower().replace("preflop", "pre_flop") == "flop" else round_row.get("communityCardTimestamp", 0) or 0))

    # Candidate observations contain only the hero's known cards, current public board,
    # and actions strictly before this source action. Full terminal accounting is separate.
    forbidden_keys = {"opponent_cards", "opponent_hole_cards", "payouts", "pots", "winner", "outcome", "terminal_state", "source_action", "future_actions"}
    state_json = json.dumps(state, sort_keys=True)
    opponent_cards = []
    for p in hand["players"]:
        if p["userId"] == HERO:
            continue
        for c in p.get("pocketCards") or []:
            opponent_cards.append(card(c))
    no_opponent_exposure = (not (forbidden_keys & set(state))
                            and state.get("hole_cards") == hero_cards
                            and all((c not in state.get("hole_cards", []) and c not in state.get("board", [])) for c in opponent_cards)
                            and not any(k.lower() in {"pocketcards", "winners", "payout", "potplayers"} for k in state))
    full_ok, accounting = full_hand_accounting(hand)
    check("opponent_cards_future_actions_current_action_and_terminal_outcome_excluded",
          no_opponent_exposure and state.get("history") == history
          and len(state.get("history", [])) == len(history)
          and "expected" not in state_json and "endChips" not in state_json
          and full_ok)

    # Validate request and episode aliases against the manifest-derived event mapping.
    alias_ids = [a["episodeId"] for a in hand_manifest_row.get("source_episode_aliases", [])]
    alias_check = bool(alias_ids) and all(info["event_id"] == event_id for info in episode_infos)
    check("correct_tournament_identity_and_saved_episode_aliases",
          alias_check and row.get("session_id") == f"triton:tournament:{event_id}"
          and row.get("group_id") == f"session:triton:tournament:{event_id}"
          and request_info.get("variables", {}).get("episodeId") in alias_ids)

    return {"checks": checks, "issues": issues, "fully_verified": all(checks.values()),
            "accounting": accounting, "prefix_facts": {
                "raw_hand_uuid": hid, "original_round_index": ri,
                "original_action_index": ai, "flattened_action_index": flat,
                "round_name": round_row["name"], "raw_timestamp": current["timestamp"],
                "raw_action_type": current["type"], "raw_action_amount_chips_added": current.get("amount"),
                "preaction_stack": stacks.get(hero), "preaction_street_bet": current_before,
                "preaction_due": due_raw, "preaction_call_amount": call_amount,
                "preaction_pot": total_pot, "source_small_blind_amount": sb_amount,
                "dead_antes_before_action": dead_antes,
                "contestable_pot_independent_dead_ante_plus_live_tiers": independent_contestable,
                "preaction_max_bet": max_bet, "preaction_last_full_raise": last_full_raise,
                "raise_right_from_raw_prefix": raise_right.get(hero),
                "opponent_with_live_stack": opponent_can_match,
                "independent_min_raise_to": min_raise, "independent_max_raise_to": max_raise_bound,
                "candidate_min_raise_to": state.get("min_raise_to"), "candidate_max_raise_to": state.get("max_raise_to"),
                "candidate_legal_actions": legal_shape,
                "source_big_blind_amount": bb_amount,
                "source_ante_amount": sum(antes_by_id.values()),
                "source_button_seat": hand.get("dealerSeatNo"),
                "actual_player_count": n, "physical_seat_capacity": capacity,
                "source_board_before_action": expected_board,
                "action_prefix_count": len(history),
                "source_response_sha256": raw_response_sha,
                "source_payload_canonical_sha256": canon_payload_sha,
                "source_request_sha256": req_sha,
                "source_query_sha256": query_sha,
                "source_request_variables": request_info["variables"],
                "tournament_uuid_from_getepisode": event_id,
                "source_episode_aliases": alias_ids}}

# Load and validate all inventory and provenance mappings.
progress_path = BATCH / "progress.json"
hand_manifest_path = BATCH / "hand-manifest.json"
decision_manifest_path = BATCH / "decision-candidate-manifest.json"
inventory_path = BATCH / "request-inventory.jsonl"
prior_summary_path = PRIOR_REVIEW / "summary.json"
prior_rows_path = PRIOR_REVIEW / "per-row-review.json"
prior_facts_path = PRIOR_REVIEW / "notes/source-hand-facts.jsonl"
conversion_run_path = OUT / "conversion-run.json"
progress = read_json(progress_path)
hand_manifest = read_json(hand_manifest_path)["hands"]
decision_manifest = read_json(decision_manifest_path)
manifest_actions = decision_manifest["actions"]
prior_summary = read_json(prior_summary_path)
prior_row_review = read_json(prior_rows_path)
prior_review_rows = prior_row_review["rows"]
prior_source_facts = [json.loads(line) for line in prior_facts_path.read_text(encoding="utf-8").splitlines() if line]
prior_facts_by_hand = {row["raw_hand_uuid"]: row for row in prior_source_facts}
conversion_run = read_json(conversion_run_path)
if (len(prior_review_rows) != 306 or len(prior_facts_by_hand) != 273
        or prior_summary["counts"]["converter_candidate_rows"] != 42
        or prior_summary["counts"]["independently_verified_recommendations"] != 37
        or conversion_run.get("converter_sha256") != sha_bytes((ROOT / "scripts/acquisition_triton_convert.py").read_bytes())):
    raise SystemExit("prior source-review checkpoint does not match the instructed 306/273 and 42/37 totals")
request_rows = [json.loads(line) for line in inventory_path.read_text(encoding="utf-8").splitlines() if line.strip()]
request_by_response = {row["response_path"]: row for row in request_rows}

# Map from saved GetEpisode.tournament.uuid, never from episode IDs or guessed labels.
episode_infos = {}
for path in sorted((BATCH / "raw/episodes").glob("*/GetEpisode.json")):
    episode_id = path.parent.name
    response_rel = rel(path).split("/triton_2023_2024/", 1)[1]
    request = request_by_response[response_rel]
    ep = find_episode(read_json(path), episode_id)
    if ep is None:
        raise SystemExit(f"cannot find GetEpisode payload for {episode_id}")
    event_id = ep["tournament"]["uuid"]
    response_sha = sha_bytes(path.read_bytes())
    request_path = BATCH / request["request_path"]
    request_bytes = request_path.read_bytes()
    request_body = json.loads(request_bytes)
    if (request["operationName"] != "GetEpisode"
            or request["variables"].get("episodeId") != episode_id
            or sha_bytes(request_body["query"].encode()) != request["query_sha256"]
            or request_body.get("variables") != request["variables"]
            or response_sha != request["response_sha256"]):
        raise SystemExit(f"GetEpisode request/response integrity mismatch for {episode_id}")
    progress_ep = progress["episodes"].get(episode_id, {})
    if progress_ep.get("response_sha256") != response_sha:
        raise SystemExit(f"progress GetEpisode hash mismatch for {episode_id}")
    tournament_progress = progress["tournaments"].get(event_id)
    if tournament_progress is None or tournament_progress.get("tournamentId") != event_id:
        raise SystemExit(f"GetEpisode tournament UUID absent from progress event mapping: {event_id}")
    tournament_response = BATCH / tournament_progress["response_path"]
    tournament_data = read_json(tournament_response)
    saved_tournament = find_tournament_uuid(tournament_data, event_id)
    if saved_tournament is None:
        raise SystemExit(f"GetTournamentWithEpisodes response does not confirm {event_id}")
    tournament_request = request_by_response.get(tournament_progress["response_path"])
    if tournament_request is None:
        raise SystemExit(f"GetTournamentWithEpisodes request absent from inventory for {event_id}")
    tournament_request_path = BATCH / tournament_request["request_path"]
    tournament_request_bytes = tournament_request_path.read_bytes()
    tournament_request_body = json.loads(tournament_request_bytes)
    if (tournament_request["operationName"] != "GetTournamentWithEpisodes"
            or sha_bytes(tournament_request_body["query"].encode()) != tournament_request["query_sha256"]
            or tournament_request_body.get("variables") != tournament_request["variables"]
            or sha_bytes(tournament_response.read_bytes()) != tournament_request["response_sha256"]):
        raise SystemExit(f"GetTournamentWithEpisodes request/response integrity mismatch for {event_id}")
    episode_infos[episode_id] = {
        "episode_id": episode_id, "event_id": event_id,
        "event_name": ep["tournament"].get("name"), "episode_title": ep.get("title"),
        "episode_response_path": request["response_path"],
        "episode_response_sha256": response_sha,
        "episode_request_path": request["request_path"],
        "episode_request_sha256": sha_bytes(request_path.read_bytes()),
        "episode_query_sha256": request["query_sha256"],
        "episode_variables": request["variables"],
        "tournament_response_path": tournament_progress["response_path"],
        "tournament_response_sha256": tournament_progress["response_sha256"],
        "tournament_request_path": tournament_request["request_path"],
        "tournament_request_sha256": sha_bytes(tournament_request_bytes),
        "tournament_query_sha256": tournament_request["query_sha256"],
        "tournament_variables": tournament_request["variables"]}

# Resolve all raw response/request facts and load event-scoped converter outputs.
hand_payloads = {}
hand_request_info = {}
hand_episode_infos = {}
hand_event_ids = {}
for hid, entry in hand_manifest.items():
    if len(entry.get("source_response_paths", [])) != 1:
        raise SystemExit(f"expected one canonical response path for {hid}")
    response_rel = entry["source_response_paths"][0]
    req_info = request_by_response.get(response_rel)
    if req_info is None:
        raise SystemExit(f"GetHand response absent from request inventory for {hid}")
    response_path = BATCH / response_rel
    response_bytes = response_path.read_bytes()
    if sha_bytes(response_bytes) != req_info["response_sha256"] or req_info["response_sha256"] not in entry["source_response_hashes"]:
        raise SystemExit(f"GetHand response hash mismatch for {hid}")
    response = json.loads(response_bytes)
    hand = response.get("data", {}).get("handV2")
    if not isinstance(hand, dict) or hand.get("handId") != hid:
        raise SystemExit(f"raw GetHand payload does not match manifest hand UUID {hid}")
    aliases = entry.get("source_episode_aliases", [])
    if not aliases:
        raise SystemExit(f"missing saved episode aliases for {hid}")
    alias_infos = []
    for alias in aliases:
        episode_id = alias["episodeId"]
        info = episode_infos.get(episode_id)
        if info is None or alias.get("requested_hand_id") != hid:
            raise SystemExit(f"manifest episode alias mismatch for {hid}: {alias}")
        alias_infos.append(info)
    event_ids = {i["event_id"] for i in alias_infos}
    if len(event_ids) != 1:
        raise SystemExit(f"cross-event alias ambiguity for {hid}: {sorted(event_ids)}")
    req_path = BATCH / req_info["request_path"]
    req_data = read_json(req_path)
    if (req_info["operationName"] != "GetHand"
            or req_info["variables"].get("handId") != hid
            or req_info["variables"].get("episodeId") not in {a["episodeId"] for a in aliases}
            or sha_bytes(req_data["query"].encode()) != req_info["query_sha256"]
            or req_data.get("variables") != req_info["variables"]):
        raise SystemExit(f"GetHand request sidecar/variables mismatch for {hid}")
    prior_fact = prior_facts_by_hand.get(hid)
    expected_fact_values = {
        "raw_response_path": response_rel,
        "raw_response_sha256": sha_bytes(response_bytes),
        "canonical_hand_payload_sha256": canonical_sha(hand),
        "request_path": req_info["request_path"],
        "request_sha256": sha_bytes(req_path.read_bytes()),
        "query_sha256": req_info["query_sha256"],
        "variables": req_info["variables"],
        "tournament_uuid": next(iter(event_ids)),
        "episode_aliases": aliases,
        "raw_hand_payload": hand,
    }
    if prior_fact is None or any(prior_fact.get(k) != v for k, v in expected_fact_values.items()):
        raise SystemExit(f"primary raw hand/request/episode facts differ from retained source-hand-facts for {hid}")
    hand_payloads[hid] = hand
    hand_request_info[hid] = req_info
    hand_episode_infos[hid] = alias_infos
    hand_event_ids[hid] = next(iter(event_ids))

converter_results = []
for path in sorted(EVENT_OUT.glob("*/converter-output.json")):
    converter_results.append(read_json(path))
if len(converter_results) != len(set(hand_event_ids.values())):
    raise SystemExit("missing saved-tournament-UUID conversion output")
converter_rows = [row for result in converter_results for row in result["records"]]
converter_hand_reports = [row for result in converter_results for row in result["hand_reports"]]
converter_rejections = [row for result in converter_results for row in result["rejections"]]
if len({row["source_decision_id"] for row in converter_rows}) != len(converter_rows):
    raise SystemExit("converter emitted duplicate source decision IDs")

# Source labels are keyed by canonical raw hand UUID + original round/action array indices.
action_by_location = {}
action_coords_by_flat = {}
for action in manifest_actions:
    key = (action["raw_hand_id"], action["original_round_index"], action["original_action_index"])
    if key in action_by_location:
        raise SystemExit(f"duplicate source decision location {key}")
    action_by_location[key] = action
    hand = hand_payloads[action["raw_hand_id"]]
    ri, ai = action["original_round_index"], action["original_action_index"]
    raw = hand["rounds"][ri]["actions"][ai]
    if (action["actor_user_id"] != raw["userId"] or action["action_type"] != raw["type"]
            or action["round_name"].lower().replace("preflop", "pre_flop") != hand["rounds"][ri]["name"].lower().replace("preflop", "pre_flop")
            or action["canonical_decision_id"] != f"{action['raw_hand_id']}:{ri}:{ai}"):
        raise SystemExit(f"candidate manifest/raw label mismatch at {key}")
    if action["hero_cards_status"] == "known_two_cards":
        hero = next(p for p in hand["players"] if p["userId"] == HERO)
        if len(hero.get("pocketCards", [])) != 2 or not all(hero["pocketCards"]):
            raise SystemExit(f"known-card label without two raw hero cards: {key}")
    elif action["hero_cards_status"] == "empty_array":
        hero = next(p for p in hand["players"] if p["userId"] == HERO)
        if hero.get("pocketCards") != []:
            raise SystemExit(f"empty-card label/raw mismatch: {key}")

flat_index_by_location = {}
for hid, hand in hand_payloads.items():
    for flat, ri, ai, _, _ in source_actions(hand):
        flat_index_by_location[(hid, ri, ai)] = flat
prior_rows_by_location = {
    (row["raw_hand_id"], row["original_round_index"], row["original_action_index"]): row
    for row in prior_review_rows
}
if set(prior_rows_by_location) != set(action_by_location):
    raise SystemExit("prior per-row review does not cover exactly the saved decision manifest locations")
for key, action in action_by_location.items():
    prior_row = prior_rows_by_location[key]
    hand = hand_payloads[key[0]]
    raw_action = hand["rounds"][key[1]]["actions"][key[2]]
    req_info = hand_request_info[key[0]]
    raw_path = BATCH / hand_manifest[key[0]]["source_response_paths"][0]
    request_path = BATCH / req_info["request_path"]
    if (prior_row.get("canonical_decision_id") != action["canonical_decision_id"]
            or prior_row.get("raw_action") != raw_action
            or prior_row.get("source_response_sha256") != sha_bytes(raw_path.read_bytes())
            or prior_row.get("source_payload_canonical_sha256") != canonical_sha(hand)
            or prior_row.get("source_request_sha256") != sha_bytes(request_path.read_bytes())
            or prior_row.get("source_query_sha256") != req_info["query_sha256"]
            or prior_row.get("source_request_variables") != req_info["variables"]
            or prior_row.get("source_tournament_uuid") != hand_event_ids[key[0]]):
        raise SystemExit(f"prior row review source/label/hash differs from raw archive at {key}")

rows_by_location = {}
flat_lookup = {}
for row in converter_rows:
    hid = row["canonical_hand_id"].removeprefix("triton:")
    hand = hand_payloads[hid]
    ri, ai, round_row, raw_action = locate_flat(hand, row["source_action_index"])
    key = (hid, ri, ai)
    if key in rows_by_location:
        raise SystemExit(f"converter emitted duplicate hand/round/action candidate: {key}")
    rows_by_location[key] = row
    flat_lookup[key] = row["source_action_index"]
    if key not in action_by_location:
        raise SystemExit(f"converter row has no source-candidate-manifest location: {key}")

# Independently audit all converted candidate rows.
row_reviews = {}
verified_candidate_rows = []
full_accounting_by_hand = {}
for row in converter_rows:
    hid = row["canonical_hand_id"].removeprefix("triton:")
    hand = hand_payloads[hid]
    ri, ai, _, _ = locate_flat(hand, row["source_action_index"])
    key = (hid, ri, ai)
    review = verify_candidate(row, hand, action_by_location[key], hand_manifest[hid],
                              hand_request_info[hid], hand_episode_infos[hid], hand_event_ids[hid])
    row_reviews[key] = review
    if review["accounting"].get("action_payments_reconciled"):
        full_accounting_by_hand[hid] = review["accounting"]
    if review["fully_verified"]:
        verified_candidate_rows.append(key)

# Recompute terminal accounting for every known-card source hand, including hands
# rejected by the frozen player limit or source-history guards.
known_card_hand_ids = {a["raw_hand_id"] for a in manifest_actions
                       if a["hero_cards_status"] == "known_two_cards"}
terminal_accounting_by_known_hand = {}
for hid in sorted(known_card_hand_ids):
    ok, detail = full_hand_accounting(hand_payloads[hid])
    terminal_accounting_by_known_hand[hid] = {"fully_reconciled": ok, **detail}

# Preserve the already-resolved Card Player 37/14 alias as one raw Triton hand.
alias_audit_path = ROOT / "data/acquisition_resume/2026-11-01/report-structured-alias-audit.json"
admission_audit_path = ROOT / "data/acquisition_resume/2026-11-02/admission_audit/audit-results.json"
alias_audit = read_json(alias_audit_path)
admission_audit = read_json(admission_audit_path)
alias_hid = "7c9c95b2-1469-48d9-8c8e-cdf335831fbc"
alias_matches = alias_audit.get("candidate_hand_matches", {}).get("cardplayer-mag-37-14", [])
alias_match = next((row for row in alias_matches if row.get("hand_id") == alias_hid), None)
primary_alias_hand = hand_payloads[alias_hid]
primary_alias_hero = next(row for row in primary_alias_hand["players"] if row["userId"] == HERO)
primary_alias_board = []
for source_round in primary_alias_hand["rounds"]:
    if "communityCards" in source_round:
        primary_alias_board.extend(card(value) for value in source_round["communityCards"])
    elif "communityCard" in source_round:
        primary_alias_board.append(card(source_round["communityCard"]))
if (alias_match is None
        or alias_match.get("hero_cards") != [card(value) for value in primary_alias_hero["pocketCards"]]
        or alias_match.get("board") != primary_alias_board
        or alias_match.get("ivey_start") != primary_alias_hero["startChips"]
        or primary_alias_hero["startChips"] != 13_550_000
        or admission_audit.get("held_report_aliases", {}).get("primary_hand_id") != f"triton:{alias_hid}"
        or admission_audit.get("held_report_aliases", {}).get("rows") != 4
        or admission_audit.get("held_report_aliases", {}).get("report_stack_claim") != 13_600_000):
    raise SystemExit("resolved Card Player 37/14 report alias no longer matches its saved primary Triton hand facts")
report_alias_review = {
    "report_hand_id": "cardplayer-mag-37-14",
    "primary_source_hand_id": f"triton:{alias_hid}",
    "primary_source_path": hand_manifest[alias_hid]["source_response_paths"][0],
    "primary_source_identity_confidence": "high: same event, hero cards, and full board confirmed against saved raw Triton payload",
    "primary_raw_hero_start_chips": primary_alias_hero["startChips"],
    "published_report_stack_claim": 13_600_000,
    "reported_rows_held_as_aliases": 4,
    "report_rows_admitted": 0,
    "legacy_report_pot_omission": "300000 big-blind ante",
    "raw_hand_source_rows": sum(1 for a in manifest_actions if a["raw_hand_id"] == alias_hid),
    "underlying_raw_hands_counted": 1,
    "disposition": "use primary raw Triton identity and source facts; keep all source action rows held while dealer seat/order is unverified; do not add four report prefixes as separate hands",
}

# Create provenance-rich candidates while keeping observations free of source-only facts.
provenance_records = []
for key, row in rows_by_location.items():
    hid, ri, ai = key
    hand = hand_payloads[hid]
    manifest_action = action_by_location[key]
    req = hand_request_info[hid]
    epinfo = hand_episode_infos[hid][0]
    response_rel = hand_manifest[hid]["source_response_paths"][0]
    response_sha = req["response_sha256"]
    request_path = BATCH / req["request_path"]
    raw = hand["rounds"][ri]["actions"][ai]
    enriched = copy.deepcopy(row)
    enriched.update({
        "admission_status": "pending_parent_admission",
        "evidence_tier": "acquired_history_independently_source_reviewed_pending_parent_admission",
        "inspection_status": "inspected_in_source_review",
        "fresh_heldout_eligible": False,
        "source_canonical_decision_id": manifest_action["canonical_decision_id"],
        "source_round_index": ri,
        "source_round_action_index": ai,
        "source_round_name": hand["rounds"][ri]["name"],
        "source_raw_action_type": raw["type"],
        "source_raw_action_amount_chips_added": raw.get("amount"),
        "source_episode_id": epinfo["episode_id"],
        "source_episode_aliases": copy.deepcopy(hand_manifest[hid]["source_episode_aliases"]),
        "source_tournament_uuid": hand_event_ids[hid],
        "source_tournament_name": epinfo["event_name"],
        "source_episode_title": epinfo["episode_title"],
        "source_capture_path": response_rel,
        "source_response_sha256": response_sha,
        "source_request_path": req["request_path"],
        "source_request_sha256": sha_bytes(request_path.read_bytes()),
        "source_query_sha256": req["query_sha256"],
        "source_request_variables": copy.deepcopy(req["variables"]),
        "source_episode_response_path": epinfo["episode_response_path"],
        "source_episode_response_sha256": epinfo["episode_response_sha256"],
        "source_episode_request_path": epinfo["episode_request_path"],
        "source_episode_request_sha256": epinfo["episode_request_sha256"],
        "source_episode_query_sha256": epinfo["episode_query_sha256"],
        "source_episode_variables": copy.deepcopy(epinfo["episode_variables"]),
        "source_tournament_response_path": epinfo["tournament_response_path"],
        "source_tournament_response_sha256": epinfo["tournament_response_sha256"],
        "source_tournament_request_path": epinfo["tournament_request_path"],
        "source_tournament_request_sha256": epinfo["tournament_request_sha256"],
        "source_tournament_query_sha256": epinfo["tournament_query_sha256"],
        "source_tournament_variables": copy.deepcopy(epinfo["tournament_variables"]),
        "source_independent_review": "passed_raw_prefix_review" if row_reviews[key]["fully_verified"] else "held_or_failed_raw_prefix_review",
        "source_review_recommendation": (
            "recommend_parent_admission_review" if row_reviews[key]["fully_verified"] else
            "hold_until_button_order_is_source_verified"
            if not row_reviews[key]["checks"].get("button_order_verified_from_occupied_dealer_seat", True)
            else "exclude_raw_prefix_review_failure"),
    })
    if hid == alias_hid:
        enriched["source_alias_review"] = copy.deepcopy(report_alias_review)
    provenance_records.append(enriched)
# validate_rows recomputes decision/group/record hashes after review metadata.
validated_records = validate_rows(provenance_records) if provenance_records else []
for r in validated_records:
    key = (r["canonical_hand_id"].removeprefix("triton:"), r["source_round_index"], r["source_round_action_index"])

# Build exact review rows for all 306 original labels, including empty-card partials.
all_review_rows = []
status_counts = Counter()
reason_counts = Counter()
known_key_set = set()
heads_up_blocked = []
for action in manifest_actions:
    hid = action["raw_hand_id"]
    hand = hand_payloads[hid]
    ri, ai = action["original_round_index"], action["original_action_index"]
    key = (hid, ri, ai)
    n = len(hand["players"])
    raw = hand["rounds"][ri]["actions"][ai]
    req = hand_request_info[hid]
    epinfo = hand_episode_infos[hid][0]
    raw_path = BATCH / hand_manifest[hid]["source_response_paths"][0]
    raw_resp_sha = sha_bytes(raw_path.read_bytes())
    candidate = rows_by_location.get(key)
    if action["hero_cards_status"] == "empty_array":
        status = "partial_missing_hero_cards"
        reason = "hero_pocket_cards_empty_in_raw_source; excluded regardless of replay"
        rec = "exclude_partial"
    elif n > 8:
        status = "rejected_frozen_protocol_player_count"
        reason = "model_observation_player_count_exceeds_eight"
        rec = "exclude_frozen_protocol_limit"
        known_key_set.add(key)
    elif candidate is None:
        # Find the converter hand-level rejection. It remains a source decision label, not a passed row.
        reports = [x for x in converter_hand_reports if x.get("source_hand_uuid") == hid and x.get("rejection")]
        report_reason = reports[0]["rejection"] if reports else "converter_did_not_emit_candidate"
        status = "rejected_converter_source_history"
        reason = report_reason
        rec = "exclude_until_source_history_resolved"
        known_key_set.add(key)
    else:
        checks = row_reviews[key]
        if not checks["fully_verified"]:
            status = "held_button_order_unverified" if not checks["checks"].get("button_order_verified_from_occupied_dealer_seat", True) else "rejected_independent_source_review"
            reason = ("dealerSeatNo is not an occupied player seat; button holder/order cannot be independently corroborated from the raw player list"
                      if status == "held_button_order_unverified" else "; ".join(checks["issues"]))
            rec = "hold_until_button_order_is_source_verified" if status == "held_button_order_unverified" else "exclude_raw_prefix_review_failure"
        else:
            status = "verified_pending_parent_admission"
            reason = "passed_independent_raw_prefix_review; inspected, not fresh heldout"
            rec = "recommend_parent_admission_review"
        known_key_set.add(key)
    status_counts[status] += 1
    reason_counts[reason] += 1
    replay_check = row_reviews.get(key)
    converter_hand_report = next((x for x in converter_hand_reports if x.get("source_hand_uuid") == hid), {})
    review_row = {
        "canonical_decision_id": action["canonical_decision_id"],
        "source_decision_id": f"triton:{hid}:action:{flat_index_by_location[key]}",
        "stable_source_decision_key": f"triton:{hid}:round:{ri}:action:{ai}",
        "source_hand_uuid": hid,
        "raw_hand_id": hid,
        "original_round_index": ri,
        "original_action_index": ai,
        "flat_source_action_index": flat_index_by_location[key],
        "source_episode_id": action["source_episode_id"],
        "source_episode_aliases": copy.deepcopy(hand_manifest[hid]["source_episode_aliases"]),
        "source_tournament_uuid": hand_event_ids[hid],
        "source_tournament_name": epinfo["event_name"],
        "source_response_path": hand_manifest[hid]["source_response_paths"][0],
        "source_response_sha256": raw_resp_sha,
        "source_payload_canonical_sha256": canonical_sha(hand),
        "source_request_path": req["request_path"],
        "source_request_sha256": sha_bytes((BATCH / req["request_path"]).read_bytes()),
        "source_query_sha256": req["query_sha256"],
        "source_request_variables": copy.deepcopy(req["variables"]),
        "source_episode_response_path": epinfo["episode_response_path"],
        "source_episode_response_sha256": epinfo["episode_response_sha256"],
        "source_episode_request_path": epinfo["episode_request_path"],
        "source_episode_request_sha256": epinfo["episode_request_sha256"],
        "source_episode_query_sha256": epinfo["episode_query_sha256"],
        "source_episode_variables": copy.deepcopy(epinfo["episode_variables"]),
        "source_tournament_request_path": epinfo["tournament_request_path"],
        "source_tournament_request_sha256": epinfo["tournament_request_sha256"],
        "source_tournament_query_sha256": epinfo["tournament_query_sha256"],
        "source_tournament_variables": copy.deepcopy(epinfo["tournament_variables"]),
        "hero_cards_status": action["hero_cards_status"],
        "hero_pocket_cards_raw": copy.deepcopy(next(p.get("pocketCards") for p in hand["players"] if p["userId"] == HERO)),
        "actual_player_count": n,
        "physical_seat_capacity": hand["noOfSeats"],
        "raw_action": copy.deepcopy(raw),
        "raw_round_name": hand["rounds"][ri]["name"],
        "status": status,
        "reason": reason,
        "recommendation": rec,
        "converter_rejection_reason": converter_hand_report.get("rejection"),
        "converter_exclusion_reason": converter_hand_report.get("exclusion"),
        "converter_emitted_candidate": candidate is not None,
        "admission_status": "pending_parent_admission" if candidate else "not_a_candidate_pending_parent_review",
        "fresh_heldout_eligible": False,
        "independent_checks": replay_check["checks"] if replay_check else {},
        "independent_check_issues": replay_check["issues"] if replay_check else [],
        "source_prefix_facts": replay_check["prefix_facts"] if replay_check else None,
        "terminal_accounting": terminal_accounting_by_known_hand.get(hid) if action["hero_cards_status"] == "known_two_cards" else None,
        "terminal_accounting_issue": (
            terminal_accounting_by_known_hand[hid].get("reason")
            if action["hero_cards_status"] == "known_two_cards"
            and not terminal_accounting_by_known_hand[hid].get("fully_reconciled") else None),
        "candidate_decision_id": candidate.get("decision_id") if candidate else None,
        "candidate_record_hash": next((r["record_hash"] for r in validated_records if (r["canonical_hand_id"].removeprefix("triton:"), r["source_round_index"], r["source_round_action_index"]) == key), None),
    }
    if hid == alias_hid:
        review_row["cross_source_alias_review"] = copy.deepcopy(report_alias_review)
    all_review_rows.append(review_row)

if len(all_review_rows) != 306 or len(validated_records) != len(rows_by_location):
    raise SystemExit(f"unexpected review totals: {len(all_review_rows)} labels / {len(validated_records)} candidates")
if len({r["canonical_decision_id"] for r in all_review_rows}) != len(all_review_rows):
    raise SystemExit("source manifest contains duplicate canonical hand/location keys")

# Raw source facts remain available outside observations and are indexed by UUID, not episode.
retained_facts = []
for hid in sorted(hand_payloads):
    entry = hand_manifest[hid]
    request = hand_request_info[hid]
    infos = hand_episode_infos[hid]
    raw_path = BATCH / entry["source_response_paths"][0]
    retained_facts.append({
        "raw_hand_uuid": hid,
        "raw_response_path": entry["source_response_paths"][0],
        "raw_response_sha256": sha_bytes(raw_path.read_bytes()),
        "canonical_hand_payload_sha256": canonical_sha(hand_payloads[hid]),
        "request_path": request["request_path"],
        "request_sha256": sha_bytes((BATCH / request["request_path"]).read_bytes()),
        "query_sha256": request["query_sha256"],
        "variables": request["variables"],
        "episode_aliases": copy.deepcopy(entry["source_episode_aliases"]),
        "episode_provenance": infos,
        "tournament_uuid": hand_event_ids[hid],
        "raw_hand_payload": copy.deepcopy(hand_payloads[hid]),
    })
notes_dir = OUT / "notes"
notes_dir.mkdir(parents=True, exist_ok=True)
(notes_dir / "source-hand-facts.jsonl").write_text("".join(json.dumps(x, sort_keys=True, ensure_ascii=False) + "\n" for x in retained_facts), encoding="utf-8")

# Compare exact raw UUID + original array location identities across named source sets.
source_paths = {
    "development_after_prospective_baseline": ROOT / "data/corpus_splits/development-after-prospective-v1.json",
    "reviewed_2026_candidates": ROOT / "data/acquisition_resume/2026-11-01/triton_2026_conversion/batch-003/candidates-with-provenance.json",
    "2025_candidates": ROOT / "data/acquisition_resume/2026-11-01/triton_2025_conversion/batch-001/candidates.json",
    "old_sample": ROOT / "data/acquisition_sprint_1h/triton_conversion/sample-candidates.json",
}
current_hand_ids = {a["raw_hand_id"] for a in manifest_actions}
current_locations = set(action_by_location)
overlap_results = {}
for name, path in source_paths.items():
    data = read_json(path)
    rows = data.get("records", data.get("candidates", data.get("rows", []))) if isinstance(data, dict) else data
    source_hids = set()
    source_decisions = set()
    source_hand_uuid_locations = set()
    for r in rows:
        for field in ("canonical_hand_id", "hand_id"):
            v = r.get(field)
            if isinstance(v, str) and v.startswith("triton:"):
                source_hids.add(v.split(":", 1)[1])
        source_decision_id = r.get("source_decision_id")
        if isinstance(source_decision_id, str):
            source_decisions.add(source_decision_id)
    shared_hids = current_hand_ids & source_hids
    overlap_results[name] = {
        "rows_examined": len(rows),
        "shared_raw_hand_uuids": sorted(shared_hids),
        "exact_current_source_decision_id_overlaps": sorted(
            r.get("source_decision_id") for r in rows
            if r.get("source_decision_id") in {x.get("source_decision_id") for x in converter_rows}),
        "baseline_source_decision_ids_available": bool(source_decisions),
        "exact_round_action_location_reconciliation": "not possible where no raw hand payload/original array indices are retained",
        "cross_source_semantic_overlap_uncertainty": (
            "possible for public-video/text sources without a shared Triton hand UUID; no independent hand identity was inferred"
            if name == "development_after_prospective_baseline" else
            "no shared Triton raw hand UUID; any same-hand re-capture under a different UUID remains unresolved"
        ),
    }

# Reconcile exact identities against the live admission ledger and held ante correction set.
baseline_path = ROOT / "data/corpus_splits/development-after-prospective-v1.json"
batch_001_path = ROOT / "data/acquisition_resume/2026-11-01/admissions/batch-001.json"
batch_002_path = ROOT / "data/acquisition_resume/2026-11-01/admissions/batch-002.json"
ante_candidates_path = ROOT / "data/acquisition_resume/2026-11-02/ante_correction/candidates.json"
baseline_records = read_json(baseline_path)["records"]
batch_001 = read_json(batch_001_path)
batch_002 = read_json(batch_002_path)
ante_candidates = read_json(ante_candidates_path)
ante_records = ante_candidates["records"]
admitted_records = baseline_records + batch_001["records"] + batch_002["records"]

def _record_key(row):
    return row.get("stable_source_decision_key") or row.get("source_decision_id")

def _triton_hand_uuid(row):
    for field in ("canonical_hand_id", "hand_id"):
        value = row.get(field)
        if isinstance(value, str) and value.startswith("triton:"):
            return value.split(":", 1)[1]
    key = row.get("stable_source_decision_key") or row.get("source_decision_id")
    if isinstance(key, str) and key.startswith("triton:"):
        return key.split(":", 2)[1]
    return None

admitted_decision_ids = [row.get("decision_id") for row in admitted_records]
admitted_record_hashes = [row.get("record_hash") for row in admitted_records]
admitted_canonical_hands = {row.get("canonical_hand_id") or row.get("hand_id") for row in admitted_records}
admitted_source_keys = {_record_key(row) for row in admitted_records if _record_key(row)}
ante_source_ids = {row.get("source_decision_id") for row in ante_records}
ante_stable_keys = {row.get("stable_source_decision_key") for row in ante_records}
held_ante_ids = set(batch_001.get("held_source_decision_ids", []))
candidate_stable_keys = {row.get("stable_source_decision_key") for row in converter_rows}
candidate_source_ids = {row.get("source_decision_id") for row in converter_rows}
admitted_hand_ids = {value for row in admitted_records if (value := _triton_hand_uuid(row))}
ante_hand_ids = {value for row in ante_records if (value := _triton_hand_uuid(row))}
candidate_hand_ids = {key[0] for key in rows_by_location}
if (len(admitted_records) != 80 or len(set(admitted_decision_ids)) != 80
        or len(set(admitted_record_hashes)) != 80
        or len(admitted_canonical_hands) != 43
        or len(ante_records) != 21 or len(ante_source_ids) != 21
        or ante_source_ids != held_ante_ids
        or len(ante_stable_keys) != 21
        or (admitted_source_keys & ante_stable_keys)
        or (candidate_stable_keys & admitted_source_keys)
        or (candidate_stable_keys & ante_stable_keys)
        or (candidate_hand_ids & admitted_hand_ids)
        or (candidate_hand_ids & ante_hand_ids)):
    raise SystemExit("candidate/current-80/pending-ante identity reconciliation failed; do not merge or count duplicates")
admission_dedup_review = {
    "current_admitted_records": len(admitted_records),
    "current_admitted_unique_decision_ids": len(set(admitted_decision_ids)),
    "current_admitted_unique_record_hashes": len(set(admitted_record_hashes)),
    "current_admitted_unique_hands": len(admitted_canonical_hands),
    "current_admitted_source_stable_keys_available": len(admitted_source_keys),
    "pending_ante_correction_records": len(ante_records),
    "pending_ante_exact_source_decision_ids": len(ante_source_ids),
    "pending_ante_stable_source_keys": len(ante_stable_keys),
    "pending_ante_keys_equal_batch_001_held_list": ante_source_ids == held_ante_ids,
    "pending_ante_exact_key_overlap_with_current_admissions": len(admitted_source_keys & ante_stable_keys),
    "pending_ante_hands_already_present_in_current_admissions": len(admitted_hand_ids & ante_hand_ids),
    "pending_ante_same_hand_different_action_cases": [
        {
            "raw_hand_uuid": hid,
            "pending_ante_source_decision_ids": sorted(row["source_decision_id"] for row in ante_records
                                                        if _triton_hand_uuid(row) == hid),
            "already_admitted_source_decision_ids": sorted(_record_key(row) for row in admitted_records
                                                            if _triton_hand_uuid(row) == hid and _record_key(row)),
            "note": "same raw hand does not make distinct source action keys duplicates",
        }
        for hid in sorted(admitted_hand_ids & ante_hand_ids)
    ],
    "candidate_source_rows": len(converter_rows),
    "candidate_exact_key_overlap_with_current_admissions": len(candidate_stable_keys & admitted_source_keys),
    "candidate_exact_key_overlap_with_pending_ante_rows": len(candidate_stable_keys & ante_stable_keys),
    "candidate_hand_uuid_overlap_with_current_admissions": sorted(candidate_hand_ids & admitted_hand_ids),
    "candidate_hand_uuid_overlap_with_pending_ante_rows": sorted(candidate_hand_ids & ante_hand_ids),
    "candidate_ids_remain_pending_parent_admission": True,
    "pending_ante_rows_remain_unadmitted": True,
}

# Compare this run with the prior 42-row / 37-recommendation review. A count
# change is recognized only when the exact six formerly blocked HU keys now pass.
prior_candidates = {key for key, row in prior_rows_by_location.items() if row["converter_emitted_candidate"]}
prior_recommendations = {key for key, row in prior_rows_by_location.items()
                         if row["status"] == "verified_pending_parent_admission"}
prior_hu_blocked = {key for key, row in prior_rows_by_location.items()
                    if row["status"] == "heads_up_replay_blocked"}
current_candidates = set(rows_by_location)
current_recommendations = {tuple(key) for key in verified_candidate_rows}
current_button_holds = {key for key, row in rows_by_location.items()
                        if not row_reviews[key]["checks"].get("button_order_verified_from_occupied_dealer_seat", True)}
prior_status_changes = {key for key, old in prior_rows_by_location.items()
                        if next(row for row in all_review_rows
                                if (row["raw_hand_id"], row["original_round_index"], row["original_action_index"]) == key)["status"] != old["status"]}
if (len(prior_candidates) != 42 or len(prior_recommendations) != 37 or len(prior_hu_blocked) != 6
        or current_candidates - prior_candidates != prior_hu_blocked
        or prior_candidates - current_candidates
        or current_recommendations - prior_recommendations != prior_hu_blocked
        or prior_recommendations - current_recommendations
        or prior_status_changes != prior_hu_blocked
        or len(current_button_holds) != 5):
    raise SystemExit("current converter delta is broader than the independently verified six HU rows")
old_review_comparison = {
    "prior_converter_candidate_rows": len(prior_candidates),
    "prior_independent_recommendations": len(prior_recommendations),
    "prior_heads_up_rows_blocked_before_converter_fix": len(prior_hu_blocked),
    "current_converter_candidate_rows": len(current_candidates),
    "current_independent_recommendations": len(current_recommendations),
    "new_candidate_keys": [f"{hid}:{ri}:{ai}" for hid, ri, ai in sorted(current_candidates - prior_candidates)],
    "new_recommendation_keys": [f"{hid}:{ri}:{ai}" for hid, ri, ai in sorted(current_recommendations - prior_recommendations)],
    "removed_prior_candidate_keys": [f"{hid}:{ri}:{ai}" for hid, ri, ai in sorted(prior_candidates - current_candidates)],
    "prior_row_status_keys_changed": [f"{hid}:{ri}:{ai}" for hid, ri, ai in sorted(prior_status_changes)],
    "all_count_delta_attributed_to_verified_hu_fix": current_candidates - prior_candidates == prior_hu_blocked
        and current_recommendations - prior_recommendations == prior_hu_blocked,
}

alias_row_review = {
    **report_alias_review,
    "current_triton_action_rows_held_for_button_order": sum(
        1 for row in all_review_rows if row["raw_hand_id"] == alias_hid
        and row["status"] == "held_button_order_unverified"),
    "cardplayer_report_source_alias_audit_path": str(alias_audit_path.relative_to(ROOT)),
    "admission_audit_path": str(admission_audit_path.relative_to(ROOT)),
    "raw_hand_counted_once": True,
}
for row in all_review_rows:
    if row["raw_hand_id"] == alias_hid:
        row["cross_source_alias_review"] = copy.deepcopy(alias_row_review)

terminal_accounting_failures = [
    {
        "raw_hand_uuid": hid,
        "decision_keys": sorted(row["canonical_decision_id"] for row in all_review_rows if row["raw_hand_id"] == hid),
        "review_status": next(row["status"] for row in all_review_rows if row["raw_hand_id"] == hid),
        "reason": values.get("reason"),
        "disposition": "source terminal payout accounting is unsupported; keep frozen player-count exclusions and do not create a candidate",
    }
    for hid, values in sorted(terminal_accounting_by_known_hand.items()) if not values.get("fully_reconciled")
]

# Input hashes and overall summaries.
input_hashes = {
    "progress_json_sha256": sha_bytes(progress_path.read_bytes()),
    "hand_manifest_json_sha256": sha_bytes(hand_manifest_path.read_bytes()),
    "decision_candidate_manifest_json_sha256": sha_bytes(decision_manifest_path.read_bytes()),
    "indexed_hand_inventory_json_sha256": sha_bytes((BATCH / "indexed-hand-inventory.json").read_bytes()),
    "request_inventory_jsonl_sha256": sha_bytes(inventory_path.read_bytes()),
    "prior_review_summary_json_sha256": sha_bytes(prior_summary_path.read_bytes()),
    "prior_per_row_review_json_sha256": sha_bytes(prior_rows_path.read_bytes()),
    "prior_source_hand_facts_jsonl_sha256": sha_bytes(prior_facts_path.read_bytes()),
    "conversion_run_manifest_json_sha256": sha_bytes(conversion_run_path.read_bytes()),
    "root_converter_sha256": conversion_run["converter_sha256"],
    "root_pot_eligibility_helper_sha256": sha_bytes((ROOT / "scripts/acquisition_pot_eligibility.py").read_bytes()),
    "independent_reviewer_script_sha256": sha_bytes(Path(__file__).read_bytes()),
    "reconversion_runner_script_sha256": sha_bytes((OUT / "reconvert.py").read_bytes()),
    "frozen_admission_and_alias_reference_hashes": {
        str(path.relative_to(ROOT)): sha_bytes(path.read_bytes()) for path in (
            baseline_path, batch_001_path, batch_002_path, ante_candidates_path,
            admission_audit_path, alias_audit_path)
    },
    "raw_hand_response_count": len(hand_payloads),
    "raw_hand_response_hashes": {hid: sha_bytes((BATCH / hand_manifest[hid]["source_response_paths"][0]).read_bytes()) for hid in sorted(hand_payloads)},
    "raw_getepisode_response_hashes": {epid: info["episode_response_sha256"] for epid, info in sorted(episode_infos.items())},
    "gethand_query_hashes": {hid: hand_request_info[hid]["query_sha256"] for hid in sorted(hand_request_info)},
    "gethand_request_variables": {hid: hand_request_info[hid]["variables"] for hid in sorted(hand_request_info)},
}
counts = {
    "indexed_hand_uuids": len(hand_manifest),
    "indexed_hand_request_responses": len(hand_payloads),
    "ivey_present_hands": sum(bool(entry.get("ivey_present")) for entry in hand_manifest.values()),
    "known_card_ivey_texas_labels": sum(a["hero_cards_status"] == "known_two_cards" for a in manifest_actions),
    "known_card_hands": len({a["raw_hand_id"] for a in manifest_actions if a["hero_cards_status"] == "known_two_cards"}),
    "empty_card_partial_labels": sum(a["hero_cards_status"] == "empty_array" for a in manifest_actions),
    "converter_candidate_rows": len(converter_rows),
    "independently_verified_recommendations": len(verified_candidate_rows),
    "pending_parent_admission_rows": len(validated_records),
    "recommended_for_parent_admission_review": len(verified_candidate_rows),
    "candidate_rows_held_pending_source_proof": len(validated_records) - len(verified_candidate_rows),
    "current_admitted_decisions_read_only": len(admitted_records),
    "pending_ante_correction_decisions_read_only": len(ante_records),
    "candidate_exact_source_key_duplicates_with_current_or_pending": (
        len(candidate_stable_keys & admitted_source_keys) + len(candidate_stable_keys & ante_stable_keys)),
    "known_card_terminal_accounting_hands_reconciled": sum(
        result["fully_reconciled"] for result in terminal_accounting_by_known_hand.values()),
    "known_card_terminal_accounting_hands_checked": len(terminal_accounting_by_known_hand),
    "known_card_terminal_accounting_failures": len(terminal_accounting_failures),
    "candidate_hands_with_terminal_accounting_reconciled": sum(
        terminal_accounting_by_known_hand[hid]["fully_reconciled"] for hid in {key[0] for key in rows_by_location}),
    "candidate_hands_with_terminal_accounting_checked": len({key[0] for key in rows_by_location}),
    "heads_up_replayed_candidate_rows": sum(1 for row in converter_rows if row["source_actual_player_count"] == 2),
    "heads_up_replayed_candidate_hands": len({row["canonical_hand_id"] for row in converter_rows
                                               if row["source_actual_player_count"] == 2}),
    "held_button_order_unverified_rows": status_counts["held_button_order_unverified"],
    "heads_up_blocked_rows": len(heads_up_blocked),
    "known_card_rows_rejected_by_frozen_player_count": status_counts["rejected_frozen_protocol_player_count"],
    "known_card_rows_rejected_by_converter_source_history": status_counts["rejected_converter_source_history"],
    "known_card_rows_independent_review_failed": status_counts["rejected_independent_source_review"],
    "row_status_counts": dict(sorted(status_counts.items())),
    "row_reason_counts": dict(sorted(reason_counts.items())),
    "tournament_uuid_groups": len(set(hand_event_ids.values())),
    "multi_event_alias_hands": sum(len({i["event_id"] for i in hand_episode_infos[hid]}) > 1 for hid in hand_payloads),
    "multi_episode_alias_hands": sum(len(hand_manifest[hid].get("source_episode_aliases", [])) > 1 for hid in hand_payloads),
    "source_actions_manifest_canonical_location_keys_unique": len(action_by_location) == len(manifest_actions),
    "cross_source_uuid_overlap_by_dataset": {k: len(v["shared_raw_hand_uuids"]) for k, v in overlap_results.items()},
}
conversion_output_hashes = {rel(p): sha_bytes(p.read_bytes()) for p in sorted(EVENT_OUT.glob("*/converter-output.json"))}
summary = {
    "schema_version": 1,
    "review_status": "completed_independent_raw_prefix_review_pending_parent_admission",
    "batch": "data/acquisition_resume/2026-11-01/triton_2023_2024",
    "converter": "scripts/acquisition_triton_convert.py from the project .venv, run once per saved GetEpisode.tournament.uuid group using only the 33 known-card hand payloads",
    "counts": counts,
    "converter_tournament_counts": {p.parent.name: r["counts"] for p, r in zip(sorted(EVENT_OUT.glob("*/converter-output.json")), converter_results)},
    "heads_up_blocked_row_keys": sorted(heads_up_blocked),
    "button_order_blocked_row_keys": sorted(r["canonical_decision_id"] for r in all_review_rows if r["status"] == "held_button_order_unverified"),
    "current_admission_dedup_review": admission_dedup_review,
    "prior_review_delta": old_review_comparison,
    "resolved_report_alias_review": alias_row_review,
    "terminal_accounting_failures": terminal_accounting_failures,
    "input_hashes": input_hashes,
    "conversion_output_hashes": conversion_output_hashes,
    "cross_source_overlap_review": overlap_results,
    "limitations": [
        "All indexed hand UUIDs are marked inspected; none are fresh held-out data.",
        "All generated candidate records remain pending parent admission; this review does not admit or split rows.",
        "Six known-card heads-up labels were reconverted under the current ordering fix and independently source-reviewed; they remain inspected development examples pending parent admission.",
        "Text/video baseline rows do not carry a canonical Triton hand UUID; semantic overlap with those sources remains unresolved.",
        "The exact 80 admitted keys and 21 pending ante-correction keys were read and deduplicated by stable source decision key; no Triton 2023–2024 candidate key or raw hand UUID overlaps either set.",
        "Four Card Player 37/14 report rows remain held aliases of one Triton primary hand with a 13.55m raw starting stack; they are not separate hands and are not among the current 80 admissions.",
        "One known-card nine-player raw hand has terminal pot awards that do not sum to the source pot; it remains excluded by the frozen >8 player guard and is explicitly listed as unsupported source accounting.",
        "Only saved raw archives, request sidecars, request inventory, manifests, and frozen candidate files were used; no network or policy evaluation was used.",
    ],
}

# All passing candidate rows are retained as pending; review rows retain source facts outside state.
candidates_report = {
    "schema_version": 1,
    "status": "converted_candidates_pending_parent_admission_with_per_row_source_review",
    "counts": {"converter_candidate_decisions": len(converter_rows),
               "independently_verified_recommendations": len(verified_candidate_rows),
               "recommended_for_parent_admission_review": len(verified_candidate_rows),
               "held_source_review": len(validated_records) - len(verified_candidate_rows),
               "pending_parent_admission": len(validated_records),
               "newly_admitted_decisions": 0},
    "input_hashes": input_hashes,
    "current_admission_dedup_review": admission_dedup_review,
    "prior_review_delta": old_review_comparison,
    "resolved_report_alias_review": alias_row_review,
    "terminal_accounting_failures": terminal_accounting_failures,
    "records": validated_records,
    "conversion_outputs": [rel(p) for p in sorted(EVENT_OUT.glob("*/converter-output.json"))],
    "limitations": summary["limitations"],
}
(OUT / "candidates.json").write_text(json.dumps(candidates_report, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
(OUT / "per-row-review.json").write_text(json.dumps({"review_status": summary["review_status"], "counts": counts,
    "rows": all_review_rows, "heads_up_blocked_row_keys": sorted(heads_up_blocked),
    "cross_source_overlap_review": overlap_results,
    "current_admission_dedup_review": admission_dedup_review,
    "prior_review_delta": old_review_comparison,
    "resolved_report_alias_review": alias_row_review,
    "terminal_accounting_failures": terminal_accounting_failures}, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
(OUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")

# Short Markdown handback, with exact recommendations and reasons.
status_lines = "\n".join(f"| {k} | {v} |" for k, v in sorted(status_counts.items()))
reason_lines = "\n".join(f"| {k} | {v} |" for k, v in sorted(Counter(r["reason"] for r in all_review_rows).items()))
review_md = f'''# Triton 2023–2024 independent source review

Status: completed raw-prefix review; every recommended row remains pending parent admission.

The archive has {counts['indexed_hand_uuids']} unique indexed hand UUIDs, {counts['ivey_present_hands']} Ivey-present hands, and {counts['known_card_ivey_texas_labels'] + counts['empty_card_partial_labels']} Ivey Texas labels. Of these, {counts['known_card_ivey_texas_labels']} labels across {counts['known_card_hands']} hands have two known hero cards; the remaining {counts['empty_card_partial_labels']} are partial empty-card labels.

## Counts

| Review result | Rows |
| --- | ---: |
{status_lines}

The converter emitted {len(converter_rows)} known-card decisions. Independent raw-prefix checks recommend {len(verified_candidate_rows)} for parent admission review; {status_counts['held_button_order_unverified']} are held because the recorded dealer seat is not occupied and button order cannot be independently confirmed. All {len(validated_records)} emitted rows remain pending parent admission. Newly admitted: 0. The batch is inspected and cannot be treated as fresh held-out data.

## Known-card exclusions and blockers

- Heads-up labels replayed under the current ordering fix: {sum(r['actual_player_count'] == 2 and r['converter_emitted_candidate'] for r in all_review_rows)}; per-row source and order results are retained above.
- Button seat not occupied in raw player list: {status_counts['held_button_order_unverified']} rows. Exact keys: {', '.join(sorted(r['canonical_decision_id'] for r in all_review_rows if r['status'] == 'held_button_order_unverified'))}.
- Frozen >8 actual-player protocol limit: {status_counts['rejected_frozen_protocol_player_count']} labels (`model_observation_player_count_exceeds_eight`). Exact keys: {', '.join(sorted(r['canonical_decision_id'] for r in all_review_rows if r['status'] == 'rejected_frozen_protocol_player_count'))}.
- Missing explicit small and big blind posts in raw history: {status_counts['rejected_converter_source_history']} labels. Exact keys: {', '.join(sorted(r['canonical_decision_id'] for r in all_review_rows if r['status'] == 'rejected_converter_source_history'))}; rows remain unsupported by the saved source history.
- Empty-card partial labels: {status_counts['partial_missing_hero_cards']}; all remain excluded and unconverted.
- Previous review delta: {old_review_comparison['prior_converter_candidate_rows']} candidates / {old_review_comparison['prior_independent_recommendations']} recommendations became {old_review_comparison['current_converter_candidate_rows']} / {old_review_comparison['current_independent_recommendations']}; exactly the six formerly blocked heads-up keys were added after independent replay. No prior candidate or recommendation was removed.

## Row reasons

| Reason | Rows |
| --- | ---: |
{reason_lines}

## Source and replay checks

Each emitted candidate was matched to the source UUID plus original round/action indices, verified against the raw hand prefix, and checked for hero cards, explicit forced bets, seat/button order, incremental amounts, pre-action stack/call/pot/contestable pot, legal action and raise bounds, board reveal timestamps, history cutoff, and hidden opponent/future/terminal information. Full terminal chip and pot accounting was recomputed independently. Request variables, query hashes, raw response hashes, canonical payload hashes, and tournament UUIDs from saved `GetEpisode.tournament.uuid` were retained in the row review and `notes/source-hand-facts.jsonl`.

The converter was run once per each of {len(set(hand_event_ids.values()))} saved tournament UUID groups. There are no indexed UUID aliases spanning multiple tournament UUIDs. Cross-source UUID overlaps with the checked baseline, 2025, 2026, and old sample sets: {', '.join(f'{k}={v}' for k,v in counts['cross_source_uuid_overlap_by_dataset'].items())}. The baseline's text/video rows cannot establish canonical hand UUIDs, so possible same-hand overlap remains unresolved rather than presumed distinct.

The current admission ledger has {admission_dedup_review['current_admitted_records']} admitted decisions across {admission_dedup_review['current_admitted_unique_hands']} hands; the separate ante-correction packet has {admission_dedup_review['pending_ante_correction_records']} pending decisions. Candidate stable keys overlap neither set. One ante-pending action shares a hand with an admitted action but has a different source key: hand `3202f078-1b51-4de2-9e20-72a58e05a8a4`, pending action 6 versus admitted action 10. These 48 candidate rows remain pending parent admission, and the pending ante rows remain unadmitted. The four Card Player 37/14 report rows are held aliases of Triton hand {alias_hid}; raw Triton records Ivey at 13.55m while the report says 13.6m and omits the 300k big-blind ante. The report rows are not admitted and do not create another hand.

Every candidate is bound to its raw GetHand response and request hashes, query hash and variables, original hand/round/action key, and saved tournament UUID. The independent prefix ledger preserves source action-array order, treats antes as dead common money, checks live contribution tiers and eligible pot, validates board reveal cutoffs and excludes the current/future action, opponent cards, and terminal outcomes from each observation. All {counts['candidate_hands_with_terminal_accounting_reconciled']} emitted candidate hands pass full terminal accounting. Full source terminal accounting was also recomputed for all {counts['known_card_terminal_accounting_hands_checked']} known-card hands; {counts['known_card_terminal_accounting_hands_reconciled']} reconcile. The remaining hand, `89a6a46c-d708-4b27-82bb-27d1e1b9b5e5`, has source terminal awards that do not sum to the reported pot and remains rejected by the >8 actual-player guard.

Raw source facts are retained outside each candidate observation. No policy call, model evaluation, admission write, split edit, commit, or push was performed. SHA inventory is in `summary.json`; raw JSON payloads are referenced by their unchanged paths in the original acquisition folder and copied by hand UUID to `notes/source-hand-facts.jsonl`.
'''
(OUT / "review.md").write_text(review_md, encoding="utf-8")
print(json.dumps({"counts": counts, "candidate_count": len(validated_records),
                  "fully_verified": len(verified_candidate_rows),
                  "heads_up_blocked": sorted(heads_up_blocked),
                  "raw_hand_facts_retained": len(retained_facts)}, indent=2, sort_keys=True))
