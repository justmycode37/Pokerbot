# Independent admission audit — 2026-11-02

## Scope and disposition

No admissions or corpus changes were made. The protected `pokerbot/`, `data/models/`, and `data/corpus_splits/` paths were read only. Frozen baseline records were checked for file/manifest/hash integrity only; they were not policy-reviewed. All 35 new records remain inspected development data, not fresh held-out data.

## Reconciled counts

| Set | Decisions | Unique hands | Groups |
|---|---:|---:|---:|
| Frozen baseline | 45 | 12 | 8 |
| Batch 001 | 30 | 29 | 2 |
| Batch 002 | 5 | 2 | 2 |
| Combined | 80 | 43 | 12 |

Batch 001 is 28 Triton 2026 rows, one eligible Triton 2025 row, and one previously pending sample row. The 2025 decision has two episode provenance references but one source hand/action key. The one sample row is a distinct source hand/action and shares the Triton 2026 tournament group; it adds one hand, not an episode count. Batch 002 is one Card Player 1547 decision and four Card Player magazine 35-14 decisions.

The 21 rows needing ante correction exactly equal the 21 `held_source_decision_ids`; none of those exact hand/action keys are admitted. One held action from hand `3202f078-1b51-4de2-9e20-72a58e05a8a4` is action 6, while a separate unaffected action 10 from that same hand is admitted. This is a distinct source action, not a duplicate.

## Integrity and source verification

- Frozen baseline SHA-256: `d172e7310677b051b8dea0163fb14b06b81ad9b5847c73d735f1e2ec66c1a483`; baseline file hash matches batch 001's baseline reference. Recomputed baseline dataset and split hashes match `3cbb867908ec7c603d8f0cb33e7843f34234ddd5f30e251729007c6b7ec1d420` and `d35341894333fa8e632d507a0169d04b1f7ecdcf1477f568e54dec29eea62a85`.
- Recomputed normalized decision IDs and record hashes: 45/45 baseline, 30/30 batch 001, 5/5 batch 002. Combined: 80/80 decision IDs unique and 80/80 record hashes unique; group IDs recompute to 12 groups.
- Batch 001 file SHA-256: `3d2e387b997fab022c9a4a1a75d84e8dfe6d1c8606644cb353c217288dc5e0ac`. Batch 002 file SHA-256: `0bcc76745a35e0f8bb846abff97cdcb750f47aefef3c07d9cceb7587b9171efe`.
- All 30 batch-001 rows (28 Triton 2026, one Triton 2025, and one prior sample) match their raw capture hash and target actor. Independently reconstructed prior history matches actor, normalized action, added chips, and street in all 30. For raw folds, the source omits an amount and the reconstructed added amount is zero. `state.history.amount` can include an actor's prior forced contribution, so it is not compared directly to the raw per-action increment. Raw hand UUID, original round/action identity, hero cards, board prefix, target label/raise target, and raw prefix pot/remaining hero stack also match. Triton 2026 rows additionally match canonical payload, request, query, and per-row-review hashes.
- Independent ante-inclusive contestable-pot reconstruction matches all 30 Triton states. The 2025 row is `triton:0fe69d0d-c62f-4a47-baac-7770b44b9bdb:action:7`: its 100,000 dead ante is inside the 450,000 pot/contestable pot. The prior sample `triton:485c77c7-8ff8-4a55-922c-09b8883819dc:action:6` includes 250,000 dead ante in its 1,125,000 pot/contestable pot.
- Nontrivial side-pot case `triton:38f21d2a-7d7b-4c51-90f1-09d60b7978bd:action:8`: total pot 3,000,000; 200,000 big-blind ante remains contestable; the 125,000 excess above Ivey’s 2,375,000 maximum contribution is not contestable, giving 2,875,000.
- All 5 batch-002 report fact, PHH, review hashes, legal labels, and zero-based hero IDs match. Report packet SHA matches `corrected-and-held.json`; source observations were unchanged and zero source-capture files were modified by the correction artifact. The corrected 5 rows in that artifact match batch 002.
- Four Montenegro report rows remain held as aliases of Triton hand `7c9c95b2-1469-48d9-8c8e-cdf335831fbc`. Raw Triton gives Ivey 13,550,000; the magazine reports 13,600,000 and its legacy pot omits a 300,000 BBA. They are not in batch 002 and do not increase the 80 count.
- WPT partial evidence remains uncounted: 35 partial decisions, zero admissions in parent integration 006.

## Report rows and actor/card audit

Card Player 1547 supports the heads-up, 30,000/60,000 blinds, 5,000 ante, Ivey AhQd with 3.45m, Antonius with 550k, and Ivey’s call. At decision time, PHH/state p0 is Ivey, p1 is Antonius; Ivey has 3.385m, faces 485k, and sees 615k contestable pot. [Card Player 1547](https://www.cardplayer.com/hand-matchups/1547).

Card Player magazine 35-14 supports the four admitted source decisions `cardplayer-mag-35-14:decision-1` through `:decision-4` (preflop call, flop check, turn call, river raise to 200,000). It reports the 2022 Triton Madrid €50k NLHE Seven-Max hand, five-handed table, 10k/20k blinds and 20k BBA, Rast’s 40k open, Ivey’s call, Kc5d4h / 5c / 7c board, and the 40k turn bet/call and 65k river bet/200k raise. Q-9 is suited and the turn creates a full flush draw on a board with Kc and 5c, so Ivey’s suit is uniquely Qc9c. [Card Player magazine PDF](https://media.cardplayer.com/assets/magazines/000/066/492/pdf/35_14_web.pdf). The four action rows map to p4 Ivey; p2 Rast; p3 CO; p0 SB; and p1 BB. The source calls Rast “hijack”; the replay maps this first-to-act seat to canonical UTG for the explicitly five-handed table. That position-name normalization is visible in history; the actor identity and action order are correct. The off-by-one actor-name error is absent from the corrected rows.

## Minimum unknown-stack invariance

For the magazine PHH, the minimum positive integer-chip stacks that allow the reported folds are p0 SB 10,001; p1 BB 40,001 (20,000 BBA + 20,000 BB, with one chip left); and p3 CO 1. The known players remain p2 Rast 510,000 and p4 Ivey 1,160,000. These lower bounds permit every forced post and leave no further contribution before the four decisions, so the recorded Ivey states are arithmetically unchanged; unknown stacks remain absent from admitted observations.

Limit: the current environment lacks `pokerkit`, so an independent engine replay at the minimum values could not be run. The saved 1m / 10m / 1b probes all match; the minimum case was checked from the exact action ledger, not replayed through the engine. No package was installed.

## Machine-readable evidence

See [`audit-results.json`](./audit-results.json) for file hashes, source-row identifiers, record/decision hashes, per-row raw checks, ante calculations, and the replay limitation.
