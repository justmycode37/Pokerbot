"""Build pending-review observations from reported actions using PokerKit.

Unknown stacks of players who fold are auxiliary engine parameters, never
claimed as source facts or included in hero observations. Replays check their
irrelevance at lower/intermediate/upper reference values. Public source review
is still required before admitting the resulting records for comparison.
"""

import argparse
import copy
import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pokerbot import ivey

DEFAULT_SOURCE = ROOT / "data/public_ivey_reports_batch2/decision-evidence.json"


def _configuration(hand, auxiliary_stack):
    hero = hand["players"]["hero"]
    opponents = hand["players"]["opponents"]
    forced = hand["blinds_and_antes"]
    sb, bb, ante = (forced[k] for k in ("small_blind", "big_blind", "big_blind_ante"))
    if hand["hand_id"] == "ivey_heath_2022_wsop_event42":
        # The original PDF explicitly says three players remain. The unknown
        # small blind's reported fold contributes exactly the posted SB.
        names = ["Unidentified small blind", opponents[0]["source_name"], "Phil Ivey"]
        stacks = [sb + auxiliary_stack, opponents[0]["hand_start_stack"], hero["hand_start_stack"]]
        antes, blinds = [0, ante, 0], [sb, bb, 0]
        prefix = []
        unknown = [0]
    elif hand["hand_id"] == "ivey_punsri_2024_triton_jeju_event8":
        # Seven players remain at this single seven-handed final table. Five
        # folds are logically required before action reaches the small blind.
        names = [opponents[0]["source_name"], "Phil Ivey"] + [f"Unreported seat {i}" for i in range(3, 8)]
        stacks = [opponents[0]["hand_start_stack"], hero["hand_start_stack"]] + [auxiliary_stack] * 5
        antes, blinds = [0, ante] + [0] * 5, [sb, bb] + [0] * 5
        prefix = [f"p{i} f" for i in range(3, 8)]
        unknown = list(range(2, 7))
    else:
        # PHH/PokerKit HU seat order is BB, BTN. Forced-bet arrays are
        # interpreted in reverse for two players, including the antes.
        bb_player = hero if hero["position_at_decision"] == "BB" else opponents[0]
        button = opponents[0] if bb_player is hero else hero
        names = [bb_player["source_name"], button["source_name"]]
        stacks = [bb_player["hand_start_stack"], button["hand_start_stack"]]
        antes, blinds, prefix, unknown = [0, ante], [sb, bb], [], []
    return names, stacks, antes, blinds, prefix, unknown


def _phh(hand, auxiliary_stack):
    names, stacks, antes, blinds, prefix, unknown = _configuration(hand, auxiliary_stack)
    hero_cards = "".join(hand["players"]["hero"]["hole_cards"])
    actions = [f"d dh p{i + 1} {hero_cards if name == 'Phil Ivey' else '????'}"
               for i, name in enumerate(names)] + prefix
    street = "preflop"
    for action in hand["actions"]:
        if action["street"] != street:
            street = action["street"]
            cards = hand["board_by_street"][street]
            actions.append("d db " + ("".join(cards) if isinstance(cards, list) else cards))
        actor = names.index(action["player"]) + 1
        kind = action["action"]
        if kind not in {"fold", "call", "check", "bet", "raise"}:
            raise ValueError("unsupported source action")
        suffix = "f" if kind == "fold" else "cc" if kind in {"call", "check"} else f"cbr {action['amount']}"
        actions.append(f"p{actor} {suffix}")
    fields = {"variant": "NT", "ante_trimming_status": False, "antes": antes,
              "blinds_or_straddles": blinds, "min_bet": hand["blinds_and_antes"]["big_blind"],
              "starting_stacks": stacks, "players": names, "hand": hand["hand_id"], "actions": actions}
    text = "\n".join(key + " = " + ("false" if value is False else json.dumps(value))
                     for key, value in fields.items()) + "\n"
    return text, unknown


def build_pending(document):
    sources = {r["source_id"]: r["direct_url"] for r in document["source_registry"]}
    by_hand = {h["hand_id"]: h for h in document["hands"]}
    records, differences, history_differences, validation = [], [], [], []
    for hand_id, hand in by_hand.items():
        snapshots = [r for r in document["snapshots"] if r["hand_id"] == hand_id]
        variants = []
        for auxiliary_stack in (1, 1_000_000, 1_000_000_000):
            source, unknown = _phh(hand, auxiliary_stack)
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "reference.phh"
                path.write_text(source)
                rows = ivey.load_decisions(path)
            if ivey.LAST_LOAD_REPORT["files_excluded"] or len(rows) != len(snapshots):
                raise ValueError(f"{hand_id}: replay failed: {ivey.LAST_LOAD_REPORT}")
            # Strip the source's temporary filesystem path before comparing.
            variants.append([{key: row[key] for key in ("state", "expected")} for row in rows])
        if any(variant != variants[0] for variant in variants[1:]):
            raise ValueError(f"{hand_id}: an unknown auxiliary stack affects a hero observation")
        for snapshot, row in zip(snapshots, variants[0]):
            expected = {k: snapshot["expected"][k] for k in ("action", "amount") if k in snapshot["expected"]}
            if row["expected"] != expected:
                raise ValueError(f"{snapshot['snapshot_id']}: source label and replay disagree")
            raw = snapshot["state"]
            names = _configuration(hand, 1)[0]
            engine_history = [dict(item, player=names[int(item["player"][1:])])
                              for item in row["state"]["history"]]
            raw_history = raw.get("history", [])
            # The Jeju source omits the five implied folds preceding the SB
            # raise. Compare the reported suffix separately from those folds.
            reported_suffix = engine_history[-len(raw_history):] if raw_history else []
            for index, (original, replayed) in enumerate(zip(raw_history, reported_suffix)):
                for key in ("street", "player", "action", "added"):
                    if original.get(key) != replayed.get(key):
                        history_differences.append({"snapshot_id": snapshot["snapshot_id"],
                                                    "reported_history_index": index, "field": key,
                                                    "collector_value": original.get(key),
                                                    "engine_value": replayed.get(key)})
            for key, value in raw.items():
                if key in {"history", "player_id", "seed"}:
                    continue
                if row["state"].get(key) != value:
                    differences.append({"snapshot_id": snapshot["snapshot_id"], "field": key,
                                        "collector_value": value, "engine_value": row["state"].get(key)})
            quality = copy.deepcopy(snapshot["field_quality"])
            quality["history"] = {"quality": "derived",
                                  "basis": "Engine reconstructs the public prefix from reported street targets; implied folds and exact targets derived from rounded all-ins remain derived facts."}
            quality["table_size"] = {"quality": "observed_or_logically_derived",
                                     "basis": "Original PDF explicitly says three remain for Heath and heads-up for Ponakovs; Jeju report says seven remain at the seven-handed final table."}
            records.append({**copy.deepcopy(row), "source": sources[hand["source_ids"][0]],
                            "corroborating_sources": [sources[s] for s in hand["source_ids"]],
                            "hand_id": hand_id, "canonical_hand_id": hand_id,
                            "session_id": hand["session_id"], "source_decision_id": snapshot["snapshot_id"],
                            "format": "tournament_nlhe",
                            "evidence_tier": "attributed_report_engine_reconstruction",
                            "field_quality": quality,
                            "label_quality": {k: snapshot["expected"][k] for k in
                                              ("quality", "source_action", "amount_quality") if k in snapshot["expected"]},
                            "derivation_notes": [
                                "Engine derives chips, legal actions and public history from street targets; dead antes never count as live bets.",
                                "Opponent cards and future cards/actions are excluded from policy observations.",
                                "Table size is three for Heath, two for the heads-up final, and seven for the Jeju final table.",
                                "Unreported folded-player stacks are auxiliary reference parameters; observed hero states are invariant to tested bounds."]})
        validation.append({"hand_id": hand_id, "decisions": len(snapshots), "auxiliary_unknown_seats": unknown,
                           "reference_stack_probes_above_forced_bet": [1, 1_000_000, 1_000_000_000],
                           "hero_observations_identical_across_probes": True,
                           "auxiliary_stacks_claimed_as_source_facts": False})
    return {"status": "pending_independent_source_review", "records_pending_review": records,
            "collector_state_differences": differences, "history_differences": history_differences,
            "engine_validation": validation,
            "selection_unit": "One complete source-issue cluster containing all four Ivey matchups, plus the independently selected Jeju matchup; two event/session groups.",
            "notes": ["This file is not directly accepted by the prospective scoring CLI.",
                      "Replay legality and invariance do not independently verify the published facts or source precision.",
                      "Raw collector history added values are replaced by engine-computed payments."]}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", default=str(DEFAULT_SOURCE))
    p.add_argument("--output", required=True)
    a = p.parse_args()
    destination = Path(a.output)
    if destination.exists():
        p.error("output exists; use a new version")
    source = Path(a.source)
    result = build_pending(json.loads(source.read_text()))
    result["raw_source_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    result["normalizer_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x") as fp:
        json.dump(result, fp, indent=2, sort_keys=True, allow_nan=False)
        fp.write("\n")
    print(json.dumps({"pending_decisions": len(result["records_pending_review"]),
                      "state_differences": result["collector_state_differences"],
                      "history_differences": result["history_differences"]}, indent=2))
