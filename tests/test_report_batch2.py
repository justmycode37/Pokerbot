import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from import_report_batch2 import build_pending
from pokerbot.corpus import load_split
from pokerbot.prospective import assert_new_groups
from pokerbot.state import Observation


class ReportBatchReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = json.loads((ROOT / "data/public_ivey_reports_batch2/decision-evidence.json").read_text())
        cls.pending = build_pending(cls.raw)
        cls.records = cls.pending["records_pending_review"]

    def test_all_known_decisions_replay_and_groups_are_disjoint(self):
        self.assertEqual(len(self.records), 22)
        self.assertEqual(len({r["hand_id"] for r in self.records}), 5)
        manifest = load_split(ROOT / "data/corpus_splits/public-reports-v1.json")
        self.assertEqual(len(assert_new_groups(self.records, manifest)), 22)
        self.assertTrue(all(r["hero_observations_identical_across_probes"]
                            for r in self.pending["engine_validation"]))

    def test_dead_big_blind_ante_does_not_reduce_raise_payment(self):
        rows = [r for r in self.records if r["hand_id"] == "ivey_heath_2022_wsop_event42"]
        self.assertEqual([r["state"]["pot"] for r in rows], [625000, 2775000, 5325000])
        heath_raise = rows[1]["state"]["history"][-1]
        self.assertEqual(heath_raise["amount"], 1850000)
        self.assertEqual(heath_raise["added"], 1600000)
        self.assertEqual(len(self.pending["history_differences"]), 2)
        self.assertTrue(all(d["collector_value"] == 1350000 and d["engine_value"] == 1600000
                            for d in self.pending["history_differences"]))

    def test_heads_up_forced_bets_table_size_and_exact_shove(self):
        rows = [r for r in self.records if r["hand_id"].endswith("final_hand")]
        first = rows[0]["state"]
        self.assertEqual(first["table_size"], 2)
        self.assertEqual(first["position"], "BB")
        self.assertEqual(first["current_bet"], 400000)
        self.assertEqual(first["stack"], 14225000 - 400000 - 400000)
        self.assertEqual(rows[-1]["expected"]["amount"], 11025000)

    def test_seven_player_table_folds_then_last_to_act(self):
        rows = [r for r in self.records if "punsri" in r["hand_id"]]
        self.assertEqual(rows[0]["state"]["table_size"], 7)
        self.assertEqual(rows[0]["state"]["players_active"], 2)
        self.assertEqual(sum(a["action"] == "fold" for a in rows[0]["state"]["history"]), 5)
        self.assertEqual(rows[1]["state"]["players_to_act"], 0)

    def test_source_added_fields_cannot_override_betting_targets(self):
        changed = copy.deepcopy(self.raw)
        for hand in changed["hands"]:
            for action in hand["actions"]:
                action["added"] = -999999
        replayed = build_pending(changed)["records_pending_review"]
        self.assertEqual(self.records, replayed)
        for row in replayed:
            obs = Observation.from_dict(row["state"])
            self.assertNotIn("expected", row["state"])
            self.assertNotIn("opponent_hole_cards", row["state"])
            self.assertEqual(len(obs.board), {"preflop": 0, "flop": 3, "turn": 4, "river": 5}[obs.street])


if __name__ == "__main__":
    unittest.main()
