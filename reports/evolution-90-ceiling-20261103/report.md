# Evolution 90% target: hole-card oracle ceiling experiment

## Result

The empirical answer is **no: a 90% outright win rate is not achievable by a legitimate policy in this structure against these pools**. Even a deliberately cheating hero that sees every live opponent's current hole cards, but not future board cards, reached a best single-pool result of **74.2%** (v2); the best result on v1 was 67.6%. The v2 result's 95% Wilson upper bound was **79.2%**, still 10.8 percentage points below the target. The pooled best oracle result was 68.4% (95% CI 64.2–72.2%).

This is an empirical upper-bound experiment, not a game-theoretic proof. The oracle is strong but heuristic; its limitations are described below. The evidence makes 90% an implausible objective for a legal policy, while the measured results put an extreme privileged-information performance level around 70–75%, not 90%. The saved legal reference won 23.0–28.5% in these same runs; earlier finalists were in the 25–35% range. That observed legal range is not itself a proven maximum.

## Per-pool outcomes

Each row is 256 tables with the same opponent sample, hero seat, and deal as the other policies on that pool. Capped tables count as non-wins. Heads-up conversion is wins divided by tables that reached heads-up, including capped tables in the denominator.

| Proxy pool / policy | Outright wins, 95% Wilson CI | Heads-up entry | Heads-up conversion | Busts at BB ≥160 / all busts | Capped non-wins |
|---|---:|---:|---:|---:|---:|
| v1 · saved reference | 73/256 (28.5%; 23.3–34.3%) | 104/256 (40.6%) | 71/104 (68.3%) | 162/181 | 6 |
| v1 · hole-card chip-EV heuristic | 160/256 (62.5%; 56.4–68.2%) | 180/256 (70.3%) | 155/180 (86.1%) | 85/96 | 2 |
| v1 · hole-card leader-aware | 173/256 (67.6%; 61.6–73.0%) | 197/256 (77.0%) | 170/197 (86.3%) | 74/83 | 1 |
| v2 · saved reference | 59/256 (23.0%; 18.3–28.6%) | 100/256 (39.1%) | 56/100 (56.0%) | 175/196 | 3 |
| v2 · hole-card chip-EV heuristic | 190/256 (74.2%; 68.5–79.2%) | 204/256 (79.7%) | 186/204 (91.2%) | 59/66 | 0 |
| v2 · hole-card leader-aware | 172/256 (67.2%; 61.2–72.6%) | 197/256 (77.0%) | 172/197 (87.3%) | 76/84 | 1 |

Across both pools (512 tables per policy), saved won 132 (25.8%; 95% CI 22.2–29.7%), the chip-EV heuristic won 350 (68.4%; 64.2–72.2%), and the leader-aware oracle won 345 (67.4%; 63.2–71.3%). The two oracle variants reached heads-up in 75.0% and 77.0% of tables and converted 88.8% and 86.8% of those entries. The hero busted in 162 and 167 tables, respectively; 144/162 and 150/167 busts happened at BB 160 or later. Capped non-wins were 2 per oracle variant across 512 tables.

The v2 chip-EV result is the most favorable cell, and still falls short of 90%: 190/256 wins with an upper 95% Wilson bound of 79.2%. Pool v2 was easier for that particular action heuristic than v1, while the leader-aware variant was stable at about 67% on both pools. This pool sensitivity is a reason to report both pools rather than treating the larger cell as a universal rate.

### Bust blind level counts

Counts below are in BB order 20 / 40 / 80 / 160 / 320 / 640 / 1,280 / 2,560.

| Pool / policy | Busts by big blind level |
|---|---|
| v1 saved | 9 / 4 / 6 / 26 / 64 / 47 / 23 / 2 |
| v1 chip-EV oracle | 7 / 3 / 1 / 2 / 19 / 32 / 30 / 2 |
| v1 leader-aware oracle | 6 / 2 / 1 / 2 / 18 / 28 / 23 / 3 |
| v2 saved | 7 / 4 / 10 / 34 / 57 / 47 / 33 / 4 |
| v2 chip-EV oracle | 4 / 3 / 0 / 5 / 24 / 13 / 17 / 0 |
| v2 leader-aware oracle | 3 / 5 / 0 / 6 / 25 / 20 / 20 / 5 |

About 89–91% of oracle busts still occurred at BB ≥160, despite seeing live opponents' cards and avoiding calls below estimated pot odds. The blind escalation continues to force difficult outcomes late in the structure.

## What the oracle knew and did

The non-canonical harness attached engine-private data to each decision, then filtered it so only the hero oracle received it. It exposed the hole cards of non-folded opponents and the board through the current street. Folded players' cards were removed from the policy input and treated as unknown cards when estimating future runouts. No future board cards were exposed. Opponents and the saved reference received the normal observation. The leader-aware variant also received the full current tournament stack sizes to identify the chip leader. Stacks are visible at a physical poker table, though they are absent from this project's hero-only observation object.

The chip-EV variant estimated multiway pot-share equity against the actual live hands, used contestable-pot odds for call/fold decisions, and sized value bets based on equity and stack/blind depth. It used exact runouts when there were at most 1,500 and 128 deterministic Monte Carlo runouts otherwise. The leader-aware variant also avoided large calls while holding the sole chip lead, requiring at least 70% equity and a margin above pot odds when calling at least 25% of its hand-start stack. Both variants used legal actions only. The strict engine run reported zero invalid actions and zero chip-conservation failures.

The chip-EV policy is a greedy heuristic, not a full chip-EV solver. Its equity sampling is noisy in large preflop states, and its bet sizing does not search every raise size or model each opponent's fold, call, and re-raise response. It compares current showdown equity with the current price, which omits some future-street options and implied-odds effects. It also does not solve for maximizing tournament win probability. A stronger perfect-information policy could improve on these numbers, potentially materially. However, the best measured oracle needs another 15.8 percentage points merely to reach 90%, and no result here suggests that gap is realistically available to a policy that lacks the oracle's private information.

## Reproduction and integrity

- 256 tables per policy on each pool: `proxy-heldout-pool-v1` / `proxy-heldout-eval-v1` and `proxy-heldout-pool-v2` / `proxy-heldout-eval-v2`.
- Each pool contains the five fixed anchors and 16 `new_random` genomes; every 8-player table samples seven opponents using the same tournament job builder as `scripts/proxy_heldout_eval.py`.
- Starting stack 2,000; blinds 20/40/80/160/320/640/1,280/2,560, increasing every 25 hands; 200-hand cap. All capped tables are non-wins.
- 512 paired tables per policy across both pool versions. The saved bot is evaluated on the exact same seeds, opponent sets, seats, and deals as both oracle variants.
- Only the proxy seed domains were used. Canonical validation and confirmation domains and outcomes were not read.
- No canonical source files were edited, and no staging, commits, pushes, or resets were used. Artifacts are limited to the two assigned directories.
- Full per-table rows, sample seeds, paired seat IDs, protocol, and aggregate summaries are in [`oracle-summary.json`](oracle-summary.json). The explicitly non-canonical harness is [`oracle_proxy_experiment.py`](oracle_proxy_experiment.py) (a copy of the run-time script; it is not imported by any canonical code).
