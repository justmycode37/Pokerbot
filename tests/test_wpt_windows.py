import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from stitch_wpt_windows import _read, export, stitch

SOURCES = [ROOT / "data/public_ivey_session_wpt_derived/source-corrections-v1/records.json",
           ROOT / "data/public_ivey_session_wpt_windows/w02/records.json"]


class WptWindowTests(unittest.TestCase):
    def test_export_replays_both_windows_and_counts_the_seam_once(self):
        before = [p.read_bytes() for p in SOURCES]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "combined"
            pending = export(SOURCES, output)
            document = json.loads((output / "records.json").read_text())
            self.assertEqual(document["source"]["review_window"]["start_seconds"], 2604)
            self.assertEqual(document["source"]["review_window"]["end_seconds"], 4044)
            self.assertEqual(document["review_totals"], {
                "hand_contexts": 36, "hands_with_ivey_decisions": 32, "ivey_decisions": 80,
                "zero_decision_contexts": 4, "completed_contexts": 35, "boundary_truncated_contexts": 1,
            })
            self.assertEqual(pending["engine_replayable_decision_count"], 80)
            self.assertFalse(pending["excluded_hands"])
            self.assertEqual(len(list((output / "phh").glob("*.phh"))), 36)
            seam = next(h for h in document["hands"] if h["hand_id"] == "WPT-FINAL1-H20")
            self.assertEqual(len(seam["source_fragments"]), 2)
            self.assertEqual([d["decision_id"] for d in seam["decisions"]],
                             [f"WPT-FINAL1-H20-D{i:02}" for i in range(1, 5)])
            self.assertEqual(sum(h.get("classification") == "zero_decision_walk"
                                 for h in pending["hand_contexts"]), 4)
            for row in pending["records_pending_review"]:
                self.assertEqual(row["admission_status"], "pending_source_review")
                self.assertTrue((output / row["evidence_image"]).is_file())
                self.assertNotIn("expected", row["state"])
                self.assertNotIn("result", row["state"])
            turn = next(r for r in pending["records_pending_review"]
                        if r["source_decision_id"] == "WPT-FINAL1-H04-D03")
            self.assertIsNone(turn["source_frame_seconds"])
            self.assertEqual(turn["source_time_interval_seconds"], [2844, 2852])
        self.assertEqual(before, [p.read_bytes() for p in SOURCES])

    def test_overlapping_or_unordered_windows_cannot_be_counted_twice(self):
        with self.assertRaisesRegex(ValueError, "adjacent and ordered"):
            stitch([SOURCES[0], SOURCES[0]], ROOT)
        with self.assertRaisesRegex(ValueError, "adjacent and ordered"):
            stitch(list(reversed(SOURCES)), ROOT)

    def test_changed_seam_context_or_boundary_fails_closed(self):
        original = [_read(p, ROOT) for p in SOURCES]
        for mutation, message in (
            (lambda d: d[1]["hands"][0]["starting_stacks_chips"].update({"Phil Ivey": 1}), "context"),
            (lambda d: d[1]["hands"][0]["continuation_of_prior_window"]["window_start_state"].update(
                {"pot_chips": 3501}), "carried boundary"),
            (lambda d: d[1]["hands"][0]["decisions"][0].update(
                {"decision_id": "WPT-FINAL1-H20-D01"}), "duplicate source decision"),
        ):
            documents = copy.deepcopy(original)
            mutation(documents)
            with patch("stitch_wpt_windows._read", side_effect=documents):
                with self.assertRaisesRegex(ValueError, message):
                    stitch(SOURCES, ROOT)


if __name__ == "__main__":
    unittest.main()
