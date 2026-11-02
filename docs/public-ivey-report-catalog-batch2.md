# Public Ivey report catalog — batch 2

## Result

**Source-review errata:** use the separately derived records and
[admission notes](report-batch2-source-audit.md) for comparison. The immutable raw
capture has an incorrect Heath `added` payment in two later prefixes, overstates
the small-blind fold as explicitly reported, and labels one derived shove history
too broadly as observed. The derived replay corrects these issues. The original
PDF explicitly identifies three players in the Heath hand.

This source-only pass added **5 complete, distinct no-limit hold'em hands and 22 Ivey decision snapshots** across two sessions. Four hands came from the same CardPlayer issue; one came from a CardPlayer matchup page and the corresponding PokerNews event report. Each snapshot contains one Ivey decision, an exact public action prefix as available, and a separate expected-action label.

This is a convenience sample of public reporting. It does not establish representative Ivey decision agreement or a 99% result.

The machine-readable facts and snapshots are in [decision-evidence.json](../data/public_ivey_reports_batch2/decision-evidence.json). The selection process and screened candidates are in [selection-method.json](../data/public_ivey_reports_batch2/selection-method.json). State fields follow [state-protocol.md](state-protocol.md).

## Selection method

Before opening hand-level action, the candidate list was locked from the CardPlayer matchup archive first, then PokerNews original reports and hand features, and public broadcaster/tour recaps where available. The fixed search queries and metadata-only lock rule are recorded in selection-method.json.

The initial list contained ten candidate slots. Two source slots produced evidence: the CardPlayer Volume 35, Issue 16 PDF contained four distinct Ivey matchups, and the Triton Jeju Punsri matchup page supplied one. All four Ivey hands in the issue were retained together once the issue was opened; none was selected or replaced based on action, outcome, strategy, or expected bot agreement. In total, five complete hands were usable. The other locked candidates remain listed with specific exclusion reasons.

Prior corpus checks excluded repeats from CardPlayer matchup IDs 1806 (Quoss), 1808 (Haxton), 2441 (Sochi), 2276 (Bonomo), and 1921 (Polk), as well as historical Dwan-Ivey 2009 material and PokerGO video YfjDfPk7e1E.

No strategy, model, performance, prediction, or bot-match material was read or compared during selection or reconstruction.

## Included hands

| Hand | Session | Ivey decisions | Expected actions |
| --- | --- | ---: | --- |
| Ivey vs. Ben Heath, WSOP Event #42 | 2022-06-20 | 3 | Raise, call, raise-to all-in |
| Ivey vs. Aleksejs Ponakovs, Q♣9♦ hand | 2022-06-20 | 5 | Raise, bet, call, check, call |
| Ivey vs. Aleksejs Ponakovs, T♠9♠ hand | 2022-06-20 | 5 | Call, check, bet, bet, fold |
| Ivey vs. Aleksejs Ponakovs, final hand | 2022-06-20 | 4 | Raise, check, check, raise-to all-in |
| Ivey vs. Punnat Punsri, Triton Jeju Event #8 | 2024-03-12 | 5 | Call, bet, check, bet, call |

Across the 22 decisions, the raw actions are 10 raises/bets, 6 calls, 5 checks, and 1 fold. The local protocol represents a bet with a raise action and the total street target; the raw hand record retains whether a source described it as a bet or raise.

### WSOP Event #42

The CardPlayer issue provides the hand details, starting stacks, cards, boards, blinds, and action for all four included hands. The [PokerNews Event #42 Day 2 report](https://www.pokernews.com/tours/wsop/2022-wsop/event-42-100000-high-roller/) supplies the event/date cross-check and additional hand reporting. The [hand-highlight view](https://www.pokernews.com/tours/wsop/2022-wsop/event-42-100000-high-roller/?highlights=1) cross-checks the final hand.

- **Ivey–Heath:** Ivey's button open, call of Heath's three-bet, and flop shove. The small blind's reported fold is kept as an unidentified player. The source does not enumerate earlier-position folds, so their count and identities remain unknown.
- **Ivey–Ponakovs, Q♣9♦:** Ivey's preflop open, flop bet, call of a check-raise, turn check, and river call.
- **Ivey–Ponakovs, T♠9♠:** Ivey's preflop call, flop check, turn bet, river bet, and fold to a river shove.
- **Ivey–Ponakovs, final hand:** Ivey's preflop three-bet, flop and turn checks, and turn all-in raise.

The exact targets are separated from rounded source amounts. The Heath hand's shove target is derived as **6,575,000** from Ivey's 8,425,000 starting stack and 1,850,000 preflop contribution; CardPlayer rounds the shove to 6.58 million. Ponakovs's river all-in in the T♠9♠ hand is derived as **11,375,000** from his 12,975,000 starting stack less 700,000 preflop and 900,000 turn contributions; PokerNews rounds it to 11.4 million. Ivey's final-hand turn shove is derived as **11,025,000** from his 14,225,000 stack less 3,200,000 preflop contribution; sources round it to 11.03 million/about 11.0 million. Each derivation is marked in the raw action record and snapshot label metadata.

Primary issue source: [CardPlayer Volume 35, Issue 16 PDF](https://media.cardplayer.com/assets/magazines/000/066/494/pdf/35_16_web.pdf).

### Triton Jeju Event #8

The [CardPlayer matchup](https://www.cardplayer.com/poker-tools/hand-matchups/2851) and [PokerNews event report](https://www.pokernews.com/news/2024/03/50k-triton-poker-jeju-45587.htm) identify Ivey with K♥J♣ against Punnat Punsri with T♥3♥, give their starting stacks and blind/ante level, and report the action and full board. The five Ivey decisions are the preflop call, flop bet, turn check, river bet, and call of Punsri's check-raise.

The source reports that the action folded to Punsri in the small blind. The number and identities of those folded players are not specified, so they are not invented in the state. The public action prefix records the reported action from Punsri's raise onward.

## State and label handling

- The hand facts preserve source URLs, ISO event dates, hand-start stacks, private cards for both players, board by street, blind and big-blind-ante amounts, and reported action targets.
- Each snapshot's state includes only Ivey's hole cards and the board visible at that decision. Opponent cards, future board cards, later actions, and outcomes remain outside state.
- Expected action is stored separately from the input state. Raise amounts are total street targets. Reported bets map to the protocol's raise action.
- Every snapshot has field-level observed/derived/unknown status and a basis. Exact hand timestamps and unreported table/fold details remain unknown.
- Players-to-act counts opponents who have not acted yet before the street can end. A player who checked is not counted again unless Ivey makes a new bet or raise.
- Pots include forced chips and all outstanding street bets. Stack, call amount, and raise bounds use the known stack ledger. A state with no legal raise uses zero raise bounds.

## Screened but not included

| Candidate | Outcome | Why no decision snapshot was built |
| --- | --- | --- |
| 2024 Triton Montenegro, Ivey vs. Mikalai Vaskaboinikau | Excluded | The [CardPlayer issue](https://media.cardplayer.com/assets/magazines/000/066/544/pdf/37_14_web.pdf) and [event recap](https://www.cardplayer.com/poker-news/28927-mikalai-vaskaboinikau-wins-triton-poker-main-event-for-4-7-million) provide a summarized line and stack figures that do not reconcile to one exact effective-stack/pot ledger; exact pot-at-decision values are absent. |
| PokerNews Ivey–Dan Cates straight-flush vs. quads feature | Excluded | The [article](https://www.pokernews.com/strategy/dan-jungleman-cates-analyzes-straight-flush-vs-quads-hand-ag-35043.htm) gives an approximate stack and action but not Ivey's exact stack, shove target, and complete blind/ante structure. |
| PokerNews “Jaw-Dropping Reads” entries #5, #4, #3, and #2 | Excluded | The [article](https://www.pokernews.com/news/2022/01/phil-ivey-top-poker-reads-40477.htm) gives hand narratives, but not a complete exact stack/pot/ante ledger and raise bounds for all required decisions. |
| 2026 WSOP $25,000 Heads-Up, Ivey vs. Shota Nakanishi | Excluded | The [report](https://www.pokernews.com/news/2026/06/2026-wsop-hands-of-the-week-1-51411.htm) gives the cards, jam/call, and board but not blinds/ante, Ivey's exact stack or shove target, and exact pot. |
| 2022 Hustler Casino Live, Ivey vs. Eric Persson | Excluded | The [report](https://www.pokernews.com/news/2022/09/phil-ivey-hustler-casino-live-adelstein-42188.htm) lacks exact blinds/ante, full action prefix, stacks, pot, and raise bounds. |

## Limits

This batch broadens the available public evidence but remains a convenience sample, especially weighted toward matchup pages, final-table hands, and memorable action. The action mix is useful for coverage review, not a representative frequency estimate. It cannot establish a 99% Ivey decision-agreement result.

No full video or source prose was copied into the dataset; the JSON contains concise factual records and direct source URLs only.
