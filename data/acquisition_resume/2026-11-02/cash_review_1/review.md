# Triton cash review 1 — 2026-11-02

## Scope and disposition

Reviewed the odd-UUID-parity half of the cached Triton cash source: **289 of 564 hand IDs**. The six cached festival/event cash-session groups were built from each saved `GetEpisode` response's festival UUID and event UUID. The current converter produced **221 pending 2024 decision candidates**. This review admitted **0** rows; everything inspected is development-only and not fresh held-out data.

## Independent checks

All 221 candidate prefixes had independently reconstructed total pot and clipped call amount equal to the PokerKit converter state. An independent source-action ledger also matched helper dead antes, live contributions, stack remaining, folds, and eligible contribution tiers on 221 rows. The candidate rows were corrected only in `state.contestable_pot` using those eligible amounts, then all 221 rows were passed through `validate_rows` to recompute and verify decision and record hashes.

Reviewed 152 candidate hands for terminal contribution/payout and stack reconciliation as validation only. History matched source actions before the current action, including pN actor mapping and total-to-street raise amounts. Known hero cards, board visibility cutoffs, legal labels/bounds, explicit blind/button/straddle order, and isolation of opponent cards, future actions, current labels, and terminal facts from `state` were checked per decision.

## 2018 seat metadata blocker

All 36 owned 2018 hands report `noOfSeats=8`; all have distinct source seats within 1–9, and seat 9 appears in 36 hands. Source order built from seat numbers modulo 9 agrees with the explicit small blind, big blind, any straddle, and occupied dealer/button in 36 of 36 hands. This supports ignoring `noOfSeats` for ordering in this specific validated event with strict 1–9 seat and anchor checks. Do not pad missing seats. The cached query selects `noOfSeats`, `dealerSeatNo`, and `players.seatNo` but includes no field documentation, so this is event-specific source evidence rather than a general schema guarantee.

The current converter still rejects all 36 owned 2018 hands: 11 for actual players exceeding the recorded capacity and 25 for seats exceeding it. Full raw details and a constrained repair recommendation are in `sourceblockers/2018-seat-capacity.json`.

## Other source blockers and dedup

The 2024 source retained 44 rejected hands; reasons are listed in `sourceblockers/2024-rejections.json`. The action-before-board-reveal cutoff remains in force.
Global dedup checked 80 admitted rows and saved Triton source material. Exact decision overlaps with the admitted 80: 0; raw hand UUID overlaps with the admitted 80: 0. The 221 exact matches in the reused Nov. 1 parity-one output are reported separately; exact matches in other saved Triton data after excluding the reused cash-review outputs: 0. Episode aliases retain their common raw hand UUIDs.

Converter source SHA at task start/conversion: `aeba51655c1927a47b2b9bd7f404a94a15a7299abde52f9ce9d8ba0cb483a7ca`. Its shared file was later written at 2026-11-02T09:25:24+00:00 UTC and now hashes to `c50a17e08cb2d76848aace6b241a6f347bf1d4f272930a092cfb916991d88268`; all six conversion outputs were created at 2026-11-02T09:19:32.371177+00:00, 2026-11-02T09:19:32.544102+00:00, 2026-11-02T09:19:32.721708+00:00, 2026-11-02T09:19:32.875168+00:00, 2026-11-02T09:19:33.052217+00:00 UTC before that file timestamp. This review did not edit the root converter.

## Files and limits

- `candidates.json`: corrected eligible-pot candidates, still pending and not admitted.
- `per-row-review.json`: per-decision provenance, source-prefix checks, independent ledgers, and validation status.
- `sidecases/eligible-pot-corrections.json`: decisions where dead antes or live-tier reachability changed the prior engine contestable amount.
- `sidecases/global-dedup-and-aliases.json`: admitted/other-source duplicate checks and raw UUID aliases.
- `sourceblockers/`: 2018 capacity evidence and 2024 source rejection details.
- `verification.json`: converter, independent review, and focused helper test checkpoint.

Focused helper tests: **10 passed** using the standard-library `unittest` runner.

Per-file SHA-256 checks match the initial contents exactly for `pokerbot/`, `data/models/`, and `data/corpus_splits/`; each has zero added, removed, or changed files. No policy, scoring, evaluation, frozen split, or raw source was changed by this review. The shared converter was changed later by another workspace action, recorded by hash and timestamp above.
