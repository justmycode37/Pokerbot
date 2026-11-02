# WPT source window 02

## Scope

Source: [official WPT broadcast](https://www.youtube.com/watch?v=daR3q3KKQ0o), video ID daR3q3KKQ0o.
Reviewed the half-open interval **00:55:24–01:07:24**. The public 720p section was sampled every two seconds (360 samples). Timestamps identify sampled source frames, not sub-frame action timing; section extraction can keyframe-align.

The JSON and retained evidence are in [records.json](../data/public_ivey_session_wpt_windows/w02/records.json) and [w02/evidence](../data/public_ivey_session_wpt_windows/w02/evidence/). Evidence stills are fully redacted: opponent hole-card/equity regions and Ivey’s equity percentage are masked, while the pot, bet/call amounts, public board, and hero cards remain visible.

## Coverage and counts

The window contains **17 hand contexts**: the continuation of canonical H20 plus provisional observed contexts H21–H36. H20–H35 complete in the reviewed interval; H36 is active at the boundary. There are **38 Ivey decisions in 15 contexts** and **83 public action events**. Fold walks H27 and H33 are included. H20-D01, Ivey’s raise to 2,500 at 00:55:22, remains a carried prefix and is not counted or duplicated here.

| Contexts | Overlay blinds | Context start times |
|---|---:|---|
| H20–H22 | 500/1,000 | 00:55:18; 00:56:24; 00:56:40 |
| H23–H33 | 600/1,200 | 00:57:58; 00:58:34; 00:58:46; 00:59:50; 01:01:06; 01:01:16; 01:01:50; 01:02:30; 01:03:06; 01:03:24; 01:05:22 |
| H34–H36 | 800/1,600 | 01:05:34; 01:06:00; 01:06:32 |

Normalized action-event counts, after deduplicating labels that persist across sampled frames: **15 bets, 19 calls, 22 checks, 13 folds, and 14 raises** (the raise count includes the visible 3-bet to 14,500). The broadcast-label counts are **15 BET, 18 CALL, 22 CHECK, 13 FOLD, 13 RAISE, and 1 3-BET**; one additional H20 call is transfer-inferred because its label is not legible in the sampled still. These are counts, not an accuracy score.

## Stack and chronology status

The official match start is 100,000 chips each. Later starting and ending totals in this file are arithmetic ledger values conditional on the visible action chronology; they are not independent exact stack displays. Rounded HUD labels such as 76.1K remain approximate.

At 00:55:24, H20 is carried from the prior record at Ivey 120,402, Antonius 76,098, pot 3,500, current bets 2,500/1,000, and 1,500 to call for Antonius. Those are conditional carried-ledger values. H20-D01 is not repeated. The observed winner after H20 gives conditional derived next-hand stacks of 118,752/81,248.

The independent audit of window01 found the H04 turn-check actors reversed (actual Antonius BB check then Ivey BTN check) and corrected H11’s uncalled flop bet from 2,253 to 2,280, with pot 6,280 and Ivey facing 2,280. The uncalled correction leaves later arithmetic and the H20 boundary unchanged. The audit did **not** establish gap-free chronology or exact carried-forward display totals. Its uncertainty is preserved in every stack basis here. The official seven-hand level statement remains unresolved against broadcast overlays. H20–H36 are provisional observed-context ordinals only; this file does not assert complete official match numbering or infer missing hands.

Opening pots match the visible small and big blind amounts in each context. Ante and straddle are recorded as zero only as a per-hand derivation from those visible posts; no BBA, ante, or straddle rule is assumed. The listed blind levels are the broadcast overlays actually shown.

## Seam and boundary handoff

H20 continues under its canonical alias, with only D02–D04 added. H36 ends after the turn checks: board 5♥ 8♥ 3♣ 7♠, pot 13,280, and conditional ledger stacks Ivey 113,738 / Antonius 72,982. The river and hand result are outside this interval. Continue canonical WPT-FINAL1-H36 in the next window; the next context is provisionally H37.

The sampled 12-minute interval shows no cut or visible hand-context gap. Two-second sampling can miss sub-two-second transitions, so this is not evidence of complete official chronology. H33’s hero cards were not exposed before Antonius folded; no board was dealt. H36 is the only boundary-truncated context.

## Validation and cleanup

The JSON was parsed and checked for the hand/action totals, decision-to-action links, redacted evidence references, hand chip conservation, and the H20/H36 seam states. There are 38 retained predecision stills. Temporary source video, raw frames, contact sheets, and OCR output were removed after retaining the redacted evidence. No TOML artifact was produced.
