import hashlib
import json
import unittest
from pathlib import Path

from pokerbot.ivey import compare_decisions

ROOT = Path(__file__).resolve().parents[1]


class PartialVideoEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.first = json.loads((ROOT / "data/public_ivey_videos/hand-reviews.json").read_text())
        cls.second = [json.loads(line) for line in
                      (ROOT / "data/public_ivey_videos_batch2/observations.jsonl").read_text().splitlines()]

    def test_corrected_capture_hashes_and_exact_scorer_exclusion(self):
        manifest = json.loads((ROOT / "data/corpus_admission/video-partial-v2.json").read_text())
        self.assertEqual(len(manifest["records"]), 30)
        for name, digest in manifest["raw_source_hashes"].items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest)
        def never_called(state):
            self.fail("A partial observation reached a policy")
        for row in manifest["records"]:
            with self.assertRaisesRegex(ValueError, "qualitative-only"):
                compare_decisions([dict(row, state=row["raw_state"], expected={"action": "fold"},
                                        hand_id=row.get("hand_id", row["video_id"]))], never_called)

    def test_reference_stills_exist_and_equity_exposing_still_is_withdrawn(self):
        count = 0
        for source in self.first["sources"]:
            for row in source["decisions"]:
                if row.get("predecision_frame"):
                    self.assertTrue((ROOT / "data/public_ivey_videos" / row["predecision_frame"]).is_file())
                    count += 1
                if row.get("withdrawn_frame"):
                    self.assertFalse((ROOT / "data/public_ivey_videos" / row["withdrawn_frame"]).exists())
        for row in self.second:
            self.assertTrue((ROOT / "data/public_ivey_videos_batch2" / row["source"]["frame"]).is_file())
            count += 1
        self.assertEqual(count, 28)

    def test_checked_opponents_are_not_pending_before_new_bet(self):
        kirk = [r for r in self.second if r["source"]["video_id"] == "mtCcWNLHMbM"
                and r["state"]["street"] in {"flop", "turn"}]
        self.assertEqual([r["state"]["players_to_act"] for r in kirk], [0, 0])
        triton = next(s for s in self.first["sources"] if s["video_id"] == "KjreElAgfRk")
        self.assertEqual(triton["decisions"][1]["hero_visible_state"]["players_to_act"], 0)

    def test_rounded_stack_derived_values_are_not_exact_state_inputs(self):
        rc3 = [r for r in self.second if r["source"]["video_id"] == "RC3ddhyKFOo"]
        self.assertTrue(all(r["state"]["stack"] is None and r["state"]["pot"] is None for r in rc3))
        facing = rc3[-1]
        self.assertIsNone(facing["state"]["to_call"])
        self.assertIsNone(facing["state"]["contestable_pot"])
        self.assertEqual(facing["data_quality"]["approximate_values"]["stack"]["value"], 257000)

    def test_pot_crops_and_unresolved_cap_are_explicit(self):
        source = next(s for s in self.first["sources"] if s["video_id"] == "g1nesioHo_c")
        self.assertEqual(source["decisions"][1]["hero_visible_state"]["pot"], 10200)
        for row in source["decisions"][1:3]:
            self.assertTrue((ROOT / "data/public_ivey_videos" / row["pot_evidence"]["frame"]).is_file())
        facing = source["decisions"][-1]
        self.assertIsNone(facing["hero_visible_state"]["to_call"])
        self.assertEqual(facing["nominal_additional_call_before_stack_cap"]["value"], 57300)


if __name__ == "__main__":
    unittest.main()
