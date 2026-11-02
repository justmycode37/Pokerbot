# Pokerbot laboratory

A Python poker strategy, local match harness, and leakage-free comparison with
available Phil Ivey hand histories, prepared for the
[Sequoia No Limit challenge](https://pokerbot.sequoiacap.com/).

The saved working checkpoint is **`ivey-transfer-v1`**, with **478/606 (78.88%)**
action agreement in the recorded whole-source-group comparison. Improvement
work is paused at the user's request; the 90% target was not reached. Install
with `python3 -m pip install .`, then run
`pokerbot-saved decide < examples/decision.json`. Its model and equity table
are bundled, so inference also works outside this checkout. See
[the saved bot instructions](docs/saved-bot.md).

**The requested greater-than-99% agreement with all of Phil Ivey's decisions
has not been established.** The initial public benchmark contains four
decisions from one televised hand. It cannot establish general imitation
accuracy, and exact action agreement does not establish playing strength.

The acquisition checkpoint contains **606 source-reviewed development
decisions from 393 hands across 18 source groups**. Acquisition is stopped.
Pending forum candidates and incomplete video evidence are excluded. See the
[publication checkpoint](docs/publication-checkpoint.md) for provenance and
the frozen strategy constraints. Verify the admitted ledger locally with
`.venv/bin/python scripts/acquisition_admissions.py`.

The [official rules](https://pokerbot.sequoiacap.com/rules.html) specify a 1 ms
decision deadline and a Python `Agent` interface, but the variant and starter
kit are revealed at the event. This project currently studies no-limit
Hold'em. Its JSON protocol and local simulator are preparation tools; an
official event adapter cannot yet be verified. See [challenge research](docs/challenge.md).

## Run locally

Requires Python 3.11 or later. The runtime strategy uses the standard library;
PokerKit is an optional pinned dependency for local matches and PHH replay.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[evaluation]'
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pokerbot decide < examples/decision.json
.venv/bin/python -m pokerbot decide --policy imitation --model data/models/ivey-imitation-v1.json < examples/decision.json
.venv/bin/python -m pokerbot profile --count 10000 --output reports/profile.json
.venv/bin/python -m pokerbot compare-ivey --output reports/ivey-fast.json
.venv/bin/python -m pokerbot compare-ivey --include-reconstructed --include-verified-video --include-public-reports --output reports/ivey-expanded.json
.venv/bin/python -m pokerbot review-ivey --include-reconstructed --include-video --output reports/qualitative-ivey.md
.venv/bin/python -m pokerbot compare-ivey --policy mc-range --samples 5000 --output reports/ivey-reference.json
.venv/bin/python -m pokerbot benchmark --hands 800 --players 8 --opponent calling-station --output reports/match.json
```

Run from this source checkout; bundled research data currently lives under
`data/`. No command submits a bot, registers for the event, or plays for money.

For the qualitative comparison, open [the written findings](docs/qualitative-findings.md)
and [the video-method demonstration](docs/video-comparison.md). Generate the
interactive local review with `.venv/bin/python scripts/build_review_html.py`,
then open `reports/qualitative-ivey.html`. The viewer hides Ivey's recorded move
until requested and shows the bot's action mix alongside the visible state.
Use `scripts/evaluate.py` to retain a complete evaluation revision with code
and data hashes; see [evaluation revisions](docs/evaluation-revisions.md).

The first [supervised imitation model](docs/imitation-model.md) is an exploratory
smoothed decision tree trained on a frozen source-group split. Its first
held-out action result was matched by a majority-action baseline and does not
establish general Ivey accuracy. [Corpus rules](docs/corpus-protocol.md) and
the immutable manifests under `data/corpus_splits/` record which examples were
previously inspected and which entered fitting or evaluation. Newly acquired
source groups can be compared with the [locked candidate](data/models/prospective-code-lock-v1.json)
through `scripts/evaluate_prospective.py`, which performs no fitting.
The [first prospective comparison](docs/prospective-results-v1.md) on 22 new
source-reviewed decisions yielded 12 exact decisions for fast and eight for
imitation. It does not establish representative accuracy; those cases now
belong to the expanded development corpus for the next candidate.
An [independent raise-size experiment](docs/sizing-experiment.md) found no
improvement in exact decisions on the old development folds; its larger sizing
trees are not adopted.

## Strategy and evaluation

`fast` is the provisional runtime policy. `mc-uniform` and `mc-range` are
slower offline references that estimate equity from unknown cards. The range
reference uses an explicit illustrative opening range after observed preflop
aggression. Those ranges are assumptions, not recovered opponent cards or a
solver strategy. Both references share the fast policy's preflop priors.

An observation contains only hero's cards, the visible board, public betting,
stacks, legal actions, and position. Raises use **total street bet** amounts.
The [local protocol](docs/state-protocol.md) explains all fields, including
side-pot adjustments. Unknown labels and private fields are discarded at the
strategy boundary.

Evaluate three things separately:

- **Correctness and runtime:** legal actions, card ranking, chip conservation,
  reproducibility, and measured local latency. Local timings cannot certify an
  unknown event sandbox.
- **Playing performance:** repeated local matches, rotated seats, and
  uncertainty across deal blocks. Simple opponents expose mistakes; beating
  them does not prove success in the official tournament.
- **Ivey similarity:** recorded action agreement, separate bet-size error,
  sample and hand counts, and provenance. Every new comparison restores the
  recorded prefix, hiding future cards and opponents' private cards. An
  alternative bot action cannot reveal how the real hand would have continued.

## Evidence needed for the full goal

Meaningful general imitation evaluation requires a sufficiently large,
representative archive with Ivey's private cards, complete preceding public
action, positions, stacks, stakes, and format. Split by whole hand/session
before training; preserve a held-out evaluation set. Record mixed-action
probabilities as well as sampled actions. A small set of selected televised
highlights is not a representative test, even if its score reaches 100%.

The source hand is distributed under its included [dataset license](data/ivey/LICENSE).
Do not fit policy branches to the four labels or use the benchmark as a
precomputed action lookup. See the replay and runtime documentation in `docs/`
for implementation assumptions and limitations.
