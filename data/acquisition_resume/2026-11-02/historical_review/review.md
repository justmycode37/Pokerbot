# Triton 2023–2024 independent source review

Status: completed raw-prefix review; every recommended row remains pending parent admission.

The archive has 273 unique indexed hand UUIDs, 218 Ivey-present hands, and 306 Ivey Texas labels. Of these, 61 labels across 33 hands have two known hero cards; the remaining 245 are partial empty-card labels.

## Counts

| Review result | Rows |
| --- | ---: |
| held_button_order_unverified | 5 |
| partial_missing_hero_cards | 245 |
| rejected_converter_source_history | 5 |
| rejected_frozen_protocol_player_count | 8 |
| verified_pending_parent_admission | 43 |

The converter emitted 48 known-card decisions. Independent raw-prefix checks recommend 43 for parent admission review; 5 are held because the recorded dealer seat is not occupied and button order cannot be independently confirmed. All 48 emitted rows remain pending parent admission. Newly admitted: 0. The batch is inspected and cannot be treated as fresh held-out data.

## Known-card exclusions and blockers

- Heads-up labels replayed under the current ordering fix: 6; per-row source and order results are retained above.
- Button seat not occupied in raw player list: 5 rows. Exact keys: 7c9c95b2-1469-48d9-8c8e-cdf335831fbc:0:5, 7c9c95b2-1469-48d9-8c8e-cdf335831fbc:1:0, 7c9c95b2-1469-48d9-8c8e-cdf335831fbc:2:0, 7c9c95b2-1469-48d9-8c8e-cdf335831fbc:3:0, 7c9c95b2-1469-48d9-8c8e-cdf335831fbc:3:2.
- Frozen >8 actual-player protocol limit: 8 labels (`model_observation_player_count_exceeds_eight`). Exact keys: 762d2829-fa61-4bb1-b42f-f587752268ce:0:11, 762d2829-fa61-4bb1-b42f-f587752268ce:1:0, 762d2829-fa61-4bb1-b42f-f587752268ce:1:2, 89a6a46c-d708-4b27-82bb-27d1e1b9b5e5:0:12, 89a6a46c-d708-4b27-82bb-27d1e1b9b5e5:0:5, 97b60ad4-28d2-430f-a3d2-8803529d8a02:0:11, a70ccedf-fd22-4a22-b003-b0a7d7bcfd0d:0:10, cc2e47a4-98f0-4d5c-a089-10eee2c6446a:0:9.
- Missing explicit small and big blind posts in raw history: 5 labels. Exact keys: eacf441e-1ff1-454c-9aaf-630b86b778e7:0:8, eacf441e-1ff1-454c-9aaf-630b86b778e7:1:0, eacf441e-1ff1-454c-9aaf-630b86b778e7:1:2, eacf441e-1ff1-454c-9aaf-630b86b778e7:2:0, eacf441e-1ff1-454c-9aaf-630b86b778e7:3:0; rows remain unsupported by the saved source history.
- Empty-card partial labels: 245; all remain excluded and unconverted.
- Previous review delta: 42 candidates / 37 recommendations became 48 / 43; exactly the six formerly blocked heads-up keys were added after independent replay. No prior candidate or recommendation was removed.

## Row reasons

| Reason | Rows |
| --- | ---: |
| dealerSeatNo is not an occupied player seat; button holder/order cannot be independently corroborated from the raw player list | 5 |
| explicit_small_and_big_blind_actors_required | 5 |
| hero_pocket_cards_empty_in_raw_source; excluded regardless of replay | 245 |
| model_observation_player_count_exceeds_eight | 8 |
| passed_independent_raw_prefix_review; inspected, not fresh heldout | 43 |

## Source and replay checks

Each emitted candidate was matched to the source UUID plus original round/action indices, verified against the raw hand prefix, and checked for hero cards, explicit forced bets, seat/button order, incremental amounts, pre-action stack/call/pot/contestable pot, legal action and raise bounds, board reveal timestamps, history cutoff, and hidden opponent/future/terminal information. Full terminal chip and pot accounting was recomputed independently. Request variables, query hashes, raw response hashes, canonical payload hashes, and tournament UUIDs from saved `GetEpisode.tournament.uuid` were retained in the row review and `notes/source-hand-facts.jsonl`.

The converter was run once per each of 7 saved tournament UUID groups. There are no indexed UUID aliases spanning multiple tournament UUIDs. Cross-source UUID overlaps with the checked baseline, 2025, 2026, and old sample sets: development_after_prospective_baseline=0, reviewed_2026_candidates=0, 2025_candidates=0, old_sample=0. The baseline's text/video rows cannot establish canonical hand UUIDs, so possible same-hand overlap remains unresolved rather than presumed distinct.

The current admission ledger has 80 admitted decisions across 43 hands; the separate ante-correction packet has 21 pending decisions. Candidate stable keys overlap neither set. One ante-pending action shares a hand with an admitted action but has a different source key: hand `3202f078-1b51-4de2-9e20-72a58e05a8a4`, pending action 6 versus admitted action 10. These 48 candidate rows remain pending parent admission, and the pending ante rows remain unadmitted. The four Card Player 37/14 report rows are held aliases of Triton hand 7c9c95b2-1469-48d9-8c8e-cdf335831fbc; raw Triton records Ivey at 13.55m while the report says 13.6m and omits the 300k big-blind ante. The report rows are not admitted and do not create another hand.

Every candidate is bound to its raw GetHand response and request hashes, query hash and variables, original hand/round/action key, and saved tournament UUID. The independent prefix ledger preserves source action-array order, treats antes as dead common money, checks live contribution tiers and eligible pot, validates board reveal cutoffs and excludes the current/future action, opponent cards, and terminal outcomes from each observation. All 27 emitted candidate hands pass full terminal accounting. Full source terminal accounting was also recomputed for all 33 known-card hands; 32 reconcile. The remaining hand, `89a6a46c-d708-4b27-82bb-27d1e1b9b5e5`, has source terminal awards that do not sum to the reported pot and remains rejected by the >8 actual-player guard.

Raw source facts are retained outside each candidate observation. No policy call, model evaluation, admission write, split edit, commit, or push was performed. SHA inventory is in `summary.json`; raw JSON payloads are referenced by their unchanged paths in the original acquisition folder and copied by hand UUID to `notes/source-hand-facts.jsonl`.
