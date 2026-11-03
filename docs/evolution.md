# Evolution playground

The playground measures poker playing performance separately from the saved
bot's Phil Ivey action agreement. The saved `ivey-transfer-v1` checkpoint is a
protected reference. Evolution creates new strategy genomes; it never rewrites
the saved model or the historical research corpus.

## Local match format

`pokerbot.tournament.play_tournament` plays complete no-limit Hold'em tables
using PokerKit for hand settlement. Stacks persist between hands, busted players
leave the table, and the button and blinds move among surviving players. Stable
anonymous player IDs survive seat rotations. Each policy sees only its own cards,
the public board, public betting, and legal actions.

The default scenario has eight bots, 2,000 chips each, blinds starting at 10/20,
an increase every 25 hands, and a cap of 200 hands. A sole surviving player wins
the table. At the cap, survivors receive exact ICM expected points and expected
finishes; a chip lead does not count as a table win. Simultaneous eliminations
are ordered by stacks entering the hand; equal stacks share the affected places
and points. Chip totals and total awarded points are checked after settlement.

The default big blinds are `20,40,80,160,320,640,1280,2560` and default payouts
are descending `8,7,6,5,4,3,2,1`. Those two schedules and the moving-button rule
are **illustrative assumptions**, recorded with every run. The exact event
variant, blind schedule, payouts, and Agent interface have not been released.
The public rules identify Sequoia as organizer and OpenAI and Citadel Securities
as hosts. Public format verified on November 2, 2026:
[official rules, sections 3–4](https://pokerbot.sequoiacap.com/rules.html).

## What evolves

New strategies vary opening cutoffs, calling margins, aggression, bluffing,
bet sizes, short-stack pushes, position, and multiway adjustments. Selection
uses training outright win rate, with tournament points breaking ties. The
event's points score remains a separate reported metric. Survivors produce mutated or crossed offspring;
new random immigrants maintain variety. Removed strategies remain in the run's
history, and archived leaders remain available as opponents.

The fixed reference families include the saved bot, the original fast policy,
a calling station, a tight passive player, and a random legal player. Their
parameters do not evolve. See [the genome reference](evolution-strategies.md)
for parameter bounds and policy details.

Fixed opponents remain eligible when their own strategy is the evaluated hero;
the hero has a separate seat role, so another seat can run the same strategy.
This keeps the evaluation pool consistent for references and new genomes.
Two-player through seven-player scenarios can be studied locally, but cannot
satisfy this experiment's eight-player promotion goal.

## The 95% target

Win rate means **outright table wins divided by all evaluation tables**.
Eliminations and surviving a capped table are reported separately. A capped
table never becomes a win just because a candidate has the largest stack.
Training performance, evaluation performance, and final confirmation are kept
separate. Evaluation uses a persisted independent opponent population, separate
seed domains, and randomized seats. Opponents are not removed to make the
target easier.

The target requires more than a lucky observed win rate: independent
confirmation must also clear a confidence-bound gate. Every result records its
sample size and uncertainty. Eight-player matches against strong opponents make
95% an ambitious target; the playground reports actual results when it is not
reached. A local result cannot establish the win rate against unknown official
entrants or an unreleased variant.

Reported 95% Wilson intervals are descriptive. Promotion uses a one-sided
exact binomial (Clopper–Pearson) lower bound from a **new confirmation batch**.
Its error allowance is `0.025 / ((i+1)*(i+2))` for confirmation attempt `i`,
starting at zero. These allowances sum to 0.025 over the search. Past
confirmation results remain in the audit history; pooling them does not make
the promotion decision. At the first allowance, even an all-win sample needs
86 matches before its exact lower bound exceeds 95%.

## Round reports

Every evaluated generation writes a full JSON, CSV, and Markdown leaderboard
for **all active bots**, including strategy and lineage, sample sizes, outright
wins, capped survivals, eliminations, uncertainty, average finish and points,
chip outcomes, invalid actions, measured local runtime, and selection status.
The run also keeps a checkpoint, leader genome, and cumulative HTML report.
Runtime measurements cover local policy calls; they do not certify the event's
one-millisecond sandbox deadline.

The evolution CLI runs in explicit chunks and can resume the same experiment.
Reaching a chunk boundary is not evidence that the target has been reached.
Use the same experiment configuration on resume; changes to code or evaluation
rules require a new run so that results remain auditable.

## Run and resume

Install the evaluation extra as described in the main README. To reproduce
the first experiment configuration:

```sh
.venv/bin/python -m pokerbot.evolution run \
  --output-dir reports/evolution-v2 --population 16 --generations 1 \
  --matches 32 --validation-matches 64 --confirmation-matches 512 \
  --seed 20261102 --workers 4
```

Use the same command with `--resume` for the next generation. `--generations`
sets the number of generations in this invocation; `--workers` sets parallel
simulation processes. They can change between chunks. The match format,
population size, sample counts, seed, and model/code fingerprint must match the
saved checkpoint. The initial experiment evaluates 704 tables per generation:
512 training tables and 192 validation tables. Confirmation adds new tables
only when a validation candidate first clears the observed-win-rate gate.

The earlier static experiment is `evolution-v2`. Two pilot rounds remain in
`evolution-v1` with a source snapshot. The corrected experiment prioritizes
wins and keeps reference copies eligible in the opponent pool, so its results
should be interpreted within its own protocol.

Generate the complete offline viewer with:

```sh
.venv/bin/python scripts/report_evolution.py --run-dir reports/evolution-v2
```

For a smaller view of a long experiment, add `--recent 3 --output
reports/evolution-v2/latest.html`. Full round JSON, CSV, and Markdown files
remain available. The checkpoint records Python and PokerKit versions and
source/model hashes; resume rejects changed simulation code or dependencies.
A durable export journal republishes a committed round after an interruption
during report writing, without replaying its matches.

To load a provisional or confirmed leader from a run:

```python
import json
from pokerbot.evolution_strategies import Genome, policy_for

leader = json.load(open("reports/evolution-v2/champion.json"))
policy = policy_for(Genome.from_dict(leader["genome"]))
decision = policy(observation)
```

Check the artifact's `status` before calling the leader confirmed. A provisional
leader is selected by training points and has not passed the requested gate.

Latency means are weighted by the number of decisions. The round-level p95
field is the maximum of the per-table p95 values, rather than a pooled p95.
All local latency measurements can vary with machine load and worker count.

## Adaptive experiment

V3 carries four leaders chosen by V2's final training ranks and four adaptive
copies of those genes, together with the five references and three fresh
strategies. The seed file and its manifest record the source checkpoint and
selection rule. Strong imported strategies remain in the training archive.
The static controls matched the V2 source snapshot on 1,800 tested policy
decisions. The fixed opponent-pool fingerprints are unchanged; a new match-seed
namespace separates V3's evaluation samples from the earlier experiments.

```sh
.venv/bin/python -m pokerbot.evolution run \
  --output-dir reports/evolution-v3 --population 16 --generations 1 \
  --adaptive-fraction 0.5 --seed-genomes reports/evolution-v3-seeds.json \
  --evaluation-namespace evolution-v3 \
  --matches 32 --validation-matches 64 --confirmation-matches 512 \
  --seed 20261102 --workers 4
```

Resume with the same flags and `--resume`. The adaptive fraction applies to
fresh initial genomes and later random immigrants; breeding inherits a parent
family. It never changes the fixed validation or confirmation opponents.
Training and fresh evaluation must establish whether the additional behavior
improves playing strength; adding adaptation does not establish the 95% target.

## Response-profile correction and larger samples

The corrected V4 run records each action's public call price in the tournament
wrapper, preserving all frozen research files. Only actions facing a price
enter fold/call response estimates. General aggression counts still include
opening bets. The earlier V3 round reports remain preserved.

```sh
.venv/bin/python -m pokerbot.evolution run \
  --output-dir reports/evolution-v4 --population 16 --generations 1 \
  --adaptive-fraction 0.5 --seed-genomes reports/evolution-v3-seeds.json \
  --evaluation-namespace evolution-v4-price \
  --matches 128 --validation-matches 128 --confirmation-matches 512 \
  --seed 20261102 --workers 4
```

Use the same flags and `--resume` for subsequent generations. Each generation
plays 2,048 training tables and 384 validation tables before any confirmation.
The seed namespace excludes reservations from the aborted preflight attempt
preserved in `reports/evolution-v4-preflight-failed/`. The fixed opponent pools
remain identical to V2's; the saved bot and static controls remain unchanged.
