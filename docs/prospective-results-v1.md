# First prospective comparison on new report groups

The v1 policy/model/evaluator lock was created before the new batch's labels
were inspected for strategy development. The first comparison used 22 admitted
decisions from five hands in two new event/session groups. Fitting used none of
these rows. See the immutable
[`reports/prospective-reports-batch2-v1.json`](../reports/prospective-reports-batch2-v1.json)
and [admission notes](report-batch2-source-audit.md).

| Frozen policy | Action classes matched | Exact action plus size | Illegal actions |
|---|---:|---:|---:|
| Fast heuristic v3 | 14 / 22 (63.6%) | 12 / 22 (54.5%) | 0 |
| Imitation v1 | 13 / 22 (59.1%) | 8 / 22 (36.4%) | 0 |
| Training majority action | 10 / 22 (45.5%) | 0 / 22 (0%) | 0 |

The labels contain ten raises/bets, six calls, five checks and one fold. The
fast policy matched all twelve non-raise actions but only two raise classes.
Neither policy matched an exact raise size. The imitation model matched five
raise classes, trading away some correct calls and checks. This makes aggression
and sizing clear development priorities, without implying that copying a
particular bluff will improve playing strength.

For the two raises whose classes it matched, fast's mean size error was 0.0308
of the pot after calling. That figure excludes eight missed raise actions and
must not be presented as its sizing accuracy across all ten raises. The
imitation model's corresponding mean error was 0.3072 on five matched raises.
Expected-action probabilities averaged 0.6469 for fast and 0.5484 for imitation;
these are descriptive probability scores, not exact-decision accuracy.

Five selected hands and two groups cannot establish representative population
agreement. The source-reviewed reconstructions include explicitly derived
all-in amounts and implied folds. Rows within each hand and event are correlated.
The requested greater-than-99% agreement remains unmet and unverified.

After this first evaluation, all 45 available complete decisions (including
the earlier inspected corpus) were frozen as development data in
`data/corpus_splits/development-after-prospective-v1.json`: 12 hands, eight groups,
and no fresh evaluation partition. The next candidate may learn from these
cases. It must be frozen and tested on different, newly acquired source groups;
rescoring the same cases cannot provide a new independent accuracy estimate.
