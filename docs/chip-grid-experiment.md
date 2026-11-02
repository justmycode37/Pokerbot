# Observed chip-grid sizing experiment

This bounded experiment wraps the frozen `pokerbot.fast.decide` policy and
changes only its proposed raise size. The selected action and its probability
distribution stay unchanged. It uses the one predeclared configuration in
`pokerbot/grid_policy.py`; there was no parameter search after seeing results.

For each public observation, the wrapper takes the GCD of positive integer
`pot`, `contestable_pot`, `current_bet`, `stack`, `min_raise_to`,
`max_raise_to`, `to_call`, and `big_blind`. If eight times that GCD is greater
than the big blind, it uses a one-chip grid. It rounds the fast policy's
intended total street target to the nearest grid multiple with integer
ties-to-even, then clamps to the supplied legal bounds. Boundary targets are
kept exactly. This GCD is an observed rounding heuristic; it does not prove
the game's minimum chip denomination.

## Data and scoring

The run uses only the 45 decisions in the `development` partition of
`data/corpus_splits/development-after-prospective-v1.json`: 12 hands across 8
source groups. The manifest was already inspected, so the run makes no fresh
accuracy claim and does not reuse or consume a future holdout.

Action agreement counts matching selected action labels. Exact action-and-size
agreement additionally requires the labeled total target to match for a
recorded raise. Raise-size errors are reported separately on every recorded
raise, using the policy's proposed `raise_amount` even when its sampled action
was call, check, or fold. The size diagnostic is therefore counterfactual when
the policy did not select raise; it does not imply action agreement.

The group-by-group metrics, source code fingerprints, and data fingerprints
are recorded in [the one-time development report](../reports/chip-grid-development-v1.json).
The script refuses to overwrite that path. To reproduce into a new report
version, pass a new output path:

```sh
.venv/bin/python scripts/experiment_grid.py \
  --output reports/chip-grid-development-v2.json
```

## Result

Fast and the wrapper selected the same actions and probabilities on all 45
decisions. Both matched 25 action labels; exact action-and-size matches were
19 for fast and 20 for the wrapper. Of 22 recorded raises, both policies
proposed sizes on 10. On those 10 counterfactual sizing scores, mean absolute
error changed from 130,727.5 to 129,730 chips (0.15099 to 0.14923 of pot after
call); exact proposed sizes changed from 0 to 1. The 12 missing sizes are not
included in those error averages.

This is a small numerical difference on already inspected development data,
not evidence of fresh accuracy or a reliable improvement. The wrapper remains
an experiment only.

This experiment does not change the fast default, register a candidate, or
modify the frozen candidate lock. Any later candidate consideration belongs
after the current frozen v2 prospective test.
