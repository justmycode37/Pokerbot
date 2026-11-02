"""Reproduce parent checks and append reviewed development admissions once.

Run from the repository root with .venv/bin/python. This does not train or
score a policy, change a frozen split, or overwrite an admission batch.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from pokerbot.corpus import _digest, validate_rows
from scripts import acquisition_triton_convert as converter

BASE = Path("data/acquisition_resume")
OUT = BASE / "2026-11-02"
ADMISSIONS = BASE / "2026-11-01/admissions"
FESTIVAL = "ccbde116-b26b-492e-8b81-30aef2575d8f"


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def resolve(value, historical=False):
    path = Path(value)
    if path.is_absolute():
        return path.relative_to(ROOT)
    if str(path).startswith("raw/") and historical:
        return BASE / "2026-11-01/triton_2023_2024" / path
    return path


def fingerprint(row):
    """Alias screen, not proof of identity: chip ratios plus exact prefix."""
    state = copy.deepcopy(row["state"])
    bb = state["big_blind"]
    chips = {"pot", "contestable_pot", "to_call", "stack", "current_bet",
             "min_raise_to", "max_raise_to", "big_blind"}
    for key in chips:
        if key in state:
            state[key] = str(Fraction(state[key], bb))
    state.pop("seed", None)
    state.pop("player_id", None)
    state["hole_cards"] = sorted(state["hole_cards"])
    if len(state["board"]) >= 3:
        state["board"] = sorted(state["board"][:3]) + state["board"][3:]
    for action in state.get("history", []):
        action.pop("player", None)
        for key in ("amount", "added"):
            if key in action:
                action[key] = str(Fraction(action[key], bb))
    expected = copy.deepcopy(row["expected"])
    for key in ("amount", "raise_to"):
        if key in expected:
            expected[key] = str(Fraction(expected[key], bb))
    return _digest({"state": state, "expected": expected})


def main():
    assert Path.cwd() == ROOT
    frozen = read(BASE / "2026-11-01/takeover-checkpoint.json")["freeze_sha256"]
    assert all(sha(path) == digest for path, digest in frozen.items())
    baseline_path = Path("data/corpus_splits/development-after-prospective-v1.json")
    prior_paths = sorted(ADMISSIONS.glob("batch-*.json"))
    assert [p.name for p in prior_paths] == ["batch-001.json", "batch-002.json"]
    previous = read(baseline_path)["records"]
    for path in prior_paths:
        previous += read(path)["records"]
    assert len(previous) == 80

    historical_review = OUT / "historical_review/per-row-review.json"
    allowed = {row["stable_source_decision_key"]
               for row in read(historical_review)["rows"]
               if row.get("status") == "verified_pending_parent_admission"}
    sources = [
        ("cash_review_0", "cash_review_0/per-row-review.json", 241, False),
        ("cash_review_1", "cash_review_1/per-row-review.json", 221, False),
        ("ante_correction", "ante_correction_review/per-row-review.json", 21, False),
        ("historical_review", "historical_review/per-row-review.json", 43, True),
    ]
    incoming = []
    replay_cache = {}
    dependencies = set()
    for name, review_name, count, historical in sources:
        candidate_path = OUT / name / "candidates.json"
        review_path = OUT / review_name
        dependencies.update([candidate_path, review_path])
        review_rows = {r["stable_source_decision_key"]: r
                       for r in read(review_path)["rows"]}
        candidates = read(candidate_path)["records"]
        if historical:
            candidates = [r for r in candidates
                          if r["stable_source_decision_key"] in allowed]
        assert len(candidates) == count
        assert all(a["record_hash"] == b["record_hash"]
                   for a, b in zip(candidates, validate_rows(candidates)))
        for original in candidates:
            key = original["stable_source_decision_key"]
            review = review_rows[key]
            status = review.get("review_status", review.get("status"))
            assert status in {
                "passed", "passed_independent_source_and_conversion_review_pending_admission",
                "eligible_for_parent_development_only_admission_review",
                "verified_pending_parent_admission"}, (key, status)
            row = copy.deepcopy(original)
            for field, value in list(row.items()):
                if field.endswith("_path") and isinstance(value, str):
                    row[field] = str(resolve(value, historical))
            capture = resolve(row["source_capture_path"])
            request = resolve(row["source_request_path"])
            assert sha(capture) == row["source_capture_sha256"]
            assert sha(request) == row["source_request_sha256"]
            request_doc = read(request)
            assert hashlib.sha256(request_doc["query"].encode()).hexdigest() == row["source_query_sha256"]
            hand, _ = converter._read_input(capture)[0][0]
            assert converter._sha256(converter._canonical_json(hand)) == row["source_payload_sha256"]
            assert hand["dealerSeatNo"] in {p["seatNo"] for p in hand["players"]}
            session = row["session_id"]
            if name.startswith("cash_review"):
                episode_id = row["source_request_episode_id"]
                episode_path = BASE / "2026-11-01/triton_cash/episodes" / (episode_id + ".json")
                episode_request = episode_path.with_suffix(".request.json")
                episode = read(episode_path)["data"]["episode"]
                tournament = episode["tournament"]
                # Correlated cash episodes are conservatively pooled across
                # nominal native event UUIDs within the same source festival.
                festival = tournament.get("festival", episode.get("festival"))
                assert festival["uuid"] == FESTIVAL
                assert tournament["name"] == "Cash Game Invitational I"
                row.update({"source_native_event_uuid": tournament["uuid"],
                            "source_cash_festival_uuid": FESTIVAL,
                            "source_episode_response_path": str(episode_path),
                            "source_episode_response_sha256": sha(episode_path),
                            "source_episode_request_path": str(episode_request),
                            "source_episode_request_sha256": sha(episode_request),
                            "source_grouping_reason": "Whole cash festival pooled conservatively; native event and episode IDs retained as provenance."})
                session = "triton:cash-festival:" + FESTIVAL
                row["session_id"] = session
            cache_key = (str(capture), session)
            if cache_key not in replay_cache:
                decisions, report = converter._convert_one(hand, session)
                replay_cache[cache_key] = {
                    r["stable_source_decision_key"]: r for r in validate_rows(decisions)}
            regenerated = replay_cache[cache_key][key]
            assert regenerated["state"] == row["state"], key
            assert regenerated["expected"] == row["expected"], key
            assert regenerated["decision_id"] == row["decision_id"], key
            row["source_prefix_pot_check"] = regenerated["source_prefix_pot_check"]
            row.update({
                "admission_status": "admitted_source_reviewed_development_only",
                "inspection_status": "inspected", "fresh_holdout": False,
                "policy_use": "development_only",
                "independent_review_path": str(review_path),
                "independent_review_sha256": sha(review_path),
                "parent_integration_path": str(OUT / "cohort-integration.json"),
            })
            for field, value in row.items():
                if field.endswith("_path") and isinstance(value, str) and Path(value).is_file():
                    dependencies.add(Path(value))
            row["parent_review_lane"] = name
            incoming.append(row)

    incoming = validate_rows(incoming)
    assert len(incoming) == 526
    previous_keys = {r.get("stable_source_decision_key") for r in previous}
    assert not previous_keys & {r["stable_source_decision_key"] for r in incoming}
    all_rows = validate_rows(previous + incoming)
    assert len({r["source_decision_id"] for r in incoming}) == 526
    signatures = {}
    for row in previous:
        signatures.setdefault(fingerprint(row), []).append(row)
    overlaps = []
    for row in incoming:
        for prior in signatures.get(fingerprint(row), []):
            if row["hand_id"] != prior["hand_id"]:
                overlaps.append({"incoming": row["stable_source_decision_key"],
                                 "prior": prior.get("source_decision_id", prior["decision_id"])})
    preflight = {"incoming_candidates": 526, "unique_source_keys": 526,
                 "normalized_prefix_signature_matches_to_prior_admissions": overlaps,
                 "limitation": "Signature screen supplements source identity review; absence of a match does not prove exhaustive chronology."}
    (OUT / "incoming-cohort-alias-preflight.json").write_text(json.dumps(preflight, indent=2) + "\n")
    assert not overlaps, overlaps
    counts = {"admitted_decisions": len(all_rows),
              "unique_hands": len({r["hand_id"] for r in all_rows}),
              "source_groups": len({r["group_id"] for r in all_rows}),
              "new_decisions": len(incoming), "remaining_to_1000": 1000-len(all_rows)}
    report = {"schema_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
              "status": "parent_replay_and_source_identity_checks_passed", "counts": counts,
              "lanes": dict(Counter(r["parent_review_lane"] for r in incoming)),
              "unique_hand_replays": len(replay_cache), "protected_files_verified": len(frozen),
              "converter_sha256": sha("scripts/acquisition_triton_convert.py"),
              "pot_helper_sha256": sha("scripts/acquisition_pot_eligibility.py"),
              "prior_batches": [str(p) for p in prior_paths],
              "new_batch": str(ADMISSIONS / "batch-003.json"),
              "fresh_holdouts_created": 0, "policy_calls": 0, "training_runs": 0,
              "score_runs": 0, "frozen_split_changes": 0,
              "limitations": ["Source archives are sparse; no complete chronology claim.",
                              "All admitted examples are inspected development data.",
                              "Five unoccupied-dealer historical candidates remain held.",
                              "Four Montenegro report aliases remain uncounted.",
                              "The 221 previously pending cash aliases are admitted once."]}
    assert all(sha(path) == digest for path, digest in frozen.items())
    batch = {"schema_version": 1, "created_at_utc": report["created_at_utc"],
             "status": "admitted_source_reviewed_development_only", "counts": counts,
             "baseline_manifest": str(baseline_path), "baseline_manifest_sha256": sha(baseline_path),
             "prior_admission_batches": [str(p) for p in prior_paths],
             "parent_integration_path": str(OUT / "cohort-integration.json"),
             "dataset_hash": _digest(sorted(r["record_hash"] for r in incoming)),
             "limitations": report["limitations"], "records": incoming}
    with (ADMISSIONS / "batch-003.json").open("x") as file:
        json.dump(batch, file, indent=2, sort_keys=True, allow_nan=False)
        file.write("\n")
    (OUT / "cohort-integration.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    dependencies.update([OUT / "incoming-cohort-alias-preflight.json", OUT / "cohort-integration.json",
                         OUT / "integrate_reviewed_cohort.py", ADMISSIONS / "batch-003.json"])
    (OUT / "publication/cohort-provenance-files.txt").write_text("\n".join(sorted(map(str, dependencies))) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
