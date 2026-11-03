# Endgame paired proxy results

All runs use the default 8-player, 2,000-chip, 20/40 doubling blind schedule,
25 hands per level, a 200-hand cap, and strict action validation. Each arm
played 256 tables for each matched proxy pool/evaluation domain. The 3,072
seeded tournament records are in [paired-results.json](paired-results.json).
The two workers used 720.61 seconds wall time. Capped tables count as
non-wins. Intervals are per-arm 95% Wilson intervals; paired differences and
switch counts use identical opponent samples, seats, and seeds.

## proxy-heldout-pool-v1 / proxy-heldout-eval-v1

| Candidate | Base wins (95% Wilson) | Wrapped wins (95% Wilson) | Paired net wins | Base loss → wrapped win | Base win → wrapped loss | Invalid actions, base / wrapped | Mean decision latency, base → wrapped (ms) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Saved | 73/256, 28.5% [23.3%, 34.3%] | 79/256, 30.9% [25.5%, 36.8%] | +6 | 50 | 44 | 0 / 0 | 0.1185 → 0.1013 |
| r90-ada-14 | 67/256, 26.2% [21.2%, 31.9%] | 77/256, 30.1% [24.8%, 36.0%] | +10 | 47 | 37 | 0 / 0 | 0.1047 → 0.0951 |
| r90-evo-02 | 64/256, 25.0% [20.1%, 30.6%] | 73/256, 28.5% [23.3%, 34.3%] | +9 | 54 | 45 | 0 / 0 | 0.0744 → 0.0856 |

## proxy-heldout-pool-v2 / proxy-heldout-eval-v2

| Candidate | Base wins (95% Wilson) | Wrapped wins (95% Wilson) | Paired net wins | Base loss → wrapped win | Base win → wrapped loss | Invalid actions, base / wrapped | Mean decision latency, base → wrapped (ms) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Saved | 59/256, 23.0% [18.3%, 28.6%] | 70/256, 27.3% [22.2%, 33.1%] | +11 | 41 | 30 | 0 / 0 | 0.1235 → 0.1053 |
| r90-ada-14 | 68/256, 26.6% [21.5%, 32.3%] | 78/256, 30.5% [25.2%, 36.4%] | +10 | 50 | 40 | 0 / 0 | 0.0949 → 0.0861 |
| r90-evo-02 | 50/256, 19.5% [15.1%, 24.8%] | 81/256, 31.6% [26.3%, 37.6%] | +31 | 54 | 23 | 0 / 0 | 0.0534 → 0.0604 |

The overlay produced a positive paired net win count for all three tested
candidates on both separate proxy pools. These development samples do not
establish a 90% win rate; the observed rates remain between 19.5% and 31.6%.
Across the arms, mean per-decision latency was 0.053–0.124 ms. The largest
single observed decision latency ranged from 0.597 to 8.484 ms in the shared
worker environment.
