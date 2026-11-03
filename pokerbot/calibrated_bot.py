"""Table-local policy factory using the pinned portable equity forest.

The immutable model is loaded and validated on the first calibrated policy
factory call in this process. Policies keep their own closure; decisions do
not read files or import training and reference-generation code.
"""

from __future__ import annotations

from pathlib import Path
import threading

from . import equity_policy, equity_runtime, evolution_strategies


MODEL_PATH = Path(__file__).resolve().parent / "models" / "postflop-equity-v1.json"
MODEL_SHA256 = "7dd0457e02c5bf5d3e3d1c9f06b4f3d043c7343a068092b23c3c3bb6ad6e48fd"

_MODEL: equity_runtime.EquityInference | None = None
_MODEL_LOCK = threading.Lock()


def _load_model() -> equity_runtime.EquityInference:
    """Load the required package artifact once, failing closed on any error."""
    global _MODEL
    if _MODEL is None:
        with _MODEL_LOCK:
            if _MODEL is None:
                try:
                    model = equity_runtime.load_model(
                        MODEL_PATH, expected_sha256=MODEL_SHA256,
                    )
                except equity_runtime.ArtifactError as exc:
                    raise RuntimeError(
                        f"required calibrated equity model at {MODEL_PATH} "
                        f"is missing or invalid: {exc}"
                    ) from exc
                _MODEL = model
    return _MODEL


def make_calibrated_policy(genome: evolution_strategies.Genome):
    """Return a fresh table policy backed by the one cached immutable model."""
    if not isinstance(genome, evolution_strategies.Genome):
        raise TypeError("make_calibrated_policy expects a Genome")
    model = _load_model()
    return equity_policy.make_equity_policy(
        genome,
        model.predict,
        model_metadata={
            "model": "postflop-equity-v1",
            "model_sha256": model.model_sha256,
            "target_semantics": equity_runtime.TARGET_SEMANTICS,
        },
    )


__all__ = ["MODEL_PATH", "MODEL_SHA256", "make_calibrated_policy"]
