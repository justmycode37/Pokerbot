# Endgame overlay

`pokerbot.endgame` provides a deterministic push/fold overlay for short stacks
and a heads-up policy for every stack depth. It consumes the public
`Observation` protocol and returns the same decision shape as the other local
policies. `wrap_policy(base_policy, params=None)` uses the overlay when it
applies and otherwise calls the supplied policy.

## Design

The tournament raises blinds from 20 to 2,560 and doubles them every 25 hands,
with a 200-hand cap. The policy uses the current `big_blind` on each decision,
so its stack depth follows the live blind level. The engine has no ante field;
an optional `ante_bb` parameter adds an assumed ante to shove and call odds.

For three or more active players, the overlay handles preflop decisions when
`(stack + current_bet) / big_blind <= short_stack_bb` (default 16 BB). It
converts the equity table's random-opponent values to a transparent chart
cutoff. Position, stack depth, players yet to act, limpers, field size, a
supplied caller-frequency estimate, and assumed dead ante chips adjust that
cutoff. Facing a raise, it distinguishes an all-in price from a normal open;
the former uses a range-adjusted call chart and the latter a short-stack
defend/rejam rule. Postflop multiway decisions and full-ring decisions above
the threshold go to the base policy.

The state protocol does not disclose opponent stacks or antes. Consequently,
the chart uses hero's preflop stack as its depth estimate and only models antes
when configured. The lookup is the repository's offline preflop equity against
one random hand. The cutoffs are analytic approximations for chip-EV under
winner-take-all incentives, not output from a solved equilibrium or a
multiway Monte Carlo table.

Heads-up play applies at all depths. Preflop it opens or completes from the
button, defends and three-bets from the big blind, and shifts to shoves at
short depths. Postflop it uses the fast policy's public hand and draw
evaluation, which is inexpensive and deterministic from the observation seed.
It never reads private opponent cards, hidden stacks, results, or evaluation
labels.

`wrap_policy` keeps smoothed call/fold frequencies from the visible action
history in wrapper-local state. These table-local estimates can tighten a
shove range against opponents who call frequently. Call and fold are only
treated as observations of responses to pressure; they are a crude proxy, not
a calibrated all-in calling model. The wrapper's `reset()` clears its local
state and forwards reset to the base policy.

## Interface

```python
from pokerbot.endgame import endgame_decision, wrap_policy
from pokerbot.state import Observation

decision = endgame_decision(obs, params={"short_stack_bb": 14, "ante_bb": 0.1})
policy = wrap_policy(base_policy, params={"short_stack_bb": 14})
```

Supported overlay parameters are `short_stack_bb` (default 16), `ante_bb`
(default 0), `heads_up_aggression` (default 1.0), and `call_shove_margin`
(default 0.095). Heads-up aggression scales preflop opening, calling, and
jamming cutoffs; a larger value widens those ranges. The call-shove margin sets
the minimum equity above pot odds, alongside the range-adjusted chart floor.
`opponent_stats` may map public player IDs to a call frequency in `[0, 1]` or
to a mapping containing `call_frequency`. The standalone function returns
`None` outside the overlay's range. The wrapper returns the base policy's
result in that case. Raise amounts use the protocol's total street bet
convention and are clamped to the observation's legal raise bounds.

## Paired proxy evaluation

The harness at `.work/endgame-20261103/paired_eval.py` builds jobs with the
normal evolution pool sampler, then replaces only the hero policy in the
wrapped arm. Each baseline/wrapped pair uses the same opponent sample, seats,
seed, deal, blind schedule, and tournament configuration. It uses at most two
worker processes. Candidate rows are the saved policy (under a fresh ID),
`r90-ada-14`, and `r90-evo-02` from `selected-seeds.json`. Only the separate
`proxy-heldout-pool-v1` / `proxy-heldout-eval-v1` and
`proxy-heldout-pool-v2` / `proxy-heldout-eval-v2` development domains are used;
the canonical validation and confirmation pools are excluded. A capped table
counts as a non-win. Intervals are per-arm 95% Wilson intervals; paired net
delta is wrapped wins minus baseline wins on the identical tables.

### Results

Each arm played 256 tables on both the v1 and v2 pool/evaluation domains. The
overlay had a positive paired net win count for each candidate on each pool:

| Proxy pool / eval domain | Candidate | Base | Wrapped | Paired net |
|---|---|---:|---:|---:|
| v1 / v1 | Saved | 73/256 (28.5%) | 79/256 (30.9%) | +6 |
| v1 / v1 | r90-ada-14 | 67/256 (26.2%) | 77/256 (30.1%) | +10 |
| v1 / v1 | r90-evo-02 | 64/256 (25.0%) | 73/256 (28.5%) | +9 |
| v2 / v2 | Saved | 59/256 (23.0%) | 70/256 (27.3%) | +11 |
| v2 / v2 | r90-ada-14 | 68/256 (26.6%) | 78/256 (30.5%) | +10 |
| v2 / v2 | r90-evo-02 | 50/256 (19.5%) | 81/256 (31.6%) | +31 |

Every arm recorded zero invalid hero actions. Mean per-decision latency ranged
from 0.053 to 0.124 ms. The full 95% Wilson intervals, paired transition
counts, latency details, and 3,072 tournament records are in
[the endgame results report](../reports/endgame-20261103/results.md) and
[its JSON data](../reports/endgame-20261103/paired-results.json). The 64-table
reference rates supplied for the unwrapped policies (19/64 saved, 15/64
`r90-ada-14`, 14/64 `r90-evo-02`) are context only and are not reused as
evaluation data. These proxy results do not establish a 90% win rate; the
measured rates remain well below that target.
