# WPT Heads Up Championship 2021 structure source note

## Findings

| Item | Finding | Evidence status |
|---|---|---|
| Starting stack | 100,000 chips at match start | Explicit integer in official WPT text; not inferred from a rounded 100K display |
| Opening blinds | 400/800 | Explicit in official WPT text |
| Blind timing | Blinds rise after every seven hands | Explicit; later numeric levels were not found |
| Series format | Best-of-three matches; best-of-five final | Explicit in official WPT Day 1 update |
| Stack reset between games | Unknown | No retrieved official source states reset versus carry-over between constituent games |
| Ante / straddle | Unknown | Not specified in the retrieved structure text |

The [official WPT Day 1 structure update](https://www.worldpokertour.com/live-update/welcome-to-day-1-of-the-wpt-heads-up-poker-championship) says: “All players will begin the match with 100,000 in chips and blinds will start at 400/800 with levels going up after every seven hands.” The official [Day 2 update](https://www.worldpokertour.com/live-update/day-2-of-the-wpt-heads-up-championship-awaits-special-events-wpt-heads-up-poker-championship-presented-by-poker-king-season-2021-2022-2) repeats a 100,000-chip start and 400/800 first level, with the blinds going up every seven hands.

The wording supports an exact nominal match-start amount of **100,000 chips**. It calls the series best-of-three (best-of-five in the final) but does not explain whether chips are reset before each constituent game or carried across games. I therefore record 100,000 as the official match-start stack and leave game-by-game reset timing unresolved.

## Broadcast context supplied with the task

The task's [selection metadata](../data/public_ivey_session_wpt/selection.json) reports that the first actual-match preflop frame shows 0–0, 400/800 blinds, and stacks of 99.2K for Phil Ivey after posting the 800 big blind and 99.6K for Patrik Antonius after posting the 400 small blind. Adding back those posted blinds yields 100,000 for each player. This is a secondary arithmetic cross-check, not a stack-reset rule and not a new hand label; this research pass did not independently review the video.

## Unknowns and bounded search

Six searches were run, limited to official WPT/PokerKing structure announcements and reset terms. The official WPT structure pages above were found. No relevant PokerKing-domain rules page surfaced. The retrieved official text does not specify ante or straddle policy, a complete later blind schedule, or whether the stack resets between constituent games. These are unknowns, not evidence that antes or straddles were absent.

The public [WPT broadcast](https://www.youtube.com/watch?v=daR3q3KKQ0o) is retained as a source candidate. This note relies on the official structure announcements and task-provided selection metadata.

For the full query list, source URLs, short quotes, and observed/inferred/unknown fields, see [research.json](../data/wpt_2021_structure/research.json).
