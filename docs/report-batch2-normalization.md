# Batch 2 report reconstruction

`scripts/import_report_batch2.py` reconstructs the reported betting targets with
PokerKit 0.7.7. It emits `records_pending_review`, rather than the `records` key
accepted by the prospective evaluation command. Legal replay alone does not
confirm the published cards, stack precision or action transcription.

The 22 hero observations from five hands replay without a discrepancy in the
collector's stated chip, action-bound, position or pending-action fields. Two
history entries require correction: Heath's raise from a 250,000 live big blind
to 1,850,000 adds 1,600,000, not 1,350,000. The separate 250,000 big-blind ante is
dead money. This correction appears in two later Ivey decision prefixes. Raw
collector files remain unchanged; the engine computes payments from targets.

Table sizes are explicit in the derived states. The CardPlayer PDF's printed
page 37 says three players remain in the Heath hand. The subsequent Ponakovs
hands are heads-up. The Punsri hand has seven players remaining at a single
seven-handed final table. The latter prefix includes five unnamed folds before
the small-blind raise, required by the reported action folding to that position.
See the [original issue](https://media.cardplayer.com/assets/magazines/000/066/494/pdf/35_16_web.pdf)
and [Jeju matchup](https://www.cardplayer.com/poker-tools/hand-matchups/2851).

Unknown stacks of folded players are not invented source facts. For engine
checks only, the missing small-blind stack and the five already-folded Jeju
stacks are reference parameters. The importer probes one chip above the forced
bet, an intermediate value and a very large value. All 22 emitted hero states
are identical across the probes. Their exact values cannot affect these hero
states: the folded players' only paid chips are known forced bets, and Heath's
known larger stack already permits Ivey's full legal raise range before the
small blind folds. No auxiliary stack is exported to the bot.

For heads-up replays, PokerKit uses seat order big blind, button, while the PHH
forced-bet arrays follow the specified heads-up reversal. The big-blind ante is
posted as dead money and is not included in `current_bet`. No opponent cards or
future board cards/actions enter a hero observation. Expected actions are
checked separately against the collector's labels.

The current derived artifact is
`data/public_ivey_reports_batch2_derived/pending-v3.json`. It records source and
normalizer hashes, the two corrected history payments, and all replay probes.
The earlier pending-v1 artifact predates the explicit history-difference report;
its reconstructed states are the same. Five tests cover the ante correction,
heads-up stack ledger, seven-player implied folds, independence from erroneous
collector `added` values, and disjointness from the already-inspected corpus.

Independent [source review](report-batch2-source-audit.md) is complete. The
corrected records were admitted separately under
`data/prospective_batches/reports-batch2-v1.json` and used in the
[first prospective comparison](prospective-results-v1.md).
