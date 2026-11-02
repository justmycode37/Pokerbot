import json
import unittest
from unittest import mock

from pokerbot import preflop
from pokerbot.saved_bot import _resource, load_bot


class SavedBotTests(unittest.TestCase):
    def test_saved_checkpoint_uses_bundled_table_without_checkout_data(self):
        expected = json.loads(_resource("preflop-equity-v1.json"))["equity_vs_one_random_opponent"]
        with mock.patch.object(preflop, "_EQUITIES", {}):
            bot = load_bot()
            self.assertEqual(preflop._EQUITIES, expected)
            state = {
                "hole_cards": ["As", "Ah"], "board": [], "pot": 150,
                "to_call": 100, "stack": 10000, "current_bet": 0,
                "min_raise_to": 200, "max_raise_to": 10000, "big_blind": 100,
                "position": "BTN", "players_active": 6, "players_to_act": 2,
                "legal_actions": ["fold", "call", "raise"], "history": [],
            }
            decision = bot(state)
            self.assertIn(decision["action"], state["legal_actions"])
            self.assertEqual(decision, bot({**state, "seed": 456}))
            if decision["action"] == "raise":
                self.assertTrue(200 <= decision["amount"] <= 10000)

    def test_corrupt_checkpoint_data_is_rejected(self):
        resource = _resource
        def corrupted(name):
            value = resource(name)
            return value + b" " if name == "ivey-transfer-v1.json" else value
        with mock.patch("pokerbot.saved_bot._resource", side_effect=corrupted):
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                load_bot()
