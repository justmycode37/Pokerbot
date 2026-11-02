# Saved working bot

The `ivey-transfer-v1` checkpoint is frozen at the user's request. Improvement
work is paused. Its recorded decision-weighted result is **478/606 (78.88%)**
with whole Ivey source groups excluded from postflop fitting. The preflop prior
was trained on 15,169 separately attributed Pluribus decisions, with no Ivey
decisions in that prior's fitting data. The requested 90% target was not reached.
The Ivey comparison remains inspected development evidence, not a fresh
population test. Exact raise sizing is a separate metric.

Install and run:

```sh
python3 -m pip install .
pokerbot-saved decide < examples/decision.json
pokerbot-saved profile --count 1000
```

The saved command includes its model and preflop equity table in the Python
package. It runs without the acquisition archive, training data, PokerKit, or
a network connection. `python -m pokerbot.saved_bot` is the equivalent module
entry point. Input is one JSON observation per line, using the existing local
[state protocol](state-protocol.md); output is one legal decision per line.

For Python callers, load once before timing decisions:

```python
from pokerbot.saved_bot import load_bot

bot = load_bot()
decision = bot(observation)
```

The bundled manifest records model and table checksums, training provenance,
and the comparison result. The frozen evaluation packet is stored under
`reports/checkpoints/ivey-transfer-v1/`. The existing `pokerbot` CLI and frozen
historical policies remain available.

From a source checkout with the evaluation extra, verify the source-group
comparison with `python scripts/verify_saved_bot.py`. The verifier checks the
606-row admitted ledger and reconstructs the same source-group folds without
refitting the external prior. It fails if the recorded match count changes.

Local runtime tests check legal actions and latency; they do not certify an
unknown event sandbox or establish poker playing strength.
