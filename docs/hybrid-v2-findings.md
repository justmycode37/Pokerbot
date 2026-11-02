# Corrected hybrid development result

The v2 successor fixes the independent review's actor-role error: hero and
matching history IDs are canonicalized together, so the fast prior retains
which earlier actions were the hero's. It also rejects evaluation/partial fitting
rows, validates nested sizing models, requires model parameters, and supplies a
legal minimum raise when an action-only model has no fitted sizer. V1 artifacts
and their matching source are preserved separately.

The same predeclared hyperparameter grids were rerun on the same 45 consumed
development decisions, with eight source groups and 12 hands. Whole groups are
excluded from each fitting fold, but settings are selected using those folds;
the selected results are post-selection development scores, not fresh accuracy.

| Policy | Action classes matched | Exact action and size |
|---|---:|---:|
| Frozen fast | 25 / 45 (55.6%) | 19 / 45 (42.2%) |
| Archived hybrid v1 | 25 / 45 (55.6%) | 17 / 45 (37.8%) |
| Corrected hybrid v2 | 26 / 45 (57.8%) | 18 / 45 (40.0%) |

The corrected model still fails the required exact-decision improvement. No
expected raise is sized exactly by fast or either hybrid version. The selected
v2 settings are residual regularization 0.1, probability blend 0.5 and size-tree
depth 1 with minimum leaf size 3. Fast remains the default. The hybrid is a
frozen experimental alternative, not a demonstrated improvement or a 99% model.

All 126 tests passed after the corrections. A further strict simulator smoke
check used 32 hands across two/eight players and two/five/25/100-big-blind
stacks, with no illegal outputs or chip-conservation failures. That check is
about runtime legality, not profitability or imitation. Local profiling over
300 warmed synthetic calls measured 97.3 microseconds mean and 121.0 microseconds
p95, without certifying an unknown official sandbox.

The model, relevant code, fitting manifests and inspected corpus are fixed in
`data/models/candidate-lock-v2.json` and archived with hashes in
`data/models/candidate-v2-source.zip`. The next quantitative efficacy test must
use newly admitted source groups and keep its inspection history explicit.
The 30 incomplete short-video records and the unresolved 2009 hand are excluded.
