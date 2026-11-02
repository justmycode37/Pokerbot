# Triton cash parity-zero review

All outputs are development-only. This review created no admissions and did not touch a frozen split. Writes are confined to this folder. The protected `pokerbot/`, `data/models/`, and `data/corpus_splits/` trees were byte-for-byte verified against the neighboring protected-baseline manifest: 46, 12, and 3 files respectively, with all SHA-256 hashes and byte totals matching.

## Reviewed counts

- Owned raw hand records: **275 of 564**, selected by `int(handId without hyphens, 16) % 2 == 0`.
- Owned hands with two known hero cards: **225**; owned hero action locators: **340**. Partial or unknown cards remain unknown and are not counted as usable.
- Cached cash-event groups: **2** across **14** episodes. All 275 source hands map to one event group; no hand crosses groups.
- 2024 Cash Game Invitational I: **234** owned raw hands; **241** candidate decisions from **152** replayed hands. All **241/241** passed independent raw-prefix review.
- Corrected `contestable_pot` on **82** decisions after helper `pot` and `to_call` matched both the converter observation and an independent source-prefix ledger. Corrected rows were passed through `validate_rows` again; decision IDs and record hashes were regenerated and rechecked.
- Two reviewed decisions have `contestable_pot` below total `pot` because a prior contribution tier is above the hero's call-reach limit. Evidence is in [contestable-top-excess.json](sidecases/contestable-top-excess.json).
- Current corpus baseline: **80** admitted rows. This review found **0** exact source-hand/original-round/action duplicates against those rows and **0** overlaps with other cached Triton source identities. There are also **0** raw UUID overlaps with the 80 admitted rows or other Triton artifacts. The 152 candidate hand UUIDs have no cross-source raw UUID overlap.
- No owned source hand has multiple episode aliases. Episode IDs remain provenance only.

## Independent checks

Every passed decision was checked against its saved response and request sidecar: raw and canonical payload hashes, query hash and `GetHand` operation, hand/episode variables, cached episode alias, cash-event identity, and the original action locator. The source action was a deliberate Ivey action with known cards.

I independently reconstructed seat order from the explicit small-blind actor and source `seatNo` values, then checked the big blind, button, straddles, ante/blind prefix, starting stacks, hero's remaining stack, prior-action history and `pN` actors, current action label, visible board and reveal timestamp cutoff, pot, amount to call, and reachable contribution tiers. Terminal pot and end-stack fields were used only for accounting validation. No opponent private cards, current label, future action, or terminal outcome appears in candidate state.

The eligible-pot helper's dead-ante ledger and live-contribution tiers matched direct raw-prefix derivations on all 241 rows. No pot or call-price mismatch was found. The conservative board cutoff remains in place: actions before the latest public-board reveal are excluded.

## Shared code hash drift

The root converter and pot helper changed after this conversion output was written. Conversion was performed from the captured start converter SHA `aeba51655c1927a47b2b9bd7f404a94a15a7299abde52f9ce9d8ba0cb483a7ca`; the output timestamp precedes the root converter's changed-file timestamp. The helper used during independent row review had SHA `fffa3df98fe5997d72d7f910c27d0a73536a06d5c82ea4426c7b2ecd28cc88cb`, while the captured start helper SHA was `3bf5bb521dfca1e4ed16871f19d50fef125cdded6c2ebd3ae253ab805dda6556`. This review made no root code edits. Each helper result was independently rebuilt from raw prefixes and matched pot, call price, dead antes, live contributions, and eligible tiers.

## 2018 capacity metadata finding

The current converter rejected all **41** parity-zero 2018 hands because each reports `noOfSeats: 8` while containing an explicit player at `seatNo: 9`. Across all **77** cached 2018 hands, `noOfSeats` is 8, seat 9 is present, physical seat numbers are unique, and explicit SB/BB/button/straddle order passes in all 77 when the actual seat labels are rotated from the SB. No missing players were padded and no raw values were changed.

The cached `GetHand` selection requests `noOfSeats`, `dealerSeatNo`, and per-player `seatNo` as separate fields. The cache contains no frontend renderer or source bundle, so the exact UI layout code is not established. The raw seat, blind, and dealer facts do support retaining `noOfSeats` as provenance while omitting it from ordering when it contradicts explicit `seatNo` values. See [2018-seat-capacity.json](sidecases/2018-seat-capacity.json) for every source hand and check.

## Source blockers and exclusions

- 2018 parity-zero: **41/41** records rejected by the capacity/seat conflict; no candidates emitted. The full 77-hand physical-seat audit is in `sidecases/2018-seat-capacity.json`.
- 2024 parity-zero: **35** hands rejected by current conservative validation: 27 action-before-board-reveal, 2 invalid hero cards, 2 missing explicit blind actors, 1 minimum-action legality conflict, 1 board-timestamp order conflict, 1 unsupported runout count, and 1 terminal contribution mismatch. See `sidecases/conversion-rejections.json`.
- No source/API acquisition, training, policy call, score evaluation, admission, or split operation was performed.

## Files

- [candidates.json](candidates.json): 241 corrected, revalidated development-only rows.
- [per-row-review.json](per-row-review.json): raw-prefix checks and source evidence for every candidate.
- [summary.json](summary.json): counts and input/code hashes.
- [global-dedup.json](global-dedup.json): exact-key and UUID dedup results against the 80 admitted rows and cached Triton artifacts.
- [sidecases/sourceblockers.json](sidecases/sourceblockers.json): machine-readable blockers.
- [sidecases/sourceblockers.md](sidecases/sourceblockers.md): concise blocker report.
