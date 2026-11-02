# HCL 2021 source window 01

## Scope and source

Data-only acquisition from the public [Hustler Casino Live stream](https://www.youtube.com/watch?v=bG7K_zq0MoQ), published 2021-10-24. The official uploader is Hustler Casino Live (`@HustlerCasinoLive`); listed source runtime is 30,830 seconds.

The recovered local segment began at source time **00:34:00**. The first visible live-hand frame was sampled at **00:36:10**, after countdown/introduction; the frozen selection is **00:36:10–01:00:10** (24 minutes). At 00:36:10 Garrett is visible in the UTG action area and the graphic reads `$200/200/400 + $200 BB ante`. The exact deal and forced-bet boundary is unresolved, so 00:36:10 is the first observed active-hand frame, not a verified first action.

See [`records.json`](../data/public_ivey_session_hcl_2021_window01/records.json) for the factual ledger. Source observations are separate from expected-action labels. `RAISE TO` totals, `BET` added amounts, and `TO CALL` amounts are kept distinct. A displayed `$4K` 3-bet remains semantically unresolved. HUD stacks are rounded and approximate; exact initial stacks were not inferred. These displays do not support exact admission/buy-in values.

## Checkpoint counts

- Acquired decision states: **12**
- Complete / partial decision states: **0 / 12**
- Independently reviewed decisions: **0** (no separate reviewer)
- Partial Ivey hand records: **4** (three decisions each)
- Partial contexts without an observed Ivey action: **1** (Ivey participation unknown)
- Confirmed sitting-out intervals: **0**
- Possible Ivey `OPTION` state near 00:45:10: **1**, excluded from acquired count because identity is unconfirmed
- Acquired hands/contexts: **5 total, all partial**

All decision states remain partial. Required action prefixes, forced-bet postings, and exact stack precision are incomplete. This is an in-progress factual ledger and carries no accuracy claim.

## Board graphic near 00:38:20

The suspected stale board was checked using adjacent pot-panel crops: at 00:38:20 the board area is blank and the pot reads `$1.8K`; at 00:38:30 the board shows `J♥ 7♥ A♥ J♦`; at 00:38:50 it adds `5♠`. The sampled progression differs from H0001's board and is consistent with a new hand. Exact action-to-card synchronization and action history remain incomplete, so H0002's later street states remain partial.

## Evidence and cleanup

Retained evidence: three redacted full stills for H0001 and nine pot/board-only crops for H0002–H0004. The crops preserve public pot, board, and blind graphics without player-card panels. Temporary video, captions, metadata, unredacted frames, contact sheets, and review-only crops have been removed from this assigned data directory after evidence extraction. A separate reviewer has not validated the evidence or transcription.

No full per-hand chip ledger or exact admission/buy-in values are supportable: rounded HUD stacks, missing initial stack values, incomplete public action prefixes, and untranscribed individual forced bets prevent exact conservation checks. Observed wager/pot displays and bet-added versus raise-to wording are retained without inferred totals.

## Handoff

This pass stopped at the user's request to prioritize bulk structured sources. If HCL coverage resumes, continue this frozen interval from **00:42:10 through 01:00:10**; enumerate hand boundaries, routine folds/checks, no-Ivey-action contexts, and sitting-out intervals; resolve the 00:45:10 candidate; then complete the public action prefixes and forced-bet chronology for H0001–H0004. Preserve unknown stacks and partial statuses. The first-deal boundary at 00:36:10 also needs confirmation. Do not count any decision as independently reviewed until a separate reviewer checks it.
