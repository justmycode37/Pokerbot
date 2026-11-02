# Independent partial-video review and corrections

The two short-video batches contain 30 labeled decisions across seven hands.
Only six hands (26 labels) are confirmed standard NLHE; four labels belong to a
hand whose betting structure remains unconfirmed. No row is admitted as an exact
protocol observation. These decisions are not part of the 45-row development
corpus or its quantitative model comparisons.

The parent applied the independent review's small corrections:

- Kirk's flop/turn pending-action counts and the Triton button flop count are
  zero after the opponents checked. A future bet can reopen action, but that
  future response is not pending before the current decision.
- The Aw preflop frames visibly show 7,600 and 27,200 pots. Those values are
  restored with corrected evidence notes; the other missing fields remain null.
- The g1nesio flop and turn have no live wager, so `to_call` is zero. Fresh
  pot-only source crops show 10,200 on the flop and 28,300 on the turn. The earlier
  10,300 transcription was wrong. The later 130,200 pot does not reconcile with
  28,300 plus Ivey's 23,000 bet and the reported 80,300 shove. The 1,400 gap is
  unresolved; no unobserved rake, excess refund or action is invented. The
  nominal 57,300 difference is stored separately from the unknown capped call.
- RC3's approximately 280,000 stack and dependent 257,000 call/stack and
  334,100 contestable-pot estimate are removed from state inputs. Approximate
  values remain explicitly typed in metadata. Its reported pot values also
  remain outside state until an exact source timestamp/ledger is established;
  the saved stills do not prove the former visibility claims.
- Batch 2's suit-specific hero cards remain partial: the collector reported
  them from the clips, but the retained stills do not establish every card and
  no per-card confirming source time was recorded.
- The 5TX river still at nominal 02:10 exposed opponent-dependent equity. It was
  withdrawn, not used for blinded comparison. That decision now has no retained
  predecision still. The set contains 28 predecision stills and two additional
  pot-only crops. No temporary movie is retained.

Original structured captures are preserved under content hashes in
`data/corpus_admission/source-snapshots/`. The earlier video-partial-v1 manifest
refers to those original capture bytes; it predates this review. The corrected
video-partial-v2 manifest records current input hashes and still quarantines all
30 decisions. Every corrected row carries the qualitative-only evidence tier,
which the exact scorer rejects before invoking any policy.

This improves evidence quality without converting uncertainty into a higher
agreement percentage or establishing the greater-than-99% target.
