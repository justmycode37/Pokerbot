"""Portable, read-only inference for the compact postflop equity forest.

This module deliberately contains no fitting or label-generation code. A model
is byte-pinned and validated once by :func:`load_model`; predictions then use
only the immutable in-memory forest and public cards/state.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .cards import normalize_card, rank_hand


FORMAT_NAME = "pokerbot-postflop-equity-regressor"
FORMAT_VERSION = 1
SCHEMA_VERSION = "postflop-equity-jsonl-v1"
FEATURE_VERSION = "public-postflop-features-v3"
TARGET_SEMANTICS = "uniform-random-opponent-showdown-share"
MAX_TREES = 63
MAX_DEPTH = 6
MAX_TREE_NODES = (1 << (MAX_DEPTH + 1)) - 1
MAX_JSON_OBJECT_BYTES = 4 * 1024 * 1024

SOURCE_FINGERPRINT_KEYS = frozenset(
    ("scripts/train_equity_lookup.py", "pokerbot/cards.py")
)

FEATURE_NAMES = (
    "players_active",
    "street_flop",
    "street_turn",
    "street_river",
    "hero_made_category",
    "hero_made_rank_score",
    "hole_high_rank",
    "hole_low_rank",
    "hole_pair",
    "hole_suited",
    "hole_rank_gap",
    "hero_overcards",
    "hero_pairs_board_rank",
    "board_high_rank",
    "board_low_rank",
    "board_unique_ranks",
    "board_duplicate_cards_by_rank",
    "board_pair_groups",
    "board_max_suit_count",
    "board_rank_span",
    "board_longest_rank_run",
    "combined_pair_groups",
    "combined_trips_groups",
    "combined_quads_groups",
    "flush_draw_outs",
    "flush_draw_present",
    "backdoor_flush_draw",
    "straight_draw_out_ranks",
    "straight_draw_open_ended_like",
    "backdoor_straight_windows",
    "hole_high_board_suit_count",
    "hole_low_board_suit_count",
)

DEFAULT_HYPERPARAMETERS = {
    "trees": 31,
    "max_depth": 4,
    "min_leaf": 8,
    "feature_candidates": 6,
    "threshold_candidates": 3,
    "split_sample_size": 512,
    "seed": 20261102,
}


class DataError(ValueError):
    """Raised when a public prediction state is invalid."""


class ArtifactError(ValueError):
    """Raised when model bytes or a model artifact are invalid."""


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, ValueError):
        return False


def _cards(value: Any, label: str, minimum: int, maximum: int) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise DataError("%s must be a sequence of card strings" % label)
    if not minimum <= len(value) <= maximum:
        raise DataError(
            "%s must contain between %d and %d cards" % (label, minimum, maximum)
        )
    try:
        result = tuple(normalize_card(card) for card in value)
    except (TypeError, ValueError) as exc:
        raise DataError("invalid %s: %s" % (label, exc)) from exc
    if len(set(result)) != len(result):
        raise DataError("%s contains duplicate cards" % label)
    return result


def _validate_public_state(
    hole_cards: Any, board: Any, players_active: Any
) -> tuple[tuple[str, str], tuple[str, ...], int]:
    hole = _cards(hole_cards, "hole_cards", 2, 2)
    community = _cards(board, "board", 3, 5)
    if set(hole).intersection(community):
        raise DataError("hole_cards and board contain duplicate cards")
    if not _is_int(players_active):
        raise DataError("players_active must be an integer from 2 through 8")
    if not 2 <= players_active <= 8:
        raise DataError("players_active must be from 2 through 8")
    return (hole[0], hole[1]), community, players_active


def _straight_sequences() -> tuple[tuple[int, ...], ...]:
    sequences = [tuple(range(high - 4, high + 1)) for high in range(6, 15)]
    sequences.append((14, 2, 3, 4, 5))
    return tuple(sequences)


STRAIGHT_SEQUENCES = _straight_sequences()


def extract_features(
    hole_cards: Sequence[str], board: Sequence[str], players_active: int
) -> tuple[float, ...]:
    """Return the frozen v3 feature vector for a public Hold'em state."""
    hole, community, active = _validate_public_state(hole_cards, board, players_active)
    combined = hole + community
    hero_rank = rank_hand(combined)
    category = hero_rank[0]

    # Base-15 digits preserve the evaluator's lexicographic rank ordering.
    score_digits = list(hero_rank[:6])
    score_digits.extend([0] * (6 - len(score_digits)))
    rank_score = sum(
        digit * (15 ** (5 - index)) for index, digit in enumerate(score_digits[:6])
    ) / float(9 * (15**5) - 1)

    def rank_value(card: str) -> int:
        return "23456789TJQKA".index(card[0]) + 2

    hole_ranks = sorted((rank_value(card) for card in hole), reverse=True)
    board_ranks = [rank_value(card) for card in community]
    combined_ranks = [rank_value(card) for card in combined]
    board_rank_counts = Counter(board_ranks)
    combined_rank_counts = Counter(combined_ranks)
    board_suit_counts = Counter(card[1] for card in community)
    combined_suit_counts = Counter(card[1] for card in combined)
    board_rank_set = set(board_ranks)
    combined_rank_set = set(combined_ranks)

    longest_run = 0
    for sequence in STRAIGHT_SEQUENCES:
        longest_run = max(longest_run, sum(rank in board_rank_set for rank in sequence))
    straight_outs = set()
    backdoor_windows = 0
    if category < 4 and len(community) < 5:
        for sequence in STRAIGHT_SEQUENCES:
            present = sum(rank in combined_rank_set for rank in sequence)
            missing = {rank for rank in sequence if rank not in combined_rank_set}
            if len(missing) == 1:
                straight_outs.update(missing)
            elif len(missing) == 2 and len(community) == 3 and present == 3:
                backdoor_windows += 1

    max_suit_count = max(combined_suit_counts.values())
    if category >= 5 or len(community) == 5:
        flush_outs = 0
    elif max_suit_count == 4:
        flush_outs = 13 - max(combined_suit_counts.values())
    else:
        flush_outs = 0

    feature_map = {
        "players_active": active,
        "street_flop": int(len(community) == 3),
        "street_turn": int(len(community) == 4),
        "street_river": int(len(community) == 5),
        "hero_made_category": category,
        "hero_made_rank_score": rank_score,
        "hole_high_rank": hole_ranks[0],
        "hole_low_rank": hole_ranks[1],
        "hole_pair": int(hole_ranks[0] == hole_ranks[1]),
        "hole_suited": int(hole[0][1] == hole[1][1]),
        "hole_rank_gap": abs(hole_ranks[0] - hole_ranks[1]) - 1,
        "hero_overcards": sum(rank > max(board_ranks) for rank in hole_ranks),
        "hero_pairs_board_rank": sum(rank in board_rank_set for rank in hole_ranks),
        "board_high_rank": max(board_ranks),
        "board_low_rank": min(board_ranks),
        "board_unique_ranks": len(board_rank_set),
        "board_duplicate_cards_by_rank": len(community) - len(board_rank_set),
        "board_pair_groups": sum(count == 2 for count in board_rank_counts.values()),
        "board_max_suit_count": max(board_suit_counts.values()),
        "board_rank_span": max(board_ranks) - min(board_ranks),
        "board_longest_rank_run": longest_run,
        "combined_pair_groups": sum(count == 2 for count in combined_rank_counts.values()),
        "combined_trips_groups": sum(count == 3 for count in combined_rank_counts.values()),
        "combined_quads_groups": sum(count == 4 for count in combined_rank_counts.values()),
        "flush_draw_outs": flush_outs,
        "flush_draw_present": int(
            len(community) < 5 and category < 5 and max_suit_count == 4
        ),
        "backdoor_flush_draw": int(
            category < 5 and len(community) == 3 and max_suit_count == 3
        ),
        "straight_draw_out_ranks": len(straight_outs),
        "straight_draw_open_ended_like": int(len(straight_outs) >= 2),
        "backdoor_straight_windows": backdoor_windows,
    }
    # For equal-rank hole cards, sort by the public board-suit count as a tie
    # breaker. This preserves blocker context without assigning suit meaning.
    hole_suit_context = sorted(
        ((rank_value(card), board_suit_counts[card[1]]) for card in hole), reverse=True
    )
    feature_map["hole_high_board_suit_count"] = hole_suit_context[0][1]
    feature_map["hole_low_board_suit_count"] = hole_suit_context[1][1]
    result = tuple(float(feature_map[name]) for name in FEATURE_NAMES)
    if not all(math.isfinite(value) for value in result):
        raise AssertionError("feature extraction produced a non-finite value")
    return result


def _validate_hyperparameters(raw: Any) -> dict[str, int]:
    if not isinstance(raw, dict):
        raise ArtifactError("model hyperparameters must be an object")
    keys = tuple(DEFAULT_HYPERPARAMETERS)
    if set(raw) != set(keys):
        raise ArtifactError("model hyperparameters have unsupported keys")
    values: dict[str, int] = {}
    for key in keys:
        value = raw[key]
        if not _is_int(value):
            raise ArtifactError("model hyperparameter %s must be an integer" % key)
        values[key] = value
    if not 1 <= values["trees"] <= MAX_TREES:
        raise ArtifactError("model tree count is outside the allowed bounds")
    if not 1 <= values["max_depth"] <= MAX_DEPTH:
        raise ArtifactError("model depth is outside the allowed bounds")
    if not 2 <= values["min_leaf"] <= 10_000:
        raise ArtifactError("model min_leaf is outside the allowed bounds")
    if not 1 <= values["feature_candidates"] <= len(FEATURE_NAMES):
        raise ArtifactError("model feature_candidates is outside the allowed bounds")
    if not 1 <= values["threshold_candidates"] <= 8:
        raise ArtifactError("model threshold_candidates is outside the allowed bounds")
    if not 32 <= values["split_sample_size"] <= 4096:
        raise ArtifactError("model split_sample_size is outside the allowed bounds")
    return values


def validate_artifact(model: Any) -> None:
    """Validate trainer artifact metadata and every forest graph before use."""
    if not isinstance(model, dict):
        raise ArtifactError("model artifact must be a JSON object")
    expected = {
        "format": FORMAT_NAME,
        "schema_version": SCHEMA_VERSION,
        "feature_version": FEATURE_VERSION,
        "feature_names": list(FEATURE_NAMES),
        "target_semantics": TARGET_SEMANTICS,
    }
    for key, value in expected.items():
        if model.get(key) != value:
            raise ArtifactError("model %s is unsupported or invalid" % key)
    if not _is_int(model.get("format_version")) or model["format_version"] != FORMAT_VERSION:
        raise ArtifactError("model format_version is unsupported or invalid")
    if model.get("complete") is not True:
        raise ArtifactError("model complete is unsupported or invalid")
    for key in ("input_sha256", "freeze_sha256"):
        if not _is_sha256(model.get(key)):
            raise ArtifactError("model %s must be a SHA-256 hex digest" % key)
    source_hashes = model.get("source_sha256")
    if not isinstance(source_hashes, dict) or set(source_hashes) != SOURCE_FINGERPRINT_KEYS:
        raise ArtifactError("model source fingerprint keys are unsupported")
    if any(not _is_sha256(value) for value in source_hashes.values()):
        raise ArtifactError("model source fingerprints are invalid")
    for key in ("training_row_count", "training_group_count"):
        if not _is_int(model.get(key)) or model[key] <= 0:
            raise ArtifactError("model %s must be a positive integer" % key)
    hyperparameters = _validate_hyperparameters(model.get("hyperparameters"))
    if hyperparameters != model["hyperparameters"]:
        raise ArtifactError("model hyperparameters are invalid")

    trees = model.get("trees")
    if not isinstance(trees, list) or not 1 <= len(trees) <= MAX_TREES:
        raise ArtifactError("model tree count is outside the allowed bounds")
    if len(trees) != hyperparameters["trees"]:
        raise ArtifactError("model tree count differs from its frozen hyperparameters")

    for tree_index, tree in enumerate(trees):
        if not isinstance(tree, list) or not 1 <= len(tree) <= MAX_TREE_NODES:
            raise ArtifactError("tree %d has an invalid node array" % tree_index)
        parents: Counter[int] = Counter()
        for index, node in enumerate(tree):
            if not isinstance(node, list) or len(node) != 4:
                raise ArtifactError("tree %d node %d must have four values" % (tree_index, index))
            feature, value, left, right = node
            if not _is_int(feature) or not _is_int(left) or not _is_int(right):
                raise ArtifactError("tree %d node %d has invalid integer fields" % (tree_index, index))
            if not _is_finite_number(value):
                raise ArtifactError("tree %d node %d has a non-finite value" % (tree_index, index))
            if feature == -1:
                if left != -1 or right != -1 or not 0.0 <= float(value) <= 1.0:
                    raise ArtifactError("tree %d node %d has an invalid leaf" % (tree_index, index))
            else:
                if not 0 <= feature < len(FEATURE_NAMES):
                    raise ArtifactError("tree %d node %d references an invalid feature" % (tree_index, index))
                if not 0 <= left < len(tree) or not 0 <= right < len(tree) or left == right:
                    raise ArtifactError("tree %d node %d references invalid children" % (tree_index, index))
                if left <= index or right <= index:
                    raise ArtifactError("tree %d child indexes must follow their parent" % tree_index)
                parents[left] += 1
                parents[right] += 1
        if parents[0] != 0 or any(parents[index] != 1 for index in range(1, len(tree))):
            raise ArtifactError("tree %d is disconnected or has shared children" % tree_index)
        visited: set[int] = set()

        def visit(index: int, depth: int) -> None:
            if index in visited:
                raise ArtifactError("tree %d contains a cycle" % tree_index)
            visited.add(index)
            if depth > hyperparameters["max_depth"]:
                raise ArtifactError("tree %d exceeds its frozen depth limit" % tree_index)
            node = tree[index]
            if node[0] >= 0:
                visit(node[2], depth + 1)
                visit(node[3], depth + 1)

        visit(0, 0)
        if len(visited) != len(tree):
            raise ArtifactError("tree %d contains unreachable nodes" % tree_index)


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ArtifactError("JSON object contains duplicate key %r" % key)
        result[key] = value
    return result


def _reject_nonfinite_constant(value: str) -> Any:
    raise ArtifactError("model JSON contains non-finite numeric value %s" % value)


def _validate_finite_json(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ArtifactError("model JSON contains a non-finite number")
    if isinstance(value, dict):
        for nested in value.values():
            _validate_finite_json(nested)
    elif isinstance(value, list):
        for nested in value:
            _validate_finite_json(nested)


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(nested) for key, nested in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(nested) for nested in value)
    return value


@dataclass(frozen=True, slots=True)
class EquityInference:
    """Immutable forest and metadata ready for repeated in-memory predictions."""

    _trees: tuple[tuple[tuple[int, int | float, int, int], ...], ...]
    _metadata: Mapping[str, Any]
    model_sha256: str

    @property
    def metadata(self) -> Mapping[str, Any]:
        """Read-only artifact metadata (tree nodes are kept private)."""
        return self._metadata

    @property
    def sha256(self) -> str:
        """SHA-256 identity of the exact model file bytes."""
        return self.model_sha256

    def predict(
        self, hole_cards: Sequence[str], board: Sequence[str], players_active: int
    ) -> float:
        """Predict public-state showdown share without I/O or mutable state."""
        features = extract_features(hole_cards, board, players_active)
        estimates = []
        for tree in self._trees:
            node_index = 0
            while tree[node_index][0] != -1:
                feature_index, threshold, left, right = tree[node_index]
                node_index = left if features[feature_index] <= threshold else right
            estimates.append(float(tree[node_index][1]))
        result = sum(estimates) / len(estimates)
        return max(0.0, min(1.0, result))


def load_model(path: str | Path, *, expected_sha256: str) -> EquityInference:
    """Read, byte-pin, validate, and freeze one compact JSON forest artifact.

    The expected digest is mandatory so callers cannot accidentally load a
    replaceable or unreviewed artifact. File bytes are size-checked and hashed
    before UTF-8 decoding or JSON parsing begins.
    """
    if not _is_sha256(expected_sha256):
        raise ArtifactError("expected_sha256 must be a lowercase SHA-256 hex digest")
    try:
        with Path(path).open("rb") as handle:
            raw = handle.read(MAX_JSON_OBJECT_BYTES + 1)
    except OSError as exc:
        raise ArtifactError("cannot read model artifact: %s" % exc) from exc
    if len(raw) > MAX_JSON_OBJECT_BYTES:
        raise ArtifactError("model artifact exceeds the 4 MiB byte limit")
    digest = hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(digest, expected_sha256):
        raise ArtifactError("model artifact SHA-256 does not match expected_sha256")
    try:
        model = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite_constant,
        )
    except ArtifactError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ArtifactError("model artifact is not valid UTF-8 JSON: %s" % exc) from exc
    _validate_finite_json(model)
    validate_artifact(model)

    immutable_trees = tuple(
        tuple(tuple(node) for node in tree) for tree in model["trees"]
    )
    immutable_metadata = _freeze_json(
        {key: value for key, value in model.items() if key != "trees"}
    )
    return EquityInference(
        _trees=immutable_trees,
        _metadata=immutable_metadata,
        model_sha256=digest,
    )


__all__ = [
    "ArtifactError",
    "DataError",
    "EquityInference",
    "FEATURE_NAMES",
    "FEATURE_VERSION",
    "MAX_DEPTH",
    "MAX_JSON_OBJECT_BYTES",
    "MAX_TREES",
    "SCHEMA_VERSION",
    "TARGET_SEMANTICS",
    "extract_features",
    "load_model",
    "validate_artifact",
]
