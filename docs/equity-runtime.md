# Portable postflop equity inference

`pokerbot.equity_runtime` provides optional, read-only inference for a compact
postflop model. It contains public feature extraction, model validation, and
immutable in-memory tree traversal. It contains no training or label-generation
code and has no third-party inference dependencies. The default saved bot does
not load or promote this model.

## Load the packaged model with a pinned digest

The model ships in the `pokerbot` package and is available in source checkouts
and wheels. Pin the digest of the exact reviewed bytes:

```python
from importlib.resources import as_file, files
from pokerbot.equity_runtime import load_model

model_resource = files("pokerbot").joinpath("models/postflop-equity-v1.json")
with as_file(model_resource) as model_path:
    model = load_model(
        model_path,
        expected_sha256="7dd0457e02c5bf5d3e3d1c9f06b4f3d043c7343a068092b23c3c3bb6ad6e48fd",
    )
share = model.predict(["As", "Kd"], ["2c", "3d", "4h"], players_active=2)
print(model.sha256, share)
```

`load_model` reads at most 4 MiB plus one byte, hashes before decoding or
parsing, and requires the expected lowercase SHA-256. It validates the model
format, schema, v3 feature names, target semantics, metadata digests, and source
fingerprints. It rejects non-finite values, bools in integer fields, oversized
forests, and malformed or disconnected tree graphs. Metadata and tree nodes
are immutable after loading. `predict` performs no file I/O or model mutation.

The included model is 176,343 bytes, with 32 frozen features and 63 trees of
maximum depth 6. Its concise source and training receipt is
[`pokerbot/models/postflop-equity-v1.manifest.json`](../pokerbot/models/postflop-equity-v1.manifest.json).

## Inputs and target

The API accepts two distinct hero hole cards, three to five distinct public
board cards, and an integer `players_active` from 2 through 8 inclusive. The
active-player count includes the hero. Card parsing follows
`pokerbot.cards.normalize_card`, including case normalization, surrounding
whitespace, and `10` as an alias for `T`. No opponent cards, ranges, action
history, or live reads are accepted.

Predictions use `public-postflop-features-v3` and estimate
`uniform-random-opponent-showdown-share`. They are bounded to `[0, 1]`. The v3
features include the corrected two-missing-rank open-ended-like draw count,
zero future draw outs on the river, and each hero card's public board-suit
count. Feature extraction preserves card-order invariance and all 24 global
suit permutations, including suit-context tie handling for pocket pairs.

This output is not opponent-range-conditioned equity, action EV, or playing
strength. The model remains an optional inference artifact; no automatic
promotion or matchplay benefit is claimed.

## Frozen parity and safety checks

The runtime tests use a checked-in, test-only 5-tree mock model and 224 frozen
public states. Their exact feature and prediction vectors were exported from
the v3 trainer identified in the fixture by SHA-256. The tests do not import or
ship the trainer. Separate golden edge cases cover pocket-pair suit ties, a
spade blocker, a gutshot, and a river with no future draw outs. All 24 global
suit maps are checked for each case.

The focused suite also checks invalid and private-input boundaries, digest
mismatch before parsing, byte limits, tampering, duplicate JSON keys,
non-finite values, bool-as-int rejection, metadata and tree graph bounds, and
inference-object immutability. Its deterministic mock labels exist only to
exercise software behavior; they are not reference equity observations.

## Evidence limits

The completed calibration-model audit recorded 42,000 reference labels and a
calibration subset of 8,408 rows across 4,196 groups. The model's reported MAE
was 0.07809 versus 0.10833 for the prior raw estimate. This is calibration
error evidence, not win rate or matchplay evidence. The first 2,304-table
comparison found no established paired gain.

The completed runtime review recorded exact trainer parity on 256 additional
states and a local p95 observation of 0.089 ms. That timing is a local
measurement, not an SDK or platform guarantee. This release also reruns the
frozen 224-state fixture independently of trainer imports. The accompanying
publication note records these limits and the source audit identifiers.
