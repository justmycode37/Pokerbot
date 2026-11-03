# Evolution strategy genomes

`pokerbot.evolution_strategies` provides bounded policy genomes and table-local
policy factories for self-play experiments. Evolved policies use the offline
preflop equity table and `fast._postflop_equity`; inference does not sample
cards, load training rows, or depend on hidden cards and outcome labels. Each
call is parsed through `Observation.from_dict()`, which applies the public
observation whitelist before the strategy reads it.

## Policy families

| Family | Behavior |
| --- | --- |
| `evolved` | Uses mutable bounded genes to adjust opening cutoffs, calling, value raises, bluffing, stack pressure, bet sizing, position, and multiway equity. |
| `adaptive` | Uses the same bounded genes with a fresh opponent profile for each table, based only on observed public actions. |
| `saved` | Runs the separately frozen `pokerbot.saved_bot.load_bot()` checkpoint. The checkpoint callable is loaded once and reused; it has no evolutionary parameters. |
| `fast` | Runs the existing deterministic fast heuristic as a reference policy. |
| `calling-station` | Checks for free and calls whenever calling is legal. It never raises. |
| `tight-passive` | Uses the existing equity estimates with conservative continuation cutoffs, checks for free, and never raises. |
| `random-legal` | Selects uniformly among the supplied legal actions using the observation's public seed and a stable bot-id salt. It uses the midpoint of legal raise bounds. |

`anchor_genomes()` returns one reference for each family except `evolved`:
`anchor-saved`, `anchor-fast`, `anchor-station`, `anchor-tight`, and
`anchor-random`. It intentionally does not add high-cost policies as anchors.

## Evolved genes

Partial parameter dictionaries use the defaults below for omitted genes. Bounds
are inclusive; `Genome` rejects unknown names, out-of-range values, booleans,
and non-finite numbers. Genome parameter dictionaries are copied and made
read-only, while `to_dict()` returns a fresh JSON-safe copy.

| Gene | Default | Bounds | Effect |
| --- | ---: | ---: | --- |
| `opening_shift` | 0.000 | -0.120 to 0.120 | Moves the position-specific preflop open cutoff. |
| `opening_frequency` | 0.880 | 0.450 to 1.000 | Scales the mixed raise frequency for qualifying unopened hands. |
| `call_margin` | 0.000 | -0.080 to 0.100 | Moves the preflop continuation margin over pot odds. |
| `postflop_call_margin` | 0.000 | -0.020 to 0.080 | Moves the postflop continuation margin over pot odds. |
| `call_frequency` | 0.950 | 0.450 to 1.000 | Controls calling within qualifying mixed decisions. |
| `value_raise_threshold` | 0.690 | 0.560 to 0.840 | Sets the equity cutoff for value reraises and bets. |
| `raise_frequency` | 0.620 | 0.200 to 1.000 | Scales value raises and bets. |
| `bet_size` | 0.500 | 0.150 to 0.900 | Sets raise sizing from smaller to larger fractions of the pot. |
| `bluff_frequency` | 0.050 | 0.000 to 0.240 | Sets eligible heads-up late-position bluff and semi-bluff mixing. |
| `short_stack_bb` | 10.000 | 4.000 to 18.000 | Defines the effective big-blind threshold for short-stack pushes. |
| `short_stack_cutoff` | 0.560 | 0.450 to 0.760 | Sets the adjusted-equity threshold for those pushes. |
| `multiway_penalty` | 0.045 | 0.015 to 0.100 | Discounts equity as additional opponents enter the pot. |
| `position_sensitivity` | 0.018 | 0.000 to 0.045 | Adjusts open and continue thresholds by early or late position. |

The postflop heuristic keeps its exact shared-board and supported suited-river
handling. The multiway gene only changes the heuristic's ordinary estimates;
it does not override exact tie or unbeatable-hand cases. Raise outputs use the
engine's total street bet convention and are clamped to the observation's legal
raise bounds. If the observation says raising is unavailable, no family
manufactures a raise.

The evolving family also recognizes a public, flush-impossible Broadway board
and board quads with the best possible kicker as guaranteed shared hands.
Favorable exact ties and unbeatable hands never receive a random-fold
probability. Short-stack depth counts remaining chips plus chips already
committed on the street, without adding the outstanding call a second time.
For a two-player table, an `SB` position alias is interpreted as the button.
These corrections leave the separately frozen `saved` and `fast` references
unchanged.

## Creating and breeding genomes

`new_random(rng, bot_id, generation=0)` samples every gene from its bounded
range using the supplied `random.Random` instance. `breed(parent, other, rng,
bot_id, generation)` starts from evolved gene values or the default vector for
reference families, optionally crosses genes from a second parent, then
mutates at least one gene. It records parent IDs, and never edits either parent.
The same parent genomes and RNG seed produce the same offspring. Evolving
parents also pass on their static or adaptive family; a cross between the two
can inherit either family.

`policy_for(genome)` returns a fresh callable for one table. Static families
remain stateless. The adaptive family learns only within that table and clears
its profile on reset. Action mixing is deterministic from the public observation
seed, public cards, and bot ID; there is no global random stream or learned
cross-table state.
