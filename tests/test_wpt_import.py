import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from import_wpt_session import build_pending


class WptImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = json.loads((ROOT / "data/public_ivey_session_wpt/records.json").read_text())
        cls.phh_dir = ROOT / "data/public_ivey_session_wpt/phh"
        cls.pending = build_pending(cls.document, cls.phh_dir)

    def test_replay_error_is_excluded_and_walks_receive_no_decision_credit(self):
        self.assertEqual(self.pending["source_recorded_decision_count"], 42)
        self.assertEqual(self.pending["engine_replayable_decision_count"], 38)
        self.assertEqual(self.pending["excluded_hands"][0]["hand_id"], "WPT-FINAL1-H04")
        self.assertEqual(self.pending["excluded_hands"][0]["decision_count"], 4)
        walks = [c for c in self.pending["hand_contexts"] if c.get("classification") == "zero_decision_walk"]
        self.assertEqual(len(walks), 2)
        self.assertTrue(all(c["recorded_decisions"] == 0 for c in walks))

    def test_labels_and_outcomes_are_not_in_observations(self):
        for row in self.pending["records_pending_review"]:
            self.assertEqual(row["admission_status"], "pending_source_review")
            for state in (row["state"], row["raw_public_observation"]):
                self.assertNotIn("expected_action", state)
                self.assertNotIn("result", state)
                self.assertNotIn("opponent_hole_cards", state)
            self.assertEqual(row["state"]["table_size"], 2)
            self.assertEqual(len(row["state"]["board"]),
                             {"preflop": 0, "flop": 3, "turn": 4, "river": 5}[row["state"]["street"]])
            self.assertIn("opponent_stack_chips", row["raw_public_observation"])

    def test_import_does_not_mutate_source_capture(self):
        before = copy.deepcopy(self.document)
        build_pending(self.document, self.phh_dir)
        self.assertEqual(self.document, before)

    def test_inconsistent_expected_label_is_not_repaired(self):
        changed = copy.deepcopy(self.document)
        changed["hands"][0]["decisions"][0]["expected_action"]["action"] = "fold"
        with self.assertRaisesRegex(ValueError, "expected actions"):
            build_pending(changed, self.phh_dir)

    def test_corrupt_chip_ledger_cannot_propagate_to_later_hands(self):
        changed = copy.deepcopy(self.document)
        changed["hands"][0]["ending_stacks_chips"]["Phil Ivey"] += 1
        with self.assertRaisesRegex(ValueError, "payout"):
            build_pending(changed, self.phh_dir)

    def test_source_corrections_replay_without_hiding_remaining_uncertainty(self):
        folder = ROOT / "data/public_ivey_session_wpt_derived/source-corrections-v1"
        corrected = json.loads((folder / "records.json").read_text())
        result = build_pending(corrected, folder / "phh")
        self.assertEqual(result["engine_replayable_decision_count"], 42)
        self.assertFalse(result["excluded_hands"])
        by_id = {r["source_decision_id"]: r for r in result["records_pending_review"]}
        turn = by_id["WPT-FINAL1-H04-D03"]
        self.assertIsNone(turn["source_frame_seconds"])
        self.assertEqual(turn["source_time_interval_seconds"], [2844, 2852])
        self.assertIn("pending", turn["evidence_time_status"])
        self.assertEqual(turn["state"]["players_to_act"], 0)
        self.assertEqual(turn["state"]["to_call"], 0)
        flop = by_id["WPT-FINAL1-H11-D03"]
        self.assertEqual(flop["state"]["to_call"], 2280)
        self.assertEqual(flop["state"]["pot"], 6280)
        self.assertEqual(flop["raw_public_observation"]["opponent_stack_chips"], 70781)
        for row in result["records_pending_review"]:
            self.assertEqual(row["admission_status"], "pending_source_review")
            self.assertIn("conditional", row["continuity_precision"])
            self.assertTrue((folder / row["evidence_image"]).is_file())


if __name__ == "__main__":
    unittest.main()
