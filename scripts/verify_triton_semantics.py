"""Independently check public Triton source accounting, without policy calls.

This checks raw payload semantics, not comparison-corpus admission. In
particular, terminal payout fields must never enter a predecision observation.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


IVEY = "3970ce21-3d14-4bdc-97ca-98df8220d040"
FORCED = {"ante", "small_blind", "big_blind", "straddle", "small_ante", "big_ante"}
DEAD = {"ante", "small_ante", "big_ante"}
DELIBERATE = {"raise", "call", "bet", "all_in", "check", "fold"}


def chips(value):
    if type(value) is not int or value < 0:
        raise ValueError("chip amounts must be nonnegative integers")
    return value


def inspect_hand(hand):
    if hand["pokerVariant"] != "texas":
        return {"hand_id": hand["handId"], "excluded": "variant is not texas"}
    players = {p["userId"]: p for p in hand["players"]}
    if len(players) != len(hand["players"]):
        raise ValueError("duplicate player identity")
    spent, payouts, pot_contributions = Counter(), Counter(), Counter()
    problems, raised_targets = [], []
    hero_actions = 0
    for round_ in hand["rounds"]:
        live = Counter()
        for action_index, action in enumerate(round_["actions"]):
            actor, kind = action["userId"], action["type"]
            if actor not in players or kind not in FORCED | DELIBERATE:
                raise ValueError("unknown action actor or action type")
            amount = chips(action.get("amount", 0))
            remaining = chips(players[actor]["startChips"]) - spent[actor]
            price = max(live.values(), default=0) - live[actor]
            where = {"round": round_["name"], "action_index": action_index,
                     "type": kind, "user_id": actor}
            if amount > remaining:
                problems.append({**where, "reason": "payment exceeds remaining stack"})
            if kind == "call" and amount != min(price, remaining):
                problems.append({**where, "reason": "call differs from additional price",
                                 "amount": amount, "price": price})
            if kind == "check" and price != 0:
                problems.append({**where, "reason": "check faces a live wager"})
            if kind == "all_in" and amount != remaining:
                problems.append({**where, "reason": "all-in does not exhaust remaining stack"})
            if kind == "raise":
                target = live[actor] + amount
                raised_targets.append({**where, "raw_added": amount, "street_target": target})
                if target <= max(live.values(), default=0):
                    problems.append({**where, "reason": "raise target does not increase live wager"})
            spent[actor] += amount
            if kind not in DEAD:
                live[actor] += amount
            hero_actions += actor == IVEY and kind in DELIBERATE
    for pot in hand["pots"]:
        if sum(chips(p["amount"]) for p in pot["potPlayers"]) != chips(pot["totalAmount"]):
            problems.append({"reason": "pot contributions do not sum to pot total"})
        for player in pot["potPlayers"]:
            pot_contributions[player["userId"]] += chips(player["amount"])
        for player in pot["hi"]["sidePlayers"]:
            payouts[player["userId"]] += chips(player["winAmount"])
    for actor, player in players.items():
        if pot_contributions[actor] != spent[actor]:
            problems.append({"user_id": actor, "reason": "terminal pot attribution differs from payments"})
        derived = chips(player["startChips"]) - spent[actor] + payouts[actor]
        if derived != chips(player["endChips"]):
            problems.append({"user_id": actor, "reason": "terminal stack does not reconcile",
                             "derived": derived, "source": player["endChips"]})
    if sum(chips(p["startChips"]) for p in players.values()) != sum(chips(p["endChips"]) for p in players.values()):
        problems.append({"reason": "total chips change across hand"})
    hero = players.get(IVEY)
    known = bool(hero and len(hero.get("pocketCards", [])) == 2
                 and all(hero["pocketCards"]))
    return {"hand_id": hand["handId"], "source_order_no": hand["orderNo"],
            "physical_capacity": hand["noOfSeats"], "actual_players": len(players),
            "ivey_present": hero is not None, "ivey_cards_known": known,
            "ivey_deliberate_actions": hero_actions,
            "known_card_ivey_actions": hero_actions if known else 0,
            "raw_raise_to_derivations": raised_targets,
            "accounting_and_prefix_price_checks_pass": not problems,
            "problems": problems}


def inspect_payload(path):
    path = Path(path)
    document = json.loads(path.read_text())
    data = document["data"]
    if isinstance(data.get("handV2"), dict):
        hands = [data["handV2"]]
    elif isinstance(data.get("game"), dict) and isinstance(data["game"].get("hands"), list):
        hands = data["game"]["hands"]
    else:
        raise ValueError("payload contains neither a completed hand nor a game hand list")
    ids = [h["handId"] for h in hands]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate raw hand IDs")
    rows = [inspect_hand(hand) for hand in hands]
    return {"schema_version": 1, "source_payload": str(path),
            "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "raw_hands": len(rows), "ivey_hands": sum(r.get("ivey_present", False) for r in rows),
            "known_card_ivey_hands": sum(r.get("ivey_cards_known", False) for r in rows),
            "known_card_ivey_actions": sum(r.get("known_card_ivey_actions", 0) for r in rows),
            "all_checks_pass": all(r.get("accounting_and_prefix_price_checks_pass", False) for r in rows),
            "new_comparison_admissions": 0, "no_policy_called": True,
            "limitation": "Accounting validation alone does not establish corpus admission, chronological coverage, card encoding, or correct converter observations.",
            "hands": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = inspect_payload(args.source)
    with Path(args.output).open("x") as output:
        json.dump(result, output, indent=2, sort_keys=True, allow_nan=False)
        output.write("\n")
    print(json.dumps({k: result[k] for k in ("raw_hands", "ivey_hands", "known_card_ivey_hands", "known_card_ivey_actions", "all_checks_pass")}))
    raise SystemExit(0 if result["all_checks_pass"] else 1)
