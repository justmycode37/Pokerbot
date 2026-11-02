"""Normalize attributed report snapshots without changing strategy code."""
import copy
import json
from pathlib import Path

from .state import Observation


def _session(hand):
    if "2014_aussie_millions" in hand["hand_id"]:
        return "2014-aussie-millions-250k"
    if "2020_millions_sochi" in hand["hand_id"]:
        return "2020-millions-sochi-25k"
    if "2018_big_one" in hand["hand_id"]:
        return "2018-wsop-big-one"
    return hand["hand_id"]


def _normalize_state(hand, snapshot):
    state = copy.deepcopy(snapshot["observation"])
    state["player_id"] = "Phil Ivey"
    state.setdefault("seed", 0)
    state.setdefault("history", [])
    if hand["blinds_and_antes"].get("table_size"):
        state["table_size"] = hand["blinds_and_antes"]["table_size"]
    corrections = []
    if hand["hand_id"] == "ivey_leow_heath_2020_millions_sochi_25k" and not state["to_call"]:
        # These reports put Ivey last after the other live players checked.
        # A new bet would reopen action, but that is not yet part of the prefix.
        state["players_to_act"] = 0
        corrections.append("players_to_act counts pending action before a new bet, so prior checkers are not counted.")
    if hand["hand_id"] == "ivey_bonomo_2018_big_one_doubleup":
        state["players_active"] = 4
        state["history"] = [{"street": "preflop", "player": "UTG", "action": "fold", "added": 0}]
        corrections.append("Five players were dealt; the player before Ivey's cutoff folded, leaving four active.")
    Observation.from_dict(state)
    return state, corrections


def _all_in_call(hand, first_state):
    """Recover a further preflop call from known targets and initial stack.

    Uses only public actions. No opponent private cards or later board appear
    in the derived observation. Last-call 'added' values are recomputed from
    street totals rather than trusting an inconsistent derived field.
    """
    actions = hand["actions"]
    if not actions or any(a["street"] != "preflop" for a in actions):
        return None
    if len(actions) < 3 or actions[-1]["player"] != "Phil Ivey" or actions[-1]["action"] != "call":
        return None
    if actions[-2]["action"] != "raise_all_in" or type(actions[-2].get("amount")) is not int:
        return None
    state = copy.deepcopy(first_state)
    start = next(i for i, a in enumerate(actions) if a["player"] == "Phil Ivey")
    for a in actions[start:-1]:
        added = a.get("added")
        if type(added) is not int or type(a.get("amount")) is not int:
            return None
        if a["player"] != "Phil Ivey" and state["players_active"] > 2:
            state["history"].append({"street": "preflop", "player": "BB", "action": "fold", "added": 0})
        state["pot"] += added
        if a["player"] == "Phil Ivey":
            state["stack"] -= added
            state["current_bet"] = a["amount"]
        state["history"].append({"street": "preflop", "player": a["player"],
            "action": "raise" if a["action"] == "raise_all_in" else a["action"],
            "amount": a["amount"], "added": added})
    state.update(to_call=min(state["stack"], actions[-2]["amount"] - state["current_bet"]),
                 players_active=2, players_to_act=0, min_raise_to=0, max_raise_to=0,
                 legal_actions=["fold", "call"], contestable_pot=state["pot"])
    Observation.from_dict(state)
    return state


def load_public_report_decisions(path=None):
    path = Path(path) if path else Path(__file__).resolve().parents[1] / "data/public_ivey_reports/decision-evidence.json"
    document = json.loads(path.read_text())
    sources = {s["source_id"]: s["direct_url"] for s in document["source_registry"]}
    rows = []
    for hand in document["hands"]:
        common = {"hand_id": hand["hand_id"], "session_id": _session(hand),
                  "format": "tournament_nlhe", "source": sources[hand["source_ids"][0]],
                  "corroborating_sources": [sources[k] for k in hand["source_ids"]],
                  "evidence_tier": "attributed_report_observed_and_derived_fields"}
        for snapshot in hand["snapshots"]:
            state, notes = _normalize_state(hand, snapshot)
            label = snapshot["expected_action"]
            expected = {"action": label["action"]}
            if label["action"] == "raise":
                expected["amount"] = label["raise_to"]
            rows.append({**common, "state": state, "expected": expected,
                         "source_decision_id": snapshot["decision_id"],
                         "field_quality": snapshot["field_quality"], "derivation_notes": notes})
        if len(hand["snapshots"]) == 1:
            state = _all_in_call(hand, rows[-1]["state"])
            if state is not None:
                rows.append({**common, "state": state, "expected": {"action": "call"},
                    "source_decision_id": hand["hand_id"] + "-facing-all-in",
                    "derivation_notes": ["Additional call recovered from the reported public line and exact street-total targets.",
                        "Call cost is the all-in target minus hero's current street target; earlier limps/calls are already paid.",
                        "The omitted big-blind fold in the Quoss hand is implied by action order and the reported heads-up all-in."]})
    return rows
