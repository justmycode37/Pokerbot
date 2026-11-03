# Evolution 90 search: training-only seed proposals

**Status:** canonical training-only screen and fresh training comparison completed. This bundle does not confirm or claim a 90% outright match-win rate. The strongest finalist won 26 of 128 matches (20.3%; Wilson 95% 14.3–28.1%).

## Protocol

- Runtime source snapshot: `.work/evolution-90-search-20261103/source`; source fingerprint `65a62efc94bf60db53770c6cdd34048f72fa558a31cf978de645775b5fc33c01`; Python `3.12.10`; PokerKit `0.7.7`.
- Runtime included 48 fingerprinted package/model/equity files. The calibrated model hash is `7dd0457e02c5bf5d3e3d1c9f06b4f3d043c7343a068092b23c3c3bb6ad6e48fd`.
- Canonical evaluator: eight players, 200-hand maximum, strict legal actions, standard stack/blind schedule. Two simulation workers were used.
- Opponents: complete frozen union of 76 IDs (21 training-opponent identities and 60 HOF identities, with overlap retained); original archived policy IDs were restored. Pool SHA-256: `8b53e5a9bcc1c9140fdbe3114f8e7b5e20f9143e52a195b2d79f8aebaf22faaa`.
- Screen: 24 bounded variants (8 evolved, 8 adaptive, 8 calibrated) plus six anchors; 32 fresh common seeds per candidate (960 tables).
- Fresh finalist comparison: seven candidates (two per parameterized family plus `anchor-saved`); 128 new common seeds per candidate (896 tables). Screen and final seed sets are disjoint, stored unchanged in each racer run.
- Any capped table is a non-win, including a chip lead. Every table is in its candidate denominator; final `won + lost = played` for every candidate.

## Final training comparison

| Rank | Candidate | Family | Played | Won | Lost | Cap survivors | Capped tables | Win rate | Wilson 95% | Mean points | Mean finish | Mean chips | Invalid actions / decisions | Invalid rate | Parameters |
|---:|---|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---|
| 1 | `r90-ada-14` | adaptive | 128 | 26 | 102 | 0 | 0 | 0.2031 | 14.3–28.1% | 4.453 | 4.547 | 3250.0 | 0 / 22046 | 0.000000 | `{"bet_size":0.167277,"bluff_frequency":0.017033,"call_frequency":1.0,"call_margin":-0.030182,"multiway_penalty":0.05305,"opening_frequency":0.91387,"opening_shift":-0.09685,"position_sensitivity":0.0235,"postflop_call_margin":0.034554,"raise_frequency":1.0,"short_stack_bb":13.007457,"short_stack_cutoff":0.715807,"value_raise_threshold":0.603034}` |
| 2 | `r90-evo-02` | evolved | 128 | 23 | 105 | 0 | 0 | 0.1797 | 12.3–25.5% | 4.539 | 4.461 | 2875.0 | 0 / 21994 | 0.000000 | `{"bet_size":0.18,"bluff_frequency":0.011771,"call_frequency":1.0,"call_margin":-0.030182,"multiway_penalty":0.057113,"opening_frequency":0.822765,"opening_shift":-0.09685,"position_sensitivity":0.028423,"postflop_call_margin":0.040286,"raise_frequency":0.829867,"short_stack_bb":9.39448,"short_stack_cutoff":0.7476,"value_raise_threshold":0.563187}` |
| 3 | `r90-cal-19` | calibrated | 128 | 20 | 108 | 0 | 0 | 0.1562 | 10.3–22.9% | 4.703 | 4.297 | 2500.0 | 0 / 23343 | 0.000000 | `{"bet_size":0.15,"bluff_frequency":0.0,"call_frequency":0.978,"call_margin":0.031368,"multiway_penalty":0.09567,"opening_frequency":1.0,"opening_shift":-0.09685,"position_sensitivity":0.030218,"postflop_call_margin":0.034554,"raise_frequency":0.753161,"short_stack_bb":9.39448,"short_stack_cutoff":0.621988,"value_raise_threshold":0.584105}` |
| 4 | `r90-evo-06` | evolved | 128 | 20 | 108 | 0 | 0 | 0.1562 | 10.3–22.9% | 4.352 | 4.648 | 2500.0 | 0 / 20725 | 0.000000 | `{"bet_size":0.719808,"bluff_frequency":0.050522,"call_frequency":1.0,"call_margin":0.002881,"multiway_penalty":0.05305,"opening_frequency":0.91387,"opening_shift":-0.071048,"position_sensitivity":0.023841,"postflop_call_margin":0.039515,"raise_frequency":1.0,"short_stack_bb":12.099221,"short_stack_cutoff":0.715807,"value_raise_threshold":0.603034}` |
| 5 | `r90-ada-12` | adaptive | 128 | 18 | 110 | 0 | 0 | 0.1406 | 9.1–21.1% | 4.234 | 4.766 | 2250.0 | 0 / 22951 | 0.000000 | `{"bet_size":0.15,"bluff_frequency":0.0,"call_frequency":1.0,"call_margin":-0.017295,"multiway_penalty":0.05305,"opening_frequency":0.902142,"opening_shift":-0.107273,"position_sensitivity":0.025478,"postflop_call_margin":0.034554,"raise_frequency":0.665875,"short_stack_bb":9.870917,"short_stack_cutoff":0.7476,"value_raise_threshold":0.603034}` |
| 6 | `r90-cal-22` | calibrated | 128 | 16 | 112 | 0 | 0 | 0.1250 | 7.8–19.3% | 4.344 | 4.656 | 2000.0 | 0 / 21914 | 0.000000 | `{"bet_size":0.167277,"bluff_frequency":0.0,"call_frequency":1.0,"call_margin":0.000381,"multiway_penalty":0.05305,"opening_frequency":0.91387,"opening_shift":-0.09685,"position_sensitivity":0.026627,"postflop_call_margin":0.046953,"raise_frequency":1.0,"short_stack_bb":11.008681,"short_stack_cutoff":0.715807,"value_raise_threshold":0.56}` |
| 7 | `anchor-saved` | saved | 128 | 14 | 114 | 0 | 0 | 0.1094 | 6.6–17.5% | 4.867 | 4.133 | 1750.0 | 0 / 22115 | 0.000000 | `{}` |

## Seed proposal

The seed file retains all seven fresh-comparison finalists: the saved baseline, two evolved genomes, two adaptive genomes, and two calibrated genomes. Every entry was reloaded through the frozen canonical `Genome` parser before writing. These are training-only proposals; ranking and selection are noisy and do not replace the existing validation gate or independent confirmation.

| Seed order | Candidate | 128-seed wins | Win rate | Family |
|---:|---|---:|---:|---|
| 1 | `anchor-saved` | 14/128 | 0.1094 | saved |
| 2 | `r90-ada-14` | 26/128 | 0.2031 | adaptive |
| 3 | `r90-evo-02` | 23/128 | 0.1797 | evolved |
| 4 | `r90-cal-19` | 20/128 | 0.1562 | calibrated |
| 5 | `r90-evo-06` | 20/128 | 0.1562 | evolved |
| 6 | `r90-ada-12` | 18/128 | 0.1406 | adaptive |
| 7 | `r90-cal-22` | 16/128 | 0.1250 | calibrated |

Candidate IDs salt deployed policy randomness, so paired comparisons do not isolate gene effects. Archived opponent identities use their original policy IDs. The 128-seed results were used only to prepare training seeds; Wilson intervals are descriptive, with no target or superiority claim.

## Reproducible artifacts

- Screen all-candidate report: [`screen/report.md`](screen/report.md); raw per-seed outcomes: [`screen/results.json.gz`](screen/results.json.gz); frozen jobs and inputs: [`screen/jobs.json.gz`](screen/jobs.json.gz), [`screen/protocol.json`](screen/protocol.json).
- Final all-candidate report: [`final/report.md`](final/report.md); raw per-seed outcomes: [`final/results.json.gz`](final/results.json.gz); frozen jobs and inputs: [`final/jobs.json.gz`](final/jobs.json.gz), [`final/protocol.json`](final/protocol.json).
- Next-run seed genomes: [`selected-seeds.json`](selected-seeds.json). Training inputs, candidate recipes, and both seed lists are under [`inputs/`](inputs/).
- Frozen runtime source and full hash list: `.work/evolution-90-search-20261103/source` and `.work/evolution-90-search-20261103/source-manifest.json`. Full owned-file hashes and provenance are recorded in `manifest.json`.

No held-out validation or confirmation result was used to generate, rank, shortlist, or select these seed genomes.

The four largest raw files (`screen/jobs.json`, `screen/results.json`, `final/jobs.json`, `final/results.json`) are stored gzipped (`*.json.gz`) to keep the repository small; `manifest.json` lists their original uncompressed paths and hashes.
