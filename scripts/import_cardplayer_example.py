"""Encode cited hand facts; no web scraping or invented hidden cards/stacks.

Source: https://www.cardplayer.com/poker-tools/hand-matchups/1921
Published 2015-02-09. Amounts, cards, positions and actions are factual data;
the source's analysis/prose is not reproduced. Re-run from the source root.
"""

import copy
import json
from pathlib import Path

SOURCE = "https://www.cardplayer.com/poker-tools/hand-matchups/1921"


def build_record():
    hand_id = "cardplayer-1921-ivey-polk"
    hero = 2_909_000
    bb = 24_000
    ante = 3_000
    history = [
        {"street": "preflop", "player": "UTG", "action": "fold", "position": "UTG"},
        {"street": "preflop", "player": "Polk", "action": "raise", "amount": 55_000, "added": 55_000, "position": "BTN"},
        {"street": "preflop", "player": "SB", "action": "fold", "position": "SB"},
    ]
    rows = []

    def snapshot(board, pot, stack, current, due, minimum, expected, pending):
        state = {"hole_cards": ["Tc", "9d"], "board": list(board), "pot": pot,
                 "to_call": due, "stack": stack, "current_bet": current,
                 "min_raise_to": minimum, "max_raise_to": current + stack,
                 "big_blind": bb, "position": "BB", "table_size": 4,
                 "players_active": 2, "players_to_act": pending,
                 "street": {0: "preflop", 3: "flop", 4: "turn", 5: "river"}[len(board)],
                 "legal_actions": ["fold", "call", "raise"] if due else ["check", "raise"],
                 "history": copy.deepcopy(history), "player_id": "Ivey",
                 "hand_id": hand_id, "seed": 4500 + len(rows)}
        rows.append({"state": state, "expected": expected, "source": SOURCE,
                     "hand_id": hand_id, "format": "tournament_nlhe"})

    # Four players paid a 3k ante; the folded small blind contributes 12k.
    # The report's two-way pot implies the other two seats folded preflop;
    # their private cards and starting stacks are neither needed nor invented.
    stack = hero - ante - bb
    pot = 4 * ante + 12_000 + bb + 55_000
    snapshot([], pot, stack, bb, 31_000, 86_000, {"action": "call"}, 0)
    stack -= 31_000
    pot += 31_000
    history.append({"street": "preflop", "player": "Ivey", "position": "BB", "action": "call", "amount": 55_000, "added": 31_000})
    flop = ["Th", "3s", "2d"]
    snapshot(flop, pot, stack, 0, 0, bb, {"action": "check"}, 1)
    history.extend([
        {"street": "flop", "player": "Ivey", "action": "check", "added": 0},
        {"street": "flop", "player": "Polk", "action": "check", "added": 0},
    ])
    turn = flop + ["2h"]
    snapshot(turn, pot, stack, 0, 0, bb, {"action": "raise", "amount": 75_000}, 1)
    history.extend([
        {"street": "turn", "player": "Ivey", "action": "raise", "amount": 75_000, "added": 75_000},
        {"street": "turn", "player": "Polk", "action": "call", "amount": 75_000, "added": 75_000},
    ])
    pot += 150_000
    stack -= 75_000
    river = turn + ["6c"]
    snapshot(river, pot, stack, 0, 0, bb, {"action": "raise", "amount": 200_000}, 1)
    history.extend([
        {"street": "river", "player": "Ivey", "action": "raise", "amount": 200_000, "added": 200_000},
        {"street": "river", "player": "Polk", "action": "raise", "amount": 580_000, "added": 580_000},
    ])
    pot += 780_000
    stack -= 200_000
    snapshot(river, pot, stack, 200_000, 380_000, 960_000, {"action": "call"}, 0)
    return {"schema_version": 1, "source": SOURCE, "publication_date": "2015-02-09",
            "hero": "Phil Ivey", "hand_id": hand_id,
            "source_facts": {"hero_starting_stack": hero, "opponent_starting_stack": 2_570_000,
                             "small_blind": 12_000, "big_blind": bb,
                             "ante_per_player": ante, "players_dealt": 4},
            "derivation_notes": [
                "Other seats' preflop folds are inferred from the reported heads-up continuation; no extra calls are reported.",
                "The 3,000 ante is per player, as described by the report's pre-big-blind-ante tournament convention.",
                "Raise bounds use the minimum full raise and hero's street bet plus remaining stack; excess is returnable.",
                "Table-wide payouts and other starting stacks are unknown and are not provided to the policy.",
            ], "decisions": rows}


if __name__ == "__main__":
    destination = Path(__file__).resolve().parents[1] / "data/ivey_normalized/cardplayer-1921.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(build_record(), indent=2) + "\n")
    print(destination)
