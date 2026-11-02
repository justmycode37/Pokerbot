# Frozen comparison of multiple candidates

`scripts/compare_candidates.py` supports named fast, original imitation and
experimental hybrid candidates. It fingerprints their runtime modules, model
files, original fitting manifests and the entire already-inspected corpus. A
separate development-majority baseline is explicitly fitted to the inspected
corpus, rather than mislabeled as each model's original training baseline.

Create a lock only after the candidate is ready for a new comparison:

```sh
.venv/bin/python scripts/compare_candidates.py freeze \
  --inspected-manifest data/corpus_splits/development-after-prospective-v1.json \
  --candidates fast imitation-v1 hybrid-v2 development-majority \
  --output data/models/candidate-lock-new.json
```

Once a new source batch is admitted, score it without fitting:

```sh
.venv/bin/python scripts/compare_candidates.py compare admitted-records.json \
  --lock data/models/candidate-lock-new.json \
  --output reports/candidate-comparison-new.json
```

The command preserves existing outputs. Changed models/code, missing lock
fingerprints, reused source groups/hands, partial/pending rows and unspecified
table sizes are rejected. The same source can have aliases, so manual
cross-source reconciliation remains necessary before admission. A lock does not
independently establish the precision of a hand transcription or the provenance
of an arbitrary model: these named models retain their guarded fitting records.

This evaluator does not imply the experimental hybrid is better or ready to
replace fast. Its independent review must be resolved before choosing which
version to freeze. Grouped development CV is not fresh evaluation. All later
scores remain descriptive of their supplied public cases, with no greater-than-
99% population claim.
