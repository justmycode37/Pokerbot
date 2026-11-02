#!/usr/bin/env python3
"""Reconvert only the Nov. 1 Triton known-card hand set by saved tournament UUID."""
from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BATCH = ROOT / "data/acquisition_resume/2026-11-01/triton_2023_2024"
PRIOR_REVIEW = ROOT / "data/acquisition_resume/2026-11-01/triton_2023_2024_review"
OUT = ROOT / "data/acquisition_resume/2026-11-02/historical_review"
CONVERTER = ROOT / "scripts/acquisition_triton_convert.py"
sys.path.insert(0, str(ROOT))
from scripts.acquisition_triton_convert import convert


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


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


def main() -> int:
    facts_path = PRIOR_REVIEW / "notes/source-hand-facts.jsonl"
    facts = {row["raw_hand_uuid"]: row for row in
             (json.loads(line) for line in facts_path.read_text(encoding="utf-8").splitlines() if line)}
    hand_manifest = read_json(BATCH / "hand-manifest.json")["hands"]
    decision_manifest = read_json(BATCH / "decision-candidate-manifest.json")
    known_ids = {row["raw_hand_id"] for row in decision_manifest["actions"]
                 if row["hero_cards_status"] == "known_two_cards"}
    if len(known_ids) != 33 or len(facts) != 273:
        raise SystemExit(f"unexpected source inventory: {len(known_ids)} known-card hands / {len(facts)} source facts")

    by_tournament: dict[str, list[Path]] = defaultdict(list)
    paths_by_hand = {}
    tournament_by_hand = {}
    for hand_id in sorted(known_ids):
        entry = hand_manifest[hand_id]
        aliases = entry.get("source_episode_aliases", [])
        if len(entry.get("source_response_paths", [])) != 1 or not aliases:
            raise SystemExit(f"canonical source or episode aliases missing for {hand_id}")
        event_ids = set()
        for alias in aliases:
            episode_id = alias.get("episodeId")
            episode_path = BATCH / "raw/episodes" / episode_id / "GetEpisode.json"
            episode = find_episode(read_json(episode_path), episode_id)
            if episode is None:
                raise SystemExit(f"saved GetEpisode mapping missing for {hand_id}: {episode_id}")
            event_ids.add(episode["tournament"]["uuid"])
        if len(event_ids) != 1:
            raise SystemExit(f"cross-tournament episode alias for {hand_id}: {sorted(event_ids)}")
        tournament_id = next(iter(event_ids))
        fact = facts.get(hand_id)
        if fact is None or fact.get("tournament_uuid") != tournament_id:
            raise SystemExit(f"source-hand-facts tournament mapping differs for {hand_id}")
        raw_path = BATCH / entry["source_response_paths"][0]
        response = read_json(raw_path)
        hand = response.get("data", {}).get("handV2")
        hero = next((player for player in hand.get("players", [])
                     if player.get("userId") == "3970ce21-3d14-4bdc-97ca-98df8220d040"), None)
        if not hero or len(hero.get("pocketCards", [])) != 2 or not all(hero["pocketCards"]):
            raise SystemExit(f"known-card manifest/raw mismatch for {hand_id}")
        if sha256(raw_path.read_bytes()) != fact["raw_response_sha256"]:
            raise SystemExit(f"raw response differs from retained source-hand-facts for {hand_id}")
        by_tournament[tournament_id].append(raw_path)
        paths_by_hand[hand_id] = str(raw_path.relative_to(ROOT))
        tournament_by_hand[hand_id] = tournament_id

    if len(by_tournament) != 7:
        raise SystemExit(f"expected 7 actual saved tournament UUID groups, got {len(by_tournament)}")
    if any(not isinstance(tournament_id, str) or len(tournament_id) != 36 for tournament_id in by_tournament):
        raise SystemExit("invalid saved tournament UUID key")

    results = {}
    for tournament_id, input_paths in sorted(by_tournament.items()):
        output = OUT / "conversionoutputs/by-tournament" / tournament_id / "converter-output.json"
        if output.exists():
            raise SystemExit(f"refusing to overwrite conversion output: {output}")
        result = convert(input_paths, output, session_id=f"triton:tournament:{tournament_id}")
        results[tournament_id] = {
            "known_card_hand_inputs": len(input_paths),
            "input_hand_uuids": sorted(path.name.split(".", 1)[0] for path in input_paths),
            "counts": result["counts"],
            "output_path": str(output.relative_to(ROOT)),
            "output_sha256": sha256(output.read_bytes()),
        }

    run = {
        "status": "reconverted_known_card_hands_pending_independent_source_review",
        "runtime": sys.executable,
        "converter_path": str(CONVERTER.relative_to(ROOT)),
        "converter_sha256": sha256(CONVERTER.read_bytes()),
        "batch": str(BATCH.relative_to(ROOT)),
        "source_hand_facts_path": str(facts_path.relative_to(ROOT)),
        "source_hand_facts_sha256": sha256(facts_path.read_bytes()),
        "known_card_hands": len(known_ids),
        "known_card_action_labels": sum(row["hero_cards_status"] == "known_two_cards"
                                         for row in decision_manifest["actions"]),
        "actual_saved_tournament_uuid_groups": results,
        "source_hand_tournament_uuid_by_hand": dict(sorted(tournament_by_hand.items())),
        "source_input_path_by_hand": dict(sorted(paths_by_hand.items())),
        "network_fetches": 0,
        "policy_calls": 0,
        "admission_writes": 0,
        "split_edits": 0,
    }
    run_path = OUT / "conversion-run.json"
    run_path.write_text(json.dumps(run, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    print(json.dumps({key: value for key, value in run.items()
                      if key not in {"source_hand_tournament_uuid_by_hand", "source_input_path_by_hand"}},
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
