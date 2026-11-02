"""Normalize source-ledger WPT decisions without scoring or fitting a bot."""

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pokerbot.cards import normalize_card
from pokerbot.ivey import LAST_LOAD_REPORT, load_decisions, policy_observation


def _cards(cards):
    suits = str.maketrans({"♣": "c", "♦": "d", "♥": "h", "♠": "s"})
    return [normalize_card(card.translate(suits).replace("\ufe0f", "").replace("10", "T")) for card in cards]


def _ledger(hand):
    """Check public chip transfers; showdown winners are source facts only."""
    stacks = dict(hand["starting_stacks_chips"])
    if len(stacks) != 2 or sum(stacks.values()) != 200000:
        raise ValueError("expected two players with 200,000 chips in total")
    if hand["ante"]["value"] != 0 or hand["straddle"]["value"] != 0:
        raise ValueError("this importer requires explicit zero-ante/no-straddle source evidence")
    bets = {name: 0 for name in stacks}
    for role, amount in (("small_blind_player", hand["blinds"]["small"]),
                         ("big_blind_player", hand["blinds"]["big"])):
        player = hand[role]
        stacks[player] -= amount
        bets[player] = amount
    pot = sum(bets.values())
    street = "preflop"
    for item in hand["actions"]:
        if item["street"] != street:
            bets = {name: 0 for name in stacks}
            street = item["street"]
        actor, action = item["actor"], item["action"]
        if action in {"check", "fold"}:
            continue
        amount = item["amount_chips"]
        if type(amount) is not int or amount < 0:
            raise ValueError("unknown or noninteger wager")
        if action == "raise_to":
            added = amount - bets[actor]
        elif action in {"call", "bet"}:
            added = amount
        else:
            raise ValueError("unknown action vocabulary")
        if not 0 <= added <= stacks[actor]:
            raise ValueError("invalid chip payment")
        stacks[actor] -= added
        bets[actor] += added
        pot += added
    winner = hand["result"]["winner"]
    if winner is None:
        boundary = hand["boundary_state_after_last_action"]
        if boundary["stacks_chips"] != stacks or boundary["pot_chips"] != pot:
            raise ValueError("truncated-hand boundary does not reconcile")
        return None
    if hand["actions"][-1]["action"] == "fold" and winner == hand["actions"][-1]["actor"]:
        raise ValueError("folding player cannot win the hand")
    if winner not in stacks:
        raise ValueError("unknown showdown winner; do not infer a payout")
    stacks[winner] += pot
    if stacks != hand["ending_stacks_chips"]:
        raise ValueError("source payout and wager ledger do not reconcile")
    return stacks


def _compare_case(hand, decision, replayed):
    state, raw = replayed["state"], decision["observation"]
    expected_fields = {"hole_cards": _cards(raw["hero_hole_cards"]),
                       "board": _cards(raw["board_cards"]), "pot": raw["pot_chips"],
                       "stack": raw["hero_stack_chips"], "to_call": raw["to_call_chips"],
                       "big_blind": raw["blinds"]["big"], "street": decision["street"],
                       "position": {"small_blind": "BTN", "button/small_blind": "BTN",
                                    "big_blind": "BB"}[raw["hero_position"]]}
    for key, expected in expected_fields.items():
        if state[key] != expected:
            raise ValueError(f"{decision['decision_id']}: source/engine mismatch in {key}")
    if raw["opponent_stack_chips"] != 200000 - state["pot"] - state["stack"]:
        raise ValueError("opponent's public remaining stack does not reconcile")
    label = decision["expected_action"]
    action = {"bet": "raise", "raise_to": "raise"}.get(label["action"], label["action"])
    expected = {"action": action}
    if action == "raise":
        expected["amount"] = label["amount_chips"] + (state["current_bet"] if label["action"] == "bet" else 0)
    elif action == "call" and label["amount_chips"] != state["to_call"]:
        raise ValueError("source call payment and engine price disagree")
    if expected != replayed["expected"]:
        raise ValueError("source and engine expected actions disagree")
    return expected


def build_pending(document, phh_dir):
    rows, excluded, contexts, fingerprints = [], [], [], {}
    previous_end = document["match"]["starting_stacks_chips"]
    for hand in document["hands"]:
        if hand["starting_stacks_chips"] != previous_end:
            raise ValueError("hand-to-hand stack continuity failed")
        previous_end = _ledger(hand)
        path = Path(phh_dir) / f"hand-{hand['hand_number_in_match']:02}.phh"
        fingerprints[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        replayed = load_decisions(path)
        report = copy.deepcopy(LAST_LOAD_REPORT)
        cases = hand["decisions"]
        context = {"hand_id": hand["hand_id"], "recorded_decisions": len(cases),
                   "engine_decisions": len(replayed), "engine_report": report,
                   "showdown_payout_basis": "source winner/status overlay; unknown opponent cards cannot independently prove a showdown winner"}
        contexts.append(context)
        if not cases:
            if replayed:
                raise ValueError("unrecorded hero decision in a purported walk")
            context["classification"] = "zero_decision_walk"
            continue
        if report["files_excluded"] or len(replayed) != len(cases):
            excluded.append({"hand_id": hand["hand_id"], "decision_count": len(cases),
                             "reason": "whole PHH prefix excluded or decision count differs", "engine_report": report})
            continue
        hand_rows = []
        for decision, replay in zip(cases, replayed):
            expected = _compare_case(hand, decision, replay)
            hand_rows.append({"state": policy_observation(replay["state"]), "expected": expected,
                              "hand_id": hand["hand_id"], "canonical_hand_id": hand["hand_id"],
                              "session_id": hand["match_group"], "event_group": hand["event_group"],
                              "source": document["source"]["url"],
                              "source_decision_id": decision["decision_id"],
                              "source_timestamp": decision["source_timestamp"],
                              "source_frame_seconds": decision["source_frame_seconds"],
                              "source_time_interval_seconds": decision.get("source_time_interval_seconds"),
                              "evidence_time_status": decision.get("evidence_time_status", "collector sampled source timestamp; independent precision review may still be pending"),
                              "continuity_precision": decision.get("continuity_precision", "Chronology and exact carried-forward stacks require independent source review."),
                              "evidence_image": decision["evidence_image"],
                              "raw_public_observation": copy.deepcopy(decision["observation"]),
                              "context": {key: copy.deepcopy(hand[key]) for key in
                                          ("variant", "game_type", "tournament_format", "opponent",
                                           "event_group", "match_group")},
                              "evidence_tier": "official_video_chronological_reconstruction",
                              "admission_status": "pending_source_review",
                              "field_quality": {"cards_and_actions": "broadcast transcription pending independent source review",
                                                "chips": "derived from official initial stack and chronological public transfers",
                                                "bounds_and_position": "engine-derived from the recorded prefix",
                                                "sampling": "two-second source samples, not exact action-button timing"}})
        rows.extend(hand_rows)
    return {"status": "pending_source_review_no_policy_scoring", "records_pending_review": rows,
            "source_recorded_decision_count": sum(len(h["decisions"]) for h in document["hands"]),
            "engine_replayable_decision_count": len(rows), "excluded_hands": excluded,
            "hand_contexts": contexts, "phh_fingerprints": fingerprints,
            "limitations": ["Internal chip/rules consistency does not establish source transcription precision.",
                            "The blind-counter discrepancy and possible cuts require source adjudication.",
                            "No policy has been called and no agreement percentage is computed."]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="data/public_ivey_session_wpt/records.json")
    parser.add_argument("--phh-dir", default="data/public_ivey_session_wpt/phh")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        parser.error("output exists; use a new version")
    source = Path(args.source)
    result = build_pending(json.loads(source.read_text()), args.phh_dir)
    result["source_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    result["normalizer_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as fp:
        json.dump(result, fp, indent=2, sort_keys=True, allow_nan=False)
        fp.write("\n")
    print(json.dumps({k: result[k] for k in ("source_recorded_decision_count", "engine_replayable_decision_count", "excluded_hands")}))
