# Public Ivey video catalog: batch 2

This catalog records three new, public standard no-limit hold'em hand segments from the official PokerGO channel. Sources were selected from public metadata before any streams were reviewed and without reading strategy, model, or result outputs. The source ordering, exclusions, replacement rule, and review outcome are recorded in [`selection-ledger.json`](../data/public_ivey_videos_batch2/selection-ledger.json).

## Sources and retained observations

| Source | Official channel and clip identity | Retained Ivey decisions | Snapshots |
| --- | --- | ---: | --- |
| [RC3ddhyKFOo](https://www.youtube.com/watch?v=RC3ddhyKFOo) | PokerGO, “Phil Ivey Folds Kings to a Sick Bluff! \| High Stakes Poker”; published 2020-04-06; 243 seconds | 3: preflop raise, flop bet, fold | [Preflop](../data/public_ivey_videos_batch2/frames/rc3-01-preflop.png), [flop](../data/public_ivey_videos_batch2/frames/rc3-02-flop.png), [facing shove](../data/public_ivey_videos_batch2/frames/rc3-03-facing-shove.png) |
| [mtCcWNLHMbM](https://www.youtube.com/watch?v=mtCcWNLHMbM) | PokerGO, “Does Horrible Timing Cost Matt Kirk vs Phil Ivey??!!”; published 2020-11-23; 182 seconds | 4: preflop raise, flop bet, turn bet, river call | [Preflop](../data/public_ivey_videos_batch2/frames/ivey-kirk-01-preflop.png), [flop](../data/public_ivey_videos_batch2/frames/ivey-kirk-02-flop.png), [turn](../data/public_ivey_videos_batch2/frames/ivey-kirk-03-turn.png), [facing all-in](../data/public_ivey_videos_batch2/frames/ivey-kirk-04-facing-allin.png) |
| [T9uJ0dpROcc](https://www.youtube.com/watch?v=T9uJ0dpROcc) | PokerGO, “Phil Ivey has Phil Hellmuth in Trouble on High Stakes Poker!”; published 2020-06-01; 231 seconds | 5: preflop call, flop bet, call facing raise, turn check, call facing all-in | [Preflop](../data/public_ivey_videos_batch2/frames/ivey-hellmuth-01-preflop.png), [flop](../data/public_ivey_videos_batch2/frames/ivey-hellmuth-02-flop.png), [facing raise](../data/public_ivey_videos_batch2/frames/ivey-hellmuth-03-facing-raise.png), [turn](../data/public_ivey_videos_batch2/frames/ivey-hellmuth-04-turn.png), [facing all-in](../data/public_ivey_videos_batch2/frames/ivey-hellmuth-05-facing-allin.png) |

The official channel ID for all three sources is `UCOPw3R-TUUNqgN2bQyidW2w`. Factual action logs with source-relative timestamps and hand IDs are in [`hand-transcripts.md`](../data/public_ivey_videos_batch2/hand-transcripts.md). Each record in [`observations.jsonl`](../data/public_ivey_videos_batch2/observations.jsonl) has the required `state`, `expected`, `source`, and `hand_id` fields; `session_id` is null because the exact session is not established. The `expected` label is separate from the state. Raise amounts follow [`state-protocol.md`](state-protocol.md) and mean total street bet targets.

## Frame and state quality

**Review correction:** the Kirk flop and turn pending-action counts are zero.
RC3's rounded stack-derived amounts and unverified pot values have been moved
outside the state into typed quality metadata. All 12 rows have an explicit
qualitative-only evidence tier. Suit-specific card timestamps still need stronger
retained provenance. See [review errata](partial-video-review-errata.md).

There are 12 decision snapshots: 6 `raise` labels (including bets), 4 calls, 1 check, and 1 fold. Every snapshot is marked `partial`. Each retained frame is a sparse predecision still with a broad opaque mask over the screen-left HUD area to remove opponent cards and equity readouts. The mask also covers some incidental HUD information. Pot and stack values are recorded only when visible or recoverable from the action; rounded estimates and inferred blind structures are explicitly tagged in `data_quality`. Unknown stacks, antes, positions, player counts, or session identifiers remain null where they cannot be established. See the hand logs for the source-specific arithmetic and gaps.

## Selection and limits

The first metadata-locked candidate was a WPT clip, [RpMJukYKKyc](https://www.youtube.com/watch?v=RpMJukYKKyc). Review showed it was a long multi-hand compilation and its first reviewed hand did not feature Ivey, so it was excluded under the predeclared single-hand eligibility rule. The next eligible official PokerGO result in the recorded metadata query/rank order, [T9uJ0dpROcc](https://www.youtube.com/watch?v=T9uJ0dpROcc), replaced it before its stream was opened. The ledger preserves both the initial selection and the replacement audit.

These editorial highlight clips were selected because metadata identified Ivey hands, and their titles or descriptions emphasize a fold, a large pot, or a heads-up confrontation. The resulting sample is small and has highlight-selection bias; it is not representative of Ivey’s full decision distribution. This batch includes calls and one check alongside aggression, but only one fold and one check. It cannot establish 99% agreement. No policy outputs were inspected, and no strategy or model files or result files were read while assembling the batch. Agreement should be measured later against the frozen candidates using the predeclared, blinded evaluation process, without treating this small curated sample as proof of a 99% target.

