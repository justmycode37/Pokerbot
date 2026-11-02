# Equity policy implementation audit

Date: 2026-11-02

## Scope

This is a standalone implementation of the optional injected-estimator policy.
It changes no existing strategy, evolution, checkpoint, model, or tournament
artifact. No model was loaded or trained.

## Verification protocol

Use focused `unittest` cases with synthetic public observations. Compare full
preflop result objects against the current evolved policy over several card
fixtures and deterministic seeds. For postflop behavior, use deterministic
stub estimators and verify estimator inputs, exact-proof handling, calibrated
share accounting, legal projections, and bounded raise totals. Do not infer
model accuracy or promote a model from these tests.

No eight-player full-table workload was run. The optional smoke would add
little evidence at this stage because the module is not wired to a calibrated
runtime model. Therefore there are no per-bot tournament results to report,
and no accuracy or promotion claim is made.

## Results

`python3 -m unittest tests.test_equity_policy -v` passed 9 tests. Coverage
includes:

- exact preflop parity for 20 fixture/seed combinations, with no estimator call;
- injected share and pressure diagnostics on a top-pair decision;
- no duplicate multiway equity deduction for five active players;
- shared-board tie and unbeatable-hand exact overrides;
- estimator inputs limited to the hero cards, public board, and active count;
- invalid and unavailable estimator behavior;
- legal-action projection and a short all-in raise bound;
- independent per-policy estimator and metadata state.

An additional combined run of `tests.test_equity_policy` and the existing
`tests.test_evolution_strategies` executed 24 tests: 23 passed. The existing
simulation-trace test errored before policy execution because the optional
`pokerkit` package is not installed. The new focused suite itself passed in
that run as well.

The test suite uses synthetic observations only; no cards were sampled and no
table or evolution run was executed.
