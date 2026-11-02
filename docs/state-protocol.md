# Local decision protocol

This is our internal JSON-lines protocol. It is **not an official Sequoia SDK**.
Each input line is one observation; each output line is one decision. Invalid
observations produce a structured error and a nonzero exit status.

Required fields:

| Field | Meaning |
| --- | --- |
| `hole_cards` | Exactly two known hero cards, such as `["As", "Kd"]` |
| `board` | Current public board, length 0, 3, 4, or 5 |
| `pot` | Total chips committed, including outstanding street bets |
| `to_call` | Actual extra chips hero must call, capped by hero stack |
| `stack` | Hero's remaining chips |
| `current_bet` | Hero's committed bet on this street |
| `min_raise_to` | Minimum legal total street bet, including current bet |
| `max_raise_to` | Maximum legal total street bet |
| `big_blind` | Big blind in chips |
| `position` | `UTG`, `MP`, `CO`, `BTN`, `SB`, or `BB`; heads-up dealer is `BTN` |
| `players_active` | Players still in this pot, including hero |
| `players_to_act` | Other players still to act before this street can end |
| `legal_actions` | Some of `fold`, `check`, `call`, `raise` |

`street` is checked against the board if provided. Optional `history` is a list
of prior visible actions, each with `street`, `player`, `action`, `amount`
(street-total target), and `added` (chips added on that action). Hero's
`player_id` should use the same identifier as `player`. `seed` controls
deterministic sampling. `hand_id` is for reporting only, never a strategy feature.

An optional `contestable_pot` excludes side pots hero cannot win and uncalled
excess that will be returned; otherwise the strategy assumes `pot` is entirely
contestable. Adapters must supply it for unequal all-in stacks.

Output includes `action`, `amount` for raises, action `probabilities`,
`raise_amount` for the size associated with raise probability, and `diagnostics`.
The `amount` for a raise is a **total street bet**, not extra chips and not a
pot fraction. An all-in call is `call`; an all-in raise is `raise` at the maximum.
The engine owns betting legality, reopening rules, chip settlement and dealing.

Never include opponent hole cards, unrevealed board cards, future actions,
expected human actions, or hand outcomes in the observation.
