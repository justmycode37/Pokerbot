# Evolution 90 proxy diagnostics

## Results first

Three paired proxy cohorts of 256 tables each produced **73/256 (28.5%)** wins for the saved policy, **67/256 (26.2%)** for `r90-ada-14`, and **64/256 (25.0%)** for `r90-evo-02`. Their table-level Wilson 95% intervals are 23.3–34.3%, 21.2–31.9%, and 20.1–30.6%. All 14 capped tables were counted as non-wins. These data show no measurable gain for either finalist over saved: paired differences were −2.3 points (approx. 95% CI −9.9 to +5.2) and −3.5 points (−10.7 to +3.7).

| Candidate | Wins | Busts | Capped non-wins | Mean finish | Reached heads-up | Won after reaching heads-up |
|---|---:|---:|---:|---:|---:|---:|
| Saved policy | 73/256 (28.5%) | 181 (70.7%) | 6 | 3.60 | 104 (40.6%) | 71/104 (68.3%) |
| `r90-ada-14` | 67/256 (26.2%) | 189 (73.8%) | 5 | 4.05 | 90 (35.2%) | 66/90 (73.3%) |
| `r90-evo-02` | 64/256 (25.0%) | 192 (75.0%) | 3 | 3.98 | 91 (35.5%) | 63/91 (69.2%) |

The saved policy appears under the unique hero ID `diag-saved-baseline` in the JSON because the proxy pool already contains `anchor-saved`; the saved policy itself is ID-independent. Every observed winner except two saved wins and one win per finalist had first reached heads-up.

## Where tables are being lost

| Candidate | Median bust hand (25th–75th percentile) | Busts at BB ≥160 | Preflop all-in busts | Blind-forced busts | Postflop all-in busts | Bust with 1 player left |
|---|---:|---:|---:|---:|---:|---:|
| Saved | 117 (101–137) | 162/181 (89.5%) | 129/181 (71.3%) | 33/181 (18.2%) | 19/181 (10.5%) | 31/181 (17.1%) |
| `r90-ada-14` | 107 (83–128) | 169/189 (89.4%) | 155/189 (82.0%) | 26/189 (13.8%) | 8/189 (4.2%) | 24/189 (12.7%) |
| `r90-evo-02` | 108 (90–133) | 174/192 (90.6%) | 160/192 (83.3%) | 18/192 (9.4%) | 14/192 (7.3%) | 28/192 (14.6%) |

The blind schedule is the main structural pressure: a stack that never changes goes from 100 BB at hand 1 to 12.5 BB at hand 76, 6.25 BB at hand 101, 3.125 BB at hand 126, and 1.56 BB at hand 151. About 90% of busts occurred at BB 160 or higher. Blind-forced busts are cases where the hero's entire remaining stack was posted as the small or big blind, with no policy decision available. The large majority of other busts came from a recorded preflop all-in decision.

The hero did not establish a reliable early chip lead. At the end of hands 25/50/75/100, mean hero chips were 2.20k/2.47k/2.83k/3.28k for saved, 2.26k/2.37k/2.62k/2.90k for adaptive, and 2.17k/2.27k/2.48k/2.68k for evolved. Chip-lead rates at those same points were 27.7/31.3/34.8/29.3%, 25.0/29.3/30.5/25.8%, and 20.3/24.6/24.6/24.6%. Chip lead is only a proxy for winning equity, but these rates show that most tables enter the late blind levels without the hero controlling the chip pool.

Measured start-of-hand depth also collapses with the schedule. At hand 100 (BB 160), median depth was 19.6/18.3/15.2 BB for saved/adaptive/evolved, with 18.8/29.7/26.6% of tables at or below 5 BB. At hand 125 (BB 320), medians were 7.7/0/6.8 BB and 46.1/53.5/48.8% were at or below 5 BB; at hand 150 (BB 640), the median was zero for all three because more than half the heroes had already busted. These summaries include busted zeros and carry terminal survivor stacks forward when a table ended before the sampled hand.

### Busting all-ins and variance

For bust hands where actor traces supplied the hero's cards, the board, and every nonfolded opponent's cards, I estimated hero's equity at the commitment point against those **actual** hands. Completed-board and short runouts were enumerated; preflop runouts used 1,024 Monte Carlo samples (mean per-hand sampling error about 1.3 percentage points).

| Candidate | Busts with actual-hand equity | Mean equity at commitment | Busts despite ≥40% equity | All-in calls below pot odds by >2 MC standard errors |
|---|---:|---:|---:|---:|
| Saved | 148 | 37.3% | 64 | 28/59 |
| `r90-ada-14` | 163 | 36.4% | 60 | 16/24 |
| `r90-evo-02` | 174 | 36.5% | 62 | 18/44 |

These counts separate losses that are compatible with substantial runout variance from obvious review candidates, but **they do not label decisions as −EV**. The hand is revealed only after the choice, and these rows are selected because the hero busted. A call whose equity against the actual hand fell below its price can still be a sound call against the opponent's range; likewise a losing all-in with 40%+ equity is not automatically a cooler. The evolved/adaptive policy's own equity diagnostics averaged 54.3% and 52.5% among their busting all-ins, respectively, versus 36.4–36.5% against the actual showdown hands. That conditional, mismatched comparison is a replay queue, not a calibration estimate.

### Opponents and who wins

In 73–78% of non-capped tables where the hero lost, the outright winner was one of the 16 generated proxy genomes; fixed anchors won the remaining 22–24%. In bust hands, the largest same-hand net stack gainer was a generated genome in 73–77% of cases. This is an attribution proxy: a player's total hand gain can include side pots and does not prove that player collected the hero's exact chips.

The random genome pool is heterogeneous. Across 16/16 genomes and roughly 25k–39k dealt hands per genome, the per-genome means were **15.8% VPIP, 8.5% PFR, 1.13 raise/call aggression factor, 76.7% fold-to-raise, and 12.8% showdown frequency**. Ranges across genomes were 8.7–28.2% VPIP, 2.4–18.1% PFR, 0.31–2.47 aggression factor, 67.4–84.1% fold-to-raise, and 8.8–20.5% showdown frequency. The most frequent proxy winners/eliminators included `proxy-opponent-0014` (28% VPIP/18% PFR/1.61 AF), `0015` (21%/14%/2.16), `0001` (26%/16%/1.42), and `0011` (20%/11%/1.14). The low-activity `0000` genome was 11% VPIP/3% PFR/0.42 AF. The full 16-genome table is in `random-genome-profiles.json`.

The proxy pool has 5 anchors and 16 random genomes, and each table samples 7 opponents. Combinatorially, 90.2% of tables contain at least one anchor (expected 1.67 anchors); 55.7% contain at least two. Among losses, `anchor-saved` and `anchor-fast` are recurring winners. The calling-station anchor is defined to check or call every bet and never raise or fold, so bluffing it has no fold equity; the tight-passive anchor folds below its hand-strength cutoff.

## What policies can observe

`Observation` exposes the hero's hole cards, board, pot and contestable pot, price to call, stack, current street bet and legal raise bounds, big blind, position, active players and players to act, street, policy seed, table size, player ID, and public action history. `Observation.from_dict()` whitelists history fields `street`, `player`, `action`, `amount`, `added`, and `position`. The tournament wrapper also provides public `hand_index` and `table_player_ids`; the adaptive policy uses them to keep per-player profiles. Its raw input can include the observed `to_call` price for prior actions, which it uses before the `Observation` whitelist. No opponent hole cards or hand outcome are available to a policy.

## Ceiling and prioritized work

There is no oracle-policy rollout here, so these measurements cannot establish a game-theoretic ceiling. They do show why a 90% rate is far beyond a local tuning step: at the observed heads-up entry rates, even **perfect heads-up conversion** plus the few observed wins without heads-up would cap these same paths at about 41% for saved and 36% for either finalist. Reaching 90% requires raising late-stage access toward near-universal levels as well as near-perfect heads-up play. In the observed losses, 77 busts were mechanically forced by posting a blind, while roughly 90% of all busts happened at BB 160 or higher.

1. **Build chips and eliminate opponents in multiway pots early.** Chip lead at hand 75 was only 25–35%, and heads-up entry only 35–41%; this is the largest bottleneck. As scenario arithmetic, raising heads-up entry to 70% while holding today's conversion rates would project about 49–52% table wins (+20–25 points). This is not a measured policy effect.
2. **Use observable per-player profiles rather than one broad range.** Track raises, calls, folds after raises, position, and bet size by player ID. The random genomes' fold-to-raise spread is 67–84%; adaptive profiles already shrink estimates until four faced-price observations, and its preflop range adjustment waits for six actions. Preserve that sample-size discipline while targeting repeated folders and avoiding marginal calls against frequent large raisers.
3. **Make short-stack play positional and explicit before the blind consumes the stack.** The default starting 2,000 chips are only 12.5 BB at the 160 level and 6.25 BB at 320. The traces contain 18–33 blind-forced busts per 256 tables. A tested push/fold policy should use effective stack, position, players yet to act, and raise history; this count is an opportunity pool, not a guaranteed win-rate gain.
4. **Improve heads-up play as a separate objective.** Current conversion is 68–73%. At fixed heads-up entry, raising conversion to 90% would project roughly 32–37% table wins (+6–9 points); perfect conversion is a looser upper bound of 36–41%. These are scenario calculations, not A/B results.
5. **Size for value against stations and reserve bluffs for folders.** The station never folds, while the random pool folds to raises about three quarters of the time on average. Use larger value bets and avoid bluffing stations; target steals or selective bluffs toward identified folders, and use cautious value thresholds against the loose-aggressive genomes that often win these tables. This run does not isolate a numeric sizing effect.

## Method and artifacts

- 256 tables per candidate; same 256 proxy evaluation seeds and opponent sampling; two worker processes maximum.
- Pool/evaluation domains: `proxy-heldout-pool-v1` and `proxy-heldout-eval-v1`, built through `scripts/proxy_heldout_eval.py` and the canonical tournament job builder. Pool: five anchors plus 16 `new_random` genomes. Stack 2,000; blinds 20, 40, 80, 160, 320, 640, 1,280, 2,560 every 25 hands; 200-hand cap. Capped tables are non-wins.
- No canonical validation/confirmation seeds or results were read. All all-in hand equity is post-hoc and uses actual opponent cards from actor-only trace wrappers.
- Full per-table results, bust profiles, win intervals, chip trajectories, and equity summaries: `proxy-summary.json`. Individual random genome behavior: `random-genome-profiles.json`. Reproduction harness: `.work/evolution-90-diagnostics-20261103/diagnose_proxy.py`.

No 90% result was observed or is claimed.
