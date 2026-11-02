"""Evaluate frozen candidates on newly acquired, disjoint source groups."""

import hashlib
import json
from pathlib import Path

from .corpus import load_split, validate_rows
from .evaluation_baselines import majority_action_policy
from .fast import decide as fast_decide
from .imitation import decide_with_model
from .ivey import compare_decisions

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FILES = ("pokerbot/cards.py", "pokerbot/state.py", "pokerbot/preflop.py",
                 "pokerbot/texture.py", "pokerbot/fast.py", "pokerbot/imitation.py",
                 "pokerbot/ivey.py", "pokerbot/corpus.py", "data/preflop_equity.json")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def make_lock(model_path, inspected_manifest_path):
    model = Path(model_path).resolve()
    manifest = Path(inspected_manifest_path).resolve()
    return {"schema_version": 1, "model_path": str(model.relative_to(ROOT)),
            "model_sha256": sha256(model),
            "inspected_manifest_path": str(manifest.relative_to(ROOT)),
            "inspected_manifest_sha256": sha256(manifest),
            "runtime_fingerprints": {name: sha256(ROOT / name) for name in RUNTIME_FILES},
            "rule": "No fitting or candidate changes after inspecting prospective labels; reject reused groups and hands."}


def verify_lock(lock):
    if lock.get("schema_version") != 1:
        raise ValueError("unsupported prospective lock schema")
    for key in ("model", "inspected_manifest"):
        if sha256(ROOT / lock[key + "_path"]) != lock[key + "_sha256"]:
            raise ValueError(f"frozen {key} changed")
    for name, expected in lock["runtime_fingerprints"].items():
        if sha256(ROOT / name) != expected:
            raise ValueError(f"frozen candidate/evaluator code changed: {name}")


def assert_new_groups(rows, inspected_manifest):
    clean = validate_rows(rows)
    known = inspected_manifest["records"]
    known_groups = {r["group_id"] for r in known}
    known_hands = {r.get("canonical_hand_id", r["hand_id"]) for r in known}
    for row in clean:
        if row["group_id"] in known_groups or row.get("canonical_hand_id", row["hand_id"]) in known_hands:
            raise ValueError("prospective data reuses an already inspected hand or source group")
    if not clean:
        raise ValueError("prospective evaluation needs new validated decisions")
    return clean


def score_prospective(rows, lock):
    verify_lock(lock)
    inspected = load_split(ROOT / lock["inspected_manifest_path"])
    clean = assert_new_groups(rows, inspected)
    model = json.loads((ROOT / lock["model_path"]).read_text())
    used = model["metadata"]["partitions_used"]
    fitting = [r for r in inspected["records"] if r["partition"] in used]
    candidates = {"imitation": lambda state: decide_with_model(state, model),
                  "fast": fast_decide,
                  "majority_action": majority_action_policy(fitting)}
    results = {name: compare_decisions(clean, candidate) for name, candidate in candidates.items()}
    verify_lock(lock)
    return {"report_type": "prospective_frozen_candidate_evaluation", "lock": lock,
            "decision_count": len(clean), "hand_count": len({r["hand_id"] for r in clean}),
            "source_group_count": len({r["group_id"] for r in clean}),
            "record_hashes": sorted(r["record_hash"] for r in clean),
            "evaluation_action_counts": {a: sum(r["expected"]["action"] == a for r in clean)
                                         for a in ("fold", "check", "call", "raise")},
            "comparisons": results, "evaluation_rows_used_for_fitting": 0,
            "population_accuracy_claim": None, "99_percent_population_agreement_demonstrated": False,
            "limitations": ["Manually reconcile aliases for the same hand across sources before admission.",
                            "Public selected clips and reports do not establish representative population coverage.",
                            "Decisions within a hand remain correlated.",
                            "Inspecting these results to choose future changes consumes this holdout."]}
