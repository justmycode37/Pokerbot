# Independent raise-size experiment

The first imitation classifier stops splitting a leaf when every training
example has the same action. That leaves its raise sizes pooled even when
visible context differs. `pokerbot/sizing.py` tests a separate shallow regression
tree for the increment above a call, divided by the contestable pot after
calling. It changes sizing only; the classifier's action probabilities remain
unchanged. Neither model receives hand IDs, source IDs or opponent cards.

The experiment used only the 20 train/development decisions in the existing
manifest, with nine recorded raises from five source groups. Each fold excluded
one entire source group from fitting. The original three evaluation decisions
and all subsequently collected records were excluded. These folds are development
evidence: the examples were previously inspected, and comparing options consumes
the folds for model selection. This is not a fresh accuracy estimate.

| Sizing method | Mean absolute size error / pot after call | Exact sizes on nine recorded raises | Exact action plus size on 20 decisions |
|---|---:|---:|---:|
| Classifier-leaf median | 0.3145 | 0 | 7 |
| Global median | 0.2733 | 0 | 7 |
| Independent tree, depth 1 | 0.3461 | 0 | 7 |
| Independent tree, depth 2 | 0.3820 | 0 | 7 |

Size error is a conditional diagnostic: it asks which size the model would use
on a recorded raise, even if its action classifier selected something else.
All four candidates matched nine action classes out of 20. Their seven exact
decisions were non-raises. A lower size error therefore does not mean higher
exact-decision agreement, improved playing strength or verified Ivey imitation.

The larger trees failed this development check and are not adopted. The global
median reduced average size error, but did not improve exact agreement; it remains
an experimental baseline. The frozen candidate, model and evaluation lock are
unchanged. More exact source groups are needed before selecting a replacement.

Run the experiment with a new output path:

```sh
.venv/bin/python scripts/experiment_sizing.py \
  data/corpus_splits/public-reports-v1.json \
  --output reports/sizing-development-new.json
```

The final guarded run is `reports/sizing-development-v2.json`; the earlier v1
run predates the explicit partial-record rejection guard and produces the same
numbers on this complete corpus. Both retain source hashes. Five focused tests
check size learning in a pure-action leaf on unseen pot sizes, chip scaling,
hidden-field invariance, legal bounds, holdout rejection and malformed models.
