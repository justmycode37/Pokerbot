# Optional injected equity policy

`pokerbot.equity_policy.make_equity_policy(genome, estimator, model_metadata=None)`
creates a stateless per-table policy. It is an optional phenotype constructor;
it does not add a genome family, change family routing, load a model, or train
an estimator.

The module uses `pokerbot.evolution_strategies` for genome validation and the
unchanged evolved preflop policy. Install the project package so this runtime
dependency is included with `pokerbot.equity_policy`.

The estimator contract is:

```python
estimator(hole_cards, board, players_active) -> float
```

It must return a finite share in `[0, 1]` for a uniform random-opponent
showdown, conditioned on the actual `players_active` count. The callback gets
only immutable tuples of the hero's two cards, public board cards, and that
count. It receives no seed, betting history, opponent cards, outcome, or
future board. Preflop decisions use the existing evolved policy unchanged and
do not call the estimator.

Postflop, the estimator's value is the only non-exact equity share used for
the decision. The old fast equity heuristic is called only to obtain public
texture and draw diagnostics and to check its existing exact shared-board-tie
and unbeatable-hand proofs. Those exact proofs override the estimator result.
The old heuristic's non-exact share and its texture and multiway deductions
are ignored. Betting pressure is reported separately as `pressure_discount`;
the call threshold adds the existing small `range_threshold_margin` to
`pot_odds`. Since the estimator already conditions on the active-player
count, the policy applies no second multiway equity penalty.

The factory uses the existing bounded genome genes for call, raise, bluff,
position, and sizing behavior. Action probabilities are projected onto the
observation's legal actions. Raise totals go through the existing bounded
raise helper, including short-stack all-in bounds.

Postflop diagnostics keep these values separate:

- `estimator_raw_share`: the validated callback result.
- `pressure_discount`: public bet-size and aggression adjustment.
- `decision_equity`: the value compared with decision thresholds after any
  exact-proof override and pressure adjustment.
- `pot_odds`: the observation's contestable-pot price.
- `model_metadata`: a private copy of optional JSON-safe caller metadata.

Missing estimators fail at construction; callback errors and invalid shares
raise during decisions. There is no silent fallback, runtime card sampling,
subprocess, model loading, or training in this module.

## Limits

This is not an opponent-range model. The estimate assumes uniform random
opponent cards and does not infer hand ranges from actions, player identity,
or table history. The action thresholds and pressure adjustments remain
heuristics. No measured model accuracy, play-strength claim, or 95% confidence
claim follows from this interface alone; those require separate calibration
and validation evidence before a model can be loaded or promoted.
