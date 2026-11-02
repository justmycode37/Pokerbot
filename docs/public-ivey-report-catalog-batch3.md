# Public Ivey report catalog — batch 3

Acquired 2026-10-31. One hand is source-confirmed but remains partial; **zero exact decision states are admitted** after independent review. Five other candidates are excluded or partial. The six-candidate list was frozen before opening source pages for detailed hand-state review. Initial discovery-search snippets did show brief hand-summary/outcome text for some leads before the freeze; this process caveat is retained in the ledger. No candidate was added or replaced during detailed review. The fixed candidate list and source-by-source exclusion evidence are in [`search_ledger.json`](../data/public_ivey_reports_batch3/search_ledger.json). The partial hand record is in [`hands.json`](../data/public_ivey_reports_batch3/hands.json).

## Source-confirmed partial hand

### B3-H01 — 2009 WSOP Main Event, Hand No. 175

The hand-specific Card Player matchup page reports a seven-handed table, Ivey's hand-start stack as 6,525,000, A♣K♠, blinds of 300,000/600,000, and a 75,000 ante. Its hand-specific state is at the card panel and “Outcome” paragraph; the page is dated Nov. 12, 2009. The ante is stored separately as dead money. The source does not separately state Ivey's chips behind after forced posts or the numeric all-in amount, so those fields remain unknown.

Independent review found that the reported “Starting Stack” is not explicitly
defined relative to the ante, and the ante-posting type is unspecified on these
pages. A shove of 6,450,000 assumes a pre-ante stack and one 75,000 individual
ante; 6,525,000 assumes the reported figure is already net of the ante. Neither
numeric shove is directly established. “First to act” is reported; UTG is its
derived positional label. This hand must not enter exact scoring until the
stack/ante timing or numeric shove is corroborated by a primary source.

The contemporaneous [PokerNews live report](https://www.pokernews.com/tours/wsop/wsop-2009-final-table/november-nine/post.125257.htm) is dated Nov. 7, 2009; see “Phil Ivey - 7th Place,” Hand No. 175. It records Ivey as first to act and the preflop all-in. The [official WSOP recap](https://www.wsop.com/news/and-then-there-were-two/) is dated Nov. 8, 2009 at 9:32 a.m. EST and confirms the event report. These HTML pages are not paginated and do not supply a video timecode.

Only the hero-visible predecision state and Ivey's all-in decision are retained. No post-decision cards, board, hand result, odds, expected value, or strategy analysis is included in the hand record. No starting nine-handed table state was mapped to eight: the hand-specific source explicitly reports seven-handed play at this point.

## Excluded and partial candidates

| Candidate | Event/source group | Disposition |
| --- | --- | --- |
| B3-C01 | 2005 Monte Carlo Millions, Ivey–Jackson | Excluded because public reports disagree on numeric flop raise sizes. [Thinking Poker](https://www.thinkingpoker.net/articles/lastbet/) (originally in the April 2007 *Two Plus Two Magazine* issue) reports 80,000, 256,000, +240,000, +300,000, and +581,000. [ESPN](https://www.espn.com/espn/poker/news/story?id=2243642) (Dec. 1, 2005, 12:21 p.m. ET) describes different 150,000 raises; [GGPoker](https://ggpoker.com/blog/pokers-greatest-bluffs-a-collection/) gives 320,000 and 470,000. These amounts were not reconciled. |
| B3-C03 | 2004 Borgata Open, Ivey–Arieh | Excluded because the Card Player hand discussion reports blinds, ante, a middle-position raise, Arieh's call, and Ivey's 403,000 all-in, but does not identify Ivey's position or earlier action. A separate [Card Player event history](https://www.cardplayer.com/cardplayer-poker-magazines/66182-thomas-pederson-8-12/articles/20339-hand-history-time-capsule-daniel-negreanu) describes a six-player final group but does not establish that this specific hand occurred at that table. Full prefix and hand-specific table state are unverified. |
| B3-C04 | 2003 WSOP Main Event, Ivey–Moneymaker | Excluded because the [Card Player recap](https://www.cardplayer.com/poker-news/4658-wsop-history-2003-recap) (July 12, 2008; hand paragraph in the 2003 recap) gives an action narrative but no exact stack, blind, ante, or table-size state. The official [WSOP/PokerGO summary](https://www.wsop.com/news/wsop-highlights-powered-by-pokergo-2003-wsop-main-event-top-5-hands/) and [PokerGO clip](https://www.youtube.com/watch?v=UizvPd9J4UI) confirm the matchup but provide no numeric predecision state in the accessible page metadata. |
| B3-C05 | 2007 Poker After Dark, “Earphones Please” | Excluded in this batch because no public report page with an exact timestamped Ivey state was located. The [PokerGO collection](https://www.pokergo.com/collections/poker-after-dark-season-1-2007-week-4) lists the six-player event and shows a login control; public [official YouTube episode metadata](https://www.youtube.com/watch?v=L6wGVXvYZq8) supplies the episode and lineup, not hand states. No account access or paywall bypass was used. |
| B3-C06 | 2014 WSOP Event #57, Big One for One Drop, Ivey–Katz | Kept partial and not admitted. [Card Player Hand Matchup #1857](https://www.cardplayer.com/hand-matchups/1857) (July 23, 2014; card panel and “Outcome” paragraph) reports the cards, hand-start stacks, blinds/ante, and Ivey's call, check, and all-in sequence. It omits the hand-specific table size and the action prefix before Katz's raise, so no table size or missing action was inferred. |

## Scope and handling

- The candidate ledger preserves all six search outcomes and the reasons for exclusion or partial status.
- Only public pages were used. No accounts, cookies, paywall bypass, full video, or full source prose were retained.
- No project strategy, model, prediction, or results files were read. Source-page odds and strategic commentary were not copied into the data.
- No files outside `data/public_ivey_reports_batch3/` and this catalog were edited. No commit was made.
