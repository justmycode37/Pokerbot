"""Frozen comparison of named candidates against new admitted source groups.

This module never fits a policy. The inspected corpus can grow between
experiments, but each comparison lock keeps its original bytes and models.
"""

import json
from pathlib import Path

from .corpus import load_split
from .evaluation_baselines import majority_action_policy
from .fast import decide as fast_decide
from .ivey import compare_decisions
from .prospective import assert_new_groups, sha256

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = {
    "fast": {},
    "imitation-v1": {"model": "data/models/ivey-imitation-v1.json",
                     "fitting_manifest": "data/corpus_splits/public-reports-v1.json"},
    "hybrid-v2": {"model": "data/models/hybrid-v2.json",
                  "fitting_manifest": "data/corpus_splits/development-after-prospective-v1.json"},
    "development-majority": {},
}
RUNTIME_FILES = (
    "pokerbot/cards.py", "pokerbot/state.py", "pokerbot/preflop.py",
    "pokerbot/texture.py", "pokerbot/fast.py", "pokerbot/imitation.py",
    "pokerbot/sizing.py", "pokerbot/hybrid.py", "pokerbot/ivey.py",
    "pokerbot/corpus.py", "pokerbot/prospective.py",
    "pokerbot/evaluation_baselines.py", "pokerbot/candidate_evaluation.py",
    "data/preflop_equity.json",
)


def _relative(path):
    absolute = Path(path).resolve() if Path(path).is_absolute() else (ROOT / path).resolve()
    try:
        return str(absolute.relative_to(ROOT))
    except ValueError as exc:
        raise ValueError("candidate artifacts must be inside the project") from exc


def _artifact_names(inspected_name, candidate_ids):
    names = {inspected_name}
    for name in candidate_ids:
        if name not in REGISTRY:
            raise ValueError("unknown candidate")
        names.update(REGISTRY[name].values())
    return names


def freeze_candidates(inspected_manifest, candidate_ids=tuple(REGISTRY)):
    ids = sorted(set(candidate_ids))
    if not ids:
        raise ValueError("at least one candidate is required")
    manifest_name = _relative(inspected_manifest)
    inspected = load_split(ROOT / manifest_name)
    known = {r["group_id"] for r in inspected["records"]}
    for name in ids:
        entry = REGISTRY.get(name)
        if entry is None:
            raise ValueError("unknown candidate")
        if entry.get("fitting_manifest"):
            fitting = load_split(ROOT / entry["fitting_manifest"])
            if not {r["group_id"] for r in fitting["records"]} <= known:
                raise ValueError("inspected corpus omits a candidate's known fitting/inspection groups")
    return {"schema": "named-candidate-lock-v1", "candidate_ids": ids,
            "inspected_manifest": manifest_name,
            "artifact_fingerprints": {name: sha256(ROOT / name) for name in sorted(_artifact_names(manifest_name, ids))},
            "runtime_fingerprints": {name: sha256(ROOT / name) for name in RUNTIME_FILES},
            "rule": "No fitting; reject previously inspected groups and hands, partial rows and changed code/models."}


def verify_candidate_lock(lock):
    if lock.get("schema") != "named-candidate-lock-v1":
        raise ValueError("unsupported candidate lock")
    ids = lock.get("candidate_ids")
    if not isinstance(ids, list) or not ids or any(name not in REGISTRY for name in ids) or ids != sorted(set(ids)):
        raise ValueError("invalid candidate registry selection")
    manifest_name = _relative(lock["inspected_manifest"])
    artifacts = lock.get("artifact_fingerprints", {})
    runtime = lock.get("runtime_fingerprints", {})
    if set(runtime) != set(RUNTIME_FILES) or set(artifacts) != _artifact_names(manifest_name, ids):
        raise ValueError("incomplete candidate lock fingerprints")
    for name, expected in {**artifacts, **runtime}.items():
        if sha256(ROOT / name) != expected:
            raise ValueError(f"frozen candidate artifact or runtime changed: {name}")


def _policy(name, inspected):
    if name == "fast":
        return fast_decide
    if name == "development-majority":
        # Named explicitly: this baseline uses all inspected development rows,
        # which is broader than the original v1 imitation training corpus.
        return majority_action_policy(inspected["records"])
    model_path = ROOT / REGISTRY[name]["model"]
    if name == "imitation-v1":
        from .imitation import decide_with_model
        model = json.loads(model_path.read_text())
        return lambda raw: decide_with_model(raw, model)
    if name == "hybrid-v2":
        from .hybrid import decide, load_model
        model = load_model(model_path)
        return lambda raw: decide(raw, model)
    raise ValueError("unknown candidate")


def compare_new_batch(rows, lock):
    verify_candidate_lock(lock)
    rows = list(rows)
    for row in rows:
        quality = row.get("data_quality") or {}
        if quality.get("status") == "partial" or str(row.get("admission_status", "")).startswith("pending"):
            raise ValueError("partial or pending records cannot enter exact candidate comparison")
        if "table_size" not in row["state"]:
            raise ValueError("new exact records need an explicitly supported table_size")
    inspected = load_split(ROOT / lock["inspected_manifest"])
    clean = assert_new_groups(rows, inspected)
    comparisons = {name: compare_decisions(clean, _policy(name, inspected)) for name in lock["candidate_ids"]}
    verify_candidate_lock(lock)
    return {"report_type": "named_frozen_candidate_comparison", "lock": lock,
            "decision_count": len(clean), "hand_count": len({r["hand_id"] for r in clean}),
            "source_group_count": len({r["group_id"] for r in clean}),
            "record_hashes": sorted(r["record_hash"] for r in clean),
            "action_counts": {a: sum(r["expected"]["action"] == a for r in clean)
                              for a in ("fold", "check", "call", "raise")},
            "comparisons": comparisons, "evaluation_rows_used_for_fitting": 0,
            "population_accuracy_claim": None, "99_percent_population_agreement_demonstrated": False,
            "limitations": ["Source aliases must be manually reconciled before admission.",
                            "Selected public hands do not establish population coverage; decisions within groups are correlated.",
                            "The development-majority baseline uses the entire inspected manifest, not each candidate's original fitting subset.",
                            "Inspecting a result for subsequent development consumes this evaluation set."]}
