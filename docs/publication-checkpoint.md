# Reviewed acquisition checkpoint — 2026-11-02

Acquisition is stopped at the user's request. The ledger contains **606
source-reviewed decisions from 393 hands across 18 source groups**. All are
inspected development data. This checkpoint makes no policy accuracy claim
and creates no fresh evaluation holdout.

| Admission set | Decisions |
| --- | ---: |
| Frozen development baseline | 45 |
| Batch 001: earlier Triton review | 30 |
| Batch 002: written reports | 5 |
| Batch 003: cash review, both partitions | 462 |
| Batch 003: ante corrections | 21 |
| Batch 003: historical tournament review | 43 |
| Total | **606** |

The earlier acquisition target was 1,000 usable decisions. The user ended
acquisition with 394 remaining. Pending forum candidates, unknown-card
histories, incomplete WPT video states, the five unoccupied-dealer historical
candidates, and four duplicate Montenegro report observations are excluded.
The 221 cash decisions previously present in a pending conversion are counted
once. The complete 2024 cash festival is pooled conservatively as one source
group, retaining the native event and episode UUIDs as provenance. Archive
coverage is sparse and does not establish complete chronology.

The source replay checks reconcile action order, source amounts, legal labels,
hero cards, stack, pot, and call price. Source raise and all-in amounts are
incremental chips added. The acquisition converter separately reconstructs
contestable pots so explicit dead antes remain common money. It preserves
original round/action keys and raw capture, request, query, and episode
provenance outside observations. Opponent cards, future board cards, later
actions, and outcomes do not enter the predecision observation.

The strategy code under `pokerbot/`, model files, and frozen corpus splits are
unchanged. The frozen development split still contains 45 rows. New admission
batches live separately under `data/acquisition_resume/2026-11-01/admissions/`;
they have not been added to a training or evaluation split. No policy was
trained or scored on these additions.

## Reproduce verification

From the repository root with Python 3.11 or later:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[evaluation]'
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/acquisition_admissions.py
shasum -a 256 -c data/acquisition_resume/2026-11-02/publication/publication.sha256
```

The ledger verifier validates the frozen split and every new row's legal
label, decision identity, record hash, source identity, development status,
and referenced provenance hashes. It checks all 35 protected source/model/
split hashes against the takeover checkpoint. The published verification
result is `data/acquisition_resume/2026-11-02/publication/admission-verification.json`.

Batch 001's legacy aggregate `dataset_hash` does not match its current row
hash set. Its immutable file is retained, and every individual row hash and
source reference validates. The verifier reports that discrepancy explicitly
and supplies a freshly computed hash of all 606 retained record hashes; the
publication checksum manifest additionally pins the complete batch files.

The CI workflow runs the full unittest suite, the admission verifier, and the
publication checksum check on Python 3.11 with read-only repository
permissions. Local verification uses Python 3.12 and the pinned PokerKit
0.7.7 optional dependency. Local results and clean-checkout verification are
recorded alongside the publication manifests. GitHub CI must pass before
the authorized merge.

## Published files

`required-data-fixtures.txt` is the exact repository-relative allowlist for
test fixtures and admission provenance. `cohort-provenance-files.txt` records
the additional reviewed cohort's dependencies. `publication-context-files.txt`
lists retained research context, which does not add usable decisions.
`publication.sha256` pins the selected source, documentation, tests, data,
and workflow files.

The publication includes retained JSON/JSONL source captures, request sidecars,
PHH files, and bounded evidence stills needed by its tests and provenance.
Local environments, caches, temporary working trees, downloaded frontend
bundles, source recordings, and incomplete downloads stay outside Git.
Unpublished local research artifacts are preserved in the workspace.
