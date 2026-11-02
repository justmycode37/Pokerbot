import copy
import json
from pathlib import Path
import tempfile
import unittest

from pokerbot.hybrid import _inference_state, decide, fit_model, load_model
from pokerbot.fast import decide as fast_decide
from pokerbot.imitation import FEATURE_VERSION
from pokerbot.sizing import SIZE_FEATURES
from scripts.train_hybrid import leave_one_group_out


def _state(*, hole_cards=("3c", "4d"), board=(), legal=None, to_call=100,
           current_bet=100, stack=2000, minimum=300, maximum=None, seed=0):
    if legal is None:
        legal = ["fold", "call", "raise"] if to_call else ["check", "raise"]
    if maximum is None:
        maximum = current_bet + stack
    street = {0: "preflop", 3: "flop", 4: "turn", 5: "river"}[len(board)]
    return {
        "hole_cards": list(hole_cards), "board": list(board), "pot": 600,
        "contestable_pot": 600, "to_call": to_call, "stack": stack,
        "current_bet": current_bet, "min_raise_to": minimum,
        "max_raise_to": maximum, "big_blind": 100, "position": "UTG",
        "players_active": 3, "players_to_act": 1, "table_size": 6,
        "legal_actions": list(legal), "street": street, "seed": seed, "history": [],
    }


def _sizer(ratio):
    return {
        "schema_version": 1,
        "algorithm": "independent-l1-raise-size-tree",
        "feature_version": FEATURE_VERSION,
        "feature_names": list(SIZE_FEATURES),
        "tree": {"leaf": True, "raise_ratio": ratio, "sample_count": 1},
        "metadata": {},
    }


def _synthetic_rows():
    state = _state()
    return [
        {"state": copy.deepcopy(state), "expected": {"action": "call"},
         "group_id": f"synthetic-source-{index % 2}", "hand_id": f"hand-{index}",
         "decision_id": f"decision-{index}"}
        for index in range(8)
    ]


def _fitted_model():
    return fit_model(
        _synthetic_rows(), regularization=0.001, blend=1.0,
        sizer=_sizer(0.5), manifest_hash="synthetic-only",
    )


class HybridTests(unittest.TestCase):
    def test_actor_renaming_preserves_hero_roles_and_fast_prior(self):
        model = _fitted_model()
        original = _state(hole_cards=("As", "Kd"), current_bet=200,
                          to_call=300, minimum=800, maximum=2200)
        original["player_id"] = "Ivey"
        original["history"] = [
            {"street": "preflop", "player": "Ivey", "action": "raise", "amount": 200, "added": 100},
            {"street": "preflop", "player": "Villain", "action": "raise", "amount": 500, "added": 400},
        ]
        self.assertEqual(fast_decide(_inference_state(original)), fast_decide(original))
        changed = copy.deepcopy(original)
        changed["player_id"] = "seat-7"
        changed["history"][0]["player"] = "seat-7"
        changed["history"][1]["player"] = "seat-2"
        self.assertEqual(decide(original, model), decide(changed, model))

    def test_action_only_model_still_has_a_legal_raise_fallback(self):
        model = _fitted_model()
        model["sizer"] = None
        model["residual"]["intercepts"] = [40.0, -40.0, -40.0, -40.0]
        model["residual"]["weights"] = [[0.0] * len(model["feature_names"]) for _ in range(4)]
        raw = _state()
        result = decide(raw, model)
        self.assertEqual(result["action"], "raise")
        self.assertEqual(result["amount"], raw["min_raise_to"])

    def test_loader_rejects_missing_parameters_and_malformed_nested_tree(self):
        baseline = _fitted_model()
        variants = []
        missing = copy.deepcopy(baseline)
        del missing["regularization"]
        variants.append(missing)
        malformed = copy.deepcopy(baseline)
        malformed["sizer"] = {}
        variants.append(malformed)
        bad_branch = copy.deepcopy(baseline)
        bad_branch["sizer"]["tree"] = {"feature": "street_preflop", "threshold": 0.5,
                                        "left": {"leaf": True, "raise_ratio": 0.5}, "right": {}}
        variants.append(bad_branch)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            for model in variants:
                path.write_text(json.dumps(model))
                with self.assertRaises(ValueError):
                    load_model(path)

    def test_direct_fitting_rejects_evaluation_and_partial_rows(self):
        for marker in ("partition", "data_quality", "evidence_tier"):
            rows = _synthetic_rows()
            rows[0][marker] = {"partition": "evaluation", "data_quality": {"status": "partial"},
                               "evidence_tier": "video_snapshot_with_rounded_or_missing_context"}[marker]
            with self.assertRaises(ValueError):
                fit_model(rows, regularization=0.01, blend=1.0)

    def test_model_loads_after_sorted_json_serialization(self):
        model = _fitted_model()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hybrid.json"
            path.write_text(json.dumps(model, sort_keys=True), encoding="utf-8")
            loaded = load_model(path)

        state = _state()
        self.assertEqual(decide(state, loaded), decide(state, model))

    def test_learns_a_shared_rule_for_an_unseen_synthetic_source_group(self):
        model = _fitted_model()
        unseen = _state(seed=987)
        unseen.update({"group_id": "never-seen-source", "hand_id": "never-seen-hand"})

        prediction = decide(unseen, model)

        self.assertEqual(prediction["action"], "call")
        self.assertEqual(model["metadata"]["training_group_count"], 2)
        self.assertNotIn("never-seen-source", model["metadata"]["training_group_ids"])

    def test_legal_action_mask_and_probability_mix_are_normalized(self):
        model = _fitted_model()
        state = _state(legal=["check", "raise"], to_call=0, current_bet=0,
                       minimum=100, maximum=2000)

        prediction = decide(state, model)

        self.assertIn(prediction["action"], state["legal_actions"])
        self.assertEqual(set(prediction["probabilities"]), {"check", "raise"})
        self.assertAlmostEqual(sum(prediction["probabilities"].values()), 1.0, places=12)
        self.assertTrue(all(0 <= value <= 1 for value in prediction["probabilities"].values()))

    def test_prediction_ignores_seed_ids_labels_and_private_or_future_fields(self):
        model = _fitted_model()
        original = _state()
        baseline = decide(original, model)
        changed = copy.deepcopy(original)
        changed.update({
            "seed": 123456, "player_id": "different-player", "hand_id": "different-hand",
            "group_id": "different-source", "decision_id": "different-decision",
            "expected_action": "raise", "label": "fold", "opponent_hole_cards": ["As", "Ad"],
            "future_cards": ["Ks", "Kd"], "private_field": {"cards": ["Qc", "Qd"]},
        })

        self.assertEqual(decide(changed, model), baseline)

    def test_raise_sizes_stay_at_minimum_maximum_and_short_all_in_limits(self):
        model = _fitted_model()
        model["residual"]["intercepts"] = [40.0, -40.0, -40.0, -40.0]
        model["residual"]["weights"] = [[0.0] * len(model["feature_names"]) for _ in range(4)]

        minimum_state = _state()
        minimum_model = copy.deepcopy(model)
        minimum_model["sizer"] = _sizer(0.0)
        minimum_prediction = decide(minimum_state, minimum_model)
        self.assertEqual(minimum_prediction["action"], "raise")
        self.assertEqual(minimum_prediction["amount"], minimum_state["min_raise_to"])

        maximum_state = _state()
        maximum_model = copy.deepcopy(model)
        maximum_model["sizer"] = _sizer(100.0)
        maximum_prediction = decide(maximum_state, maximum_model)
        self.assertEqual(maximum_prediction["action"], "raise")
        self.assertEqual(maximum_prediction["amount"], maximum_state["max_raise_to"])

        short_all_in_state = _state(stack=500, current_bet=100, to_call=100,
                                    minimum=500, maximum=600)
        all_in_prediction = decide(short_all_in_state, maximum_model)
        self.assertEqual(all_in_prediction["action"], "raise")
        self.assertEqual(all_in_prediction["amount"], short_all_in_state["max_raise_to"])
        self.assertEqual(all_in_prediction["amount"], short_all_in_state["current_bet"] + short_all_in_state["stack"])

    def test_leave_one_group_out_never_fits_the_held_out_group(self):
        rows = _synthetic_rows()

        folds = list(leave_one_group_out(rows))

        self.assertEqual(len(folds), 2)
        for held_out, training, validation in folds:
            train_groups = {row["group_id"] for row in training}
            validation_groups = {row["group_id"] for row in validation}
            self.assertEqual(validation_groups, {held_out})
            self.assertNotIn(held_out, train_groups)
            self.assertFalse(train_groups.intersection(validation_groups))


if __name__ == "__main__":
    unittest.main()
