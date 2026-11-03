# Equity runtime publication evidence

This release publishes an optional read-only inference module and the exact
reference model bytes. The artifact is pinned at 176,343 bytes with SHA-256
`7dd0457e02c5bf5d3e3d1c9f06b4f3d043c7343a068092b23c3c3bb6ad6e48fd`. Its
manifest records the model format, feature contract, training source hashes,
and calibration summary.

The completed audit `reports/evolution-audits/equity-calibration-model-v1`
recorded 42,000 reference labels, including 8,408 calibration rows across
4,196 groups. It reported model MAE 0.07809 versus 0.10833 for the prior raw
estimate. These figures describe calibration error, not win rate. The first
2,304-table comparison found no established paired gain, so this publication
makes no matchplay improvement claim.

The independent runtime review recorded 17 checks, exact trainer parity across
256 additional public states, and local p95 prediction latency of 0.089 ms.
That latency is an observed local measurement and is not an SDK or platform
guarantee. This PR carries a test-only 5-tree mock model and 224 golden
feature/prediction vectors exported from trainer SHA-256
`0ec6cdabd27518187b61ee77fadb076fed4beefe2d1937c28add01375f8ce96e`. Tests
use these frozen fixtures without importing or shipping the trainer.
Features and suit-invariance predictions remain exact; frozen predictions
allow one ULP for Python 3.11/3.12 summation rounding. The tests exercise both
native and sequential summation.

The full calibration and runtime review reports, training scripts, raw run
logs, recalibration artifacts, and experimental evolution patches remain in
the research workspace and are not part of this portable runtime slice. The
runtime is optional; it does not replace or promote the saved bot by default.
