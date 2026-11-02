# Fast policy v3

The current implementation is `fast-heuristic-v3`. It retains the v2 preflop
fixes and shared-board tie handling, and uses the [suited-board model](texture-model.md)
for supported flush textures. That model already accounts for blockers and
opponent count, so generic texture and multiway penalties are not applied a
second time. Supported river values are exact against uniformly dealt
unknown opponents; the restricted turn path is a conservative lower bound.
This does not recover actual opponent ranges or Ivey's decision policy.

Revision 2 fixes first-in preflop decisions when the posted blind is still to
call, separates visible limpers/raisers from seats waiting to act, and preserves
the exact multiway share for an unbeatable royal flush on the board. The prior
warm-call benchmark was recorded for v1; a fresh v2 sample is reported below.

## Scope and assumptions

`pokerbot.fast.decide(raw)` implements the repository's internal observation
protocol by calling `Observation.from_dict`. The official tournament variant,
starter SDK, action encoding, and execution environment are not yet known, so
this is a provisional no-limit Texas Hold'em policy. It needs an adapter and
review against the event kit when those details are released.

The policy uses only the validated hero cards, public board, public action
history, pot, stack, position, player counts, and legal bounds in the current
observation. It does not use showdown labels, opponent cards, outcomes, or
Ivey data. Runtime equity is estimated from a static table before the flop and
simple hand, draw, texture, price, and player-count heuristics after the flop;
it does not sample cards at runtime.

## Preflop policy

`data/preflop_equity.json` contains 169 starting-hand classes and their
estimated equity against one uniformly random opponent. It was generated with
1,000 samples per class, base seed `260131`, and seed `base + class index` in
the builder's stable class order. The representatives are suit-equivalent
examples. The values are rough baselines, not equity against an observed
raising range.

An unopened pot is identified by no visible voluntary preflop entrant and a
highest street bet no greater than the big blind. Those decisions use a
raise-or-fold mix even when `to_call` equals the posted big blind. AA and KK
always raise when raising is legal. A visible caller makes the pot limped;
visible calls/raises, rather than `players_active`, determine how many
opponents have entered. `players_to_act` can tighten an opening cutoff but is
never counted as an opponent already in the pot.

Unopened raises use these cutoffs on that random-opponent equity scale:

| Position | Cutoff |
| --- | ---: |
| UTG | 0.625 |
| MP | 0.605 |
| CO | 0.575 |
| BTN | 0.545 |
| SB | 0.565 |
| BB | 0.615 |

The BB checks its free option by default and raises limpers for value with a
strong hand. Facing a raise, the policy discounts table equity for the implied
opponent range, tightens for visible extra callers and early/out-of-position
seats, then compares the result with pot odds plus a margin. The BB gets a
smaller call margin. Short-stack opens widen as the stack falls below 16, 10,
and 6 big blinds; at 10 big blinds or less, selected value raises go to the
maximum legal total. Deeper opens target 2.25 big blinds, and deeper re-raises
target about three times the call total, bounded by the observation.

## Postflop policy

The existing exact `rank_hand` evaluator identifies the best made hand. Fixed
category estimates are adjusted for hole-card contribution, overcards, flush
and straight outs, board pairing/connectivity/suits, the number of opponents,
and the visible current-street aggression. Calls compare that adjusted estimate
with `to_call / (contestable_pot + to_call)` plus a margin. River decisions do
not count future draws. An exact board-play tie suppresses raises. A board
royal flush is an unbeatable shared hand: equity stays exactly
`1 / players_active`, with no pressure, multiway, or texture discount, and it
continues whenever that share exceeds raw pot odds.

Value raises and bets are weighted by hand strength. Small six-to-eight percent
raise weights provide some heads-up late-position bluffs on dry boards and
semi-bluffs with strong draws. A stable hash of the supplied seed and known
cards selects from the reported action probabilities, so the same observation
replays identically without a runtime RNG. The `amount` and `raise_amount`
fields are total street bets; all targets are clamped through
`Observation.raise_to` to the legal min/max range.

## Building and checking the table

Run the build-time generator from the repository root:

```sh
python3 scripts/build_preflop_table.py --samples 1000 --seed 260131
```

It uses `pokerbot.cards.estimate_equity` offline and writes only the specified
table file. The runtime imports no external dependency; if the table is missing
it has a conservative analytic fallback.

Focused implementation tests:

```sh
python3 -m unittest discover -s tests -p 'test_fast.py' -v
```

The tests cover the repository decision example, premium first-in raises across
positions, limped pots, BB defense, free BB checks, exact board-play ties,
legal calls/folds, short-stack total-bet bounds, and varied postflop fixtures.

## Warm-call timing sample

On Python 3.12.10, macOS 26.6.2 arm64, 30,000 calls cycling through the
repository preflop example, a draw-heavy flop, a royal-board tie, and BB
defense against a button open, after 1,000 warm-up calls per fixture, measured
v2 decision time was:

| Percentile | Time |
| --- | ---: |
| Median | 21.17 µs |
| p95 | 34.33 µs |
| p99 | 36.29 µs |

The largest sampled call was 206.50 µs. This local sample does not establish a
1 ms guarantee in the unknown official sandbox; the event SDK and target
runtime still need profiling. The warm-call figures exclude Python startup and
the one-time JSON table load at module import.

This is a compact heuristic policy, not a solver or a claim of GTO play.
