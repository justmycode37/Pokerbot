# 90% outright win rate: consolidated results (2026-11-03)

## Bottom line

**No policy has reached 90%, and none has come close.** The best legitimate
results are about 29–36% outright wins, depending on the pool. The hand-tuned exploit genome
won 184/512 on proxy v1 (35.9%, Wilson 95% 31.9–40.2%) and 149/512 on v2
(29.1%, 25.3–33.2%). The search-selected exploit genome won 174/512 (34.0%,
30.0–38.2%), 166/512 (32.4%, 28.5–36.6%) and 170/512 (33.2%, 29.3–37.4%) on
v1, v2 and v3. The saved policy won 23–30% on the same tables. No candidate has
ever passed the 90% validation gate, so the fresh exact-binomial confirmation
has never run. A cheating oracle could see every live opponent's hole cards.
It still won only 62.5–74.2% per pool, and its best Wilson upper bound was
79.2%. This is strong empirical evidence that 90% is out of reach for a
policy that sees only public information in this tournament structure. It is
not a proof (see [Why 90% looks infeasible](#why-90-looks-infeasible)).

**Late update (stopped run, not a full report).** A stronger oracle sees
opponents' cards and every stack, and also simulates opponents' actual policy
code to predict their responses. Its "no-steals" mode won 86/96 on proxy v1
(89.6%, Wilson 95% 81.9–94.2%) and 39/49 on v2 (79.6%, 66.4–88.5%). Its main
"response-icm" mode won 104/192 on each pool (54.2%). The run was stopped
before completion. The rows are not in the repository, so treat these as
provisional. They suggest 90% is not structurally impossible with perfect
information, so the oracle bound above understates what a privileged policy
can do. Legitimate policies remain at about 30–38%.

## Rules that apply to every number

- 8-player tables, 2,000-chip stacks, blinds 20/40/80/160/320/640/1,280/2,560
  doubling every 25 hands, 200-hand cap, no antes. **Capped tables count as
  non-wins.**
- Proxy pools copy the held-out construction (5 anchors plus 16 `new_random`
  genomes, 7 opponents sampled per table) on separate seed domains
  (`proxy-heldout-pool-vN` / `proxy-heldout-eval-vN`). Within a pool, every arm
  plays identical seeds, opponents and seats, so comparisons are paired.
- The 512-table runs extend the 256-table runs: their first 256 seeds are
  identical. I checked this against the raw JSON for exploit and saved, where
  the counts match exactly (89/256, 73/256, 72/256, 59/256).
- Promotion requires more than 90% observed on validation (at least 116/128)
  and then a fresh confirmation. At the first confirmation (α = 0.0125), that
  confirmation needs **at least 476/512 wins (93.0%)**. I derived this from
  `exact_lower_bound` and `_one_sided_alpha` in `pokerbot/evolution.py`; no
  report states it.

## All evaluated approaches

Wins/tables, win rate and Wilson 95% CI, copied from the linked reports. "—" means not run.

| Approach | Proxy v1 | Proxy v2 | Report |
|---|---|---|---|
| **256-table paired runs** | | | |
| Saved (`saved-proxy-reference`) | 73/256, 28.5% (23.3–34.3) | 59/256, 23.0% (18.3–28.6) | [exploit](exploit-policy.md#final-results), [diagnostics](../reports/evolution-90-diagnostics-20261103/report.md) |
| `r90-ada-14` (archive-search finalist) | 67/256, 26.2% (21.2–31.9) | 68/256, 26.6% (21.5–32.3) | [exploit](exploit-policy.md#final-results), [endgame](../reports/endgame-20261103/results.md) |
| `r90-evo-02` (archive-search finalist) | 64/256, 25.0% (20.1–30.6) | 50/256, 19.5% (15.1–24.8) | [endgame](../reports/endgame-20261103/results.md) |
| Exploit, hand-tuned `exploit-wide-thin` | 89/256, 34.8% (29.2–40.8) | 72/256, 28.1% (23.0–33.9) | [exploit](exploit-policy.md#final-results) |
| Exploit-endgame, default genes | 76/256, 29.7% (24.4–35.6) | 70/256, 27.3% (22.2–33.1) | [exploit-endgame](../reports/exploit-endgame-20261103/report.md) |
| Exploit-endgame, HU aggression 1.25 | 79/256, 30.9% (25.5–36.8) | 73/256, 28.5% (23.3–34.3) | [exploit-endgame](../reports/exploit-endgame-20261103/report.md) |
| Saved + endgame wrapper | 79/256, 30.9% (25.5–36.8) | 70/256, 27.3% (22.2–33.1) | [endgame](../reports/endgame-20261103/results.md) |
| `r90-ada-14` + endgame wrapper | 77/256, 30.1% (24.8–36.0) | 78/256, 30.5% (25.2–36.4) | [endgame](../reports/endgame-20261103/results.md) |
| `r90-evo-02` + endgame wrapper | 73/256, 28.5% (23.3–34.3) | 81/256, 31.6% (26.3–37.6) | [endgame](../reports/endgame-20261103/results.md) |
| **512-table runs (exploit gene search)** | | | |
| Exploit, hand-tuned `exploit-wide-thin` | 184/512, 35.9% (31.9–40.2) | 149/512, 29.1% (25.3–33.2) | [search](../reports/exploit-search-20261103/report.md) |
| Exploit, search-selected (`finalist-01`) | 174/512, 34.0% (30.0–38.2) | 166/512, 32.4% (28.5–36.6) | [search](../reports/exploit-search-20261103/report.md) |
| Saved (`saved-proxy-reference`) | 153/512, 29.9% (26.1–34.0) | 139/512, 27.1% (23.5–31.2) | [search](../reports/exploit-search-20261103/report.md) |
| **CHEATING: sees live opponents' hole cards (not legal policies)** | | | |
| Oracle: hole-card chip-EV heuristic | 160/256, 62.5% (56.4–68.2) | 190/256, 74.2% (68.5–79.2) | [ceiling](../reports/evolution-90-ceiling-20261103/report.md) |
| Oracle: hole-card leader-aware, also sees all stacks | 173/256, 67.6% (61.6–73.0) | 172/256, 67.2% (61.2–72.6) | [ceiling](../reports/evolution-90-ceiling-20261103/report.md) |

Additional single cells:

- On fresh proxy v3, the search-selected genome won 170/512, 33.2% (29.3–37.4).
- Pooled over both pools (512 tables per policy), the ceiling report gives
  saved 132 (25.8%, 22.2–29.7), the chip-EV oracle 350 (68.4%, 64.2–72.2) and
  the leader-aware oracle 345 (67.4%, 63.2–71.3).
- Pooled v1+v2 figures for the 512-table runs are my own derivation; no report
  states them. Hand-tuned exploit won 333/1024 (32.5%, 29.7–35.4),
  search-selected 340/1024 (33.2%, 30.4–36.1) and saved 292/1024 (28.5%,
  25.8–31.4). Every confidence interval for exploit overlaps saved's
  interval on the same pool.

Results on the canonical validation pool were run by the engine, not on a
proxy. These numbers are reported here only as outcomes and were never used
for development:

- [Archive-trained evolution run](../reports/evolution-90-run-20261103/LOOP-LOG.md),
  12 generations, 36 leader validations: the counts ranged from 27/128 to
  44/128. The best was 44/128 (34.4%). Its Wilson CI of 26.7–43.0% comes from
  the exploit run's log, which reports the same 44/128 count. `anchor-saved`
  itself scored between 31/128 and 41/128 at the same gate. The 44/128 is the
  maximum of 36 tests, so it is biased upward.
- [Exploit-seeded run](../reports/evolution-exploit-run-20261103/LOOP-LOG.md),
  generation 1 (pending): `seed-exploit-random-02` scored 44/128 (26.7–43.0),
  `seed-exploit-wide-thin` 40/128 and `seed-exploit-search-selected` 41/128.
- [Training-only seed search](../reports/evolution-90-search-20261103/report.md)
  against the archive union rather than the held-out distribution: `r90-ada-14`
  won 26/128 (20.3%, 14.3–28.1%) and `anchor-saved` 14/128.

## Why 90% looks infeasible

**Structural argument (arithmetic, not measured).** The table holds 16,000
chips in total, and blinds double every 25 hands:

| Hands | Big blind | 2,000-chip stack in BB | Whole table in BB |
|---|---:|---:|---:|
| 1–25 | 20 | 100 | 800 |
| 26–50 | 40 | 50 | 400 |
| 51–75 | 80 | 25 | 200 |
| 76–100 | 160 | 12.5 | 100 |
| 101–125 | 320 | 6.25 | 50 |
| 126–150 | 640 | 3.1 | 25 |
| 151–175 | 1,280 | 1.56 | 12.5 |
| 176–200 | 2,560 | 0.78 | 6.25 |

- From hand 76 onward, the whole table holds only 100 BB. An average stack is
  short enough that most contested pots become preflop all-ins.
- Blinds keep forcing play, so a player cannot fold its way through these
  levels.
- An all-in is a probabilistic event. A player who is covered and calls with
  65% equity still busts 35% of the time. Winning outright means surviving
  every all-in in which the player is covered, plus winning the heads-up
  match, all within 200 hands.
- One anchor is a calling station that never folds, so bluffing it has no fold
  equity.

These points explain why the variance does not go away. They do not set a
precise upper bound.

**Measured evidence from the
[diagnostics](../reports/evolution-90-diagnostics-20261103/report.md)** (proxy v1, 256 tables per bot):

- **When busts happen:** 89.4–90.6% of busts happened at BB ≥160. The median bust hand was 107–117.
- **How busts happen:** 71.3–83.3% of busts came from a preflop all-in, and 9.4–18.2% were forced by the blinds.
- **Heads-up access:** the bots reached heads-up in only 35.2–40.6% of tables and converted 68.3–73.3% of those.
- **Upper bound from heads-up access:** even with perfect heads-up conversion, these paths cap at about 41% (saved) and 36% (finalists).
- **Equity at bust:** against the opponents' actual hands, mean equity at commitment was 36.4–37.3%, and 60–64 busts happened with at least 40% equity. This sample is selected on busting, so it is not a calibration estimate.

**Oracle evidence from the
[ceiling report](../reports/evolution-90-ceiling-20261103/report.md).** The
cheating hero saw every non-folded opponent's current hole cards, but no
future board cards. Its results:

- **Heads-up access and conversion:** it reached heads-up in 70.3–79.7% of tables and converted 86.1–91.2% of those.
- **When busts happen:** 89–91% of its busts still came at BB ≥160.
- **Win rate:** it won 62.5–74.2% per pool. The best cell, 190/256 on v2, has a Wilson upper bound of 79.2%.

**Evidence versus proof.**

- The oracle is a greedy heuristic. It compares current equity to price,
  does not model how opponents respond, and does not maximize tournament win
  probability. The report itself says a stronger perfect-information policy
  "could improve on these numbers, potentially materially".
- The proxy pools are stand-ins for the held-out pools. They are built the
  same way but drawn from different seeds. The gene search found a 10.9-point
  spread between pools even with table seeds held fixed.
- So the oracle evidence gives no upper bound for a legal policy. It shows that
  near-perfect information reached only about 62–74%, and that a legal policy
  would have to beat that by a wide margin. The stronger oracle (pending) is
  the next test of that gap.

## What helped and what did not

**Helped, modestly:**

- *Public opponent profiles (exploit family).* Exploit beat saved on every
  paired pool: 89 vs 73 and 72 vs 59 wins on 256 tables, 184 vs 153 and
  149 vs 139 on 512. The gain is about 2–6 points, and the confidence
  intervals overlap. The exploit report gives no paired test against saved.
- *Endgame wrapper on non-exploit bases.* It added paired net wins in all six
  cells. On v1: saved +6, `r90-ada-14` +10, `r90-evo-02` +9. On v2: +11, +10,
  +31. All wrapped results stay between 27.3% and 31.6%.
- *Gene search.* The selected genome is the most consistent across pools
  (34.0%, 32.4%, 33.2%), but it does not clearly beat the hand-tuned genome.
  The hand-tuned genome led on v1 (184 vs 174), and the search-selected genome
  led on v2 (166 vs 149).

**Did not help:**

- *Endgame overlay on top of exploit.* Paired net wins against exploit were
  −13 (v1) and −2 (v2) with default genes, and −10 and +1 with heads-up
  aggression 1.25.
- *Archive-trained evolution.* Over 12 generations, no validation result was
  better than 44/128, and `anchor-saved` reached 41/128 at the same gate. On
  proxy v1 the finalists did not beat saved, with paired differences of
  −2.3 points (95% CI −9.9 to +5.2) and −3.5 points (−10.7 to +3.7). The
  training pool was the imported archive, which is the wrong opponent
  distribution for the held-out gate.
- *Public-information inference (partial).* In the latest
  [`final.json`](../reports/inference-policy-20261103/final.json) snapshot,
  which I read at about 17:41 on 2026-11-03, results on proxy v1 were:
  - **Win counts (352 tables each):** inference 109, exploit 123, saved 110.
  - **Paired net wins for inference:** −14 against exploit and −1 against saved.
  - **How often inference changed the action:** it overrode exploit's
    fallback in only 600 of 58,999 decisions.

  Its exploit and saved arms reproduce the 256-table counts exactly on the
  same seeds.

## Pending work (not reflected above)

- **Stronger response-simulating oracle**
  (`reports/evolution-90-oracle2-20261103/`): stopped part-way. Its partial
  results are in the bottom line; the ablation runs are incomplete.
- **Public-information inference policy**
  (`reports/inference-policy-20261103/`): stopped part-way through pool v1.
  At the stop it had won 137/449 (30.5%), against 160/449 (35.6%) for
  exploit-best and 141/449 (31.4%) for saved on the same tables. It is not
  merged.
- **Exploit-seeded evolution without the archive**
  (`reports/evolution-exploit-run-20261103/`): stopped after generation 2.
  Its best validation result was `seed-exploit-random-02` with 49/128
  (38.3%). The gate is effectively 0.95, not 0.90 (see inconsistencies).
- **Early-phase chip accumulation for exploit:** the diagnostics found a
  hand-75 chip-lead rate of only 24.6–34.8%. No report exists in the
  repository yet.
- **Public `table_stacks` observation and stack-aware play:** the current
  `Observation` does not expose opponents' stacks. No report exists in the
  repository yet.

## Inconsistencies and caveats found between reports

1. **The ceiling headline overstates the result.** Its headline says 90% "is
   not achievable by a legitimate policy", but the same report calls its
   result an empirical upper bound, "not a game-theoretic proof". This
   document treats it as evidence.
2. **The search-selected genome's bot ID differs between runs.** The search
   report says the genome is stored as `exploit-search-selected` "used for
   candidate comparisons". The raw v1/v2 512-table JSON instead uses
   `exploit-search-final-01`, and only v3 uses `exploit-search-selected`.
   Exploit decisions are salted by bot ID ([exploit-policy.md](exploit-policy.md)),
   so re-running under the other ID may not reproduce the counts exactly.
3. **The inference partial result in the brief does not match the file.** The
   brief cited 95/296 for inference against 104/296 for exploit. No report
   file contains those numbers. `final.json` is rewritten while the run
   progresses: it showed 92/288 against 100/288 when I first read it, and
   109/352 against 123/352 later.
4. **The exploit-seeded run uses a 0.95 target, not 0.90.** Its log records
   that the requested target 0.90 was dropped by the frozen parallel runner,
   so the checkpoint's effective target is 0.95. The cause was
   `scripts/evolve_parallel.py`, which built its config by hand and omitted
   `--target-win-rate` and the archive options. That is now fixed: both
   CLIs share `evolution.config_from_args`, and a regression test covers it.
   The running checkpoint keeps 0.95 for resume compatibility. No leader is
   near either threshold, so no gate outcome changes.
5. **Runs on different opponent pools do not compare.** The seed search
   (archive opponents), the evolution-run validation (canonical pool) and the
   proxy runs each use different opponents. For example, saved scored 14/128
   in the seed search, 31–41/128 on validation, and 73/256 on proxy v1.

## How to reproduce

Proxy evaluation uses [`scripts/proxy_heldout_eval.py`](../scripts/proxy_heldout_eval.py).
Every candidate in the JSON list plays the same seeded tables.

```sh
# Development pool (v1); reproduces the 256-table exploit / saved / r90-ada-14 rows
.venv/bin/python scripts/proxy_heldout_eval.py \
  reports/exploit-policy-20261103/candidates-final.json \
  --matches 256 --workers 2 --output OUT-v1.json

# Second pool (v2): the same command with both domains switched
.venv/bin/python scripts/proxy_heldout_eval.py CANDIDATES.json --matches 256 --workers 2 \
  --pool-domain proxy-heldout-pool-v2 --eval-domain proxy-heldout-eval-v2 --output OUT-v2.json

# Fresh confirmation-style re-test of an already selected genome (e.g. v3)
.venv/bin/python scripts/proxy_heldout_eval.py \
  reports/exploit-search-20261103/selected-genomes.json --matches 512 --workers 2 \
  --pool-domain proxy-heldout-pool-v3 --eval-domain proxy-heldout-eval-v3 --output OUT-v3.json
```

Domain rules:

- **Never use the canonical domains for development.** These are `training`,
  `validation`, `confirmation`, `training-opponents`, `validation-pool` and
  `confirmation-pool`, including any `namespace:`-prefixed form. The script
  rejects them. Never read canonical validation or confirmation results to
  rank, tune or select candidates. Only the engine's own gate may use them.
- **Tune only on v1.** Use v2 as a cross-pool check. Use a fresh domain
  (v3 or later) once per selected candidate, and never reuse a domain after
  tuning on it.
- **Keep candidate IDs stable and unique.** Bot IDs salt policy randomness.
  IDs that collide with pool members (for example `anchor-saved`) are
  rejected, which is why saved runs as `saved-proxy-reference`.

Other harnesses: endgame-wrapper rows are in
`reports/endgame-20261103/paired-results.json`; the oracles use the
non-canonical `reports/evolution-90-ceiling-20261103/oracle_proxy_experiment.py`;
diagnostics use `.work/evolution-90-diagnostics-20261103/diagnose_proxy.py`.
