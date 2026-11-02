# Equity policy implementation audit

Date: 2026-11-02

## Scope

This publishes the optional injected-estimator policy with
`pokerbot.evolution_strategies`, the public-information genome and policy module
it uses for genome validation and unchanged preflop behavior. No checkpoint,
model, dataset, or tournament-result artifact changed. No model was loaded or
trained.

## Verification protocol

Use focused `unittest` cases with synthetic public observations. Compare full
preflop result objects against the current evolved policy over several card
fixtures and deterministic seeds. For postflop behavior, use deterministic
stub estimators and verify estimator inputs, exact-proof handling, calibrated
share accounting, legal projections, and bounded raise totals. Do not infer
model accuracy or promote a model from these tests.

No eight-player tournament or model-performance workload was run. There is no
calibrated runtime model to evaluate, so these checks provide no model accuracy
or promotion evidence.

## Results

`python -m unittest tests.test_equity_policy tests.test_evolution_strategies -v`
passed all 24 focused tests. Coverage includes:

- exact preflop parity for 20 fixture/seed combinations, with no estimator call;
- injected share and pressure diagnostics on a top-pair decision;
- no duplicate multiway equity deduction for five active players;
- shared-board tie and unbeatable-hand exact overrides;
- estimator inputs limited to the hero cards, public board, and active count;
- invalid and unavailable estimator behavior;
- legal-action projection and a short all-in raise bound;
- independent per-policy estimator and metadata state.

The full repository suite passed all 229 tests in an isolated environment with
the `evaluation` extra (`pokerkit==0.7.7`) installed. The local equivalents of
the CI verification commands also passed: admission and protected-file checks (35 frozen files),
saved-bot source-group verification, an installed-wheel smoke test outside the
checkout, and publication checksum verification. The built wheel imported
both `pokerbot.equity_policy` and `pokerbot.evolution_strategies` from
`site-packages`. These local checks used Python 3.12.10.

Equity-policy tests use synthetic observations and deterministic estimator
stubs. The strategy dependency tests also exercise simulated hands. No
tournament or evolution run was executed.
