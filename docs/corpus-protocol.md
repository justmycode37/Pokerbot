# Attributed Ivey corpus and held-out comparisons

The target remains greater-than-99% agreement with Ivey's decisions. Current
public selections cannot establish that population claim. Keep exact
action-plus-size agreement separate from action-class agreement, and never
present training accuracy as held-out accuracy.

`pokerbot.corpus.validate_rows` accepts attributed records with `state`,
`expected`, `source`, `hand_id`, and an evidence tier. It validates hero-visible
observations and legal labels, removes reporting metadata from policy inputs,
and rejects duplicate source-decision identities. Rounded/incomplete video
snapshots are excluded from exact scoring. A complete factual video
reconstruction with exact header stacks and reconciled pots is a separate
eligible evidence tier; its assumptions and missing reads stay disclosed.

`split_rows` groups a whole session when `session_id` is known, otherwise a
whole video when its YouTube identity is known, otherwise a whole canonical
hand. Every decision in a group stays in the same partition. Source aliases
for the same hand must be reconciled before freezing; matching states alone
do not prove two distinct historical hands are duplicates.

Three partitions are retained:

- `development`: previously inspected hands, listed in `data/seen_ivey_hands.json`.
  These cannot be relabeled as unseen evaluation evidence.
- `train`: eligible groups assigned to model fitting.
- `evaluation`: groups reserved before fitting. Once results guide changes,
  that holdout is consumed and future claims need a fresh holdout.

`save_split` refuses to overwrite a frozen version. `load_split` checks hashes
of source records and partition assignments, reconstructs group identities,
and rejects a group crossing partitions. This prevents accidental movement of
labels or streets across training and evaluation.

Data collection must be independent of whether the current bot matches the
recorded action. Collect all usable decisions in each selected hand, including
checks, folds and calls. Record the selection method, exact source, field-level
observed/derived/unknown status, and reasons for exclusion. Highlights remain
selection-biased even when each observation is reconstructed correctly.
