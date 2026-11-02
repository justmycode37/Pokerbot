"""Stitch chronological source fragments and replay their public action ledger.

This is an acquisition check, with no policy calls, fitting, or scoring.
All derived observations remain pending source/continuity review.
"""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path

from import_wpt_session import _cards, _ledger, build_pending


def _read(path, output_dir):
    path = Path(path)
    output_dir = Path(output_dir).resolve()
    document = json.loads(path.read_text())
    for hand in document["hands"]:
        hand["source_fragments"] = [{"records_file": str(path), "hand_id": hand["hand_id"],
                                     "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}]
        for decision in hand["decisions"]:
            image = (path.parent / decision["evidence_image"]).resolve()
            if not image.is_file():
                raise ValueError("source decision evidence is missing")
            decision["evidence_image"] = os.path.relpath(image, output_dir)
            decision["continuity_precision"] = (
                "Ledger-derived stacks are conditional on complete source chronology; "
                "rounded HUD badges and unresolved blind cadence do not independently prove exact stacks.")
        # These fingerprints describe the original fragments, not the stitched hand.
        for key in ("hand_context_fingerprint_sha256", "duplicate_guard_key"):
            hand.pop(key, None)
    return document


def stitch(paths, output_dir):
    if not paths:
        raise ValueError("at least one source window is required")
    documents = [_read(path, output_dir) for path in paths]
    sources = [d["source"] for d in documents]
    windows = [s["review_window"] for s in sources]
    if any((s["video_id"], s["url"]) != (sources[0]["video_id"], sources[0]["url"]) for s in sources):
        raise ValueError("windows must belong to the same public video")
    if any(w["start_seconds"] >= w["end_seconds"] for w in windows):
        raise ValueError("source window must have positive duration")
    if any(a["end_seconds"] != b["start_seconds"] for a, b in zip(windows, windows[1:])):
        raise ValueError("source windows must be adjacent and ordered")
    source = {k: copy.deepcopy(v) for k, v in sources[0].items() if k not in {"review_window", "sampling"}}
    source["review_window"] = {
        "start_seconds": windows[0]["start_seconds"], "end_seconds": windows[-1]["end_seconds"],
        "start": windows[0]["start"], "end": windows[-1]["end"], "interval_semantics": "half-open",
    }
    source["sampling"] = {"basis": "Original sampling and precision notes are retained per source document.",
                          "continuity_completeness_verified": False}
    match = copy.deepcopy(documents[0]["match"])
    match["blind_progression_crosscheck"] = {
        "status": "official seven-hand cadence remains unresolved; use observed per-hand blinds",
        "per_source": [copy.deepcopy(d["match"].get("blind_progression_crosscheck")) for d in documents],
    }
    result = {
        "schema_version": "1.0", "record_type": "stitched_chronological_public_broadcast_hand_decisions",
        "completeness": "engine_replayable_prefixes_pending_independent_source_and_continuity_review",
        "source": source, "match": match, "hands": [],
        "source_documents": [{"records_file": str(path),
                              "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                              "capture_metadata": {k: copy.deepcopy(v) for k, v in document.items() if k != "hands"}}
                             for path, document in zip(paths, documents)],
        "chronology_and_stack_uncertainty": {
            "hand_ids": "Provisional observed-context aliases, not certified official hand ordinals.",
            "stacks": "Conditional transfer arithmetic; rounded HUD labels do not independently verify exact balances.",
            "source_admission": "Legal replay does not establish complete broadcast chronology or source transcription accuracy.",
        },
    }
    seen_decisions, seen_hands = set(), set()
    for document in documents:
        for hand in document["hands"]:
            for decision in hand["decisions"]:
                key = decision["decision_id"]
                if key in seen_decisions:
                    raise ValueError("duplicate source decision across windows")
                seen_decisions.add(key)
            if result["hands"] and hand["hand_id"] == result["hands"][-1]["hand_id"]:
                prior = result["hands"][-1]
                if prior["result"]["winner"] is not None:
                    raise ValueError("a settled hand cannot be continued")
                for key in ("starting_stacks_chips", "hero_hole_cards", "small_blind_player",
                            "big_blind_player", "match_group"):
                    if prior[key] != hand[key]:
                        raise ValueError("continuation disagrees with prior hand context: " + key)
                if any(prior["blinds"][role] != hand["blinds"][role] for role in ("small", "big")):
                    raise ValueError("continuation changes a blind amount")
                if hand["public_board_cards"][:len(prior["public_board_cards"])] != prior["public_board_cards"]:
                    raise ValueError("continuation changes an already dealt board")
                _ledger(prior)  # Check the carried boundary before replacing it.
                boundary = prior["boundary_state_after_last_action"]
                carried = hand.get("continuation_of_prior_window", {}).get("window_start_state")
                if carried is None or any(carried.get(k) != boundary[k] for k in ("stacks_chips", "pot_chips")):
                    raise ValueError("continuation does not preserve the carried boundary")
                actions = prior["actions"] + hand["actions"]
                decisions = prior["decisions"] + hand["decisions"]
                fragments = prior["source_fragments"] + hand["source_fragments"]
                combined = copy.deepcopy(hand)
                combined.update(actions=actions, decisions=decisions, source_fragments=fragments)
                result["hands"][-1] = combined
            else:
                if hand["hand_id"] in seen_hands:
                    raise ValueError("a hand reappeared outside the adjacent window seam")
                seen_hands.add(hand["hand_id"])
                result["hands"].append(copy.deepcopy(hand))
    # Convert the second collector's boundary vocabulary for the common ledger check.
    for hand in result["hands"]:
        boundary = hand.get("boundary_state_after_last_action")
        if boundary and "state_before_window_end" in boundary:
            state = boundary["state_before_window_end"]
            boundary["stacks_chips"] = {p: state[p] for p in hand["starting_stacks_chips"]}
            boundary["pot_chips"] = state["pot_chips"]
    result["stitching"] = {
        "source_files": {str(p): hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths},
        "status": "ledger normalization pending source and continuity review",
        "unique_source_decisions": len(seen_decisions),
        "source_fragments_are_not_independent_hands": True,
        "no_policy_called": True,
    }
    result["review_totals"] = {
        "hand_contexts": len(result["hands"]),
        "hands_with_ivey_decisions": sum(bool(h["decisions"]) for h in result["hands"]),
        "ivey_decisions": len(seen_decisions),
        "zero_decision_contexts": sum(not h["decisions"] for h in result["hands"]),
        "completed_contexts": sum(h["result"]["winner"] is not None for h in result["hands"]),
        "boundary_truncated_contexts": sum(h["result"]["winner"] is None for h in result["hands"]),
    }
    return result


def write_phh(hand, path):
    """Project a two-player public prefix; unknown opponent cards stay unknown."""
    players = [hand["big_blind_player"], hand["small_blind_player"]]
    seats = {player: "p" + str(i + 1) for i, player in enumerate(players)}
    hero_cards = "".join(_cards(hand["hero_hole_cards"])) if hand["hero_hole_cards"] else "????"
    actions = [f"d dh {seats[p]} {hero_cards if p == hand['hero'] else '????'}" for p in players]
    board = _cards(hand["public_board_cards"])
    street = "preflop"
    live = {p: hand["blinds"]["big"] if i == 0 else hand["blinds"]["small"] for i, p in enumerate(players)}
    for item in hand["actions"]:
        if item["street"] != street:
            street = item["street"]
            cards = {"flop": board[:3], "turn": board[3:4], "river": board[4:5]}[street]
            if len(cards) != (3 if street == "flop" else 1):
                raise ValueError("source board is incomplete for the recorded street")
            actions.append("d db " + "".join(cards))
            live = dict.fromkeys(players, 0)
        player, move = item["actor"], item["action"]
        if move == "fold":
            actions.append(seats[player] + " f")
        elif move in {"check", "call"}:
            actions.append(seats[player] + " cc")
            if move == "call":
                live[player] += item["amount_chips"]
        elif move in {"bet", "raise_to"}:
            target = item["amount_chips"] + (live[player] if move == "bet" else 0)
            actions.append(f"{seats[player]} cbr {target}")
            live[player] = target
        else:
            raise ValueError("unsupported source action")
    data = {"variant": "NT", "antes": [0, 0],
            "blinds_or_straddles": [hand["blinds"]["small"], hand["blinds"]["big"]],
            "min_bet": hand["blinds"]["big"],
            "starting_stacks": [hand["starting_stacks_chips"][p] for p in players],
            "actions": actions, "players": players, "hand": hand["hand_id"],
            "url": "https://www.youtube.com/watch?v=" + hand["source_video_id"]}
    with Path(path).open("x") as fp:
        fp.write("# Derived public prefix; exact stacks remain conditional on source continuity.\n")
        for key, value in data.items():
            fp.write(key + " = " + json.dumps(value, ensure_ascii=False) + "\n")


def export(paths, output_dir):
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    document = stitch(paths, output_dir)
    source_path = output_dir / "records.json"
    source_path.write_text(json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    phh_dir = output_dir / "phh"
    phh_dir.mkdir()
    for hand in document["hands"]:
        write_phh(hand, phh_dir / f"hand-{hand['hand_number_in_match']:02}.phh")
    pending = build_pending(document, phh_dir)
    pending["source_sha256"] = hashlib.sha256(source_path.read_bytes()).hexdigest()
    pending["stitching"] = document["stitching"]
    pending["stitcher_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    pending["normalizer_sha256"] = hashlib.sha256(Path(__file__).with_name("import_wpt_session.py").read_bytes()).hexdigest()
    (output_dir / "pending.json").write_text(json.dumps(pending, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return pending


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="+")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = export(args.sources, args.output)
    print(json.dumps({k: result[k] for k in ("source_recorded_decision_count", "engine_replayable_decision_count", "excluded_hands")}))
