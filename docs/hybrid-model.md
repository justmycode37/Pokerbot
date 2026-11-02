# Hybrid fast-prior candidate

The current runtime is v2. It canonicalizes the hero ID and matching history
actors together, preserving public actor roles. It also rejects explicit
evaluation/partial fitting rows, validates nested sizing trees and supplies a
legal minimum raise when no size model exists. The original v1 model, negative
report and matching source archive remain under `data/models/hybrid-v1*` and
`reports/hybrid-development-v1.json`; the v2 loader deliberately rejects that
older algorithm ID. The archive permits reproducing its original behavior.

`pokerbot.hybrid` adds a small multinomial residual classifier to the frozen
`pokerbot.fast` legal-action probabilities. It extracts inputs only through
`pokerbot.imitation.features` (`imitation-features-v1`), masks illegal actions,
and returns a deterministic maximum-probability action with a normalized
probability mix. Ties use check, call, fold, raise order. The frozen prior is
made independent of player IDs before its probabilities are read; random seeds,
record labels, source IDs, opponent cards, and future fields do not enter the
features or prediction.

The correction is a multinomial logit residual over the log of the legal fast
prior. Feature centers and scales are fit on training groups only. Each source
group receives equal total fitting weight, and an L2 penalty applies to feature
weights. The prior floor is `0.02`; fitting uses 500 deterministic full-batch
gradient steps. The predeclared selection grid is regularization `{0.001, 0.01, 0.1}`
and probability blend `{0.5, 0.75, 1.0}`. The trainer selects the pair with the
lowest mean of per-source-group multiclass log loss. Action sizing is selected
separately from the existing L1 raise-size tree at depth 0 or 1, with minimum
leaf size 3, using source-group mean absolute raise-size error divided by the
pot after calling. The chosen size predictor returns a legal total street bet.

## Training and evidence

Run `python3 scripts/train_hybrid.py --help` for the fixed command options. The
trainer accepts only
`data/corpus_splits/development-after-prospective-v1.json` and creates
`data/models/hybrid-v2.json` and `reports/hybrid-development-v2.json` once. It
refuses different paths and preserves existing artifacts. It first runs
leave-one-source-group-out CV across all 8 groups, comparing the candidate,
frozen fast, a fold-fitted majority policy, and a fresh fold-fitted CART model.
No source group crosses a fold. Only after selection does it fit the final
candidate on all 45 rows.

These 45 decisions cover 12 hands and 8 groups. Every case has been inspected,
including the 22 decisions from the consumed prospective batch. The data is
development-only; there are no fresh held-out rows. The JSON report separates
action agreement, exact action-and-total-street-size agreement, independent
total-street raise sizing, per-class metrics, probability-of-recorded-action,
multiclass log loss, group means, and per-group results. The candidate is
described as superior only if its group-held-out action, exact action-and-size,
and exact sizing rates all exceed frozen fast. This selected sample cannot
support a population or 99% agreement claim.

The report includes corpus and code SHA-256 fingerprints, row/group counts,
selected hyperparameters, per-fold group membership, and a warmed local timing
on four synthetic valid observations. The timing uses a model parsed once and
measures local Python calls only; it is not an official sub-millisecond
guarantee.

The [corrected v2 findings](hybrid-v2-findings.md) remain a negative result on
exact decisions. Fast stays the default, and the next candidate comparison is
locked separately from these consumed development folds.

## Runtime use

```python
from pokerbot.hybrid import decide, load_model

model = load_model("data/models/hybrid-v2.json")  # load once at startup
result = decide(observation, model)
```

Runtime imports use the Python standard library and the repository's existing
fast, state, imitation-feature, and sizing modules. The candidate assumes the
current validated no-limit Hold'em observation contract. Calls use that
contract's total street bet convention, clamp to legal minimum/maximum raise
targets, and preserve short all-ins at the observation's legal maximum.
