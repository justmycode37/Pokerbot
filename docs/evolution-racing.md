# Training-only candidate comparisons

`scripts/race_evolution.py` runs an experimental equal-sample comparison of candidate genomes through the canonical evolution tournament evaluator. It does not alter `pokerbot.evolution`, select survivors, promote a champion, or establish a performance target.

Prepare a candidate file containing canonical `Genome.to_dict()` objects and a seed file containing the complete, fresh integer seed list. The racer does not generate, filter, reorder, or replace those seeds. The seed source must be isolated from the engine's training, validation, and confirmation seed domains; use a new one-use `racer-*` namespace for each comparison. The tool records the seed file hash and the exact seed list in the frozen protocol.

```json
[
  {
    "bot_id": "candidate-a",
    "family": "evolved",
    "params": {"call_frequency": 0.61},
    "parents": ["parent-x"],
    "generation": 7
  }
]
```

```json
[782341, 928107, 1192044]
```

Run with one or more checkpoint sources:

```sh
.venv/bin/python scripts/race_evolution.py \
  --candidates reports/evolution-audits/racer-tool-candidates.json \
  --checkpoint reports/evolution-next-20261102/checkpoint.json \
  --checkpoint reports/evolution-v4/checkpoint.json \
  --seeds reports/evolution-audits/racer-tool-seeds.json \
  --namespace racer-v4-recheck-unique-01 \
  --workers 4 \
  --output-dir reports/evolution-audits/racer-tool-v4-recheck-01
```

The output directory must not already exist. `--resume` is explicitly unsupported in this version and is refused. A failed run leaves its protocol and jobs in place with `status.json` marked `incomplete`; no `COMPLETE.json` marker is written. A run is complete only when the final marker exists. CSV, JSON, Markdown, and marker writes use atomic replacements.

## Frozen comparison design

The checkpoint reader immediately projects only the training table configuration, `training_opponents`, `hall_of_fame`, and genome records referenced by those IDs. Validation, confirmation, fitness, history, and report fields are not used. Checkpoint source hashes cover only this allowlisted projection. The tool unions every supplied training and HOF genome by ID, preserves the full archive, and rejects an ID reused with a different family or parameter set. When an ID has the same family and parameters but different parents or generation across sources, every source record is retained as explicit provenance.

Independent experiments may reuse a bot ID for different genes. To retain both records, prepare immutable training-only projections with distinct report aliases and preserve original source hashes and lineage in a separate preparation manifest. Supply `--policy-ids path/to/policy-ids.json`, a JSON object mapping those aliases to their original bot IDs. The report and opponent plan use aliases, while the frozen canonical job's genome records use original policy IDs. This preserves ID-dependent policy action sampling. The protocol records the full mapping and its file hash; results include both IDs. Aliasing without this mapping changes the deployed policy. Unknown mapping aliases are rejected. No source checkpoint should be modified.

Candidate IDs may be clones or may already be in the opponent pool. Candidates are never removed from opponent draws. Each candidate gets the full supplied seed list, the same sampled opponent IDs in the same seats, and the same deal seed. Every match has eight players, uses strict legal actions, and stops at the canonical 200-hand cap. A capped table is a non-win even if the hero holds the chip lead; the win-rate denominator includes every played table, including cap survivors and cap eliminations.

Before any evaluator work starts, the run directory receives `protocol.json`, byte-for-byte `seeds.json`, and `jobs.json` with the frozen ordered jobs. The protocol records candidate, training-pool, HOF-pool, complete-union, checkpoint-projection, and source fingerprints, dependency versions, namespace, seeds, game settings, and worker count. The actual tournament execution calls `pokerbot.evolution._execute_jobs`, which uses the canonical per-job adapter and tournament implementation.

The output bundle is:

- `protocol.json` and `jobs.json`: the frozen input and ordered work manifest.
- `results.csv`, `results.json`, and `report.md`: every candidate with the same sample count, provenance, rank, wins/losses, cap outcomes, Wilson 95% interval, mean points/finish/chips, invalid-action counts, and policy latency metrics.
- `paired-comparisons.json`: per-seed candidate-minus-reference differences and deterministic descriptive paired bootstrap intervals. The reference defaults to the first candidate in input order; override it with `--reference-id`.
- `COMPLETE.json`: hashes of the final reports and frozen inputs. Its presence marks successful completion.

The source and dependency fingerprints are checked again after evaluation; a change leaves the comparison incomplete. Operators must independently verify that their supplied fresh seeds have not appeared in historical runs. The namespace is recorded as provenance, rather than used to replace the supplied seed values.

## How to read the results

Equal-sample rankings remain noisy at finite sample sizes, including 128-match samples. Wilson intervals and paired percentile-bootstrap intervals are descriptive. The bootstrap intervals receive no multiple-test adjustment and make no superiority or target claim. Timing values may differ across worker counts or machines; output row ordering, seeds, seat assignments, and non-timing calculations are deterministic.

Changing the supplied training + HOF pool changes the estimand because it changes the opponent distribution. Candidate IDs influence deployed policy randomness, so paired effects compare complete ID-specific policies and do not isolate gene changes. These are training-only comparisons; held-out evaluation is still required before making a performance or promotion decision.
