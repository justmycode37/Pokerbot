# WPT source window 04

## Scope and progress

Source: [official WPT broadcast](https://www.youtube.com/watch?v=daR3q3KKQ0o), video ID `daR3q3KKQ0o`. Review interval: **01:31:24–01:55:24**, half-open. `records.json` is a resumable in-progress ledger; it currently contains the first complete hand only and review has reached 01:32:24.

A bounded 120-second clip (source seconds 5,480–5,600) was downloaded at 720p as H.264 with stream copy. Its first decoded frame byte-matches a direct official-source frame at 5,480 seconds. Additional checks matched source seconds 5,484, 5,488, and 5,544 to local frames at the corresponding 30 fps offsets. The reviewed first hand was sampled every two seconds. No whole-window re-encode was used.

The source shows a **Best of 5, 1–0** scoreboard and 500/1,000 blinds at the W04 boundary. This establishes the visible score only; the match/game interpretation and any chip reset remain unresolved. `WPT-FINAL1-W04-H001` is a stable local alias. Its canonical ordinal/game alias remains pending the W03 seam handoff. The first included frame is preflop before Ivey's action, so no earlier action is carried into this hand.

## First complete hand

Local hand `WPT-FINAL1-W04-H001` runs from first observed state 01:31:24 through the winner display at 01:32:24. Phil Ivey is button/small blind; Patrik Antonius is big blind. The visible opening pot is 1,500 with 500/1,000 blinds. Zero ante/straddle is recorded only as a per-hand derivation from that pot equality and the absence of another visible forced post.

Ivey's 8♠ Q♦ are visible before the first decision. The board is K♦ Q♥ 6♦ 6♠ 4♣. The hand has **4 Ivey decisions**, **9 public post actions**, and a source-visible Phil Ivey winner label. Action amounts preserve semantics: Ivey's preflop raise is to 2,500 total; his 1,650 bets and Antonius's calls are additional contributions. The tracked pot reconciles to 8,300. Ending exact stacks remain null.

| Precision | Recorded state |
|---|---|
| Source facts | 500/1,000 blinds; 1,500 opening pot; hero cards and board; visible action labels/amounts; 8,300 final pot; Phil Ivey winner label; scoreboard 1–0 |
| Conditional/derived | 0 ante/straddle for this hand; 8,300 pot transfer ledger; 4,150 net transfer to Ivey |
| Unknown | Exact stacks; official hand ordinal; whether score 1–0 marks a new game or match state; exact game reset/stack continuity |
| Approximate display only | HUD stacks: opening 101.9K/96.6K; after-hand 106.5K/93.5K. Rounded labels are not exact totals. |

Four retained predecision stills are in [w04/evidence](../data/public_ivey_session_wpt_windows/w04/evidence/). Each masks opponent hole-card/equity regions and Ivey's equity area while retaining Ivey's visible cards, the current board, pot, action labels, and available chip information. No opponent hole cards, equity values, later board cards, or Ivey equity values are recorded.

## Current seam and continuation

W04 begins at 01:31:24 with a new preflop state in view. The parent may reconcile its hand alias against W03; no exact carried stack is assumed. Last reviewed state: H001 completed at 01:32:24. Next interval starts at 01:32:24; provisional local context alias is `WPT-FINAL1-W04-H002`.

The remaining 23 minutes of the requested interval are unreviewed. No official match chronology completeness, training, policy, scoring, or accuracy claim is made.
