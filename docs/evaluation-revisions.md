# Reproducible evaluation revisions

The first integration run (`reports/*v1*.json`) exposed an unopened-pot bug:
the posted blind was mistaken for an opponent raise, and waiting players were
discounted as if they had already entered. A separate guaranteed board-tie
probe exposed a multiway penalty that incorrectly erased the tie share.
The fast-policy Luna agent fixed both generally in `fast-heuristic-v2`, with
regression tests independent of Ivey labels.

The `*v2*.json` runs repeat the local cash-reset settings. The Ivey replay was
also hardened using PokerKit, and reporting seeds/seat IDs changed. Therefore
the v1/v2 sampled Ivey action rates are **not a controlled measure of imitation
improvement**. The first reports are retained as diagnostic history; they lack
the complete frozen-code manifests added below. Local match results are not
the official event's sit-and-go scoring.

For subsequent revisions, run from this source checkout:

```sh
.venv/bin/python scripts/evaluate.py revision-3 --hands 800 --samples 5000
```

Each new directory contains primary and separately reconstructed Ivey results
for the fast and two offline reference policies, a qualitative packet including
the separately labeled video snapshot, warm latency and legality checks, and
three local baseline matches. The manifest records source/data hashes, Python,
platform, PokerKit version, seeds and sample counts. A `source.zip` retains the
exact evaluated code/data and source license so later edits do not erase the
baseline. Evaluation rejects a
concurrent source change and refuses to overwrite a completed revision.

The qualitative packet is the useful human-review artifact: inspect range,
aggression, sizing, price and unknown reads. The sample scores describe the
selected observations; they cannot verify the original >99% population target.
The video snapshot has rounded or missing context and is included only in the
qualitative packet, never silently added to scored results.
