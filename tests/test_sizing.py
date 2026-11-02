import copy
import json
import unittest

from pokerbot.imitation import decide_with_model, fit_model
from pokerbot.sizing import decide_with_sizer, fit_sizer, predict_raise_to


def state(*, river=False, pot=10000, stack=100000):
    return {"hole_cards": ["Ac", "Kd"], "board": ["2c", "4d", "7h", "9s", "Jc"] if river else [],
            "pot": pot, "to_call": 0, "stack": stack, "current_bet": 0,
            "min_raise_to": 100, "max_raise_to": stack, "big_blind": 100,
            "position": "BTN", "players_active": 2, "players_to_act": 0,
            "legal_actions": ["check", "raise"], "history": [], "seed": 0}


def rows():
    return [{"state": state(river=river), "expected": {"action": "raise", "amount": 15000 if river else 5000},
             "hand_id": f"synthetic-{river}-{i}", "group_id": f"synthetic-{river}-{i}", "partition": "train"}
            for river in (False, True) for i in range(4)]


class SizingTests(unittest.TestCase):
    def test_learns_sizes_even_when_action_leaf_is_pure(self):
        training = rows()
        classifier = fit_model(training)
        self.assertTrue(classifier["tree"]["leaf"])
        sizer = fit_sizer(training)
        # New pot sizes and hand identities test the learned ratio relation.
        for river, expected in ((False, 10000), (True, 30000)):
            raw = state(river=river, pot=20000)
            raw["hand_id"] = "never-fitted"
            self.assertEqual(predict_raise_to(raw, sizer), expected)
            result = decide_with_sizer(raw, classifier, sizer)
            self.assertEqual(result["amount"], expected)
            self.assertEqual(result["probabilities"], decide_with_model(raw, classifier)["probabilities"])

    def test_scaling_identity_and_private_extras_do_not_change_ratio(self):
        model = fit_sizer(rows())
        raw = state(pot=20000)
        expected = predict_raise_to(raw, model)
        changed = copy.deepcopy(raw)
        changed.update(hand_id="other", source="other", seed=100, expected={"action": "fold"},
                       opponent_hole_cards=["As", "Ah"], future_board=["Qs"])
        self.assertEqual(predict_raise_to(changed, model), expected)
        for field in ("pot", "stack", "min_raise_to", "max_raise_to", "big_blind"):
            changed[field] *= 7
        self.assertEqual(predict_raise_to(changed, model), expected * 7)

    def test_legal_bounds_no_raises_and_empty_size_training(self):
        model = fit_sizer(rows())
        self.assertEqual(predict_raise_to(state(river=True, stack=500), model), 500)
        passive = state()
        passive["legal_actions"] = ["check"]
        self.assertIsNone(predict_raise_to(passive, model))
        training = rows()
        for row in training:
            row["expected"] = {"action": "check"}
        empty = fit_sizer(training)
        json.dumps(empty, allow_nan=False)
        self.assertIsNone(predict_raise_to(state(), empty))

    def test_rejects_holdout_implicit_development_and_partial_rows(self):
        for partition, error in (("evaluation", "evaluation"), ("development", "include_development")):
            training = rows()
            training[0]["partition"] = partition
            with self.assertRaisesRegex(ValueError, error):
                fit_sizer(training)
        training = rows()
        training[0]["evidence_tier"] = "video_snapshot_with_rounded_or_missing_context"
        with self.assertRaisesRegex(ValueError, "partial"):
            fit_sizer(training)

    def test_bad_model_ratio_is_rejected(self):
        model = fit_sizer(rows(), max_depth=0)
        model["tree"]["raise_ratio"] = True
        with self.assertRaisesRegex(ValueError, "ratio"):
            predict_raise_to(state(), model)


if __name__ == "__main__":
    unittest.main()
