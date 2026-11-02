import copy
import json
import unittest
from pathlib import Path
from unittest import mock

from pokerbot.candidate_evaluation import compare_new_batch, freeze_candidates, verify_candidate_lock
from pokerbot.corpus import load_split

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "data/corpus_splits/development-after-prospective-v1.json"


def new_synthetic_row():
    return {"hand_id": "synthetic-unseen", "session_id": "synthetic-unseen-session",
            "source": "https://example.test/synthetic-unseen", "expected": {"action": "call"},
            "state": {"hole_cards": ["As", "Kd"], "board": [], "pot": 100,
                      "to_call": 10, "stack": 1000, "current_bet": 0,
                      "min_raise_to": 20, "max_raise_to": 1000, "big_blind": 10,
                      "position": "BTN", "players_active": 2, "players_to_act": 1,
                      "table_size": 2, "legal_actions": ["fold", "call", "raise"],
                      "history": [], "seed": 0, "hand_id": "report-only-identifier"}}


class CandidateEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.lock = freeze_candidates(MANIFEST, ["fast"])

    def test_lock_is_serializable_and_rejects_changed_or_omitted_hashes(self):
        verify_candidate_lock(json.loads(json.dumps(self.lock)))
        changed = copy.deepcopy(self.lock)
        changed["runtime_fingerprints"]["pokerbot/fast.py"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "changed"):
            verify_candidate_lock(changed)
        del changed["runtime_fingerprints"]["pokerbot/fast.py"]
        with self.assertRaisesRegex(ValueError, "incomplete"):
            verify_candidate_lock(changed)

    def test_all_previously_inspected_groups_are_rejected_before_policy_loading(self):
        old = load_split(ROOT / MANIFEST)["records"][-1]
        with mock.patch("pokerbot.candidate_evaluation._policy") as factory:
            with self.assertRaisesRegex(ValueError, "already inspected"):
                compare_new_batch([old], self.lock)
            factory.assert_not_called()

    def test_policy_input_is_sanitized_and_no_population_claim_is_made(self):
        seen = []
        def policy(state):
            seen.append(state)
            self.assertNotIn("hand_id", state)
            self.assertNotIn("expected", state)
            return {"action": "call", "probabilities": {"call": 1.0}}
        with mock.patch("pokerbot.candidate_evaluation._policy", return_value=policy):
            report = compare_new_batch([new_synthetic_row()], self.lock)
        self.assertEqual(len(seen), 1)
        self.assertEqual(report["evaluation_rows_used_for_fitting"], 0)
        self.assertIsNone(report["population_accuracy_claim"])
        self.assertFalse(report["99_percent_population_agreement_demonstrated"])

    def test_partial_pending_and_unspecified_table_size_are_rejected(self):
        for mutation in ("partial", "pending", "table_size"):
            row = new_synthetic_row()
            if mutation == "partial":
                row["data_quality"] = {"status": "partial"}
            elif mutation == "pending":
                row["admission_status"] = "pending_source_review"
            else:
                del row["state"]["table_size"]
            with self.assertRaises(ValueError):
                compare_new_batch([row], self.lock)


if __name__ == "__main__":
    unittest.main()
