# Public Phil Ivey video hand catalog

**Review correction:** the collection now retains 16 predecision stills and two
pot-only detail crops. One river still was withdrawn because it exposed equity.
Action-order counts and visible pots were corrected; all 18 decision records
remain partial and outside exact scoring. See [review errata](partial-video-review-errata.md).

## Discovery and selection

The search used public YouTube metadata from these fixed, ordered queries:

1. `ytsearch20:Phil Ivey poker PokerGO`
2. `ytsearch15:Phil Ivey PokerStars poker hand`
3. `ytsearch15:Phil Ivey Triton Poker hand`
4. `ytsearch10:Phil Ivey WPT poker hand`

The official channels were checked by channel name and stable channel ID. The
first three eligible PokerGO single-hand clips were locked before any stream
was opened. To reach a useful first batch, a supplementary query,
`ytsearch20:Phil Ivey Triton NLH poker`, was added after the initial review.
Its first metadata-eligible candidate was locked before playback. That 20-minute
video proved to intercut unrelated hands, so it was excluded by the
predeclared single-hand rule. The next single-hand result in that query order
was then locked before its review. The action or result did not determine
selection. The complete query and screening audit is in
[`selection-manifest.json`](../data/public_ivey_videos/selection-manifest.json).

Eligibility required an official operator channel, a public stream requiring no
account or access workaround, and metadata indicating one specific Ivey hand.
Only confirmed standard no-limit hold'em is counted as eligible for standard
NLHE scoring. The already reconstructed [PokerGO video YfjDfPk7e1E](https://www.youtube.com/watch?v=YfjDfPk7e1E)
was skipped. The existing Dwan/PHH and Ivey/Polk Card Player records were not
duplicated or changed.

## Selected sources

| Source | Classification | Ivey decisions | Review result |
|---|---|---:|---|
| [PokerGO — Phil Ivey Making Phil Ivey Reads](https://www.youtube.com/watch?v=Aw_KVPxe7d0), 2018-05-03, 4:59 | 2015 Super High Roller cash game; NLHE. Event report gives $400/$800 blinds and $200 ante. | 6 | Eligible; exact hero stack and protocol position are unavailable. PokerNews identifies his raw seat as hijack, which is outside the local position enum. [Hand report](https://www.pokernews.com/tours/super-high-roller-bowl/2015-super-high-roller-series/cash-game/post.241843.htm) |
| [PokerGO — Phil Hellmuth Gets Himself in Trouble vs Phil Ivey](https://www.youtube.com/watch?v=g1nesioHo_c), 2023-08-15, 4:58 | Poker After Dark cash-game segment; the betting structure is not established by the available hand-specific sources. | 4 | Preserved as an unscored source. The clip starts during Ivey’s preflop raise, so that decision has no predecision still. [PGT coverage](https://www.pgt.com/news/blowup-alert-hellmuth-traps-ivey-with-the-worst-hand) |
| [PokerGO — Phil Ivey vs Doyle Brunson Cash Game Clash](https://www.youtube.com/watch?v=5TX7WuLl7IQ), 2020-11-30, 3:07 | Super High Roller cash game; event reporting supports NLHE and $400/$800 blinds with $200 ante. | 4 | Eligible; stack displays are rounded and seat positions are unavailable. [Event report](https://www.pokernews.com/news/2015/06/super-high-roller-cash-game-1-22103.htm) |
| [Triton Poker — Can Phil Ivey find the right move with his tournament life at risk?](https://www.youtube.com/watch?v=KjreElAgfRk), 2022-09-11, 9:37 | $200K Coin Rivet Invitational NLH tournament; 3K/6K blinds with 6K big-blind ante. | 4 | Eligible; button is visible. Stack headers use rounded K-style values. [Hand report](https://highstakesdb.com/news/live-poker-news/phil-ivey-s-a-bluff-catcher-in-huge-pot-vs-christoph-vogelsang-in-200k-coin-rivet-invitational) |

Three of the four selected hands have support for standard NLHE. The
Hellmuth/Poker After Dark hand remains unscored because its no-limit betting
structure could not be independently confirmed. Public records identify the
Triton hand as tournament NLH; the PokerGO Super High Roller hands are cash
games. Shark Cage and Short Deck are not included in standard NLHE scoring.

## Decision transcription and retained frames

The structured record in
[`hand-reviews.json`](../data/public_ivey_videos/hand-reviews.json) stores each
Ivey decision’s hero-visible state separately from its observed action. It
contains 18 action labels: six for Aw_KVPxe7d0, four for g1nesioHo_c, four for
5TX7WuLl7IQ, and four for KjreElAgfRk.

| Video | Decisions in order | Retained predecision frames |
|---|---|---:|
| Aw_KVPxe7d0 | 00:20 preflop call 2,500; 00:55 preflop call 12,500; 01:40 flop call 30,000; 02:30 flop call 70,000; 03:10 turn check; 03:40 turn fold facing 154,000. | 6 |
| g1nesioHo_c | 00:00 preflop raise to 2,500 (clip begins during/after the action; no frame); 00:38 flop bet 8,000; 01:18 turn bet 23,000; 02:03 turn call after Hellmuth moves all-in to 80,300; exact capped payment unresolved. | 3 |
| 5TX7WuLl7IQ | 00:20 preflop call 3,500; 00:50 flop raise to 20,000 after 7,000 bet; 01:30 turn bet 30,000; 02:10 river bet 80,000 (river still withdrawn). | 3 |
| KjreElAgfRk | 00:25 button open to 13,000; 02:00 flop bet 16,000; 04:30 turn call 55,000; 05:45 river all-in call versus 250,000 bet. | 4 |

Frames are sparse stills sampled before the corresponding action when the clip
shows a decision window. The retained set excludes the equity-exposing river
frame identified during review. Opponent hole cards and equity graphics are
covered with opaque black masks, including equity attached to Ivey’s own
cards. A frame is omitted where the source starts during the action. No full
movie or audio file is retained. The timestamp is relative to the original
YouTube video and is recorded with each image.

For the Aw hand, the public hand report identifies Ivey as hijack, but the
local protocol supports only UTG/MP/CO/BTN/SB/BB; its protocol `position` is
therefore null. In the Triton hand, the button and blind/ante level are
visible. For the other hands, seat positions and/or blind levels remain
unknown where the source does not support an exact value.

## State quality and exclusions

There are 18 action labels and 16 retained predecision frames. No source
provides an exact hero stack at every decision: some displays are rounded to
thousands, and others do not show a stack. The records keep those values null
and store rounded display text separately. Missing pot, call, position, legal
action, and raise-bound values are also left null rather than inferred from
the action label. Exact pot and call figures are retained only where shown or
supported by the action sequence.

As a result, **zero of the 18 states is a complete local `Observation`, and
zero hands supports a complete PHH replay**. The records are evidence-backed
partial states and factual action labels, not padded benchmark rows. The
standard-NLHE confirmed subset has three hands and 14 decision labels. It is
too small and incomplete to support a >99% agreement estimate. No bot strategy
or output was consulted.

Other screened public official sources and reasons for exclusion:

- [Triton Poker, 0Sxl63GSLJ0](https://www.youtube.com/watch?v=0Sxl63GSLJ0):
  published description identifies €100K Short Deck; nonstandard variant.
- [PokerStars, fcegeGil86M](https://www.youtube.com/watch?v=fcegeGil86M):
  Shark Cage rules; nonstandard variant.
- [PokerStars, SIfMqu_IkaA](https://www.youtube.com/watch?v=SIfMqu_IkaA):
  *Greatest Poker Moments From Phil Ivey* compilation, not one hand.
- [World Poker Tour, daR3q3KKQ0o](https://www.youtube.com/watch?v=daR3q3KKQ0o):
  11,131-second heads-up match broadcast, not a hand-specific clip.
- [Triton Poker, jdiDizWlIz0](https://www.youtube.com/watch?v=jdiDizWlIz0):
  locked from metadata as a candidate for expansion, then excluded when review
  showed multiple unrelated hands intercut throughout the video.

No full-length video files were retained in the repository. The source videos
remain attributable by their original URLs, official channel names/IDs, and
timestamps in the manifest and hand records.
