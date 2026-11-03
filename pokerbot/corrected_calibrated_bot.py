"""Inference-only policy factory for the reviewed equity correction v2.

This candidate composes the pinned v1 postflop forest with a separately
sealed, player-count-specific isotonic transform. Both artifacts are loaded
and validated once per process, then kept immutable in memory. Decisions use
only public state and perform no file I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import math
from pathlib import Path
import threading
from types import MappingProxyType
from typing import Any, Mapping

from . import equity_policy, equity_runtime, evolution_strategies


MODEL_PATH = Path(__file__).resolve().parent / "models" / "postflop-equity-v1.json"
CORRECTION_PATH = (
    Path(__file__).resolve().parent / "models" / "postflop-equity-correction-v2.json"
)

# These pins identify the exact reviewed inputs. The correction's file digest
# is distinct from its canonical candidate digest and its portable-transform
# digest; all three are checked before any curve is used.
BASE_MODEL_SHA256 = "7dd0457e02c5bf5d3e3d1c9f06b4f3d043c7343a068092b23c3c3bb6ad6e48fd"
CORRECTION_FILE_SHA256 = "3dfb27cfa15e12da01b94c9a69851ae1b0f4e4f3833743b1f740fef54bc51b0d"
CANDIDATE_SHA256 = "d8321112b47ed593d61f036d40ca9a3a29869ff3a02d04dd735f055d7ea734d3"
PORTABLE_TRANSFORM_SHA256 = "64b4efb1ef361d7b631206f8707815868186336f3030409b08f70633492934d6"
PROTOCOL_ID = "equity-recalibration-v2-frozen-candidate"
PROTOCOL_SHA256 = "4d06ea7bcc0590dc4651a7ad16a4ba286c51f8c72e45e5fd2399281fff093ef7"
TARGET_SEMANTICS = "uniform-random-opponent-showdown-share"
MAX_CORRECTION_BYTES = 2 * 1024 * 1024

_CORRECTION_FORMAT = "pokerbot-public-share-isotonic-correction"
_METHOD = {
    "algorithm": "per-player-weighted-pava-on-threefold-grouped-oof-v1",
    "bounds": "raw input and output are finite and in [0,1]",
    "grouping": "canonical public hole-card and board group; all players and replicate seeds stay in one fold",
    "input": "OOF raw v1 predicted share; target: original training label share",
    "interpolation": "piecewise linear between strictly ordered raw prediction knots; clamp to endpoint fitted values outside the knot range",
    "min_training_rows": 100,
    "pava_objective": "row-weighted squared error with nondecreasing fitted share",
    "small_sample": "if a player-count curve has fewer than 100 OOF rows, use the identity curve (0,0) to (1,1)",
    "ties": "exact equal raw predictions are aggregated by row count before PAVA",
}
_SOURCE_SHA256 = {
    "pokerbot/cards.py": "89a27b217402dd3bccda1d75ac16be52d477484e7e4115896ea135e6ff0efc12",
    "scripts/calibrate_equity_lookup.py": "2dbebd17edb963e448016f2ddf4a96136c7d10c9768a40089037cc075e5c3c05",
    "scripts/equity_reference.cpp": "0a021febddec2118d35193b9e9fbc242f71544f9c83e978249f1af2012b4882d",
    "scripts/generate_equity_data.py": "cae6f7d915f364e028c7914ddb43897d2eb7b2e86fd2dcde8d047323ef64c27c",
    "scripts/train_equity_lookup.py": "0ec6cdabd27518187b61ee77fadb076fed4beefe2d1937c28add01375f8ce96e",
}
_TOP_LEVEL_KEYS = frozenset({
    "base_freeze_canonical_sha256",
    "base_freeze_file_sha256",
    "base_model_sha256",
    "candidate_sha256",
    "corrections",
    "created_from_partition",
    "fold_assignment_sha256",
    "fold_count",
    "fold_seed",
    "folds",
    "format",
    "format_version",
    "method",
    "oof_prediction_rows",
    "oof_predictions_sha256",
    "original_calibration_labels_used",
    "original_labels_sha256",
    "original_training_groups",
    "original_training_rows",
    "portable_transform_sha256",
    "protocol_id",
    "protocol_sha256",
    "source_sha256",
    "target_semantics",
})
_CURVE_KEYS = frozenset({
    "behavior", "knots", "training_group_count", "training_row_count",
})


class CorrectionArtifactError(ValueError):
    """Raised when the packaged correction bytes or schema are invalid."""


def _is_digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CorrectionArtifactError(f"correction JSON contains duplicate key {key!r}")
        result[key] = value
    return result


def _reject_nonfinite_constant(value: str) -> Any:
    raise CorrectionArtifactError(f"correction JSON contains non-finite value {value}")


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise CorrectionArtifactError("correction candidate is not canonical JSON") from exc


@dataclass(frozen=True, slots=True)
class EquityCorrection:
    """Validated immutable player-count curves from the sealed v2 candidate."""

    curves: Mapping[int, tuple[tuple[float, float], ...]]
    candidate_sha256: str
    file_sha256: str
    portable_transform_sha256: str

    def correct(self, raw_share: Any, players_active: Any) -> float:
        """Apply the bounded monotone curve for the actual active-player count."""
        if isinstance(raw_share, bool) or not isinstance(raw_share, (int, float)):
            raise ValueError("raw_share must be a finite number from 0 through 1")
        try:
            x = float(raw_share)
        except (OverflowError, TypeError, ValueError) as exc:
            raise ValueError("raw_share must be a finite number from 0 through 1") from exc
        if not math.isfinite(x) or not 0.0 <= x <= 1.0:
            raise ValueError("raw_share must be a finite number from 0 through 1")
        if type(players_active) is not int or players_active not in self.curves:
            raise ValueError("players_active must be an integer from 2 through 8")

        points = self.curves[players_active]
        if x <= points[0][0]:
            return points[0][1]
        if x >= points[-1][0]:
            return points[-1][1]
        # Locate the same first right-hand knot used by the reviewed
        # left-to-right transform, with logarithmic lookup for match runtime.
        low, high = 1, len(points) - 1
        while low < high:
            middle = (low + high) // 2
            if x <= points[middle][0]:
                high = middle
            else:
                low = middle + 1
        left_x, left_y = points[low - 1]
        right_x, right_y = points[low]
        fraction = (x - left_x) / (right_x - left_x)
        return max(0.0, min(1.0, left_y + fraction * (right_y - left_y)))


def _parse_correction_bytes(raw: bytes) -> EquityCorrection:
    """Verify byte pin, canonical seal, fingerprints, schema and every knot."""
    if not isinstance(raw, bytes):
        raise CorrectionArtifactError("correction artifact must be bytes")
    if len(raw) > MAX_CORRECTION_BYTES:
        raise CorrectionArtifactError("correction artifact exceeds the 2 MiB byte limit")
    file_digest = hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(file_digest, CORRECTION_FILE_SHA256):
        raise CorrectionArtifactError("correction artifact SHA-256 does not match the reviewed file")
    try:
        candidate = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite_constant,
        )
    except CorrectionArtifactError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise CorrectionArtifactError("correction artifact is not valid UTF-8 JSON") from exc

    if not isinstance(candidate, dict) or set(candidate) != _TOP_LEVEL_KEYS:
        raise CorrectionArtifactError("correction artifact has an unsupported top-level schema")
    expected_metadata = {
        "format": _CORRECTION_FORMAT,
        "format_version": 1,
        "protocol_id": PROTOCOL_ID,
        "protocol_sha256": PROTOCOL_SHA256,
        "base_model_sha256": BASE_MODEL_SHA256,
        "candidate_sha256": CANDIDATE_SHA256,
        "portable_transform_sha256": PORTABLE_TRANSFORM_SHA256,
        "target_semantics": TARGET_SEMANTICS,
        "created_from_partition": "original-v1-training-only",
        "original_calibration_labels_used": False,
    }
    for key, expected in expected_metadata.items():
        actual = candidate.get(key)
        if type(expected) is int and type(actual) is not int:
            raise CorrectionArtifactError(f"correction metadata {key!r} has an invalid type")
        if actual != expected:
            raise CorrectionArtifactError(f"correction metadata {key!r} does not match its pin")
    if candidate.get("method") != _METHOD:
        raise CorrectionArtifactError("correction method metadata differs from the reviewed schema")
    if candidate.get("source_sha256") != _SOURCE_SHA256:
        raise CorrectionArtifactError("correction source fingerprints differ from the reviewed protocol")

    seal = candidate.get("candidate_sha256")
    if not _is_digest(seal):
        raise CorrectionArtifactError("candidate_sha256 must be a lowercase SHA-256 digest")
    unsigned = {key: value for key, value in candidate.items() if key != "candidate_sha256"}
    if not hmac.compare_digest(hashlib.sha256(_canonical_json(unsigned)).hexdigest(), seal):
        raise CorrectionArtifactError("candidate SHA-256 digest does not match its contents")

    corrections = candidate.get("corrections")
    if not isinstance(corrections, dict) or set(corrections) != {str(player) for player in range(2, 9)}:
        raise CorrectionArtifactError("candidate must contain exactly seven player-count curves")
    curves: dict[int, tuple[tuple[float, float], ...]] = {}
    for players in range(2, 9):
        curve = corrections[str(players)]
        if not isinstance(curve, dict) or set(curve) != _CURVE_KEYS:
            raise CorrectionArtifactError(f"curve for {players} players has an unsupported schema")
        if curve.get("behavior") != "weighted_pava":
            raise CorrectionArtifactError(f"curve for {players} players has an unsupported behavior")
        for count_name in ("training_group_count", "training_row_count"):
            count = curve.get(count_name)
            if type(count) is not int or count <= 0:
                raise CorrectionArtifactError(f"curve {count_name} must be a positive integer")
        raw_knots = curve.get("knots")
        if not isinstance(raw_knots, list) or not raw_knots:
            raise CorrectionArtifactError(f"curve for {players} players must contain knots")
        knots: list[tuple[float, float]] = []
        previous_x = -1.0
        previous_y = -1.0
        for knot in raw_knots:
            if not isinstance(knot, list) or len(knot) != 2:
                raise CorrectionArtifactError("each correction knot must contain x and y")
            x, y = knot
            if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in (x, y)):
                raise CorrectionArtifactError("correction knots must contain finite numbers")
            try:
                x, y = float(x), float(y)
            except (OverflowError, ValueError) as exc:
                raise CorrectionArtifactError("correction knots must contain finite numbers") from exc
            if not math.isfinite(x) or not math.isfinite(y):
                raise CorrectionArtifactError("correction knots must contain finite numbers")
            if not 0.0 <= x <= 1.0 or not 0.0 <= y <= 1.0 or x <= previous_x or y < previous_y:
                raise CorrectionArtifactError("correction knots must be bounded, strictly x-sorted and monotone")
            previous_x, previous_y = x, y
            knots.append((x, y))
        curves[players] = tuple(knots)

    return EquityCorrection(
        curves=MappingProxyType(curves),
        candidate_sha256=seal,
        file_sha256=file_digest,
        portable_transform_sha256=candidate["portable_transform_sha256"],
    )


_MODEL: equity_runtime.EquityInference | None = None
_CORRECTION: EquityCorrection | None = None
_ASSET_LOCK = threading.Lock()


def _load_assets() -> tuple[equity_runtime.EquityInference, EquityCorrection]:
    """Load both byte-pinned files once; publish neither unless both validate."""
    global _MODEL, _CORRECTION
    if _MODEL is None or _CORRECTION is None:
        with _ASSET_LOCK:
            if _MODEL is None or _CORRECTION is None:
                try:
                    correction = _parse_correction_bytes(CORRECTION_PATH.read_bytes())
                except (OSError, CorrectionArtifactError) as exc:
                    raise RuntimeError(
                        f"required corrected equity artifact at {CORRECTION_PATH} is missing or invalid: {exc}"
                    ) from exc
                try:
                    model = equity_runtime.load_model(
                        MODEL_PATH, expected_sha256=BASE_MODEL_SHA256,
                    )
                except equity_runtime.ArtifactError as exc:
                    raise RuntimeError(
                        f"required corrected equity base model at {MODEL_PATH} is missing or invalid: {exc}"
                    ) from exc
                if model.model_sha256 != BASE_MODEL_SHA256:
                    raise RuntimeError("loaded corrected equity base model fingerprint is inconsistent")
                _CORRECTION = correction
                _MODEL = model
    return _MODEL, _CORRECTION


def make_corrected_calibrated_policy(genome: evolution_strategies.Genome):
    """Return a fresh policy using the v2 transform for each active-player count."""
    if not isinstance(genome, evolution_strategies.Genome):
        raise TypeError("make_corrected_calibrated_policy expects a Genome")
    if genome.family != "corrected-calibrated":
        raise ValueError("make_corrected_calibrated_policy requires family 'corrected-calibrated'")
    model, correction = _load_assets()

    def estimate_share(hole_cards, board, players_active):
        raw_share = model.predict(hole_cards, board, players_active)
        return correction.correct(raw_share, players_active)

    return equity_policy.make_equity_policy(
        genome,
        estimate_share,
        model_metadata={
            "model": "postflop-equity-correction-v2",
            "base_model": "postflop-equity-v1",
            "base_model_sha256": model.model_sha256,
            "correction_file_sha256": correction.file_sha256,
            "correction_candidate_sha256": correction.candidate_sha256,
            "portable_transform_sha256": correction.portable_transform_sha256,
            "estimator_output": "v2-corrected-share",
            "target_semantics": equity_runtime.TARGET_SEMANTICS,
        },
    )


__all__ = [
    "BASE_MODEL_SHA256",
    "CANDIDATE_SHA256",
    "CORRECTION_FILE_SHA256",
    "CORRECTION_PATH",
    "MODEL_PATH",
    "PORTABLE_TRANSFORM_SHA256",
    "PROTOCOL_ID",
    "PROTOCOL_SHA256",
    "CorrectionArtifactError",
    "EquityCorrection",
    "make_corrected_calibrated_policy",
]
