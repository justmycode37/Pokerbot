# Review: equity recalibration v2

## Findings

**No material issues found.** No P1 or P2 findings. The candidate remains an optional calibration artifact and must stay separate from runtime use or claims about playing strength.

## Data flow and provenance

- `load_training_partition` hashes the full original JSONL and reconstructs canonical card-state groups before calling the trainer row parser only for groups assigned `train` by the pinned freeze. It JSON-decodes records to read public cards, but does not access or validate calibration targets. The saved inputs reproduce 42,000 input rows, 33,592 training rows across 16,783 groups, and 8,408 excluded calibration rows across 4,196 groups. The existing test instruments the row parser and asserts that it receives only train-assigned IDs.
- The saved OOF file contains one row for every training ID. I matched each OOF row to its training group and player count, verified the target against the train-assigned row, recomputed the deterministic group-to-fold map, and confirmed that each canonical group stays in one fold. The fold group counts are 5,595 / 5,594 / 5,594; the recorded assignment digest matches. Since the group key canonicalizes hole cards and board without player count or replicate, this covers those rows together.
- The preserved fit source SHA matches the calibration-source fingerprint in the frozen protocol. In `load_fresh_test_rows`, the only changed join behavior is schema handling: labels are joined to the pre-frozen state by ID, `replicate` is taken from that state, and the parser checks the frozen `trials` request instead of requiring the generator-omitted `samples` field. The rest of that function matches the saved fit source after those substitutions. The original `run` body also matches after removing only the line that saves the preserved source.
- The runner adds a resume path that validates the frozen protocol, preserved source, candidate, transform, OOF digest and folds, public plan, and reference-file hashes before scoring existing labels. It does not call OOF fitting, candidate creation, or candidate sealing. The candidate file and transform hashes match the run receipt; the candidate's internal SHA is `d8321112…734d3`, and the transform SHA is `64b4efb1…934d6`.
- The saved fresh set has 2,100 distinct public-state groups, exactly 100 groups in each of the 21 street/player strata, and no overlap with the 20,979 original groups. Its 4,200 labels each carry 1,024 trials, with 4,300,800 trials total. The actual generator rows omit `replicate` and `samples`; label IDs are unique, both replicates join to their frozen state, outcome totals sum to 1,024, and shares agree with the saved share sums.
- The bootstrap implementation resamples canonical public-state groups and keeps the two Monte Carlo rows together. Re-scoring the existing labels against the frozen v1 model and correction reproduced the saved metrics and intervals exactly; row-level outputs also match the CSV to its displayed precision.

## Verification evidence

The read-only audit records 22/22 checks passing in [the evidence JSON](../../.work/equity-recalibration-v2-review-evidence.json). It compared the portable transform with the reference interpolator on 5,712 bounded inputs across all seven player counts: maximum absolute difference was 0, and outputs were monotone and bounded. Invalid numeric and player-count inputs were rejected. A tampered in-memory candidate was rejected by candidate hash validation.

The fit-source to runner comparison is saved in [the unified diff](../../.work/equity-recalibration-v2-review-runner-diff.txt). The reproducible audit is [equity-recalibration-v2-review-audit.py](../../.work/equity-recalibration-v2-review-audit.py). It used `.venv/bin/python`; it did not run the test suite, regenerate labels, refit OOF models, generate matches, or install packages. The root agent reported that all eight tests passed; I reviewed the tests without rerunning them.

## Limits

The artifact measures public-state showdown-share calibration only. It says nothing about action EV or full-match playing strength, and the descriptive bootstrap intervals do not establish a 95% superiority claim. The report and source establish the intended order of sealing and scoring. No per-attempt logs for the two schema failures were among the reviewed artifacts, so I did not independently reconstruct their exact command chronology.
