# Ivey decision replay benchmark

## Evidence scope

The public [`uoftcprg/phh-dataset`](https://github.com/uoftcprg/phh-dataset) repository contains one explicitly named Ivey NLHE record: `data/dwan-ivey-2009.phh`. I inspected the repository tree, downloaded that source record, and scanned the other 4 top-level named historical PHHs and all 83 WSOP hand records for Ivey mentions; none contained another Ivey reference. The repository also lists 10,000 Pluribus hands and a HandHQ corpus described as anonymized, so those records cannot be attributed to Ivey from the published identities. I did not treat them as Ivey benchmark examples.

The source is the televised 2009 Dwan–Ivey–Antonius hand. This replay uses **4 observed Ivey decisions from 1 hand**:

| Street | Decisions | Observed labels |
| --- | ---: | --- |
| Preflop | 1 | raise to 23,000 |
| Flop | 1 | raise to 35,000 |
| Turn | 2 | raise to 90,000; raise to 1,067,100 |

These are four sequential choices from the same hand, not four independent examples. They share the same hero cards and unfolding action line. This sample cannot establish general Ivey behavior, policy quality, or a useful population accuracy estimate.

The source file and its upstream MIT license are retained under [`data/ivey/`](../data/ivey/README.md). Source: [official PHH record](https://github.com/uoftcprg/phh-dataset/blob/main/data/dwan-ivey-2009.phh).

## Replay contract

`pokerbot.ivey.load_decisions(path=None)` returns rows with `state`, `expected`, `source`, and `hand_id`. It parses PHH as TOML and uses pinned PokerKit 0.7.7 to validate every action without implicit folds or source repair. Install the `evaluation` extra to replay histories. The state contains only Ivey's dealt cards, the visible board and betting history, pot and stacks, legal actions, and position. Stable seat identifiers such as `p0` identify the hero and prior actors. `contestable_pot` excludes inaccessible side pots; table size is explicit.

Pot is the sum of chips actually committed by all players by that point, including antes and blinds. Raise amounts in `expected`, history `amount`, `min_raise_to`, and `max_raise_to` are total targets for the current street; history `added` records the chips added on that action. For a call, replay pays the lesser of the call amount and the player's remaining stack. `players_to_act` counts other live, non-all-in players already pending action at the observed state; it does not predict which players would respond to a raise the actor has not yet chosen.

No opponent hole cards, future board cards, future actions, or labels enter a policy observation. Reporting hand IDs and arbitrary metadata are removed before callbacks run; history is whitelisted and deeply copied. Unknown hero cards are excluded rather than recovered from a later showdown. A corrupt or illegal action rejects the whole source file, preventing later snapshots from inheriting stale state. Inspect `pokerbot.ivey.LAST_LOAD_REPORT` for exclusions.

Fractional currency values are converted to exact integer ticks, with up to six decimal places. `chip_ticks_per_currency_unit` on each decision records the conversion. Sizes and sizing tolerances use those ticks; fractions are never silently truncated.

The bot interface remains `decide_callable(state) -> {"action": "fold|check|call|raise", "amount": optional street-total target}`. No strategy import or API change is required.

## Scoring

`compare_decisions(decisions, decide_callable, sizing_tolerance=0)` checks legal actions and integer raise bounds before awarding credit. It reports action-class agreement separately from exact action-plus-size agreement, absolute sizing error, sizing error relative to the pot after calling, and the probability assigned to Ivey's action class. Missing, illegal or out-of-range predicted raises cannot receive agreement credit. Expected actions must also be legal. Mixed-action probability is descriptive and is not an exact bet-size likelihood.

The Wilson interval is computed over decision rows and does not adjust for within-hand dependence. It is explicitly descriptive; `population_confidence_interval` is null. Do not tune the policy to these labels or present a high score here as broad validation.

## Qualitative review

Run `.venv/bin/python -m pokerbot review-ivey --output reports/qualitative-ivey.md` to produce a readable Markdown packet and companion JSON with code/table fingerprints. Each decision records the visible facts, bot action and diagnostics, recorded Ivey action, sizing and pot odds, and specific questions about range, aggression and missing opponent reads. These are hypotheses for review, not automatic judgments that either action is optimal. `--include-reconstructed` adds the separately labeled CardPlayer report discussed in `docs/ivey-candidates.md`.

## Missing data and limitations

The benchmark includes 4 decisions and excludes 0 because Ivey's cards and the relevant action sequence are present in the source. Antonius's unknown hand is not required to replay Ivey's legal state and is never copied into it. The source record has no Ivey decision after the turn; the river is dealt after the recorded showdown actions, so no river decision is invented.

Other Ivey hands may exist in external footage or records not identifiable in this PHH repository. The anonymized HandHQ data cannot be attributed to him from its published metadata. The current score therefore evaluates a small historical case study, not a representative benchmark.
