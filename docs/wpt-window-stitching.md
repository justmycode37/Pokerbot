# WPT chronological window integration

The current combined capture is `data/public_ivey_session_wpt_derived/windows01-02-v3/`.
It covers the official [WPT finals broadcast](https://www.youtube.com/watch?v=daR3q3KKQ0o)
from **00:43:24 to 01:07:24**, a half-open 24-minute interval. It combines the corrected
first-window transcript with the second-window source capture without changing either source.

The combined ledger contains **80 Ivey decisions across 32 observed hand contexts**,
plus four zero-decision walks. There are 36 unique contexts in total, 35 completed and
one boundary-truncated. H20 spans the two source windows: its first decision is retained
once, then the second window supplies its continuation. The next boundary is H36 after
the turn checks: pot 13,280, conditional remaining stacks Ivey 113,738 and Antonius 72,982.
The river and later choices are outside this capture.

All 80 decision rows replay under the pinned PokerKit rules through the existing PHH
loader. The generated PHHs keep opponent cards unknown. The source JSON and replay
agree on hero cards, visible board, street, position, pot, stack, call price, labels,
and legal raise bounds. These are checks of the recorded ledger's consistency.

**All 80 remain pending source review and are excluded from the admitted comparison
corpus.** The official seven-hand blind schedule still conflicts with the observed
context sequence. Rounded stack badges do not independently confirm exact carried
balances; those balances remain conditional on a complete transfer chronology.
H04's turn order is corrected from source review, but its exact retained predecision
frame time remains withdrawn, with only the 47:24–47:32 interval retained. Window 2
still needs an independent source and redaction audit. Showdown payouts use public
winner indicators; unknown opponent cards cannot independently prove those results.
H01–H36 are provisional observed-context aliases, not certified official hand ordinals.

The stitcher rejects overlapping or reordered windows, duplicate decision IDs, and
inconsistent boundary hand contexts or carried balances. It retains original source
hashes and metadata per fragment, rewrites evidence paths, and recomputes the combined
time range and counts. Earlier `windows01-02-v2` is a superseded draft: its replay
passed, but its root counts and time range incorrectly retained first-window metadata.
Use v3 for the combined capture.

Reproduce in a new output directory:

```sh
.venv/bin/python scripts/stitch_wpt_windows.py \
  data/public_ivey_session_wpt_derived/source-corrections-v1/records.json \
  data/public_ivey_session_wpt_windows/w02/records.json \
  --output /tmp/wpt-windows01-02-new
.venv/bin/python -m unittest discover -s tests -p 'test_wpt*.py' -v
```

No policy inference, fitting, bot comparison, or accuracy scoring is performed by this
integration. Source acquisition remains the priority before strategy work resumes.
