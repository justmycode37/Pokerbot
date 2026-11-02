"""Independent external preflop prior with a group-fitted postflop overlay."""
import copy
import json
from pathlib import Path

from . import expert_ranges, postflop_policy
from .state import Observation

ALGORITHM = "external-preflop-and-public-postflop-v1"


def _validate_model(model):
    if (not isinstance(model, dict) or set(model) != {
            "schema_version", "algorithm", "external_preflop", "postflop"}
            or type(model.get("schema_version")) is not int
            or model["schema_version"] != 1 or model.get("algorithm") != ALGORITHM):
        raise ValueError("unsupported transfer policy model")
    expert_ranges.validate_model(model["external_preflop"])
    postflop_policy._validate_model(model["postflop"])


def fit_model(rows, *, external_prior, include_development=False, regularization=3.0):
    expert_ranges.validate_model(external_prior)
    model = {
        "schema_version": 1, "algorithm": ALGORITHM,
        "external_preflop": copy.deepcopy(external_prior),
        "postflop": postflop_policy.fit_model(
            rows, include_development=include_development, regularization=regularization),
    }
    _validate_model(model)
    return model


def decide(raw, model):
    if model.get("algorithm") != ALGORITHM or model.get("schema_version") != 1:
        raise ValueError("unsupported transfer policy model")
    obs = Observation.from_dict(raw)
    if obs.street == "preflop":
        return expert_ranges.decide(raw, model["external_preflop"])
    return postflop_policy.decide(raw, model["postflop"])


def load_model(path):
    model = json.loads(Path(path).read_text(encoding="utf-8"))
    _validate_model(model)
    return model
