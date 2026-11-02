"""Immutable hand/session splits for attributed decision imitation research."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import random
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .ivey import _legal_prediction, policy_observation


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def grouping_key(row):
    """Use explicit session identity, then video, then the canonical hand ID.

    An absent session ID is a limitation, not proof two hands are independent.
    Source aliases must be reconciled before freezing a corpus.
    """
    if row.get("session_id"):
        return "session:" + str(row["session_id"])
    source = urlparse(row["source"])
    if source.hostname in ("www.youtube.com", "youtube.com", "youtu.be"):
        video_id = source.path.strip("/") if source.hostname == "youtu.be" else parse_qs(source.query).get("v", [""])[0]
        if video_id:
            return "video:" + video_id
    return "hand:" + str(row.get("canonical_hand_id", row["hand_id"]))


def validate_rows(rows):
    """Validate labels, exclude report metadata from features, reject duplicates."""
    result, seen = [], set()
    for original in rows:
        if not original.get("hand_id") or not original.get("source"):
            raise ValueError("attributed decisions need hand_id and source")
        if original.get("evidence_tier") == "video_snapshot_with_rounded_or_missing_context":
            raise ValueError("rounded/incomplete snapshots cannot enter an exact-decision corpus")
        row = copy.deepcopy(original)
        row["state"] = policy_observation(row["state"])
        if not _legal_prediction(row.get("expected"), row["state"]):
            raise ValueError("invalid expected action or raise target")
        row["group_id"] = grouping_key(row)
        # The recorded move never defines the feature identity. Conflicting
        # labels for one source decision must be resolved rather than hidden.
        identity_state = copy.deepcopy(row["state"])
        identity_state.pop("seed", None)
        identity = _digest({"hand_id": row.get("canonical_hand_id", row["hand_id"]),
                            "state": identity_state})
        if identity in seen:
            raise ValueError("duplicate decision identity in corpus")
        seen.add(identity)
        row["decision_id"] = identity
        row["record_hash"] = _digest({k: v for k, v in row.items() if k != "record_hash"})
        result.append(row)
    return result


def split_rows(rows, *, seed=20261031, evaluation_fraction=0.25, development_hand_ids=()):
    """Freeze whole groups; never split streets from one hand across partitions.

    Previously inspected development hands cannot become held-out evaluation
    data. The manifest retains them in a separate partition for transparency.
    """
    if type(seed) is not int or not 0 < evaluation_fraction < 1:
        raise ValueError("require integer seed and fraction strictly between zero and one")
    records = validate_rows(rows)
    development_ids = set(development_hand_ids)
    development_groups = {r["group_id"] for r in records if r["hand_id"] in development_ids}
    eligible = sorted({r["group_id"] for r in records} - development_groups)
    random.Random(seed).shuffle(eligible)
    count = min(len(eligible) - 1, max(1, math.ceil(len(eligible) * evaluation_fraction))) if len(eligible) >= 2 else 0
    evaluation_groups = set(eligible[:count])
    for row in records:
        row["partition"] = ("development" if row["group_id"] in development_groups else
                            "evaluation" if row["group_id"] in evaluation_groups else "train")
    dataset_hash = _digest(sorted(r["record_hash"] for r in records))
    split_hash = _digest(sorted((r["decision_id"], r["group_id"], r["partition"]) for r in records))
    return {"schema_version": 1, "seed": seed, "evaluation_fraction": evaluation_fraction,
            "split_hash": split_hash,
            "dataset_hash": dataset_hash, "records": records,
            "counts": {name: {"decisions": sum(r["partition"] == name for r in records),
                               "groups": len({r["group_id"] for r in records if r["partition"] == name})}
                       for name in ("train", "evaluation", "development")},
            "limitations": ["Source aliases need manual cross-source reconciliation before freezing",
                            "Missing session identity falls back to whole-hand grouping",
                            "Public selections do not establish representative population coverage",
                            "Inspecting an evaluation result for policy tuning consumes that holdout"]}


def save_split(split, path):
    path = Path(path)
    if path.exists():
        raise FileExistsError("frozen split already exists; create a new version")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as fp:
        json.dump(split, fp, indent=2, sort_keys=True, allow_nan=False)
        fp.write("\n")


def load_split(path):
    manifest = json.loads(Path(path).read_text())
    clean = validate_rows([{k: v for k, v in row.items() if k not in
                            ("record_hash", "decision_id", "group_id", "partition")}
                           for row in manifest["records"]])
    actual_hash = _digest(sorted(r["record_hash"] for r in clean))
    if actual_hash != manifest["dataset_hash"]:
        raise ValueError("corpus contents changed after freezing")
    split_hash = _digest(sorted((r["decision_id"], r["group_id"], r["partition"]) for r in manifest["records"]))
    if split_hash != manifest["split_hash"]:
        raise ValueError("corpus partition assignments changed after freezing")
    groups = {}
    for row, reconstructed in zip(manifest["records"], clean):
        if any(row[key] != reconstructed[key] for key in ("decision_id", "group_id", "record_hash")):
            raise ValueError("corpus record identity changed after freezing")
        if row["partition"] not in ("train", "evaluation", "development"):
            raise ValueError("unknown corpus partition")
        prior = groups.setdefault(row["group_id"], row["partition"])
        if prior != row["partition"]:
            raise ValueError("one source group crosses train/evaluation partitions")
    return manifest
