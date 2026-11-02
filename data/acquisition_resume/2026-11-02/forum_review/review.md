# Independent forum conversion review — 2026-11-02

## Scope and disposition

Reviewed the Nov 1 saved forum conversion artifacts and the 111 candidate decision prefixes from the 31 exact Full Tilt hand IDs. Also reviewed one additional exact-ID history with unknown hero cards and no candidate decisions. This is a source transcription and identity review; it is separate from PokerKit/engine replay, policy behavior, and held-out scoring. I did not rerun the converter or tests, train, call policies, evaluate scores, admit data, or modify any candidate/source rows.

**Result:** all 111 candidate decisions are fully supported by their raw source action prefixes. No hand or decision has a source/conversion mismatch. 100 decisions have awards in the saved source extract; 11 decisions across three histories have no machine-readable award in that saved extract. A separate manual check of the original public forum posts finds payout facts that reconcile for all four award-gap histories. The three histories with candidate decisions therefore do not need a hold for prefix support. If the parent intake rule requires the saved record itself to contain machine-readable terminal awards, conditionally hold those 11 rows until that rule is satisfied. The fourth history (`5228844526`) has unknown hero cards and zero candidate decisions; it remains ineligible as a hand regardless of its externally reconciled outcome.

All 111 rows remain marked inspected and development-only, with no fresh-held-out claim. Nothing here is an admission recommendation to mutate the corpus; parent owns integration.

## Independent checks

- Audited 32 source histories total: 31 with candidate rows plus `5228844526` as the unknown-card edge case. All 32 hand-level check groups and all 111 decision rows passed: 512 hand checks and 2,109 decision checks; zero failures.
- Reconstructed source pre-action state from raw seat stacks, blinds, button, actions, folds, and boards. Verified actor IDs, positions, action index and full prefix digest, pre-action history, exact decimal tick scale, pot/stack/to-call/current bet, raise bounds, legal actions, contestable pot, hero cards, board cutoff, labels, and canonical hand/action IDs. Candidate observations contain no opponent cards, future board cards, outcome fields, expected label, or source evidence.
- Money scale is exact: 107 decisions at 100 ticks per currency unit and 4 at 1 tick. No source amount truncation was found.
- The input `data/acquisition_sprint_1h/online_forum/records.jsonl` and Nov 1 `source_records.jsonl` snapshot are byte-identical: 71 rows, 170,059 bytes, SHA-256 `0e938458832c506a04b1bceb19ef3c11c2117758448649e9d5e88dca28def4a1`.
- Candidate exact IDs, decision IDs, action-prefix identities, and observation states do not overlap the 80 admitted decisions (45 frozen plus 35 prior additions). No duplicate candidate decision ID or prefix identity exists within the 111 rows.
- The 14 prior no-visible-ID converted histories have no full source-signature matches and no same game/stakes/hero-cards/full-board matches to these candidate histories. All 31 candidate IDs are already present in the existing ID-exclusion ledger. The source snapshot has 57 unique exact IDs with zero collisions.
- A bounded text scan of `data/` covered 7,124 files / 94,892,436 bytes. The only raw-source-copy paths containing candidate IDs were the original input and its byte-identical Nov 1 snapshot; no other raw copies were found. The Nov 2 forum capture has 16 records and no exact-ID collisions with these 31 candidates; its progress has duplicate references to `5260871551` and `5261000520`.
- The Nov 2 secondary converted-forum review has zero candidate rows and zero pending decisions. Its seat-order fingerprint warnings for `9327292808`, `9327359467`, and `5228844526` are resolved by the raw source blind posts and button: actual source positions match the reviewed mapping. Those warnings do not signal a source mismatch.

## Saved-extract award gap and original-page follow-up

The saved raw extracts for the four listed histories contain no machine-readable winner award line, so the local source audit correctly marks their extract-level award reconciliation pending. The original public forum posts do expose the outcome figures; I checked the amounts manually and stored facts only, not copied passages:

| Full Tilt ID | Candidate decisions | Gross pot | Rake | Public-page award(s) | Award(s) + rake = pot |
|---|---:|---:|---:|---:|---|
| `5258419612` | 4 | $38,000 | $0.50 | $18,999.75 + $18,999.75 | true |
| `5228844526` | 0 | $86,598 | $1 | $86,597 | true |
| `5229856787` | 3 | $139,798 | $0.50 | $139,797.50 | true |
| `5229878446` | 4 | $120,000 | $0.50 | $119,999.50 | true |

Primary source pages: [`#5258419612` on the Feb 14 thread, post #121](https://forumserver.twoplustwo.com/29/news-views-gossip/2-14-high-stakes-action-thread-ivey-seda-durrr-ziigmund-etc-129937/index5.html); [`#5228844526`, `#5229856787`, and `#5229878446` on the Feb 12 thread, posts #4, #16, and #17](https://forumserver.twoplustwo.com/29/news-views-gossip/2-12-high-stakes-railbirding-thread-durrrr-ivey-urin-etc-128476/). The full row/hand evidence and conditional hold recommendation are in [`external_award_followup.json`](external_award_followup.json).

The original page also shows a converted two-player hand immediately adjacent to raw Full Tilt hand `5260871551` with matching stakes, stacks, board, and betting sequence, so it is an alias, not another canonical hand. [Page 8, posts #198–199](https://forumserver.twoplustwo.com/29/news-views-gossip/2-14-high-stakes-action-thread-ivey-seda-durrr-ziigmund-etc-129937/index8.html). The Nov 2 progress log also reports a converted copy at post #201 skipped on that identity, but the page 9 URL could not be fetched during this review; that specific post body remains unverified.

## Files and checkpoints

- [`source_review.json`](source_review.json): per-hand checks and all 111 per-row checks, raw source URL/extract SHA, exact IDs, and row recommendations from the saved-extract audit.
- [`external_award_followup.json`](external_award_followup.json): separately verified original-page award facts, affected row IDs, source alias evidence, and residual page 9 limitation.
- [`checkpoint.json`](checkpoint.json): final protected-path/source hashes, per-file inventory, and review artifact digests.
- Audit script: [`review_audit.py`](review_audit.py), independent read-only reconstruction; it only writes `source_review.json` in this review folder.

No engine validation was repeated in this source review. The prior Nov 1 conversion checkpoint remains the separate record for converter replay/test evidence.
