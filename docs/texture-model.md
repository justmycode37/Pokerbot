# Suited-board equity model

`pokerbot.texture.suited_board_equity(obs)` returns a uniform-card equity
estimate for a made flush on selected four- and five-suited public boards. It
returns `None` when the board or hero hand falls outside those conditions. The
caller can then retain its existing estimate.

## Supported cases

- **River:** five public cards, ranks unpaired, and exactly four or five cards
  of one suit on the board. Hero must have a flush or straight flush.
- **Turn:** four public cards, ranks unpaired, and all four share a suit. Hero
  must have a flush. A non-straight flush is supported only when every private
  card of that suit ranks below the lowest public card of that suit. A made
  straight flush is also supported.
- Both paths accept 2 through 8 active players and treat all opponents' hole
  cards as uniformly dealt from the remaining deck, without replacement.

Other streets, paired boards, boards with other suit counts, and unsupported
turn flushes return `None`. The turn restriction keeps the conservative floor
focused on the low flushes that were being overvalued. A paired river can make
a full house or quads, so ordinary turn flushes do not receive credit for those
runouts. A straight flush remains ahead of those categories.

## River calculation: exact

On an unpaired board, two private cards cannot make a full house or quads.
With four public cards of a suit, an opponent needs at least one more card of
that suit to make a flush; with five, everyone already has the board flush.
Only the zero-, one-, or two-card combinations of the board's suit can tie or
beat hero. Other private cards matter only as available card counts.

For example, on `Jc 9c Tc Ac 2d` with `4c` in hero's hand, six unseen clubs
(`5c`, `6c`, `7c`, `8c`, `Qc`, and `Kc`) can beat the flush. Holding `8c`
instead blocks one of those cards, leaving only `Qc` and `Kc` above hero's
flush. The multiway count deals all opponent cards without replacement, so a
single higher club cannot be assigned to two different players.

The implementation ranks those suited combinations, including two-card-only
straight flushes. It first counts the chance of dealing no individually
winning suited card. Conditional on that event, remaining winning pairs form
a graph over physical cards. Inclusion-exclusion counts disjoint edge
matchings: intersecting pair events cannot reuse the same card, and disjoint
pairs must belong to different opponents. This accounts for suit blockers
without enumerating each opponent's deal. On a five-suited board where hero plays the board, every
non-winning opponent ties, so the safe-deal count is divided by the number of
players. When hero improves the board flush, or on a four-suited board, a tie
would require a suited card already held by hero; therefore safe deals are
wins. No runtime Monte Carlo is used.

## Turn calculation: conservative lower bound

For each possible river card, the code counts a subset of deals on which no
opponent receives a suited card that could tie or beat hero. It also excludes
both cards of any two-card straight-flush completion, even when each card by
itself looks harmless. Those safe deals contribute a combinatorial count; a
paired river contributes zero for an ordinary flush. The result is averaged
over all possible river cards. For a made straight flush, paired rivers are
counted too because full houses and quads cannot beat a straight flush.

This turn value is a lower bound, not an unbiased estimate. It intentionally
discards safe hands and paired-board runouts, so it can understate equity. In
particular, the implementation returns `None` for non-straight turn flushes
whose private suited cards rise above the public suit ranks.

## Numeric checks

The checks below compare against `pokerbot.cards.estimate_equity` with its
uniform random-card model. Monte Carlo values have sampling noise; the river
calculation itself is exact. Seeds and sample counts are included for
reproduction.

| State | Model result | Uniform MC | Difference | Samples / seed |
| --- | ---: | ---: | ---: | --- |
| Turn `8s 4c`, `Jc 9c Tc Ac`, 8 active | 0.055968 lower bound | 0.077431 | -0.021463 | 60,000 / 8127 |
| Turn `Kc Qc`, `Jc 9c Tc Ac`, 8 active (royal flush) | 1.000000 exact | 1.000000 | 0.000000 | 30,000 / 6161 |
| River `8s 4c`, `Jc 9c Tc Ac 2d`, 4 active | 0.400565 exact | 0.399100 | +0.001465 | 60,000 / 991 |
| River `As Kd`, `Ac Kc 9c 6c 3c`, 3 active (board tie) | 0.165140 exact | 0.165356 | -0.000216 | 60,000 / 341 |
| River `Kc As`, `4c 5c 6c Tc Kd`, heads-up (pair-only straight-flush threat) | 0.952525 exact | 0.952417 | +0.000109 | 60,000 / 718 |
| River `Kc Qc`, `Jc 9c Tc Ac 2d`, 8 active (royal flush) | 1.000000 exact | 1.000000 | 0.000000 | 20,000 / 552 |

The pair-only straight-flush case also matches exhaustive enumeration of all
990 possible heads-up opponent holdings. The tests check exact combinatorial
values for weak flushes and multiway board ties, plus blockers, nut flushes,
unsupported boards, and the turn lower bound.

As an additional offline check, 20 randomly generated supported river states
(10 four-suited and 10 five-suited) were each compared against exhaustive
heads-up enumeration of all 990 opponent hands. Maximum absolute error was
0.000000000000.

## Runtime

There is no sampling at runtime. A broader integration check of 200 seeded
unpaired four-suit river states with seven opponents found that the original
opponent-deal dynamic program sometimes exceeded 2 ms. The parent replaced
that counting step with the equivalent matching-graph inclusion-exclusion
calculation above. On the same cold-rank-cache states, median was 27.0 μs,
p95 31.8 μs, and the maximum 415.1 μs; no sample exceeded 1 ms. This is a local
measurement, not a guarantee for an unknown event sandbox. The turn floor
retains the original bounded combinatorial calculation.
