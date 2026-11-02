"""Hierarchical preflop action counts learned only from an external expert.

The cells are ordinary 169-hand classes, public positions and betting contexts,
not source decisions. Ivey labels are never accepted by the fitter.
"""
from __future__ import annotations

import json
import math
from collections.abc import Mapping
from collections import defaultdict
from pathlib import Path

from .fast import _preflop_entry_counts, _raise_count, decide as fast_decide
from .imitation import TIE_BREAK_ORDER
from .map_policy import decide as map_decide
from .preflop import hand_class
from .state import Observation

ALGORITHM = "external-expert-hierarchical-preflop-v1"
ACTIONS = ("fold", "check", "call", "raise")
SOURCE_COMMIT = "e47fbd5816372360bade4de5d712346fe1bb70f6"
SOURCE_PREFIX = f"https://github.com/uoftcprg/phh-dataset/blob/{SOURCE_COMMIT}/data/pluribus/"
EXTERNAL_GROUP = "external-session:uoftcprg-phh-dataset:pluribus-archive"


def _require_external_row(row):
    if not isinstance(row, Mapping):
        raise ValueError("external training rows must be objects")
    if (row.get("partition") != "train" or row.get("evidence_tier") != "external_expert_phh"
            or row.get("expert_name") != "Pluribus" or row.get("fresh_holdout") is True):
        raise ValueError("only external Pluribus train rows are allowed")
    quality = row.get("data_quality") or {}
    if not isinstance(quality, Mapping):
        raise ValueError("external data_quality must be an object")
    if (row.get("policy_use") not in (None, "external_training_only") or row.get("admission_status")
            or quality.get("status") not in (None, "", "complete", "reviewed")):
        raise ValueError("development, partial or pending rows cannot fit the external prior")
    relative = row.get("source_relative_path")
    digest = row.get("source_sha256")
    if (row.get("source_repo_commit") != SOURCE_COMMIT
            or row.get("data_identity") != "external_pluribus_phh_training_data_not_ivey"
            or row.get("format") != "phh_no_limit_holdem"
            or row.get("group_id") != EXTERNAL_GROUP or row.get("session_id") != EXTERNAL_GROUP
            or not isinstance(relative, str) or not relative or Path(relative).is_absolute()
            or ".." in Path(relative).parts or row.get("source") != SOURCE_PREFIX + relative
            or not isinstance(digest, str) or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest.lower())
            or not isinstance(row.get("hand_id"), str) or not row["hand_id"]
            or not isinstance(row.get("source_hand_id"), str) or not row["source_hand_id"]):
        raise ValueError("external training rows require pinned-source provenance")


def _context(obs):
    raises = _raise_count(obs, "preflop")
    entrants, _ = _preflop_entry_counts(obs)
    if raises >= 2:
        return "reraised"
    if raises == 1:
        return "raised"
    return "limped" if entrants else "unopened"


def _keys(obs):
    parent = _context(obs) + ":" + hand_class(obs.hole_cards)
    return parent, parent + ":" + obs.position


def fit_model(rows, *, alpha=4.0):
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)) or not math.isfinite(alpha) or alpha <= 0:
        raise ValueError("alpha must be finite and positive")
    parents = defaultdict(lambda: [0] * 4)
    cells = defaultdict(lambda: [0] * 4)
    count = preflop_count = 0
    for row in rows:
        _require_external_row(row)
        obs = Observation.from_dict(row["state"])
        label = row.get("expected", {})
        action = label.get("action")
        if not isinstance(action, str) or action not in obs.legal_actions:
            raise ValueError("illegal expert training action")
        if action == "raise" and (type(label.get("amount")) is not int
                                 or not obs.min_raise_to <= label["amount"] <= obs.max_raise_to):
            raise ValueError("illegal expert training raise")
        count += 1
        if obs.street != "preflop":
            continue
        parent, cell = _keys(obs)
        parents[parent][ACTIONS.index(action)] += 1
        cells[cell][ACTIONS.index(action)] += 1
        preflop_count += 1
    if preflop_count == 0:
        raise ValueError("at least one external preflop decision is required")
    return {
        "schema_version": 1, "algorithm": ALGORITHM, "alpha": float(alpha),
        "parents": dict(parents), "cells": dict(cells),
        "metadata": {"expert_name": "Pluribus", "training_decisions": count,
                     "training_preflop_decisions": preflop_count, "ivey_fitting_decisions": 0},
    }


def _prior(raw, obs):
    safe = {**raw, "seed": 0}
    # A complete prefix with no voluntary raises may have an elevated forced
    # opening price. Keep it distinct from a previous opponent raise.
    if _raise_count(obs, "preflop") == 0:
        price = obs.current_bet + obs.to_call
        if price > obs.big_blind:
            safe["big_blind"] = price
    return fast_decide(safe)


def decide(raw, model):
    if model.get("algorithm") != ALGORITHM or model.get("schema_version") != 1:
        raise ValueError("unsupported external preflop model")
    obs = Observation.from_dict(raw)
    if obs.street != "preflop":
        return map_decide(raw)
    prior = _prior(raw, obs)
    parent, cell = _keys(obs)
    prior_weights = {a: max(0.02, prior["probabilities"].get(a, 0.0)) for a in ACTIONS}
    total = sum(prior_weights.values())
    prior_weights = {a: value / total for a, value in prior_weights.items()}
    parent_counts = model["parents"].get(parent, [0] * 4)
    cell_counts = model["cells"].get(cell, [0] * 4)
    alpha = model["alpha"]
    parent_total, cell_total = sum(parent_counts), sum(cell_counts)
    posterior = {
        a: (parent_counts[i] + 2 * alpha * prior_weights[a]) / (parent_total + 2 * alpha)
        for i, a in enumerate(ACTIONS)
    }
    posterior = {
        a: (cell_counts[i] + alpha * posterior[a]) / (cell_total + alpha)
        for i, a in enumerate(ACTIONS)
    }
    probabilities = {a: posterior[a] for a in ACTIONS if a in obs.legal_actions}
    total = sum(probabilities.values())
    probabilities = {a: value / total for a, value in probabilities.items()}
    action = max(TIE_BREAK_ORDER, key=lambda a: probabilities.get(a, -1))
    target = 0
    if "raise" in obs.legal_actions:
        target = prior.get("raise_amount", 0)
        if not obs.min_raise_to <= target <= obs.max_raise_to:
            target = obs.raise_to(obs.current_bet + obs.to_call + max(obs.big_blind, obs.contestable_pot // 2))
    return {
        "action": action, "amount": target if action == "raise" else 0,
        "raise_amount": target, "probabilities": probabilities,
        "diagnostics": {"policy": ALGORITHM, "expert_name": "Pluribus",
                        "parent_samples": parent_total, "cell_samples": cell_total},
    }


def validate_model(model):
    if (not isinstance(model, dict) or type(model.get("schema_version")) is not int
            or model["schema_version"] != 1 or model.get("algorithm") != ALGORITHM):
        raise ValueError("unsupported external preflop model")
    alpha = model.get("alpha")
    if type(alpha) not in (int, float) or not math.isfinite(alpha) or alpha <= 0:
        raise ValueError("invalid external preflop smoothing")
    for name in ("parents", "cells"):
        if not isinstance(model.get(name), dict):
            raise ValueError("invalid external preflop counts")
        for key, counts in model[name].items():
            if (not isinstance(key, str) or not isinstance(counts, list) or len(counts) != 4
                    or any(type(n) is not int or n < 0 for n in counts)):
                raise ValueError("invalid external preflop cell")
    metadata = model.get("metadata")
    if (not isinstance(metadata, dict) or metadata.get("expert_name") != "Pluribus"
            or type(metadata.get("ivey_fitting_decisions")) is not int
            or metadata["ivey_fitting_decisions"] != 0):
        raise ValueError("invalid external expert provenance")
    for name in ("training_decisions", "training_preflop_decisions"):
        if type(metadata.get(name)) is not int or metadata[name] < 1:
            raise ValueError("invalid external expert training count")
    n = metadata["training_preflop_decisions"]
    if (n > metadata["training_decisions"] or sum(sum(v) for v in model["parents"].values()) != n
            or sum(sum(v) for v in model["cells"].values()) != n):
        raise ValueError("inconsistent external expert counts")


def load_model(path):
    model = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_model(model)
    return model
