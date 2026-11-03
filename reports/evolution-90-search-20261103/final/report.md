# Evolution candidate comparison (training only)

**Status: comparison_only.** This is an experimental equal-sample comparison, not a promotion gate, superiority claim, or target test.

- Namespace: `racer-evolution-90search-final-20261103-v1`
- Seeds: 128 supplied unchanged; SHA-256 `70e926ecdf03eebd462c0c1a7e2f67c1afbaacc1c70792fcad847bb0715d7774`
- Opponent pool: 76 complete training + HOF IDs; SHA-256 `8b53e5a9bcc1c9140fdbe3114f8e7b5e20f9143e52a195b2d79f8aebaf22faaa`
- Reference for paired differences: `anchor-saved`
- Source fingerprint: `65a62efc94bf60db53770c6cdd34048f72fa558a31cf978de645775b5fc33c01`

Every candidate receives the same seeded opponent IDs, seats, and deal stream. All matches use eight players, strict legal actions, and a 200-hand cap. Any capped table is a non-win even when the hero has the chip lead; win rate uses every played table as its denominator.

| Rank | Candidate | Original policy ID | Generation | Family | Parents | Parameters | Played | Won | Lost | Cap survivors | Table caps | Win rate | Wilson 95% | Mean points | Mean finish | Mean chips | Invalid actions / decisions | Invalid rate | Latency mean / p95 / max ms | Status |
|---:|---|---|---:|---|---|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---|---:|---|---|
| 1 | `r90-ada-14` | `r90-ada-14` | 4 | adaptive | `evolution-next-g0000-variant-01-evolved`, `evo-g0003-0000` | `{"bet_size":0.167277,"bluff_frequency":0.017033,"call_frequency":1.0,"call_margin":-0.030182,"multiway_penalty":0.05305,"opening_frequency":0.91387,"opening_shift":-0.09685,"position_sensitivity":0.0235,"postflop_call_margin":0.034554,"raise_frequency":1.0,"short_stack_bb":13.007457,"short_stack_cutoff":0.715807,"value_raise_threshold":0.603034}` | 128 | 26 | 102 | 0 | 0 | 0.2031 | 0.1426–0.2810 | 4.4531 | 4.546875 | 3250.00 | 0 / 22046 | 0.000000 | 0.056178714460673136 / 0.207417 / 1.699666 | comparison_only |
| 2 | `r90-evo-02` | `r90-evo-02` | 4 | evolved | `evo-g0003-0000`, `evo-g0002-0002-1` | `{"bet_size":0.18,"bluff_frequency":0.011771,"call_frequency":1.0,"call_margin":-0.030182,"multiway_penalty":0.057113,"opening_frequency":0.822765,"opening_shift":-0.09685,"position_sensitivity":0.028423,"postflop_call_margin":0.040286,"raise_frequency":0.829867,"short_stack_bb":9.39448,"short_stack_cutoff":0.7476,"value_raise_threshold":0.563187}` | 128 | 23 | 105 | 0 | 0 | 0.1797 | 0.1228–0.2552 | 4.5391 | 4.4609375 | 2875.00 | 0 / 21994 | 0.000000 | 0.03437281344912249 / 0.140042 / 1.020333 | comparison_only |
| 3 | `r90-cal-19` | `r90-cal-19` | 7 | calibrated | `evo-g0006-0004`, `evo-g0005-0002` | `{"bet_size":0.15,"bluff_frequency":0.0,"call_frequency":0.978,"call_margin":0.031368,"multiway_penalty":0.09567,"opening_frequency":1.0,"opening_shift":-0.09685,"position_sensitivity":0.030218,"postflop_call_margin":0.034554,"raise_frequency":0.753161,"short_stack_bb":9.39448,"short_stack_cutoff":0.621988,"value_raise_threshold":0.584105}` | 128 | 20 | 108 | 0 | 0 | 0.1562 | 0.1035–0.2290 | 4.7031 | 4.296875 | 2500.00 | 0 / 23343 | 0.000000 | 0.06521218549458081 / 0.3845 / 7.819417 | comparison_only |
| 4 | `r90-evo-06` | `r90-evo-06` | 4 | evolved | `evolution-next-g0000-variant-01-evolved`, `evo-g0003-0000` | `{"bet_size":0.719808,"bluff_frequency":0.050522,"call_frequency":1.0,"call_margin":0.002881,"multiway_penalty":0.05305,"opening_frequency":0.91387,"opening_shift":-0.071048,"position_sensitivity":0.023841,"postflop_call_margin":0.039515,"raise_frequency":1.0,"short_stack_bb":12.099221,"short_stack_cutoff":0.715807,"value_raise_threshold":0.603034}` | 128 | 20 | 108 | 0 | 0 | 0.1562 | 0.1035–0.2290 | 4.3516 | 4.6484375 | 2500.00 | 0 / 20725 | 0.000000 | 0.033981522026537994 / 0.167375 / 0.221584 | comparison_only |
| 5 | `r90-ada-12` | `r90-ada-12` | 5 | adaptive | `evo-g0004-0005@next`, `evo-g0003-0000` | `{"bet_size":0.15,"bluff_frequency":0.0,"call_frequency":1.0,"call_margin":-0.017295,"multiway_penalty":0.05305,"opening_frequency":0.902142,"opening_shift":-0.107273,"position_sensitivity":0.025478,"postflop_call_margin":0.034554,"raise_frequency":0.665875,"short_stack_bb":9.870917,"short_stack_cutoff":0.7476,"value_raise_threshold":0.603034}` | 128 | 18 | 110 | 0 | 0 | 0.1406 | 0.0908–0.2114 | 4.2344 | 4.765625 | 2250.00 | 0 / 22951 | 0.000000 | 0.06209544237723846 / 0.2365 / 4.126167 | comparison_only |
| 6 | `r90-cal-22` | `r90-cal-22` | 4 | calibrated | `evolution-next-g0000-variant-01-evolved`, `evo-g0003-0000` | `{"bet_size":0.167277,"bluff_frequency":0.0,"call_frequency":1.0,"call_margin":0.000381,"multiway_penalty":0.05305,"opening_frequency":0.91387,"opening_shift":-0.09685,"position_sensitivity":0.026627,"postflop_call_margin":0.046953,"raise_frequency":1.0,"short_stack_bb":11.008681,"short_stack_cutoff":0.715807,"value_raise_threshold":0.56}` | 128 | 16 | 112 | 0 | 0 | 0.1250 | 0.0784–0.1934 | 4.3438 | 4.65625 | 2000.00 | 0 / 21914 | 0.000000 | 0.06444414141644611 / 0.479417 / 29.579333 | comparison_only |
| 7 | `anchor-saved` | `anchor-saved` | 0 | saved | — | `{}` | 128 | 14 | 114 | 0 | 0 | 0.1094 | 0.0663–0.1752 | 4.8672 | 4.1328125 | 1750.00 | 0 / 22115 | 0.000000 | 0.06222160090436356 / 0.231208 / 4.211084 | comparison_only |

## Paired differences

Intervals are descriptive paired percentile-bootstrap intervals (2000 resamples, nominal 95%). No multiple-test adjustment or target claim is made. Candidate IDs affect deployed policy randomness, so paired effects do not isolate gene changes.

| Candidate | Reference | Win-rate difference | 95% interval | Mean points difference | 95% interval |
|---|---|---:|---|---:|---|
| `anchor-saved` | `anchor-saved` | 0.0000 | 0.0000–0.0000 | 0.0000 | 0.0000–0.0000 |
| `r90-ada-12` | `anchor-saved` | 0.0312 | -0.0469–0.1094 | -0.6328 | -1.0781–-0.1797 |
| `r90-ada-14` | `anchor-saved` | 0.0938 | 0.0156–0.1719 | -0.4141 | -0.8594–0.0469 |
| `r90-cal-19` | `anchor-saved` | 0.0469 | -0.0312–0.1328 | -0.1641 | -0.6250–0.2969 |
| `r90-cal-22` | `anchor-saved` | 0.0156 | -0.0625–0.0938 | -0.5234 | -0.9768–-0.0469 |
| `r90-evo-02` | `anchor-saved` | 0.0703 | -0.0156–0.1562 | -0.3281 | -0.7814–0.1018 |
| `r90-evo-06` | `anchor-saved` | 0.0469 | -0.0391–0.1328 | -0.5156 | -1.0234–-0.0469 |

## Limits

Equal-sample rankings remain noisy at finite sample sizes. Changing the training + HOF source pool changes the estimand. Candidate IDs also influence policy randomness, so this paired design does not isolate gene effects. These training-only results do not replace held-out evaluation; independent held-out evaluation is still required before any performance or promotion decision.
