from __future__ import annotations

import random
import unittest

from pokerbot.endgame import endgame_decision, shove_equity_cutoff, wrap_policy
from pokerbot.state import Observation


DECK = tuple(rank + suit for rank in "23456789TJQKA" for suit in "cdhs")


def raw_observation(*, seed=1, players_active=8, stack_bb=10, position="BTN",
                    players_to_act=2, street="preflop", to_call_bb=0,
                    history=None, legal_raise=True):
    rng = random.Random(seed)
    cards = rng.sample(DECK, 2 + (0 if street == "preflop" else {"flop": 3, "turn": 4, "river": 5}[street]))
    bb = 20
    current_bet = bb if to_call_bb else 0
    stack = max(1, stack_bb * bb - current_bet)
    to_call = min(stack, to_call_bb * bb)
    legal = ["call", "fold"] if to_call else ["check"]
    minimum = current_bet + to_call + bb
    maximum = current_bet + stack
    if legal_raise and minimum <= maximum:
        legal.append("raise")
    return {
        "hole_cards": cards[:2], "board": cards[2:], "pot": bb * 3 + to_call,
        "contestable_pot": bb * 3 + to_call, "to_call": to_call, "stack": stack,
        "current_bet": current_bet, "min_raise_to": minimum if "raise" in legal else 0,
        "max_raise_to": maximum if "raise" in legal else 0, "big_blind": bb,
        "position": position, "players_active": players_active,
        "players_to_act": min(players_to_act, players_active - 1),
        "legal_actions": legal, "street": street, "seed": seed,
        "history": history or [], "player_id": "p0", "table_size": 8,
    }


class EndgameDecisionTests(unittest.TestCase):
    def test_push_chart_monotonicity(self):
        common = dict(stack_bb=8, players_to_act=3)
        early = shove_equity_cutoff(position="UTG", **common)
        middle = shove_equity_cutoff(position="MP", **common)
        late = shove_equity_cutoff(position="BTN", **common)
        self.assertGreater(early, middle)
        self.assertGreater(middle, late)
        self.assertLess(
            shove_equity_cutoff(position="BTN", stack_bb=5, players_to_act=2),
            shove_equity_cutoff(position="BTN", stack_bb=12, players_to_act=2),
        )
        self.assertLess(
            shove_equity_cutoff(position="BTN", stack_bb=8, players_to_act=1),
            shove_equity_cutoff(position="BTN", stack_bb=8, players_to_act=5),
        )
        self.assertLess(
            shove_equity_cutoff(position="BTN", stack_bb=8, players_to_act=2, caller_frequency=0.1),
            shove_equity_cutoff(position="BTN", stack_bb=8, players_to_act=2, caller_frequency=0.9),
        )

    def test_returns_none_outside_overlay(self):
        obs = Observation.from_dict(raw_observation(stack_bb=90, players_active=8))
        self.assertIsNone(endgame_decision(obs))
        full_ring_flop = Observation.from_dict(raw_observation(stack_bb=8, players_active=4, street="flop"))
        self.assertIsNone(endgame_decision(full_ring_flop))

    def test_deterministic_for_same_public_observation(self):
        obs = Observation.from_dict(raw_observation(stack_bb=8, seed=91))
        first = endgame_decision(obs, opponent_stats={"p1": 0.7})
        second = endgame_decision(obs, opponent_stats={"p1": 0.7})
        self.assertEqual(first, second)
        heads_up_flop = Observation.from_dict(raw_observation(
            stack_bb=30, players_active=2, position="BTN", street="flop", seed=43,
        ))
        self.assertEqual(endgame_decision(heads_up_flop), endgame_decision(heads_up_flop))

    def test_endgame_tuning_parameters_preserve_defaults_and_change_cutoffs(self):
        heads_up = raw_observation(players_active=2, stack_bb=100, position="BTN")
        heads_up["hole_cards"] = ["As", "Kd"]
        obs = Observation.from_dict(heads_up)
        self.assertEqual(
            endgame_decision(obs),
            endgame_decision(obs, {"heads_up_aggression": 1.0, "call_shove_margin": 0.095}),
        )
        default_hu = endgame_decision(obs)
        aggressive_hu = endgame_decision(obs, {"heads_up_aggression": 1.25})
        self.assertLess(aggressive_hu["diagnostics"]["open_cutoff"],
                        default_hu["diagnostics"]["open_cutoff"])

        shove = raw_observation(stack_bb=10, players_active=8, to_call_bb=8,
                                history=[{"street": "preflop", "player": "p1",
                                          "action": "raise", "amount": 200, "added": 180}])
        shove["hole_cards"] = ["As", "Ah"]
        shove["contestable_pot"] = 80
        shove_obs = Observation.from_dict(shove)
        cautious = endgame_decision(shove_obs, {"call_shove_margin": 0.18})
        loose = endgame_decision(shove_obs, {"call_shove_margin": 0.04})
        self.assertGreater(cautious["diagnostics"]["equity_cutoff"],
                           loose["diagnostics"]["equity_cutoff"])

    def test_heads_up_button_folds_bottom_of_range_when_fold_is_legal(self):
        raw = raw_observation(players_active=2, stack_bb=100, position="BTN", to_call_bb=1)
        raw["hole_cards"] = ["2c", "3d"]
        obs = Observation.from_dict(raw)
        self.assertEqual(endgame_decision(obs)["action"], "fold")

    def test_short_stack_call_shove_accepts_premiums_and_folds_trash(self):
        history = [{"street": "preflop", "player": "p1", "position": "UTG",
                    "action": "raise", "amount": 200, "added": 180}]
        aces = raw_observation(stack_bb=10, players_active=8, players_to_act=2,
                               to_call_bb=8, history=history)
        aces["hole_cards"] = ["As", "Ah"]
        trash = dict(aces, hole_cards=["2c", "3d"])
        self.assertEqual(endgame_decision(Observation.from_dict(aces))["action"], "call")
        self.assertEqual(endgame_decision(Observation.from_dict(trash))["action"], "fold")

    def test_random_short_stack_and_heads_up_actions_are_legal(self):
        rng = random.Random(8042)
        for index in range(100):
            active = rng.randint(3, 8)
            positions = ["UTG", "MP", "CO", "BTN", "SB", "BB"]
            position = rng.choice(positions)
            stack_bb = rng.randint(1, 16)
            to_call = rng.choice([0, 1, 2, 4, 8])
            obs = Observation.from_dict(raw_observation(
                seed=index + 20, players_active=active, stack_bb=stack_bb,
                position=position, players_to_act=rng.randrange(active),
                to_call_bb=to_call,
                history=([{"street": "preflop", "player": "p1", "action": "raise", "amount": 160, "added": 140}]
                         if to_call else []),
            ))
            decision = endgame_decision(obs)
            self.assertIn(decision["action"], obs.legal_actions)
            if decision["action"] == "raise":
                self.assertGreaterEqual(decision["amount"], obs.min_raise_to)
                self.assertLessEqual(decision["amount"], obs.max_raise_to)

        for index in range(100):
            active = 2
            position = "BTN" if index % 2 == 0 else "BB"
            stack_bb = rng.randint(1, 100)
            street = rng.choice(["preflop", "flop", "turn", "river"])
            to_call = 0 if street != "preflop" else rng.choice([0, 1, 2, 4])
            obs = Observation.from_dict(raw_observation(
                seed=index + 1000, players_active=active, stack_bb=stack_bb,
                position=position, players_to_act=1, street=street,
                to_call_bb=to_call,
                history=([{"street": "preflop", "player": "p1", "action": "raise", "amount": 100, "added": 80}]
                         if to_call else []),
            ))
            decision = endgame_decision(obs)
            self.assertIsNotNone(decision)
            self.assertIn(decision["action"], obs.legal_actions)
            if decision["action"] == "raise":
                self.assertGreaterEqual(decision["amount"], obs.min_raise_to)
                self.assertLessEqual(decision["amount"], obs.max_raise_to)

    def test_wrapper_delegates_outside_endgame_and_is_fresh(self):
        calls = []

        def base(raw):
            calls.append(raw["seed"])
            return {"action": "check" if raw["to_call"] == 0 else "fold"}

        first = wrap_policy(base)
        second = wrap_policy(base)
        self.assertIsNot(first, second)
        raw = raw_observation(stack_bb=90, players_active=8, seed=733)
        self.assertEqual(first(raw)["action"], "check")
        self.assertEqual(calls, [733])

    def test_wrapper_reset_resets_base_and_local_observations(self):
        class Base:
            def __init__(self):
                self.resets = 0

            def reset(self):
                self.resets += 1

            def __call__(self, raw):
                return {"action": "check" if raw["to_call"] == 0 else "fold"}

        base = Base()
        wrapped = wrap_policy(base, {"short_stack_bb": 12.0})
        wrapped(raw_observation(stack_bb=60))
        self.assertEqual(base.resets, 0)
        wrapped.reset()
        self.assertEqual(base.resets, 1)
        self.assertEqual(wrapped._history_cursor, 0)
        self.assertEqual(wrapped._counts, {})


if __name__ == "__main__":
    unittest.main()
