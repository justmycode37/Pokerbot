# Offline imitation model

`pokerbot.imitation` provides a small supervised policy that is separate from
the `fast` policy. It fits a shallow CART classifier from attributed decisions
and stores only numeric split rules, per-leaf action counts, and raise-size
medians. Inference uses the standard library plus the existing card and state
modules; it does not call an external model service.

## Observation features

`features(raw)` validates `raw` with `Observation.from_dict` and returns a named
mapping of finite floats. The tree can use hero card ranks and texture, public
board texture, position, legal actions, pot odds, stack and raise bounds,
players still in the hand, and summary counts of visible actions. History actor
identifiers are ignored.

The feature extractor does not use hand, session, source, player, or record IDs;
the random seed; expected labels; outcomes; opponent hole cards; unrevealed
board cards; future actions; or other extra fields. Those fields may be present
in an input mapping, but the validated observation and feature list exclude
them.

## Fitting and inference

```python
from pokerbot.imitation import decide_with_model, features, fit_model

model = fit_model(train_rows, manifest_hash="<sha256>")
vector = features(observation)
decision = decide_with_model(observation, model)
```

`fit_model` rejects rows marked `evaluation`. Rows marked `development` require
`include_development=True`. The classifier uses Gini CART splits, a default
maximum depth of four, a minimum leaf size of two, and Laplace smoothing over
the action classes present in fitting rows. Every decision is masked against
the observation's legal actions before probabilities are normalized. If no
learned class is legal, it falls back to check, call, then fold where legal.

For each raise example, fitting records the ratio
`(raise_to - current_bet - to_call) / (contestable_pot + to_call)`. Inference
uses the median ratio among raises in the reached leaf, falling back to the
global training median if that leaf has no raises. It reconstructs a total
street-bet target and clamps it to `min_raise_to...max_raise_to`, including
short all-in bounds. `amount` is zero unless the selected action is raise;
`raise_amount` gives the legal size associated with the raise probability when
raise was observed during fitting.

## Freeze, train, and compare

Create and preserve a frozen manifest after reconciling public source aliases.
The three previously inspected hands listed in
`data/seen_ivey_hands.json` must be in its `development` partition. For example,
after assembling the eligible attributed rows:

```python
import json
from pokerbot.benchmarks import load_ivey_corpus
from pokerbot.corpus import save_split, split_rows

rows, _ = load_ivey_corpus(include_reconstructed=True, include_verified_video=True)
seen = json.loads(open("data/seen_ivey_hands.json", encoding="utf-8").read())
manifest = split_rows(rows, development_hand_ids=seen["development_hand_ids"])
save_split(manifest, "data/ivey-imitation-split-v1.json")
```

Then explicitly run the trainer with new output paths:

```sh
.venv/bin/python scripts/train_imitation.py data/ivey-imitation-split-v1.json \
  --model-output models/ivey-imitation-v1.json \
  --report-output reports/ivey-imitation-v1.json
```

The model and report are only written by that explicit command. Existing output
files are preserved; choose new paths for a new run. Add
`--include-development` only when deliberately fitting on previously inspected
development hands. Evaluation source groups are always excluded from fitting.
The trainer refuses a missing train or evaluation group and verifies the
manifest through `corpus.load_split` before fitting.

The report includes the SHA-256 of the complete frozen manifest in both model
metadata and report metadata, counts by partition, per-class metrics, raise
sizing metrics, mixed-action metrics, and `compare_decisions` results for the
imitation model and `fast` baseline on the same evaluation rows. It does not
report training accuracy, tune on evaluation rows, or claim that 99% agreement
has been achieved. Small evaluation samples are explicitly marked
**EXPLORATORY ONLY**. More hands from independent public source groups are
needed before estimating broad agreement; even a large curated sample would
not by itself prove representative population accuracy.

## Runtime profile and limits

The included tests use a synthetic relation held out by group and check that
fitting rejects evaluation rows, features ignore IDs/labels/future fields,
probabilities normalize after legal masking, and raise targets remain inside
unseen-state bounds. Inference is deterministic and does not use the seed.

On the local Python 3.12 environment, a synthetic 26-row fixture produced a
three-node tree with 48 features. JSON serialization succeeded, and five runs
of 10,000 preflop decisions measured a median of **15.59 microseconds per
call** (runs: 20.93, 15.59, 15.84, 14.55, 14.49 microseconds). This is a local
warm-process profile, not an event-sandbox guarantee or benchmark accuracy
measurement.

The tree is intentionally shallow, but its predictions remain limited by the
attributed examples and selected public footage. It cannot infer private live
reads, opponent cards, hidden strategy, or population behavior from missing
data. Row-wise agreement is descriptive; decisions from one hand are
correlated.


## First real-data exploratory run

The first frozen report corpus has 23 decisions across seven hands. Fifteen
previously inspected decisions remain development data. The first model fits
five newly assigned training decisions plus those fifteen development rows,
with that inclusion explicitly requested. It evaluates only three decisions
from one held-out source group. These three labels are all bets.

The imitation model matches all three action classes and one exact raise size.
The fast policy matches one action class and no exact size. A fitting-set
majority-action baseline also matches all three action classes, with no exact
size matches. Consequently the perfect action-class score provides little
evidence of strategic imitation; the sample is small and class-imbalanced.
The outputs are exploratory and do not establish the requested 99% population
agreement. The original frozen manifest and first result are retained; a
supplementary majority-baseline report uses the same rows and is not new
independent evidence.

A parent review corrected the CART split counter: the minimum-leaf constraint
must not cause the first labels in sorted order to be skipped when accumulating
left-child class counts. A synthetic regression verifies the best legal split
for seven call labels followed by one raise label. The correction preceded
fitting the real-data model and did not use held-out outcomes.
