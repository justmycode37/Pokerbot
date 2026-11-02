import copy
import json
import tempfile
import unittest
from pathlib import Path

from pokerbot.benchmarks import load_ivey_corpus
from pokerbot.corpus import grouping_key, load_split, save_split, split_rows


class CorpusSplitTests(unittest.TestCase):
    def setUp(self):
        self.rows, _ = load_ivey_corpus(include_reconstructed=True, include_verified_video=True)

    def test_entire_hands_stay_together_and_old_reviews_are_not_held_out(self):
        known = [self.rows[0]["hand_id"]]
        split = split_rows(self.rows, development_hand_ids=known)
        memberships = {}
        for row in split["records"]:
            memberships.setdefault(row["hand_id"], set()).add(row["partition"])
            self.assertNotIn("hand_id", row["state"])
        self.assertTrue(all(len(parts) == 1 for parts in memberships.values()))
        self.assertEqual(memberships[known[0]], {"development"})
        self.assertEqual(split["counts"]["evaluation"]["groups"], 1)

    def test_same_video_groups_separate_hands_together(self):
        a = {"hand_id": "first", "source": "https://youtu.be/abc?t=20"}
        b = {"hand_id": "second", "source": "https://www.youtube.com/watch?v=abc&t=40s"}
        self.assertEqual(grouping_key(a), grouping_key(b))

    def test_frozen_source_tampering_and_overwrite_are_rejected(self):
        split = split_rows(self.rows)
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "split.json"
            save_split(split, p)
            self.assertEqual(load_split(p)["dataset_hash"], split["dataset_hash"])
            with self.assertRaises(FileExistsError):
                save_split(split, p)
            changed = copy.deepcopy(split)
            changed["records"][0]["expected"]["amount"] += 1
            p.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, "changed"):
                load_split(p)

    def test_duplicate_decisions_do_not_inflate_the_dataset(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            split_rows(self.rows + [self.rows[0]])
        different_seed = copy.deepcopy(self.rows[0])
        different_seed["state"]["seed"] += 1
        with self.assertRaisesRegex(ValueError, "duplicate"):
            split_rows(self.rows + [different_seed])
