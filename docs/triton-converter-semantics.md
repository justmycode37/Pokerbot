# Public Triton hand semantics review

This independent review inspects the public frontend and the unchanged
`sample-final-table.json` payload supplied by the acquisition coordinator. It
does not fetch duplicate hand data, call a policy, modify a candidate or split,
or admit comparison rows. Frontend source URLs and SHA-256 hashes are retained
in [`frontend-manifest.json`](../data/triton_semantics_review/frontend-manifest.json).

## Action amounts are chips added

The official [replay utility chunk](https://tritonpoker.plus/729.aa098f2e4cee3999e53d.js)
provides three consistent calculations:

- Module 27568, exported helper `J`, sums action amounts across rounds for a
  player, excluding the dead ante from live commitments.
- Module 63221, helper `p`, subtracts the sum of all amounts, including antes,
  from `startChips` to obtain chips behind.
- Module 63221, helper `d`, obtains the displayed street total by summing that
  player's preceding non-ante amounts in the round and adding this action's
  amount. This also applies to raises and all-ins.

Therefore raw `amount` is **chips added**, including `raise`, `call`, `bet` and
`all_in`. A converter's raise-to value is the player's existing live street
commitment plus raw `amount`. Antes reduce the remaining stack and enter the
pot, but do not count toward calling the live wager. Use actual forced-action
actors to identify blind seats; completed-hand headers do not expose all of
the live-hand fragment's blind-seat fields.

The UI computes chips behind through `timestamp <= current timestamp`, which
includes the current action. A predecision state must instead stop before the
current action in the source action array. Equal timestamps must preserve
source ordering. Do not use a timestamp filter that includes the target label
or another simultaneous event inadvertently.

## Independent checks on the first payload

[`sample-final-table-audit.json`](../data/triton_semantics_review/sample-final-table-audit.json)
was produced by
[`verify_triton_semantics.py`](../scripts/verify_triton_semantics.py).
For all 19 raw hands, every player's ending stack equals starting stack minus
all incremental action payments plus the sum of terminal pot awards. Pot
contribution attribution, total-chip conservation, additional call prices,
check prices, all-in stack exhaustion, and raise targets also pass.

Terminal `pots.hi.sidePlayers.winAmount` includes one-player pots representing
uncalled chips. For example, the final hand contains such a pot of 17,500,000.
Retain it in terminal accounting rather than treating it as a contested win or
dropping it. Terminal results and pot eligibility are validation evidence and
must not be copied into predecision inputs.

The payload contains seven hands with Ivey, but only **one hand with his two
cards present and one deliberate action in that hand**. The other six Ivey
hands have empty card arrays. Empty cards are unknown, not permission to
generate cards. The represented hand order numbers are sparse; 19 returned
hands do not prove a complete chronological session.

`noOfSeats` is physical capacity. A sample with capacity nine contains seven
actual player records; do not add imaginary players. Raw cards use forms such
as `CARD_9H`; card decoding still needs explicit validation against all values
encountered. Restrict this converter to the intended Texas no-limit format;
the API also exposes Short Deck and Omaha variants.

Accounting checks support the amount interpretation. They do not by
themselves verify converter legality, pot eligibility at every decision,
board-reveal cutoffs, information hiding, deduplication, or corpus admission.
Those checks remain required on the converted records.

## Archived episode provenance and duplicates

The acquisition coordinator subsequently found that current-game hand lists
can be empty for old broadcasts, while episode-index hand IDs can resolve
through `GetHand` with an `episodeId`. This retrieval finding is reported by
the coordinator; the independent review must inspect an unchanged archived
response before asserting that all historical payload semantics match the
first sample.

Retain the episode ID, raw request variables, response hash and source index as
provenance. Use underlying hand ID and original round/action indices for
canonical decision identity. Repeated appearances of one hand in episodes or
highlight segments are source aliases, not new decisions. Preserve action
array ordering when timestamps tie. Missing Ivey card arrays remain unknown
and excluded from exact known-card comparison counts. Selectively exposed
cards also require a selection-bias qualification on later accuracy results.
