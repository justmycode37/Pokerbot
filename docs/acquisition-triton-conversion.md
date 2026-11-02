# Triton hand conversion

`scripts/acquisition_triton_convert.py` converts saved PokerHandV2 JSON or
JSONL into exact Ivey decision observations using PokerKit. It reads local
files only. It does not make network requests, train or score a policy, admit
records, or edit a frozen split.

## First sample run

From the repository root, run:

```sh
./.venv/bin/python scripts/acquisition_triton_convert.py \
  data/acquisition_sprint_1h/triton_public/sample-final-table.json \
  --output data/acquisition_sprint_1h/triton_conversion/sample-candidates.json
```

The committed sample artifact contains one replayed Ivey decision from 19
hands. Seven hands include Ivey, seven of his actions were replayed, and one
decision has his two private cards available. The other six hands with Ivey
have empty card arrays and contribute no decision rows. Twelve hands do not
contain Ivey. There are no hand rejections. The seven actual player records
in the sample are replayed as seven players despite the table's physical
capacity of nine.

The sample artifact is
[`data/acquisition_sprint_1h/triton_conversion/sample-candidates.json`](../data/acquisition_sprint_1h/triton_conversion/sample-candidates.json).
Its sole row has hand identity
`triton:485c77c7-8ff8-4a55-922c-09b8883819dc`, action index 6, pocket cards
`9h 9c`, and an all-in raise target of 3,300,000. The observation contains a
preflop board, only prior actions, and no opponent cards or terminal payout
labels.

## Source amounts and replay

The independent frontend review in
[`triton-converter-semantics.md`](triton-converter-semantics.md) and
[`verify_triton_semantics.py`](../scripts/verify_triton_semantics.py) confirms
that every Triton action amount is the number of chips added by that action.
For raises, bets, and raising all-ins, the PHH/engine raise target is the
actor's prior live street commitment plus this increment. Calls are checked
against the additional price. Antes reduce the stack and contribute to the pot,
but stay outside the live street total. Blind, ante, and straddle actors come
from explicit forced-action records. The converter preserves the API action
array order; equal timestamps retain their source order.

Before replay, the converter checks action and board reveal timestamps, action
actors, physical seats, chip increments, calls, checks, raise increases,
all-in exhaustion, terminal pot contribution attribution, and each player's
ending stack. Terminal one-player pots are retained in payout accounting as
uncalled returns. For example, the source's 17,500,000 one-player pot is not
dropped. These terminal values are validation-only and never enter an
observation.

Archived responses can leave `blindLevel.minChip` null. That optional
denomination remains unknown; replay still uses explicit blind amounts and
integer action increments. Supplied invalid denominations are rejected.
Flop timestamps correspond to card positions and can be unsorted. The
converter preserves their pairing and waits until the latest of the three
reveals before permitting a flop action; it never sorts the action stream.

PokerKit then replays the whole ordered action stream. It receives Ivey's
private cards only; all opponent hole cards are dealt as unknown. Board cards
are dealt when their source street begins, after checking the reveal times.
When an all-in requires a runout, hidden cards are mucked in the engine so it
can continue without exposing them. A decision observation is captured before
Ivey's current action. The current action becomes the separate expected label;
future actions and board cards are excluded from the state.

The stable hand ID is `triton:<hand UUID>` and each source decision ID adds its
original round/action-array index. Source payload SHA-256, tournament session
ID, official GraphQL endpoint plus hand UUID, actual player count, and physical
capacity remain in the pending review record. Identical UUID/payload pairs are
deduplicated; conflicting copies invalidate that UUID.

## Larger saved batches

Pass saved hand payloads or directories containing `.json` and `.jsonl`
files. For stand-alone hand files without a tournament wrapper, supply a
tournament/event grouping ID:

```sh
./.venv/bin/python scripts/acquisition_triton_convert.py \
  data/acquisition_sprint_1h/triton_recent/hands.jsonl \
  data/acquisition_sprint_1h/triton_historical/hands.jsonl \
  --session-id triton:tournament:<tournament-uuid> \
  --output data/acquisition_sprint_1h/triton_conversion/combined-candidates.json
```

Each output path is new-only; choose another filename for a new run. Records
are marked `pending_independent_source_and_conversion_review`, and the report
always sets `newly_admitted_decisions` to zero. Unsupported variants, malformed
actions, missing hero cards, incomplete boards, inconsistent settlement,
unsupported actual player counts, or engine-illegal prefixes are excluded with
reasons in the report.

## Ante-aware acquisition observations

The acquisition converter cross-checks each hero prefix against the independent
`acquisition_pot_eligibility.inspect_prefix_pot` ledger after engine replay.
Prefix pot, clipped call price, and hero stack must match the engine; a mismatch
rejects the hand. The ledger treats antes as common dead money and derives
contestable live tiers from explicit prior contributions, retaining folded
money and excluding unreachable side pots and unmatched excess. Its evidence
stays outside the policy observation.

This corrects the acquisition path for the documented big-blind-ante issue in
the frozen simulation helper. The locked simulator, strategies, models, and
evaluation splits remain unchanged. Corrected candidate states receive new
decision hashes and require a fresh review before admission; their original
hand/round/action keys remain stable.
