# Public Ivey long-session source queue — batch 1

This is a metadata-only discovery and availability catalog for future blinded annotation. It follows the frozen, ordered 12-query ledger in [search_ledger.json](../data/session_catalog/search_ledger.json). The machine-readable source list is available as [JSON](../data/session_catalog/source_catalog.json) and [CSV](../data/session_catalog/source_catalog.csv).

## Queue summary

The fixed searches yielded **12 distinct public, official-channel videos of at least 30 minutes** whose official metadata names Ivey or has an Ivey-tagged chapter. They represent **5 source groups**. Five Triton Cash Game Invitational I day streams have NLH/no-limit markers in official metadata. The other seven sources remain conditional on exact game-variant verification. Six videos have **12 chapter spans naming Ivey**; six have only a title/description mention and no time-coded Ivey chapter.

Public YouTube metadata reports all 12 as public and age limit 0. No account, cookies, or access workaround was used. Video playback was not opened, and no media was downloaded. Ivey hole-card visibility has not been visually checked for any source. Thus **zero sources are annotation-ready and zero decision rows are verified**.

The 12 chapter spans cover 16,496 seconds (about 4 hours 35 minutes). A planning estimate of **54–110 possible Ivey decision opportunities** applies only to that time, using a rough 12–24 opportunities per hour of in-action footage. This is an estimate, not a row count: a chapter timecode does not establish a hand, decision, visible hole cards, or usable state.

## Strongest next candidates

| Priority | Source and useful context | Ivey-tagged coverage from metadata | Screening status |
|---|---|---|---|
| 1 | [Triton Cash Game Invitational I — Day 2](https://www.youtube.com/watch?v=Z_tHx2jdXuY), 2024-08-06, 10:17:32 | 03:30:50–04:52:40 | Official NLH/no-limit metadata and an Ivey chapter; best long cash-game starting point. |
| 2 | [Triton Cash Game Invitational I — Day 4](https://www.youtube.com/watch?v=XLVJ9bnHgIA), 2024-08-08, 10:23:25 | 05:31:53–07:23:35 | Official NLH/no-limit metadata and an Ivey chapter. |
| 3 | [Triton Cash Game Invitational I — Day 6](https://www.youtube.com/watch?v=0JTY5_zXf18), 2024-08-10, 10:08:00 | 04:31:52–04:54:44 | Official NLH/no-limit metadata and an Ivey chapter. |
| 4 | [WPT Heads Up Championship final vs Patrik Antonius](https://www.youtube.com/watch?v=daR3q3KKQ0o), 2021-06-22, 3:05:31 | 00:17:17–00:20:42; 01:12:52–01:19:03; 02:18:32–02:32:22 | Official WPT final source. **The already-under-review 00:43:24–00:55:24 window is excluded**; none of these chapter spans overlaps it. |
| 5 | [WPT Action!](https://www.youtube.com/watch?v=4TwrfGZnlP4), 2021-06-19, 7:07:15 | 03:57:26–04:17:36 | Official description and chapter identify Ivey in the 2021 Heads Up Championship context; opponent and exact match identity still unknown. |
| 6 | [Bellagio Cup final-table source](https://www.youtube.com/watch?v=jAtJ6byQnxs), published 2024-10-14, 39:14 | 00:03:56–00:08:03; 00:10:12–00:13:00; 00:25:56–00:29:40; 00:29:40–00:32:15; 00:32:15–00:33:57 | Five Ivey chapter spans, but edition, original event date, and game variant are unverified. Hold for source verification. |

Other conditional long candidates are [WPT Action!](https://www.youtube.com/watch?v=gayVmix3s1Q) and [WPT Action!](https://www.youtube.com/watch?v=wKSyC5OwfWI) from 2021-06-22, [WPT World Championship high-stakes cash](https://www.youtube.com/watch?v=WE-ugA3EnrM), [PGT Championship Day 1 free stream](https://www.youtube.com/watch?v=ETsL_XlAE-I), and Triton Cash Game Invitational I Days [3](https://www.youtube.com/watch?v=HJxTVoJFJ8I) and [5](https://www.youtube.com/watch?v=KEboRsH9y6s). Their official metadata mentions Ivey, but did not provide an Ivey chapter time. Day 3 and Day 5 are NLH/no-limit metadata-confirmed; the WPT cash and PokerGO tournament variant remain unresolved. These are whole-source *screening spans*, not confirmed Ivey-only windows.

## WPT 2021 structure and opponent coverage

The official WPT structure source says players started the match with 100,000 chips, blinds opened at 400/800, and levels rose every seven hands. That is a **125 BB match-start depth** by arithmetic. The source does not resolve resets between games, later numeric blind levels, or ante/straddle rules; see [the WPT structure note](wpt-2021-structure.md) and its official [Day 1](https://www.worldpokertour.com/live-update/welcome-to-day-1-of-the-wpt-heads-up-poker-championship) and [Day 2](https://www.worldpokertour.com/live-update/day-2-of-the-wpt-heads-up-championship-awaits-special-events-wpt-heads-up-poker-championship-presented-by-poker-king-season-2021-2022-2) sources.

Within the 2021 WPT heads-up candidates, only the final video title names a specific opponent (Patrik Antonius). The official WPT Action archives have Ivey metadata, but the returned metadata did not identify their opponents or exact matches. A full-match queue against multiple named opponents was therefore **not established in this batch**. No decision-level positions or deep/short stack contexts were inferred. Future workers should record these from eligible predecision states only.

## Negative findings and queue handling

- **PokerStars:** no 30-minute standard-NLHE session passed the metadata screen. The long official Ivey results were Shark Cage/all-hands or greatest-moments compilations, so they are retained as nonstandard/compilation exclusions.
- **PokerGO:** long public High Stakes Poker streams found by the fixed queries did not name Ivey in official title, description, or chapters. A PGT Championship Day 1 stream mentions Ivey but has no timecode and does not establish NLHE in the captured metadata. Short Deck and multi-hand compilations are excluded.
- **Triton:** Days 2–6 of Cash Game Invitational I are long public official streams; all five have NLH/no-limit markers. Days 2, 4, and 6 have Ivey-named chapter spans. Days 3 and 5 mention Ivey without a chapter offset.
- Full sessions and multiway cash games were allowed. Short highlights, Short Deck, Shark Cage, and ambiguous multi-hand compilations were retained with exclusion reasons in the JSON catalog.

For future parallel annotation, use each `future_worker_lane` with the disjoint `window_id` ranges in the catalog. Keep all rows with the same `source_group_id` in one train/validation/test split: in particular, keep all WPT Heads Up Championship 2021 sources together and all five Triton Cash Game Invitational I days together. A full-source screening span must first be narrowed to an Ivey participation window. Confirm standard NLHE, visible Ivey hole cards, and exact state evidence before creating labels. **All current verified decision counts remain zero.**
