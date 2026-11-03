# Evolution 90 run log

## Frozen protocol

- Snapshot commit: `fa75bece158eb87224585f148e2eca3d5f6f3d2e` (`fa75bec`).
- Snapshot archive SHA-256: `c43346b082cebbb6dfada41e7c43bf71ad2945400b481edf56ac5c339a0f4fac`.
- Engine code fingerprint: `0a95799fcaee8798b8cf29aee7c8019747276e8ac581d46d53b7aaffa863b818`; source hashes for all 44 fingerprinted package/model/data files: [source manifest](../../.work/evolution-90-run-20261103/source-manifest.json).
- Runtime: Python `3.12.10`, PokerKit `0.7.7`. Run snapshot: [source](../../.work/evolution-90-run-20261103/src).
- Seed input: [original search seeds](../evolution-90-search-20261103/selected-seeds.json); [compatible seed list](../../.work/evolution-90-run-20261103/selected-seeds-compatible.json). The conversion omits only `anchor-saved`, which is already a fixed anchor and fails the runner's duplicate-ID validator. The remaining six canonical genomes were accepted unchanged.
- Experiment: eight-player tables; population 16; 128 training matches per candidate; 128 validation matches; 512 confirmation matches; target `>0.90` observed validation win rate and fresh exact confirmation bound; adaptive fraction `0.5`; seed `20261103`; three worker processes. Capped tables count as non-wins.

## Resume command

Run one generation at a time, adding `--resume` after the first successful generation:

```sh
/Users/benajaheger/Documents/museum\ of\ failures/Pokerbot/.venv/bin/python -m pokerbot.evolution run \
  --output-dir /Users/benajaheger/Documents/museum\ of\ failures/Pokerbot/reports/evolution-90-run-20261103 \
  --population 16 --generations 1 --resume \
  --target-win-rate 0.90 --adaptive-fraction 0.5 \
  --archive-checkpoint /Users/benajaheger/Documents/museum\ of\ failures/Pokerbot/reports/evolution-next-20261102/checkpoint.json \
  --archive-checkpoint /Users/benajaheger/Documents/museum\ of\ failures/Pokerbot/reports/evolution-v4/checkpoint.json \
  --seed-genomes /Users/benajaheger/Documents/museum\ of\ failures/Pokerbot/.work/evolution-90-run-20261103/selected-seeds-compatible.json \
  --evaluation-namespace evolution-90-run-20261103 \
  --matches 128 --validation-matches 128 --confirmation-matches 512 \
  --seed 20261103 --workers 3
```

## Generations


## Execution stopped before generation 0001

No training, validation, or confirmation batch completed. The canonical runner rejected the archive while constructing its initial checkpoint because `train-opponent-0000` conflicts with a fixed genome ID. Per the run instructions, no source changes or retries were made.

```text
Traceback (most recent call last):
  File "<frozen runpy>", line 198, in _run_module_as_main
  File "<frozen runpy>", line 88, in _run_code
  File "/Users/benajaheger/Documents/museum of failures/Pokerbot/.work/evolution-90-run-20261103/src/pokerbot/evolution.py", line 1681, in <module>
    raise SystemExit(main())
                     ^^^^^^
  File "/Users/benajaheger/Documents/museum of failures/Pokerbot/.work/evolution-90-run-20261103/src/pokerbot/evolution.py", line 1665, in main
    runner = EvolutionRunner(args.output_dir, config, resume=args.resume, workers=args.workers)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/benajaheger/Documents/museum of failures/Pokerbot/.work/evolution-90-run-20261103/src/pokerbot/evolution.py", line 1007, in __init__
    self.state = _init_checkpoint(self.config, self.code_fingerprint)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/benajaheger/Documents/museum of failures/Pokerbot/.work/evolution-90-run-20261103/src/pokerbot/evolution.py", line 692, in _init_checkpoint
    raise ValueError(f"archive genome ID conflicts with a fixed genome: {bot_id}")
ValueError: archive genome ID conflicts with a fixed genome: train-opponent-0000
```

## Retry from the fixed snapshot

The initial `fa75bec` snapshot and failed attempt artifacts are preserved as
`.work/evolution-90-run-20261103/src-attempt1`,
`.work/evolution-90-run-20261103/source-manifest-attempt1.json`, and
`.work/evolution-90-run-20261103/generation-0001-attempt1.log`. No checkpoint
was present in the output directory before this retry.

- Snapshot commit: `00ac00ee93b7aa4176a007b5ba1a1f113948eed7`.
- Snapshot archive SHA-256: `c1fdffe56a41c094d1f6c22296ffd5cb923acb033045bc4f9568d1ac53a8d5a4`.
- Engine code fingerprint: `5056671b239e281b3680a4fe5e9410424708a9ae353c24ec17b595873eaf8e7e`.
- Source hashes: [retry source manifest](../../.work/evolution-90-run-20261103/source-manifest.json).
- Runtime: Python `3.12.10`, PokerKit `0.7.7`.

The fresh run command is:

```sh
cd "/Users/benajaheger/Documents/museum of failures/Pokerbot/.work/evolution-90-run-20261103/src"
"/Users/benajaheger/Documents/museum of failures/Pokerbot/.venv/bin/python" -m pokerbot.evolution run \
  --output-dir "/Users/benajaheger/Documents/museum of failures/Pokerbot/reports/evolution-90-run-20261103" \
  --population 16 --generations 1 \
  --target-win-rate 0.90 --adaptive-fraction 0.5 \
  --archive-checkpoint "/Users/benajaheger/Documents/museum of failures/Pokerbot/reports/evolution-next-20261102/checkpoint.json" \
  --archive-checkpoint "/Users/benajaheger/Documents/museum of failures/Pokerbot/reports/evolution-v4/checkpoint.json" \
  --seed-genomes "/Users/benajaheger/Documents/museum of failures/Pokerbot/.work/evolution-90-run-20261103/selected-seeds-compatible.json" \
  --evaluation-namespace evolution-90-run-20261103 \
  --matches 128 --validation-matches 128 --confirmation-matches 512 \
  --seed 20261103 --workers 3
```

For each later chunk, repeat these options with `--generations 1 --resume`.

## Generations

### Generation 1

- Best training bot: `r90-cal-19`, 29/128 outright wins = `0.2266`.
- Round report with results for all 16 evaluated bots and 7 unplayed offspring: [round-0001.md](round-0001.md).
- Births: 7 offspring. Kills: 7 eliminated bots. Capped tables: 0.
- Validation: none of the three tested leaders passed. `r90-cal-19` 39/128 (`0.3047`); `r90-evo-06` 27/128 (`0.2109`); `r90-evo-02` 28/128 (`0.2188`).
- Confirmation: not run; no candidate cleared validation. Engine status: `target_not_reached`; no target promotion.

### Generation 2

- Best training bot: `evo-g0001-0002`, 27/128 outright wins = `0.2109`.
- Round report with results for all 16 evaluated bots and 7 unplayed offspring: [round-0002.md](round-0002.md).
- Births: 7 offspring. Kills: 7 eliminated bots. Capped tables: 2 (counted as non-wins).
- Validation: none of the three tested leaders passed. `evo-g0001-0002` 38/128 (`0.2969`); `r90-ada-12` 34/128 (`0.2656`); `r90-evo-06` 43/128 (`0.3359`).
- Confirmation: not run; no candidate cleared validation. Engine status: `target_not_reached`; no target promotion.

### Generation 3

- Best training bot: `anchor-saved`, 30/128 outright wins = `0.2344`.
- Round report with results for all 16 evaluated bots and 7 unplayed offspring: [round-0003.md](round-0003.md).
- Births: 7 offspring. Kills: 7 eliminated bots. Capped tables: 1 (counted as a non-win).
- Validation: none of the three tested leaders passed. `anchor-saved` 38/128 (`0.2969`); `evo-g0001-0001` 43/128 (`0.3359`); `evo-g0002-0001` 35/128 (`0.2734`).
- Confirmation: not run; no candidate cleared validation. Engine status: `target_not_reached`; no target promotion.

### Generation 4

- Best training bot: `r90-cal-22`, 36/128 outright wins = `0.2813`.
- Round report with results for all 16 evaluated bots and 7 unplayed offspring: [round-0004.md](round-0004.md).
- Births: 7 offspring. Kills: 7 eliminated bots. Capped tables: 0.
- Validation: none of the three tested leaders passed. `r90-cal-22` 34/128 (`0.2656`); `evo-g0002-0004` 36/128 (`0.2813`); `evo-g0002-0002-2` 30/128 (`0.2344`).
- Confirmation: not run; no candidate cleared validation. Engine status: `target_not_reached`; no target promotion.

### Generation 5

- Best training bot: `r90-evo-06`, 28/128 outright wins = `0.2188`.
- Round report with results for all 16 evaluated bots and 7 unplayed offspring: [round-0005.md](round-0005.md).
- Births: 7 offspring. Kills: 7 eliminated bots. Capped tables: 0.
- Validation: none of the three tested leaders passed. `r90-evo-06` 35/128 (`0.2734`); `evo-g0001-0001` 33/128 (`0.2578`); `evo-g0004-0001` 33/128 (`0.2578`).
- Confirmation: not run; no candidate cleared validation. Engine status: `target_not_reached`; no target promotion.

### Generation 6

- Best training bot: `evo-g0002-0004`, 29/128 outright wins = `0.2266`.
- Round report with results for all 16 evaluated bots and 7 unplayed offspring: [round-0006.md](round-0006.md).
- Births: 7 offspring. Kills: 7 eliminated bots. Capped tables: 1 (counted as a non-win).
- Validation: none of the three tested leaders passed. `evo-g0002-0004` 37/128 (`0.2891`); `r90-evo-06` 39/128 (`0.3047`); `r90-cal-22` 34/128 (`0.2656`).
- Confirmation: not run; no candidate cleared validation. Engine status: `target_not_reached`; no target promotion.

### Generation 7

- Best training bot: `anchor-saved`, 27/128 outright wins = `0.2109`.
- Round report with results for all 16 evaluated bots and 7 unplayed offspring: [round-0007.md](round-0007.md).
- Births: 7 offspring. Kills: 7 eliminated bots. Capped tables: 1 (counted as a non-win).
- Validation: none of the three tested leaders passed. `anchor-saved` 39/128 (`0.3047`); `evo-g0006-0001-1` 29/128 (`0.2266`); `evo-g0006-0002-1` 30/128 (`0.2344`).
- Confirmation: not run; no candidate cleared validation. Engine status: `target_not_reached`; no target promotion.

### Generation 8

- Best training bot: `r90-cal-22`, 32/128 outright wins = `0.2500`.
- Round report with results for all 16 evaluated bots and 7 unplayed offspring: [round-0008.md](round-0008.md).
- Births: 7 offspring. Kills: 7 eliminated bots. Capped tables: 2 (counted as non-wins).
- Validation: none of the three tested leaders passed. `r90-cal-22` 36/128 (`0.2813`); `evo-g0007-0002-1` 42/128 (`0.3281`); `anchor-saved` 31/128 (`0.2422`).
- Confirmation: not run; no candidate cleared validation. Engine status: `target_not_reached`; no target promotion.

### Generation 9

- Best training bot: `evo-g0008-0005`, 30/128 outright wins = `0.2344`.
- Round report with results for all 16 evaluated bots and 7 unplayed offspring: [round-0009.md](round-0009.md).
- Births: 7 offspring. Kills: 7 eliminated bots. Capped tables: 0.
- Validation: none of the three tested leaders passed. `evo-g0008-0005` 34/128 (`0.2656`); `r90-cal-22` 42/128 (`0.3281`); `anchor-saved` 41/128 (`0.3203`).
- Confirmation: not run; no candidate cleared validation. Engine status: `target_not_reached`; no target promotion.

### Generation 10

- Best training bot: `evo-g0006-0002-1`, 27/128 outright wins = `0.2109`.
- Round report with results for all 16 evaluated bots and 7 unplayed offspring: [round-0010.md](round-0010.md).
- Births: 7 offspring. Kills: 7 eliminated bots. Capped tables: 0.
- Validation: none of the three tested leaders passed. `evo-g0006-0002-1` 40/128 (`0.3125`); `evo-g0008-0005` 33/128 (`0.2578`); `evo-g0009-0005` 44/128 (`0.3438`).
- Confirmation: not run; no candidate cleared validation. Engine status: `target_not_reached`; no target promotion.

### Generation 11

- Best training bot: `evo-g0008-0005`, 28/128 outright wins = `0.2188`.
- Round report with results for all 16 evaluated bots and 7 unplayed offspring: [round-0011.md](round-0011.md).
- Births: 7 offspring. Kills: 7 eliminated bots. Capped tables: 0.
- Validation: none of the three tested leaders passed. `evo-g0008-0005` 35/128 (`0.2734`); `evo-g0008-0004` 38/128 (`0.2969`); `anchor-saved` 33/128 (`0.2578`).
- Confirmation: not run; no candidate cleared validation. Engine status: `target_not_reached`; no target promotion.

### Generation 12

- Best training bot: `evo-g0011-0001`, 27/128 outright wins = `0.2109`.
- Round report with results for all 16 evaluated bots and 7 unplayed offspring: [round-0012.md](round-0012.md).
- Births: 7 offspring. Kills: 7 eliminated bots. Capped tables: 0.
- Validation: none of the three tested leaders passed. `evo-g0011-0001` 35/128 (`0.2734`); `r90-cal-22` 29/128 (`0.2266`); `evo-g0006-0002-1` 43/128 (`0.3359`).
- Confirmation: not run; no candidate cleared validation. Engine status: `target_not_reached`; no target promotion.


## Run closed after generation 12

Generation 13 was in training when every delegated agent in the environment
was interrupted at about 17:12 local time (2026-11-03). Its worker processes
died. The checkpoint still marks generation 13 as in flight, so the run is
resumable with the command above. It was intentionally not resumed. This
run imports a large evolved archive into its training pool, but the
validation and confirmation pools contain only the five anchors and
`new_random` genomes. Its training fitness therefore tracks the wrong
opponents. The follow-up run `reports/evolution-exploit-run-20261103/` uses
no archive and is seeded with the exploit families.

| Gen | Best training bot (wins/128) | Best tested leader on validation (wins/128) | Confirmation |
|---:|---|---|---|
| 1 | `r90-cal-19` 29 | `r90-cal-19` 39 | not run |
| 2 | `evo-g0001-0002` 27 | `r90-evo-06` 43 | not run |
| 3 | `anchor-saved` 30 | `evo-g0001-0001` 43 | not run |
| 4 | `r90-cal-22` 36 | `evo-g0002-0004` 36 | not run |
| 5 | `r90-evo-06` 28 | `r90-evo-06` 35 | not run |
| 6 | `evo-g0002-0004` 29 | `r90-evo-06` 39 | not run |
| 7 | `anchor-saved` 27 | `anchor-saved` 39 | not run |
| 8 | `r90-cal-22` 32 | `evo-g0007-0002-1` 42 | not run |
| 9 | `evo-g0008-0005` 30 | `r90-cal-22` 42 | not run |
| 10 | `evo-g0006-0002-1` 27 | `evo-g0009-0005` 44 | not run |
| 11 | `evo-g0008-0005` 28 | `evo-g0008-0004` 38 | not run |
| 12 | `evo-g0011-0001` 27 | `evo-g0006-0002-1` 43 | not run |

The best single validation result was 44/128 (34.4%). No leader came near
the 90% validation threshold, so the fresh confirmation gate never ran. No
90% result is claimed.

The per-round raw JSON files are stored as `round-NNNN.json.gz` (gzip of the
original JSON) to keep the repository small. The Markdown and CSV round
reports are unchanged.
