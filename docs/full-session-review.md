# Chronological WPT session review

## Source and selection

The source is the public [World Poker Tour broadcast](https://www.youtube.com/watch?v=daR3q3KKQ0o), titled *Phil Ivey vs Patrik Antonius – WPT Heads Up Championship – Finals*. The review selected the first continuous Ivey–Antonius final game after the recap and introduction. Selection was fixed by source order before hand transcription; no hands were selected by action or outcome.

The source timeline is recorded in [`selection.json`](../data/public_ivey_session_wpt/selection.json):

| Source interval | Disposition |
|---|---|
| 00:00–12:18 | Excluded countdown |
| 12:18–33:17 | Excluded recap and highlights, including earlier Ivey–Chris Kruk material |
| 33:17–43:24 | Excluded interviews and final introduction |
| 43:24–55:24 | Frozen 12-minute chronological review window |
| 55:24–end | Not reviewed in this batch |

At 00:43:24, the broadcast shows “Best of 5,” score 0–0, “FINALS,” Phil Ivey and Patrik Antonius, 400/800 blinds, Ivey at 99.2K after posting 800, Antonius at 99.6K after posting 400, and a 1,200 pot. The official [WPT Day 1 structure update](https://www.worldpokertour.com/live-update/welcome-to-day-1-of-the-wpt-heads-up-poker-championship) specifies a 100,000-chip match start, 400/800 opening blinds, blind-level increases every seven hands, best-of-three ordinary matches, and a best-of-five final. The official [Day 2 update](https://www.worldpokertour.com/live-update/day-2-of-the-wpt-heads-up-championship-awaits-special-events-wpt-heads-up-poker-championship-presented-by-poker-king-season-2021-2022-2) corroborates the 100,000 start and 400/800 first level. The [WPT event page](https://www.worldpokertour.com/event/wpt-heads-up-poker-championship-presented-by-poker-king) identifies Ivey and Antonius as the finalists.

The exact 100,000-chip start is supported by the official numeric rule and the first-hand source state: subtracting the visible 800 and 400 posts gives 99,200 and 99,600, matching the broadcast’s rounded stacks. This establishes the opening stack for this first game only. The official material does not define stack resets between later games, and this batch makes no claim about later games.

No ante or straddle is specified in the official structure announcements. For each hand in this window, the settled broadcast pot at the opening state equals its displayed small blind plus big blind (1,200 at 400/800 or 1,500 at 500/1,000), with no additional forced payment visible. The per-hand evidence and arithmetic are in `forced_bets_at_opening` in [`records.json`](../data/public_ivey_session_wpt/records.json); zero ante and no straddle are limited to these reviewed hands.

## Records

[`records.json`](../data/public_ivey_session_wpt/records.json) contains 20 consecutive hand contexts, 18 with an Ivey decision, and 42 Ivey decisions total. Nineteen hand contexts finish inside the window. Hand 20 begins at 00:55:18; Ivey raises to 2,500 at 00:55:22, and the interval ends at 00:55:24 before Antonius responds. The boundary state records Ivey 120,402, Antonius 76,098, a 3,500 pot, and 1,500 to call.

| Review hand | First–last sampled context | Blinds | Ivey decisions | Status |
|---|---|---:|---:|---|
| H01 | 00:43:24–00:44:42 | 400/800 | 5 | Complete |
| H02 | 00:44:46–00:45:22 | 400/800 | 2 | Complete |
| H03 | 00:45:28–00:46:38 | 400/800 | 4 | Complete |
| H04 | 00:46:44–00:47:52 | 400/800 | 4 | Complete |
| H05 | 00:48:02–00:48:14 | 400/800 | 1 | Complete |
| H06 | 00:48:22–00:48:34 | 400/800 | 1 | Complete |
| H07 | 00:48:42–00:50:06 | 400/800 | 6 | Complete |
| H08 | 00:50:10–00:50:16 | 400/800 | 1 | Complete |
| H09 | 00:50:22–00:50:30 | 400/800 | 1 | Complete |
| H10 | 00:50:34–00:50:42 | 400/800 | 1 | Complete |
| H11 | 00:50:52–00:51:20 | 400/800 | 3 | Complete |
| H12 | 00:51:28–00:52:48 | 500/1,000 | 4 | Complete |
| H13 | 00:52:52–00:52:58 | 500/1,000 | 0 | Complete |
| H14 | 00:53:02–00:53:32 | 500/1,000 | 2 | Complete |
| H15 | 00:53:42–00:53:54 | 500/1,000 | 1 | Complete |
| H16 | 00:53:58–00:54:06 | 500/1,000 | 1 | Complete |
| H17 | 00:54:14–00:54:52 | 500/1,000 | 3 | Complete |
| H18 | 00:54:56–00:55:02 | 500/1,000 | 1 | Complete |
| H19 | 00:55:08–00:55:16 | 500/1,000 | 0 | Complete |
| H20 | 00:55:18–00:55:24 | 500/1,000 | 1 | Truncated at window boundary |

The broadcast overlay stays at 400/800 through review hand H11 and shows 500/1,000 from H12. If H01 is counted as the first hand of this game, that transition does not match the official statement that levels rise every seven hands. The sampled chronology shows no missing hand or cut in the reviewed interval. The ledger preserves the per-hand overlay values and leaves the counter discrepancy unresolved; it does not insert unseen hands or infer a different blind schedule.

Every dealt Ivey card and public board card needed for the decisions was visible. No opponent hole cards or equity values are retained. No source cut, play interruption, or missing hand context was detected in the two-second frame sequence; transitions shorter than that sampling interval could be missed. Brief pot-overlay animations at 00:48:04, 00:50:34, 00:53:44, 00:54:56, and 00:55:18 are logged with their settled values in `interruptions_and_missing_information.transient_overlay_updates`.

Each `decisions` entry contains only the predecision state; the observed action is stored separately in `expected_action`. Source card/action/blind facts are distinguished from arithmetic stack, pot, and to-call values. Exact subsequent stacks are reconstructed from the official opening stack and the visible posts and contributions. Completed hands conserve 200,000 chips between the two players. The JSON records the complete chronology, states, source timestamps, and derivation bases.

There are 42 retained predecision stills under [`evidence/`](../data/public_ivey_session_wpt/evidence/), one per recorded Ivey decision. The collector reports masking opponent cards/equity and hero equity while retaining Ivey’s cards and the visible board; independent source and redaction review remains pending. Twenty PHH action prefixes under [`phh/`](../data/public_ivey_session_wpt/phh/) use unknown opponent cards (`????`) and the heads-up blind assignment convention in the [PHH specification](https://phh.readthedocs.io/en/latest/required.html). The JSON is the provenance ledger; the PHH files stop at each last recorded in-window action. The original collection pass validated TOML syntax only.

Subsequent parent normalization and an independent accounting review replayed these files with PokerKit 0.7.7. **38 decisions replay successfully and match the recorded cards, visible board, pot, stack, call amount, position and action labels.** H04 is held out in full: its turn prefix makes Ivey act first from the button/small blind, while the big blind must act first. Its four decisions require source adjudication before any repair. H13 and H19 are valid walks with zero Ivey decisions. Their lack of decision rows is not a malformed-hand finding.

The pending normalization is saved in [`pending-v2.json`](../data/public_ivey_session_wpt_derived/pending-v2.json), generated by [`import_wpt_session.py`](../scripts/import_wpt_session.py). It also checks chip conservation, public wager payments, source-reported payouts and hand-to-hand stack continuity. Opponent cards remain unknown, so engine replay cannot independently establish showdown winners. All 38 normalized rows remain marked `pending_source_review`; arithmetic consistency alone does not establish broadcast transcription precision or resolve the blind-counter discrepancy. No bot was called or scored on this batch.

The subsequent source spot-audit confirmed that Antonius checks first on H04's turn, around 47:24, followed by Ivey around 47:32. It also read H11's flop bet as **2,280**, correcting the collector's 2,253: the facing state has a 6,280 pot, 2,280 to call and a derived opponent stack of 70,781. Because Ivey folds to that uncalled bet, the correction leaves later starting balances unchanged. H07's retained H07-D03 and H07-D05 stills show transient pots of 6,341 and 16,199; their wager-derived settled values are 7,280 and 16,579.

These source corrections are preserved separately in [`source-corrections-v1/records.json`](../data/public_ivey_session_wpt_derived/source-corrections-v1/records.json) and its copied PHHs. The originals remain unchanged. The corrected [`pending-v4.json`](../data/public_ivey_session_wpt_derived/pending-v4.json) replays **42 decisions**, all still pending admission. H04-D03's incorrect 47:22 predecision timestamp has been withdrawn; the source-supported interval after Antonius's check and before Ivey's check is retained pending precise frame re-anchoring. The audit verified the retained hero cards, boards, masks and completed-hand outcomes, but it was a spot check. Rounded stack badges do not independently establish exact balances, and a separate continuity investigation must resolve or qualify the seven-hand blind discrepancy before any broader precision claim.

All records share event and match-group identifiers. Each hand also has a source-independent context fingerprint and source-time guard key. Cross-corpus duplicate checking was not performed because earlier corpus directories were outside this batch’s ownership; the parent merge should compare these keys with the seven original hands and four batch-1 clips.

This is a bounded source acquisition, not an accuracy result or representative sample of every Ivey decision. It covers one opponent and only the first 12 minutes of the first final game. No accuracy claim is made.
