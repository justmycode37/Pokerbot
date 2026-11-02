import copy
import json
import tempfile
import unittest
from pathlib import Path

from pokerbot.expert_ranges import decide, fit_model, load_model


def state(hole=("As", "Kh")):
    return {
        "hole_cards": list(hole), "board": [], "pot": 150, "to_call": 100,
        "stack": 10000, "current_bet": 0, "min_raise_to": 200, "max_raise_to": 10000,
        "big_blind": 100, "position": "BTN", "players_active": 6, "players_to_act": 2,
        "table_size": 6, "legal_actions": ["fold", "call", "raise"],
        "history": [], "player_id": "bot", "seed": 0,
    }


def external_row():
    return {"state": state(), "expected": {"action": "raise", "amount": 225},
            "partition": "train", "expert_name": "Pluribus", "evidence_tier": "external_expert_phh",
            "source_repo_commit": "e47fbd5816372360bade4de5d712346fe1bb70f6",
            "source": "https://github.com/uoftcprg/phh-dataset/blob/e47fbd5816372360bade4de5d712346fe1bb70f6/data/pluribus/test/0.phh",
            "source_relative_path": "test/0.phh", "source_sha256": "0" * 64,
            "hand_id": "pluribus-phh:test/0.phh#hand=0", "source_hand_id": "0",
            "group_id": "external-session:uoftcprg-phh-dataset:pluribus-archive",
            "session_id": "external-session:uoftcprg-phh-dataset:pluribus-archive",
            "format": "phh_no_limit_holdem",
            "data_identity": "external_pluribus_phh_training_data_not_ivey"}


class ExternalRangeTests(unittest.TestCase):
    def test_hand_classes_generalize_across_suits_ids_and_source_labels(self):
        model = fit_model([external_row()] * 8)
        first = decide(state(), model)
        other = state(("Ac", "Kd"))
        other.update({"seed": 999, "player_id": "different", "source": "unused", "expected": {"action": "fold"}})
        self.assertEqual(first, decide(other, model))
        self.assertEqual(first["action"], "raise")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prior.json"
            path.write_text(json.dumps(model))
            self.assertEqual(load_model(path), model)

    def test_ivey_holdout_and_partial_rows_are_not_external_training_data(self):
        for updates in (
            {"expert_name": "Phil Ivey"}, {"partition": "evaluation"},
            {"partition": "development"}, {"fresh_holdout": True},
            {"data_quality": {"status": "partial"}},
            {"policy_use": "development_only"}, {"source_repo_commit": "unrelated"},
        ):
            candidate = external_row()
            candidate.update(updates)
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                fit_model([candidate])

    def test_external_posterior_is_masked_and_raise_size_is_bounded(self):
        model = fit_model([external_row()] * 8)
        raw = state()
        raw.update({"stack": 150, "current_bet": 100, "to_call": 100,
                    "min_raise_to": 250, "max_raise_to": 250})
        prediction = decide(raw, model)
        self.assertAlmostEqual(sum(prediction["probabilities"].values()), 1.0)
        self.assertEqual(prediction["amount"], 250)
        raw = state(("7c", "2d"))
        raw.update({"to_call": 0, "legal_actions": ["check"], "min_raise_to": 0, "max_raise_to": 0})
        prediction = decide(raw, model)
        self.assertEqual(prediction["action"], "check")
        self.assertEqual(prediction["probabilities"], {"check": 1.0})


if __name__ == "__main__":
    unittest.main()
