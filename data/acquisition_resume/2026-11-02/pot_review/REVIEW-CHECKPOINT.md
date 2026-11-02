# Pot eligibility independent review checkpoint

Review completed 2026-11-02. No source code, tests, admissions, corpus splits, model data, conversion outputs, or git state were modified by this review. All review artifacts are confined to this directory.

## Verdict

Recommend integrating `inspect_prefix_pot` for contestable-pot eligibility after the converter's existing raw-source checks and engine replay. Preserve the original flattened action ordinal, reject `PrefixPotError`, and cross-check helper `pot` and clipped `to_call` against the engine prefix as specified in the Nov. 1 integration note. The helper alone does not validate seat order or full action-turn legality; the converter/replay remains responsible for those checks.

No material mathematical error was reproduced. Conservative unsupported short blind behavior is confirmed: a BB smaller than the preceding SB contribution is rejected with `big_blind_below_small_blind`; reversed live forced-bet order is rejected with `unsupported_live_forced_bet_order`.

## Verification

- Re-ran all 10 focused eligibility tests: pass.
- Independently parsed 50 diagnostic prefixes across 48 unique raw capture files and 50 canonical decisions. For all 50, source hand ID, target actor/ordinal, prefix pot, diagnostic ante total, raw call due, clipped call, and independently calculated reachable contribution tiers matched. Raw action timestamps in each checked prefix were nondecreasing.
- Recomputed the diff: 21 old values differ (19 from 2026 and 2 from 2025); 29 remain unchanged. The 50 independent capture hashes match the helper's reproduction report.
- Mutated target amounts, suffix actions, cards, terminal pots, and ending stacks for all 50 hands; helper outputs remained unchanged.
- This confirms the 50 source rows only. It does not admit or correct them. The current 80 admitted examples remain unaffected and development-only; there are no fresh held-out rows from this review.

## Reporting caveat

The reproduction JSON reports 75 usable / 30 newly admitted because `reproduce_ante_diagnostic` reads only the Nov. 1 `admissions/batch-001.json`. That is a historical scope snapshot, not the current 80 / 35 state (which also includes batch-002). Do not use those sidecar ledger totals as current inventory. The eligibility math and 21 pending correction identities are unaffected.

## SHA-256

- `scripts/acquisition_pot_eligibility.py`: `3bf5bb521dfca1e4ed16871f19d50fef125cdded6c2ebd3ae253ab805dda6556`
- `tests/test_acquisition_pot_eligibility.py`: `9434079e51047e3130416f76912cf768abd35a33055f751e3664274d9c7663a2`
- Nov. 1 integration note: `9dbd22c4b82deb010c36ee0fc2c2368b3f215d2b98692c094a3d4e672966c361`
- 50-row ante diagnostic: `dca5d4ccdc914d2fc97b2fb66992324a757bbc1ac5917cc4d0055217db485269`
- helper reproduction output: `88e5bb0fe957b2572dda3b99ed908ce21d9e2618c6c97f5ceb8d3dd5cecd86b3`
- independent source-row audit: `872d3c6417ad84d2a7b9162bcd26cbaacb2823f18dd4ea4f1bc56c680ee650a8`
- checked protected references match Nov. 1 checkpoint hashes: `pokerbot/simulation.py` `80f0ea85dade54141ce814af76a7a271875389615e00793fa7202e51a4cf7b97`; development split manifest `d172e7310677b051b8dea0163fb14b06b81ad9b5847c73d735f1e2ec66c1a483`.
