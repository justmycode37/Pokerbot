# One-hour Ivey acquisition sprint

Requested 2026-10-31 at 11:58:41 UTC; target checkpoint 12:58:41 UTC.
The requested intermediate target is 1,000 actual Ivey decisions usable for
comparison. The existing larger acquisition milestone remains 2,000. The
baseline is 45 admitted, previously inspected decisions across 12 hands and
eight source groups. The target deadline does not lower source requirements.

The collection thread owns existing WPT and HCL capture, source-action review,
and WPT admission integration. This sprint owns disjoint written-report,
original online-hand-history, and bulk-archive lanes under
`data/acquisition_sprint_1h/`. Three Luna workers at maximum reasoning acquire
sources while the parent prepares batch replay, deduplication and integration.
Strategy, models and frozen evaluation splits remain unchanged.

`scripts/acquisition_import.py` imports a source manifest into a new run file.
Its source entries specify `path`, `source_url`, `format` (`phh`, `full_tilt`,
or `decision_rows`), and a stable `source_namespace` for PHH inputs. Optional
`canonical_hand_id` and `session_id` explicitly reconcile source identities.
Decision-row inputs must contain `state`, separate `expected`, `hand_id` and
`canonical_hand_id` fields. Capture provenance and card-source basis remain
outside observations. Full Tilt cap/ante logs require a dedicated importer.
Alias histories require source-reviewed normalization before intake.

Example (paths in a manifest are relative to that manifest):

```sh
.venv/bin/python scripts/acquisition_import.py manifest.json \
  --baseline data/corpus_splits/development-after-prospective-v1.json \
  --output data/acquisition_sprint_1h/imports/run-001.json
```

Passing replay or protocol checks creates pending review candidates. It does
not automatically admit source facts. Unknown hero cards are excluded by the
strict replay. Metadata entries, sampled frames, repeated source copies,
opponent decisions, non-NLHE hands and synthetic variants do not count toward
the usable target. A new run preserves earlier outputs. Independent review and
cross-source reconciliation remain necessary before evaluation.
