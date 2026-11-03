# Corrected calibrated policy candidate

`pokerbot.corrected_calibrated_bot.make_corrected_calibrated_policy` composes
the byte-pinned v1 postflop forest with the independently reviewed v2
per-player weighted-PAVA correction. It is an inference-only candidate. It
does not retrain the forest, consume labels, or modify the existing `calibrated`
factory.

## Runtime contract

- The factory accepts a `Genome` from the `corrected-calibrated` family and
  returns a fresh table policy. It uses the genome's original `bot_id` for the
  existing deterministic policy salt.
- Preflop actions use the existing evolved preflop path. The estimator is
  called only postflop with the hero's two cards, public board, and actual
  active-player count.
- The v2 curve selected by that active-player count returns a bounded,
  monotone uniform-random-opponent showdown-share estimate. Existing policy
  pressure handling remains separate; there is no second multiway equity
  subtraction.
- The model and correction bytes load and validate once per process and are
  cached immutably. A missing, changed, or malformed artifact raises an
  error; there is no fallback policy. Decisions do not read files.
- Runtime imports only pokerbot inference/policy modules and the standard
  library. Training and reference generation stay outside the policy path.

## Reviewed artifact pins

| Input | SHA-256 |
| --- | --- |
| Base v1 model file | `7dd0457e02c5bf5d3e3d1c9f06b4f3d043c7343a068092b23c3c3bb6ad6e48fd` |
| Packaged v2 correction file | `3dfb27cfa15e12da01b94c9a69851ae1b0f4e4f3833743b1f740fef54bc51b0d` |
| Sealed candidate canonical digest | `d8321112b47ed593d61f036d40ca9a3a29869ff3a02d04dd735f055d7ea734d3` |
| Portable transform source | `64b4efb1ef361d7b631206f8707815868186336f3030409b08f70633492934d6` |
| Frozen protocol | `4d06ea7bcc0590dc4651a7ad16a4ba286c51f8c72e45e5fd2399281fff093ef7` |

The candidate is copied byte-for-byte from
`.work/equity-recalibration-v2-correction.json`. Its loader checks the exact
file and candidate digests, protocol and base-model bindings, training-source
fingerprints, supported schema, all seven curve shapes, and bounded monotone
knots. The audit reports exact agreement with the portable transform over
5,712 bounded inputs and a fresh-state MAE change from 0.0769 to 0.0524. These
are calibration results for showdown share only, not action EV or match
strength. See [the v2 audit](../reports/evolution-audits/equity-recalibration-v2.md)
and [the independent review](../reports/evolution-audits/equity-recalibration-v2-review-findings.md).

## Evolution integration

The `corrected-calibrated` family is registered in `pokerbot/evolution_strategies.py`:

1. Genome validation and gene loading accept the same bounded parameters.
2. Breeding retains the candidate family when its parent family is selected.
3. `policy_for` dispatches to `make_corrected_calibrated_policy` from this module.

No change to the legacy calibrated or saved family is needed. Keep the five
hash pins above in candidate review/evaluation metadata. Existing frozen
opponent-pool fingerprints should change only if the actual pool definitions
change, not merely because this optional factory is registered.

## Verification scope

`tests/test_corrected_calibrated_bot.py` checks the real reviewed correction
against seven preserved calibration rows in a small fixture with its source
CSV hash, covers player counts 2 through 8, confirms a
real v1 model prediction reproduces the report sample, rejects missing or
modified correction files, checks preflop parity and bot-id salt, verifies
bounded multiway semantics, and exercises immutable caching and independent
policy closures. This enables a candidate family; it does not report a match
win-rate result or satisfy a 90% confirmation gate.
