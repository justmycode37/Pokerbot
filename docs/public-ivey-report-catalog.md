# Public Phil Ivey NLHE decision evidence

This catalog covers the new source acquisition in [`decision-evidence.json`](../data/public_ivey_reports/decision-evidence.json). It records attributable public hand facts and decision snapshots. It does not tune the bot or duplicate the already-present Dwan–Ivey PHH and CardPlayer `/1921` record.

## Acquired evidence

| Hand | Public hand sources | Usable Ivey decisions | Notes |
|---|---|---:|---|
| 2014 Aussie Millions $250K Challenge: Fabian Quoss | [CardPlayer matchup](https://www.cardplayer.com/hand-matchups/1806), [PokerNews live report](https://www.pokernews.com/tours/aussie-millions/2014-aussie-millions/250k-challenge/chips.77749.htm) | 1 | Ivey’s preflop 3-bet decision; five antes are included in the derived 345,000 pot. Quoss’s all-in target is derived from the reported 880,000 raise over Ivey’s 530,000. |
| 2014 Aussie Millions $250,000 Challenge: Isaac Haxton | [CardPlayer matchup](https://www.cardplayer.com/hand-matchups/1808), [PokerNews final-hand report](https://www.pokernews.com/tours/aussie-millions/2014-aussie-millions/250k-challenge/post.225799.htm) | 1 | Ivey’s initial button decision. The 280,000 pot includes both 20,000 antes and both blinds. His call target is 160,000. |
| 2020 MILLIONS Sochi $25,000 NLHE: Ivan Leow and Ben Heath | [CardPlayer matchup](https://www.cardplayer.com/poker-tools/hand-matchups/2441), [PokerNews event context](https://www.pokernews.com/news/2020/03/sam-trickett-shrs-sochi-36762.htm) | 3 | Ivey decisions on flop, turn, and river. The source calls his position hijack; protocol position `MP` is a derived coarse mapping. Exact hand date is unknown; the festival range is March 6–15, 2020. |
| 2018 WSOP Big One for One Drop: Justin Bonomo | [CardPlayer matchup](https://www.cardplayer.com/poker-tools/hand-matchups/2276), [PokerNews hand recap](https://www.pokernews.com/tours/wsop/2018-wsop/news/top-five-hands-1-million-big-one-for-one-drop-30543.htm), [PokerGO Tour Day 2 context](https://www.pgt.com/news/phil-ivey-headlines-day-2-of-big-one-for-one-drop-on-pokergo) | 1 | Ivey’s preflop cutoff open. The reports disagree on Ivey’s later river decision amount (5.17M vs. 5.12M), so later snapshots are excluded. Exact hand date is not reported. |

**New total:** 3 complete hand histories plus 1 partial hand record with a usable preflop decision; 4 distinct hands with usable decisions; 6 protocol snapshots; 0 PHH records. Each raise label is an exact total street target. The JSON puts the expected label outside the observation and keeps revealed opponent cards and later board cards out of observations. It marks each observation field as observed or derived and documents the derivation. Pots include all known blinds and antes.

The Bonomo hand’s preflop state uses CardPlayer’s hand-start stack as reported. PokerNews’s later 5.12M decision amount conflicts with CardPlayer’s 5.17M call amount; no stack is reconstructed for later streets. This evidence is not a promise of 99% decision agreement.

## YouTube search

An official [PokerStars Global Aussie Millions 2014 $250K Challenge episode](https://www.youtube.com/watch?v=kNrn0OibLi8) was found and recorded as event-level supplemental material. Public video metadata did not identify a timestamp for either the Quoss or Haxton hand, so the video contributes no hand facts or decision snapshot. No individual hand timestamp was verified.

## Candidates excluded from verified snapshots

- [PokerNews online railbird report, June 3, 2015](https://www.pokernews.com/news/2015/06/the-online-railbird-report-you-wont-believe-how-much-phil-i-21882.htm): action and cards are reported, with HighStakesDB credited for the underlying data, but the ante structure is unstated and some pot reporting is rounded or cannot be reconstructed without assumptions. Hand 2 also omits the opponent’s exact cards.
- [Ivey–Cary Katz, 2014 WSOP Big One](https://www.cardplayer.com/hand-matchups/1857): the per-player ante count is not known, so the pot at a decision cannot be calculated exactly.
- [Ivey–Quinn Do, 2008 WPT L.A. Poker Classic](https://www.worldpokertour.com/live-update/hand-100-phil-ivey-wins-the-wpt-l-a-poker-classic-1596100-la-poker-classic-level-30-100000-200000): the update header’s 100K/200K blinds conflict with the reported 160K button limp; the exact ante and Ivey’s hand-start stack are unresolved.
- [Ivey–Hellmuth, 2015 WSOP Main Event](https://www.cardplayer.com/hand-matchups/1980): Ivey’s exact remaining stack and shove target are absent; pot reconstruction also depends on the unreported number of posted antes.
- [CardPlayer hand matchup 156](https://www.cardplayer.com/hand-matchups/156): exact blinds and ante are given, but table size is not, so the total ante pot is unknown.
- [PokerNews 2014 WSOP Main Event Day 4 hands](https://www.pokernews.com/strategy/phil-ivey-at-the-feature-table-two-hands-from-the-2014-wsop-19533.htm): the first hand gives only “more than 500,000” for Ivey’s starting stack; the second omits Ivey’s exact stack and exact river bet target.
- [Ivey’s 2018 WSOP Big One elimination hand](https://www.pokernews.com/tours/wsop/2018-wsop/event-78-the-big-one-for-one-drop-1000000/chips.232842.htm): cards, positions, board, blinds, and ante are attributable, but Ivey’s stack and shove target are missing.
- [CardPlayer’s 2015 Aussie Millions Ivey–McDonald matchup](https://www.cardplayer.com/poker-tools/hand-matchups/1923) cannot be confidently matched to [PokerNews’s live report](https://www.pokernews.com/tours/aussie-millions/2015-aussie-millions/250000-challenge/post.238638.htm). Both concern the heads-up event and say Ivey held K♣Q♣, but list incompatible opponent cards, boards, and action. PokerNews’s report does not reveal Ivey’s cards or exact starting stack. The sources are not merged.

The JSON retains these exclusions with the specific missing or conflicting facts and source names. No incomplete or rounded later-street state is represented as verified; the Bonomo record is explicitly marked partial and contributes only its supported preflop snapshot.
