# Local NLHE policy simulator

This is a **local model for testing policies**. It is not the official
Sequoia tournament simulator, tournament rules, SDK, or sandbox. It plays
no-limit Texas Hold'em cash-reset hands for two through eight players and
uses PokerKit 0.7.7 for betting, all-in and short-raise reopening rules,
side-pot construction, showdown, and chip settlement.

## Install and run

The simulator is optional so the strategy package can be used without
PokerKit. Install the evaluation extra, then call it from Python:

```sh
.venv/bin/pip install -e '.[evaluation]'
```

```python
from pokerbot.simulation import benchmark, calling_station, random_legal

hand = benchmark(
    random_legal,
    [calling_station] * 5,
    hands=100,
    seed=2026,
)
print(hand["hero_net_bb_per_100"])
print(hand["uncertainty"])
```

To inspect actor-visible observations from one hand:

```python
from pokerbot.simulation import calling_station, play_hand

result = play_hand([calling_station, calling_station], seed=7, trace=True)
print(result["trace"][0]["observation"])
```

Run its tests with:

```sh
.venv/bin/python -m unittest tests.test_simulation
```

## Policy and hand interfaces

A policy is a callable from an observation dictionary to a decision
dictionary. The observation uses [the local state protocol](state-protocol.md).
The decision is `{"action": "fold"}`, `{"action": "check"}`,
`{"action": "call"}`, or `{"action": "raise", "amount": N}`. A raise
amount is the **total bet on this street**, including chips already committed
this street. It is not the extra amount to add and not a pot fraction.

```python
def cautious_policy(observation):
    if observation["to_call"] == 0:
        return {"action": "check"}
    odds = observation["to_call"] / max(
        1, observation["contestable_pot"] + observation["to_call"]
    )
    return {"action": "call" if odds < 0.2 else "fold"}
```

`play_hand(policies, *, seed=0, stacks=2000, big_blind=20, strict=True,
trace=False)` returns:

- `payoffs`: net chip changes from the reset stacks, in seat order.
- `stacks`: final stack sizes in seat order.
- `actions`: public actions with `amount` as the street-total target and
  `added` as chips added by that action.
- `invalid_actions`: invalid policy outputs handled in non-strict mode.
- `trace`: included only when requested; each record contains the exact
  policy observation, the normalized decision, and the resulting action.

`stacks` may be one integer applied to every seat or a sequence of one
positive integer per seat. Each hand starts from those stacks and settles
independently; there is no cross-hand bankroll or tournament elimination.
The small blind is half the big blind rounded down, with a minimum of one
chip.

Policies are passed in PokerKit seat order. At a heads-up table seat `p0` is
the big blind and `p1` is the button/small blind. With three or more players,
`p0` is the small blind, `p1` the big blind, and the final seat is the button.
`table_size` is the number of policies. `player_id` and history player IDs
are strings such as `p0`.

## Observation and legality

Each observation is validated through `pokerbot.state.Observation`. It
contains the acting player's two hole cards, the current public board,
public actions so far, pot and stack figures, legal actions, and PokerKit's
street-total raise bounds. It does not contain opponents' hole cards, the
unrevealed deck or board, future actions, or the hand result. `players_active`
counts the acting player; `players_to_act` counts other queued actors.

Raise bounds come from PokerKit's legal betting state, including its rules
for a short all-in raise and whether action has reopened. `min_raise_to` and
`max_raise_to` are total street bets. If no raise is available, both are zero
and `raise` is omitted from `legal_actions`. Calls are translated to
PokerKit's check/call operation; raise amounts are sent directly to its
complete/bet/raise operation.

`pot` includes all committed chips, including outstanding street bets.
`contestable_pot` splits contribution tiers at actual contributions and at
players' reachable call limits. It includes only currently committed chips
at levels the hero can reach by calling and at which another live player can
also reach the level. This excludes inaccessible side pots and unmatched
excess. Folded players' committed chips remain in eligible tiers.

By default, invalid policy outputs raise `InvalidActionError`. With
`strict=False`, each invalid output appears in `invalid_actions` along with
the explicit fallback used: check when available, otherwise fold when
available, otherwise call. The simulator does not silently turn an invalid
decision into a check/call.

## Reproducibility and benchmarking

For `play_hand`, the full standard deck is shuffled once with a private
`random.Random(seed)` and predealt before any policy acts. Hole cards are
dealt round-robin, followed by burns and board cards from that same shuffled
deck. The policy receives a separate deterministic seed derived with
SHA-256 domain separation from the input seed, seat, and that seat's decision
number. This seed supports reproducible policy sampling without passing the
deck generator or unrevealed cards to the policy.

`benchmark(hero_policy, opponents, *, hands=100, seed=0, stacks=2000,
big_blind=20)` returns hero net bb/100, hero decision metrics, total and
hero-only invalid-action counts, and uncertainty. A duplicate-deal block reuses one shuffled deck
across one hand per seat while rotating the hero through every seat. Because
blocks are complete rotations, `hands_played` rounds `hands` up to the next
multiple of the player count. `standard_error_bb_per_100` is calculated from
the block means; the reported 95% interval uses a normal 1.96 multiplier.
With one block, uncertainty is `null` because a between-block estimate is not
available.

`hero_decisions` summarizes only calls made by the hero policy. It reports
the distribution of legal-action counts and policy-call latency in
milliseconds (mean, p50, p95, p99, and maximum). Latency covers only the
callable invocation, not observation construction, and is a local Python
measurement rather than an estimate of an official sandbox deadline.

Three basic policies are provided: `calling_station` calls or checks,
`tight_passive` uses a small illustrative starting-hand heuristic and
otherwise prefers cheap calls, and `random_legal` samples from the observed
legal actions using the supplied observation seed. They are evaluation
baselines, not optimized strategies.

## Limitations

This model uses fixed blinds, no rake, no ante, one runout, and a full hand
reset for each call. It does not implement tournament elimination, blind
schedules, tournament scoring/ICM, official submission/runtime behavior,
time limits, sandbox restrictions, or an official agent interface. Results
are useful for repeatable local policy comparisons only.
