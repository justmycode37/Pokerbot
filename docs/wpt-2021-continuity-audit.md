# WPT 2021 continuity audit

**Status:** complete for the assigned source window and the permitted H20 settlement extension. This is a chronology and chip-ledger audit, not an action-accuracy review.

## Scope and method

The frozen review window was `[00:43:24, 00:55:24)` in the public WPT video [daR3q3KKQ0o](https://www.youtube.com/watch?v=daR3q3KKQ0o). The opening lead-in was checked through the table dissolve, and the source was followed past the window only far enough to settle H20, through the post-hand display near 00:56:20. Selection candidates and splits were not changed.

The interrupted audit’s sampled frames and clips were reused. The lead-in review found interviews and match introduction before the table dissolve at 00:43:24, with no earlier final-game deal observed. Nineteen adjacent hand-boundary windows were checked at 250 ms sampling. No additional deal or walk was observed. This finding is limited by the sample cadence; it does not rule out an event shorter than 250 ms.

The existing per-hand public action ledgers remain the source for actions before the boundary. Their amount semantics are preserved: `raise_to` is total contribution on the current street; bet and call amounts are chips added. H20’s post-window actions are transcribed separately in the audit JSON. Source observations remain separate from expected actions and contain no opponent private cards/equity, hero equity, future board, action labels, or hand-result labels.

## Chronology and blind-level discrepancy

The source shows H11 dealt by 00:50:46.500 and H12 by 00:51:23.750. At the H12 transition, the blind overlay is 400/800 at 00:51:23.500 and 500/1,000 at 00:51:23.750. H01 through H11 therefore show 400/800, and H12 through H20 show 500/1,000. No intervening hand or walk was found in the checked boundaries.

The official structure summary says blinds increase after every seven hands. If H01 is counted as the first hand, the broadcast transition after H11 does not match that rule. The discrepancy remains unresolved. No hands were inserted and no cadence exception was inferred. The per-hand blind overlays and observed chronology remain recorded as shown.

## Exact and approximate chip states

H01 begins at the official 100,000 chips per player. The opening 400/800 posts and 1,200 pot corroborate the first hand’s after-post state. For each hand, the audit records the source timestamp and displayed small blind, big blind, and settled opening pot. Ante and straddle are recorded as zero only as per-hand derivations where the settled pot equals the two visible blinds and no extra forced payment is visible; the official structure text does not establish those values.

All 20 hand contexts reconcile to 200,000 total chips. H01–H19 ending stacks exactly match the following hand’s opening stacks. The later exact stacks are arithmetic derivations from the source action ledger and forced bets, not readings from rounded HUD badges.

H20 starts with Ivey at 122,902 and Antonius at 77,098. Ivey raises to 2,500 total preflop; Antonius calls 1,500 more. On the flop, Ivey bets 1,650 and Antonius calls 1,650. Both players check the turn and river. The public pot is 8,300. Each player contributed 4,150. The post-hand rounded badges show approximately 118.8K and 81.2K, corroborating the exact derived carry of Ivey 118,752 and Antonius 81,248. Rounded badges are not used as exact inputs, and no result label is retained.

## H04-D03 source re-anchor

The stale 00:47:22 source anchor is withdrawn for this report. At 00:47:24.750, a 250 ms sample first shows Ivey active. At 00:47:25.000, the first sampled frame with Antonius’s preceding big-blind check visible also shows Ivey active. Ivey’s check is visible by 00:47:32.000. The first confirmed predecision frame after Antonius’s check is therefore 00:47:25.000; the exact button-press time is unknown. This re-anchor follows the existing H04 turn-order correction. The correction directory was not edited.

The existing H11 correction records the uncalled flop bet as 2,280. The existing H07 correction distinguishes transient pot graphics from the wager-derived pot. Neither correction directory was changed or recreated.

## Counts

| Measure | Count |
| --- | ---: |
| Acquired decision rows in the existing source ledger | 42 |
| Complete decision rows with observation and separate expected action | 42 |
| Partial decision rows in the existing source ledger | 0 |
| Decision rows in contexts settled inside the frozen window | 41 |
| Decision rows in H20, settled by the allowed tail extension | 1 |
| Full decision rows independently re-audited by this continuity pass | 0 |
| Decision rows partially re-anchored by this pass | 1 (H04-D03) |
| Hand contexts acquired | 20 |
| Hand contexts settled inside the frozen window | 19 |
| Hand contexts settled by the allowed H20 extension | 1 |
| Partial hand contexts after the allowed extension | 0 |
| Zero-Ivey-decision contexts | 2 (H13 and H19; Antonius folds preflop) |
| Hand-boundary windows checked | 19 |
| Public action rows in existing records | 86 |
| H20 continuation action rows added to the audit | 8 |
| Public action rows accounted for, including H20 continuation | 94 |

The continuity pass does not claim that all 42 decisions were independently source-reviewed and makes no action-accuracy claim. The 80 WPT w01+w02 decisions noted in the continuation remain pending source review; engine replay alone does not establish transcription or chronology.

## Admission and unresolved evidence

The observed H01–H20 chronology is conditionally admitted as the sampled public sequence: the opening lead-in was checked, all 19 boundaries were checked, and H20 was followed through settlement. The exact derived chip ledger is conditionally admitted for that sequence because every hand conserves 200,000 chips and adjacent hand states reconcile. The seven-hand rule conflict remains attached as unresolved metadata. A primary final-specific structure/counter or a higher-resolution source review identifying a missed hand or different counter boundary would reopen the chronology.

Sparse retained evidence is under `data/wpt_2021_continuity_audit/evidence/`. The blind-transition stills show only title/blind overlays. `h20_public_wager.png` is cropped to the public flop, wager chips, and pot; player panels and action/result labels are excluded. Temporary unredacted review clips and frames were removed after these safe references were saved and checked.

## Next-window handoff

Continue public source acquisition toward several thousand attributable Phil Ivey decisions across varied contexts before further bot or model work. Keep candidates and splits frozen. Resume after H20 near 00:56:20, preserve routine folds/checks and zero-decision contexts, and continue to separate predecision observations from expected actions. Resolve the blind-level discrepancy only with source evidence such as a final-specific structure or hand counter; do not insert unseen hands. No policy call, fitting, scoring, accuracy evaluation, or bot change was made in this audit.
