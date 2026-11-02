import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from pokerbot.corpus import save_split, split_rows
from pokerbot.imitation import FEATURE_NAMES, decide_with_model, features, fit_model
import train_imitation


def observation(**updates):
    raw = {
        "hole_cards": ["As", "Kd"],
        "board": [],
        "pot": 120,
        "to_call": 10,
        "stack": 300,
        "current_bet": 0,
        "min_raise_to": 20,
        "max_raise_to": 300,
        "big_blind": 10,
        "position": "BTN",
        "players_active": 2,
        "players_to_act": 1,
        "legal_actions": ["fold", "call", "raise"],
        "history": [],
        "seed": 91,
    }
    raw.update(updates)
    return raw


def training_row(hole_cards, action, *, hand_id="train", partition="train"):
    state = observation(hole_cards=hole_cards)
    expected = {"action": action}
    if action == "raise":
        expected["amount"] = 80
    return {
        "state": state,
        "expected": expected,
        "hand_id": hand_id,
        "group_id": hand_id,
        "partition": partition,
    }


class ImitationFeatureTests(unittest.TestCase):
    def test_features_ignore_labels_ids_seeds_and_future_fields(self):
        raw = observation(history=[
            {"street": "preflop", "player": "seat-2", "action": "raise", "amount": 20, "added": 20}
        ])
        expected = features(raw)
        changed = copy.deepcopy(raw)
        changed.update({
            "hand_id": "a different hand",
            "canonical_hand_id": "another id",
            "source": "https://example.invalid/video",
            "session_id": "session-elsewhere",
            "player_id": "a different hero key",
            "seed": 987654,
            "expected": {"action": "fold"},
            "outcome": {"winner": "opponent"},
            "future_board": ["2c", "3c"],
            "opponent_hole_cards": ["Qc", "Qd"],
            "future_actions": [{"action": "raise"}],
        })
        changed["history"][0]["player"] = "seat-99"
        self.assertEqual(expected, features(changed))
        self.assertEqual(tuple(expected), FEATURE_NAMES)
        self.assertTrue(all(type(value) is float for value in expected.values()))


class ImitationModelTests(unittest.TestCase):
    def test_tree_learns_a_generalizable_relation_on_unseen_groups(self):
        training = []
        for rank in "23456789TJQKA":
            pair = [rank + "c", rank + "d"]
            training.append(training_row(pair, "raise", hand_id="train-pair-" + rank))
            next_rank = "2" if rank == "A" else "23456789TJQKA"["23456789TJQKA".index(rank) + 1]
            nonpair = [rank + "c", next_rank + "d"]
            training.append(training_row(nonpair, "fold", hand_id="train-unpaired-" + rank))

        evaluation = [
            training_row(["6h", "6s"], "raise", hand_id="heldout-pair", partition="evaluation"),
            training_row(["5h", "7s"], "fold", hand_id="heldout-unpaired", partition="evaluation"),
        ]
        self.assertTrue({row["group_id"] for row in training}.isdisjoint(
            row["group_id"] for row in evaluation
        ))
        model = fit_model(training)
        json.dumps(model, allow_nan=False)
        predicted = [decide_with_model(row["state"], model) for row in evaluation]
        json.dumps(predicted, allow_nan=False)
        self.assertEqual([item["action"] for item in predicted], ["raise", "fold"])
        self.assertEqual(model["tree"]["feature"], "hole_pair")
        self.assertTrue(all(abs(sum(item["probabilities"].values()) - 1.0) < 1e-12
                            for item in predicted))

    def test_fit_rejects_evaluation_and_implicit_development_rows(self):
        with self.assertRaisesRegex(ValueError, "evaluation"):
            fit_model([training_row(["As", "Ah"], "raise", partition="evaluation")])
        with self.assertRaisesRegex(ValueError, "include_development"):
            fit_model([training_row(["As", "Ah"], "raise", partition="development")])

    def test_legal_mask_empty_call_and_short_all_in_bounds(self):
        call_only_model = fit_model([
            training_row(["As", "Ah"], "call"),
            training_row(["Ks", "Kh"], "call", hand_id="train-call-2"),
        ])
        free_check = observation(
            hole_cards=["7c", "2d"], to_call=0, current_bet=0,
            min_raise_to=20, max_raise_to=300,
            legal_actions=["check", "raise"],
        )
        free_result = decide_with_model(free_check, call_only_model)
        self.assertEqual(free_result["action"], "check")
        self.assertNotIn("call", free_result["probabilities"])
        self.assertAlmostEqual(sum(free_result["probabilities"].values()), 1.0)

        raise_model = fit_model([
            training_row(["As", "Ah"], "raise"),
            training_row(["Ks", "Kh"], "raise", hand_id="train-raise-2"),
        ])
        short_all_in = observation(
            hole_cards=["5c", "5d"], to_call=10, stack=25, current_bet=20,
            min_raise_to=40, max_raise_to=45,
            legal_actions=["fold", "call", "raise"],
        )
        result = decide_with_model(short_all_in, raise_model)
        self.assertEqual(result["action"], "raise")
        self.assertEqual(result["amount"], 45)
        self.assertEqual(result["raise_amount"], 45)
        self.assertGreaterEqual(result["amount"], short_all_in["min_raise_to"])
        self.assertLessEqual(result["amount"], short_all_in["max_raise_to"])
        self.assertTrue(set(result["probabilities"]).issubset(short_all_in["legal_actions"]))
        self.assertAlmostEqual(sum(result["probabilities"].values()), 1.0)


class ImitationTrainingScriptTests(unittest.TestCase):
    def _corpus_rows(self):
        rows = []
        ids = ["dwan-ivey-2009", "train-a", "train-b", "train-c", "eval-candidate"]
        cards = [["As", "Ah"], ["Ks", "Kh"], ["Qs", "Qh"], ["Js", "Jh"], ["Ts", "Th"]]
        for hand_id, hole in zip(ids, cards):
            state = observation(hole_cards=hole)
            rows.append({
                "state": state,
                "expected": {"action": "raise", "amount": 80},
                "source": "https://example.test/hand/" + hand_id,
                "hand_id": hand_id,
            })
        return rows

    def test_frozen_manifest_training_and_scoring_use_disjoint_partitions(self):
        rows = self._corpus_rows()
        seen = {"dwan-ivey-2009"}
        manifest = split_rows(rows, seed=17, evaluation_fraction=0.25,
                              development_hand_ids=seen)
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "split.json"
            save_split(manifest, manifest_path)
            fit_calls = []
            comparison_calls = []

            def fake_fit(fitting_rows, **kwargs):
                fit_calls.append((list(fitting_rows), kwargs))
                return {"metadata": {"manifest_hash": kwargs["manifest_hash"]}}

            def fake_compare(evaluation_rows, decide_callable, *, sizing_tolerance):
                comparison_calls.append([row["group_id"] for row in evaluation_rows])
                return {
                    "predictions": [{
                        "expected_action": row["expected"]["action"],
                        "predicted_action": row["expected"]["action"],
                        "action_match": True,
                    } for row in evaluation_rows],
                    "raise_sizing": {"sized_raise_count": 0},
                    "mixed_action_comparison": {"scored_count": 0},
                }

            with mock.patch.object(train_imitation, "fit_model", side_effect=fake_fit), \
                    mock.patch.object(train_imitation, "compare_decisions", side_effect=fake_compare):
                model, report = train_imitation.train_and_evaluate_manifest(manifest_path)
                model_with_development, dev_report = train_imitation.train_and_evaluate_manifest(
                    manifest_path, include_development=True
                )

        fitting_rows, fit_options = fit_calls[0]
        fitting_rows_with_development, dev_fit_options = fit_calls[1]
        evaluation_groups = {row["group_id"] for row in manifest["records"]
                             if row["partition"] == "evaluation"}
        self.assertTrue(fitting_rows)
        self.assertTrue(all(row["partition"] == "train" for row in fitting_rows))
        self.assertTrue({row["group_id"] for row in fitting_rows}.isdisjoint(evaluation_groups))
        self.assertNotIn("dwan-ivey-2009", {row["hand_id"] for row in fitting_rows})
        self.assertEqual(fit_options["include_development"], False)
        self.assertTrue(all(row["partition"] in {"train", "development"}
                            for row in fitting_rows_with_development))
        self.assertIn("dwan-ivey-2009", {row["hand_id"] for row in fitting_rows_with_development})
        self.assertEqual(dev_fit_options["include_development"], True)
        self.assertGreaterEqual(len(comparison_calls), 4)
        self.assertTrue(all(groups == list(evaluation_groups) for groups in comparison_calls))
        self.assertEqual(report["training"]["evaluation_rows_used_for_fitting"], 0)
        self.assertEqual(report["manifest_hash"], model["metadata"]["manifest_hash"])
        self.assertEqual(dev_report["manifest_hash"], model_with_development["metadata"]["manifest_hash"])
        self.assertEqual(report["99_percent_population_agreement_demonstrated"], False)
        self.assertTrue(report["exploratory_only"])

    def test_previously_seen_hand_cannot_be_frozen_as_train_or_evaluation(self):
        rows = self._corpus_rows()
        manifest = split_rows(rows, seed=17, evaluation_fraction=0.25)
        fitting = [row for row in manifest["records"] if row["partition"] == "train"]
        evaluation = [row for row in manifest["records"] if row["partition"] == "evaluation"]
        with self.assertRaisesRegex(ValueError, "previously inspected"):
            train_imitation.prepare_partitions(
                {"records": fitting + evaluation},
                development_hand_ids={"dwan-ivey-2009"},
            )

    def test_script_refuses_empty_partitions_and_cross_partition_groups(self):
        manifest = split_rows(self._corpus_rows(), seed=17, evaluation_fraction=0.25)
        train_rows = [row for row in manifest["records"] if row["partition"] == "train"]
        evaluation_rows = [row for row in manifest["records"] if row["partition"] == "evaluation"]
        with self.assertRaisesRegex(ValueError, "no train groups"):
            train_imitation.prepare_partitions(
                {"records": evaluation_rows}, development_hand_ids=set()
            )
        with self.assertRaisesRegex(ValueError, "no evaluation groups"):
            train_imitation.prepare_partitions(
                {"records": train_rows}, development_hand_ids=set()
            )
        crossed = copy.deepcopy(train_rows[0])
        crossed["partition"] = "evaluation"
        with self.assertRaisesRegex(ValueError, "source group crosses"):
            train_imitation.prepare_partitions(
                {"records": train_rows + [crossed]}, development_hand_ids=set()
            )


if __name__ == "__main__":
    unittest.main()
