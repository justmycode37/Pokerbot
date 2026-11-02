# Ante correction independent review (2026-11-02)

## Scope and disposition

Reviewed the exact 21 rows in `ante_correction/candidates.json`; the row IDs match all 21 diagnostic rows needing correction and cover 21 unique hands. Of 50 diagnostic decisions checked, the 29 unaffected ones were not copied into the review set.
The regenerated conversion files contain 22 unique decision IDs; their only output-only key(s) outside this 21-row review are `triton:3202f078-1b51-4de2-9e20-72a58e05a8a4:action:10`. The extra key is already admitted and excluded from the correction recommendations.
Independent raw-prefix recommendation: 21 eligible for a separate parent development-only admission review; 0 held. Admissions created: 0. Fresh holdout rows: 0. The current admitted count remains 80.
Exact admitted source-key overlap: 0. 1 candidate hand(s) have a different action already admitted; those source decision keys are distinct.
The eligibility status is not an admission. All reviewed records remain development-only, and no policy, training, score, admission, split, frozen-data, or model operation was run.

## Method

For each row, I re-read the cached source capture and GetHand request; recalculated their byte hashes, the query hash, and canonical hand payload hash; checked the request hand and episode variables against cached episode metadata; and listed every cached episode alias containing the hand.
I walked only the source action prefix before the target decision. I accounted for explicit dead ante posts (including a big blind's ante), live blinds/straddles, and prior betting payments. I formed live contribution tiers directly from those source payments, including folded contributors, and counted only tiers reachable by the hero after calling and by at least one live opponent. Dead antes were added as common money. Neither the converter, PokerKit, the frozen helper, opponent private cards, terminal pots, winners, nor end stacks were used as the equality oracle.
I also checked physical seat order, button/SB/BB identity, preflop actor queue, the hero's remaining stack, call price, raise bounds, public board cutoff, exact prior-action history, source label mapping, development-only status, state-field whitelist, and predecessor-row diffs. The predecessor comparison confirms only `contestable_pot` changed in each state; expected labels and stable source decision keys match, while decision IDs changed. Where a predecessor did not persist round/action subkeys, equality is derived from its unchanged flat source action locator and the same raw source array position.

## Per-row accounting and recommendation

| Source decision | Dead ante | Live pot before action | Old → corrected contestable pot | Recommendation | Notes |
|---|---:|---:|---:|---|---|
| `triton:238da98b-1804-492f-9518-64cb73388dfd:action:3` | 150000 | 375000 | 225000 → 375000 | eligible_for_parent_development_only_admission_review | all independent checks passed |
| `triton:7233ae8e-33b6-4786-a574-8623b63c849b:action:4` | 150000 | 375000 | 225000 → 375000 | eligible_for_parent_development_only_admission_review | all independent checks passed |
| `triton:23899063-1648-48ae-ba75-e19736f62607:action:5` | 250000 | 625000 | 375000 → 625000 | eligible_for_parent_development_only_admission_review | all independent checks passed |
| `triton:26564730-167d-4edc-957d-884a19fa2fe3:action:3` | 200000 | 500000 | 300000 → 500000 | eligible_for_parent_development_only_admission_review | all independent checks passed |
| `triton:3202f078-1b51-4de2-9e20-72a58e05a8a4:action:6` | 250000 | 625000 | 375000 → 625000 | eligible_for_parent_development_only_admission_review | all independent checks passed |
| `triton:46b26eec-7ee5-494b-9dd5-885db8c5318b:action:3` | 250000 | 625000 | 375000 → 625000 | eligible_for_parent_development_only_admission_review | all independent checks passed |
| `triton:47e1dbd2-ebd2-484e-b15c-3a5d281b7260:action:4` | 150000 | 375000 | 225000 → 375000 | eligible_for_parent_development_only_admission_review | all independent checks passed |
| `triton:4b7834c2-7399-4f17-b608-f1a6ec2c0709:action:3` | 250000 | 625000 | 375000 → 625000 | eligible_for_parent_development_only_admission_review | all independent checks passed |
| `triton:5646b6a0-ac9f-4924-921d-23e57364de3f:action:6` | 150000 | 375000 | 225000 → 375000 | eligible_for_parent_development_only_admission_review | all independent checks passed |
| `triton:5ab29a77-01a3-474c-b142-55a44b1c9f86:action:8` | 250000 | 1025000 | 925000 → 1025000 | eligible_for_parent_development_only_admission_review | all independent checks passed |
| `triton:5b7014d8-d730-4290-83d2-f49ff318c4b9:action:4` | 200000 | 500000 | 300000 → 500000 | eligible_for_parent_development_only_admission_review | all independent checks passed |
| `triton:7e7c09d2-911c-40dc-a856-29e356881f98:action:4` | 250000 | 625000 | 375000 → 625000 | eligible_for_parent_development_only_admission_review | all independent checks passed |
| `triton:80813dde-3d2d-4000-bf4b-621775703e44:action:6` | 200000 | 500000 | 300000 → 500000 | eligible_for_parent_development_only_admission_review | all independent checks passed |
| `triton:9dd266da-35c6-4a6e-992e-7703b663951d:action:9` | 250000 | 7650000 | 3800000 → 3550000 | eligible_for_parent_development_only_admission_review | all independent checks passed |
| `triton:9e27b1d3-fb94-4807-acf6-2f1b1f88e20c:action:3` | 150000 | 375000 | 225000 → 375000 | eligible_for_parent_development_only_admission_review | all independent checks passed |
| `triton:9e8f436e-7969-457d-8eb9-52c671018ada:action:3` | 150000 | 375000 | 225000 → 375000 | eligible_for_parent_development_only_admission_review | all independent checks passed |
| `triton:9eb09c11-8af6-4dad-a4a6-f81f373eb9ca:action:7` | 125000 | 300000 | 175000 → 300000 | eligible_for_parent_development_only_admission_review | all independent checks passed |
| `triton:a28ed451-3515-4197-bc58-04c89fce7197:action:3` | 200000 | 500000 | 300000 → 500000 | eligible_for_parent_development_only_admission_review | all independent checks passed |
| `triton:a3bf889c-bee5-4dbb-aa00-527b4114c7f6:action:4` | 250000 | 625000 | 375000 → 625000 | eligible_for_parent_development_only_admission_review | all independent checks passed |
| `triton:c3bb5083-4b04-47e2-ac6b-a146a3a9f704:action:9` | 200000 | 8450000 | 2675000 → 2475000 | eligible_for_parent_development_only_admission_review | all independent checks passed |
| `triton:dc29202b-88a6-437d-9546-0968babfc2c7:action:4` | 150000 | 375000 | 225000 → 375000 | eligible_for_parent_development_only_admission_review | all independent checks passed |

## Episode aliases and partial source facts

| Source decision | Requested episode | Cached aliases that index the hand | Source context |
|---|---|---|---|
| `triton:238da98b-1804-492f-9518-64cb73388dfd:action:3` | `a6f4a4cc-d665-4268-8805-660d7e569da0` | `a6f4a4cc-d665-4268-8805-660d7e569da0` (Final Table Highlights); `fbeb374a-3921-4d87-87ee-6371285c11ae` (Final Table) | 2025 Triton Montenegro: $150K NLH 8-Handed |
| `triton:7233ae8e-33b6-4786-a574-8623b63c849b:action:4` | `fbeb374a-3921-4d87-87ee-6371285c11ae` | `fbeb374a-3921-4d87-87ee-6371285c11ae` (Final Table) | 2025 Triton Montenegro: $150K NLH 8-Handed |
| `triton:23899063-1648-48ae-ba75-e19736f62607:action:5` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` (Final Table) | 2026 Triton Jeju II: $50K NLH 8-Handed |
| `triton:26564730-167d-4edc-957d-884a19fa2fe3:action:3` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` (Final Table) | 2026 Triton Jeju II: $50K NLH 8-Handed |
| `triton:3202f078-1b51-4de2-9e20-72a58e05a8a4:action:6` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` (Final Table) | 2026 Triton Jeju II: $50K NLH 8-Handed |
| `triton:46b26eec-7ee5-494b-9dd5-885db8c5318b:action:3` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` (Final Table) | 2026 Triton Jeju II: $50K NLH 8-Handed |
| `triton:47e1dbd2-ebd2-484e-b15c-3a5d281b7260:action:4` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` (Final Table) | 2026 Triton Jeju II: $50K NLH 8-Handed |
| `triton:4b7834c2-7399-4f17-b608-f1a6ec2c0709:action:3` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` (Final Table) | 2026 Triton Jeju II: $50K NLH 8-Handed |
| `triton:5646b6a0-ac9f-4924-921d-23e57364de3f:action:6` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` (Final Table) | 2026 Triton Jeju II: $50K NLH 8-Handed |
| `triton:5ab29a77-01a3-474c-b142-55a44b1c9f86:action:8` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` (Final Table) | 2026 Triton Jeju II: $50K NLH 8-Handed |
| `triton:5b7014d8-d730-4290-83d2-f49ff318c4b9:action:4` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` (Final Table) | 2026 Triton Jeju II: $50K NLH 8-Handed |
| `triton:7e7c09d2-911c-40dc-a856-29e356881f98:action:4` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` (Final Table) | 2026 Triton Jeju II: $50K NLH 8-Handed |
| `triton:80813dde-3d2d-4000-bf4b-621775703e44:action:6` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` (Final Table) | 2026 Triton Jeju II: $50K NLH 8-Handed |
| `triton:9dd266da-35c6-4a6e-992e-7703b663951d:action:9` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` (Final Table) | 2026 Triton Jeju II: $50K NLH 8-Handed |
| `triton:9e27b1d3-fb94-4807-acf6-2f1b1f88e20c:action:3` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` (Final Table) | 2026 Triton Jeju II: $50K NLH 8-Handed |
| `triton:9e8f436e-7969-457d-8eb9-52c671018ada:action:3` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` (Final Table) | 2026 Triton Jeju II: $50K NLH 8-Handed |
| `triton:9eb09c11-8af6-4dad-a4a6-f81f373eb9ca:action:7` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` (Final Table) | 2026 Triton Jeju II: $50K NLH 8-Handed |
| `triton:a28ed451-3515-4197-bc58-04c89fce7197:action:3` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` (Final Table) | 2026 Triton Jeju II: $50K NLH 8-Handed |
| `triton:a3bf889c-bee5-4dbb-aa00-527b4114c7f6:action:4` | `68c65aa8-edb9-4dcb-99e0-479c02d117bf` | `68c65aa8-edb9-4dcb-99e0-479c02d117bf` (Final Table Highlights); `f28c0720-f7b1-471f-be4f-0d4d558d060d` (Final Table) | 2026 Triton Jeju II: $50K NLH 8-Handed |
| `triton:c3bb5083-4b04-47e2-ac6b-a146a3a9f704:action:9` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` (Final Table) | 2026 Triton Jeju II: $50K NLH 8-Handed |
| `triton:dc29202b-88a6-437d-9546-0968babfc2c7:action:4` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` | `f28c0720-f7b1-471f-be4f-0d4d558d060d` (Final Table) | 2026 Triton Jeju II: $50K NLH 8-Handed |

Prior-hand overlap detail: `triton:3202f078-1b51-4de2-9e20-72a58e05a8a4` has candidate key `triton:3202f078-1b51-4de2-9e20-72a58e05a8a4:action:6` and prior admitted key(s) `triton:3202f078-1b51-4de2-9e20-72a58e05a8a4:action:10`. This is a different source action, not a repeated source decision key.

## Integrity and output hashes

- Candidate input SHA-256: `a229398d9b9df7e25abafd7cc0f5633a08068e6c7ec86a86fbaf43080a1b896a`
- Review code SHA-256: `ed05df9a880cfd3fe0e65df2b156539024d2a168ed0821975188fb32ba5b770a`
- Converter SHA-256 (as recorded in regenerated input): `c50a17e08cb2d76848aace6b241a6f347bf1d4f272930a092cfb916991d88268`
- Pot helper SHA-256 (as recorded in regenerated input): `fffa3df98fe5997d72d7f910c27d0a73536a06d5c82ea4426c7b2ecd28cc88cb`
- Regenerated source output `data/acquisition_resume/2026-11-02/ante_correction/event-01-converter.json` SHA-256: `26f0d40c253b79f9548bfe7c44340d40e53b6e4ff7cf9cb06f8901da6ebac2ca` (matches recorded hash: `True`)
- Regenerated source output `data/acquisition_resume/2026-11-02/ante_correction/event-02-converter.json` SHA-256: `f16068cfe84c278d030fb411cf3b692dc0dbae6408d9118f6bd684389a9460f2` (matches recorded hash: `True`)
- Candidate rows' prior admitted-key overlap: 0
- Machine-readable row review and recommendations have SHA-256 values in `SHA256SUMS`.

## Review limits

This review establishes source-prefix/accounting and row-integrity eligibility only. It does not validate strategy quality, hand-label quality beyond matching source actions, or fresh-holdout status. Every episode alias is listed per row, including the requested episode and alternate indexed-episode references. Episode metadata hashes and captured GetEpisode request hashes are checked against the 2026 collector manifest where it declares a source; 2025 aliases are read from their source capture directories. The 2026 manifest states episode coverage may be sparse, so no complete-chronology claim is made; that chronology limitation remains unsupported by this review.
