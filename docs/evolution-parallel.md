# Optional persistent-pool evolution driver

`scripts/evolve_parallel.py` runs the canonical evolution optimizer with one
scoped `ProcessPoolExecutor` shared across training, validation, confirmation,
and all generations in one command invocation. It inherits population changes,
fresh seed reservations, frozen opponent pools, checkpoint writes, and the
target confirmation gate from `pokerbot.evolution.EvolutionRunner`. Only
tournament-job scheduling is overridden. `executor.map` keeps results in
reserved-job order, and the canonical simulator and table configuration are
used for every job.

## Start an isolated fresh run

This example writes a new two-generation trajectory under its own output
directory. It leaves an existing evolution output directory untouched.

```sh
.venv/bin/python scripts/evolve_parallel.py run \
  --output-dir reports/evolution-audits/parallel-runner-fresh-20261102 \
  --generations 2 \
  --population 8 \
  --matches 8 \
  --validation-matches 32 \
  --confirmation-matches 128 \
  --seed 20261103 \
  --evaluation-namespace parallel-runner-fresh-20261102 \
  --workers 2 \
  --chunksize 4
```

The parser shares the canonical run options. `--workers` defaults to 2 in this
driver. `--chunksize` defaults to 4 and accepts values from 1 through 64.
`ProcessPoolExecutor.map` retains the original job order for every value.

To continue after interruption, repeat the same command options and add
`--resume`. Keep the same driver source, worker count, chunksize, and evolution
configuration. `--generations` can change because it controls the size of this
invocation's chunk, not the saved evolution configuration. Resume uses the
canonical checkpoint checks and rejects a missing or incompatible parallel
execution record before changing checkpoint state.

Each run directory has an append-only
`parallel-execution-provenance.jsonl`. Each invocation records the driver
source SHA-256, canonical configuration SHA-256, worker count, chunksize,
Python version, executor type, and ordered-result contract. Resume rejects a
different driver hash or execution settings. The source hash check is exact,
so editing even a nonbehavioral part of the driver requires a new output
directory or a deliberate provenance migration.

## Throughput measurement

The training-only measurement is recorded in
[`parallel-runner-throughput-20261102.json`](../reports/evolution-audits/parallel-runner-throughput-20261102.json).
Its driver and benchmark script hashes and measurement settings are recorded
in the append-only
[`parallel-runner-throughput-provenance.jsonl`](../reports/evolution-audits/parallel-runner-throughput-provenance.jsonl).
It used two workers, 2,000 starting chips, the standard blind schedule, and a
200-hand cap. One scenario had four training batches of eight tables with
fresh reservations and a fixed candidate set, to measure repeated pool setup.
A second scenario ran one 32-table batch. Canonical and accelerated runs
reserved matching training jobs; ordered outcomes matched after excluding
runtime and latency fields. No validation or confirmation jobs were
evaluated, and no held-out results were inspected.

| Measurement | Canonical pool | Persistent pool |
| --- | ---: | ---: |
| Four 8-table training batches | 4.677 s | 4.343 s |
| Repeated-batch throughput | 6.84 tables/s | 7.37 tables/s |
| Median of batches after first | 1.195 s | 1.116 s |
| First 8-table batch | 1.084 s | 1.124 s |
| Executor object construction | Included per batch | 0.00013 s |
| Pool shutdown | Included per batch | 0.0169 s |
| One 32-table batch | 4.035 s | 4.114 s |

The recorded repeated-batch speedup was 1.077x, a 7.1% reduction in elapsed
batch time. The single 32-table batch was 2.0% slower with the persistent driver.
This indicates a small benefit when a run has repeated batches and no measured
benefit for this single-batch case. Process startup is lazy, so the first
persistent batch includes worker startup; executor-object construction alone
is not the full pool setup cost. An earlier exploratory run using the same
repeated-batch setup took 7.394 s canonical and 6.934 s persistent, showing
substantial absolute wall-time variation across runs. Treat the observed gains
as sensitive to host load; table runtime and contention can dominate pool
setup. Full breeding dynamics are outside this timing setup. The reproducible timing script is
`.work/parallel-runner-benchmark-20261102.py`.

## Safety and resume behavior

The pool exists only inside `PersistentPoolRunner.run()` and shuts down in a
`finally` path, including when a worker raises. The driver does not patch
canonical module globals. A failed batch leaves the canonical durable seed
reservation in the checkpoint; a later resume follows canonical behavior and
retries the in-flight generation with fresh reserved seeds. The inherited
confirmation gate remains the only path to promoting a champion.
