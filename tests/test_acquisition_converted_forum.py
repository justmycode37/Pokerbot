import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import acquisition_converted_forum as converted


class ConvertedForumAcquisitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_rows, cls.old_hash = converted._load_jsonl(converted.OLD_INPUT)
        cls.mid_rows, cls.mid_hash = converted._load_jsonl(converted.MID_INPUT)
        cls.plus_rows, cls.plus_hash = converted._load_jsonl(converted.PLUS_INPUT)
        cls.new_plus_rows, cls.new_plus_hash = converted._load_jsonl(converted.NEW_PLUS_INPUT)
        cls.identity_basis = json.loads(converted.IDENTITY_BASIS.read_text(encoding="utf-8"))

    @staticmethod
    def _record(rows, record_id):
        return next(row for row in rows if row.get("record_id") == record_id)

    def _convert(self, kind, rows, record_id):
        record = self._record(rows, record_id)
        with tempfile.TemporaryDirectory(prefix="converted-forum-test-") as temporary:
            report = converted._convert_one(
                kind, record, self.identity_basis, Path(temporary) / "normalized_phh")
        return report

    def test_registered_inputs_and_admission_counts_are_exact(self):
        hashes, _ = converted._verify_registered_inputs(
            converted.MID_INPUT, converted.NEW_PLUS_INPUT, converted.REGISTRATION)
        self.assertEqual(hashes, converted.REGISTERED_INPUTS)
        ledger = json.loads(converted.REGISTRATION.read_text(encoding="utf-8"))
        ledger_counts = {entry["path"]: entry["counts"] for entry in ledger["batches"]}
        self.assertEqual(ledger_counts[
            "data/acquisition_resume/2026-11-02/forum_2009_2011/records.jsonl"]
            ["hero_action_events_known_card_source_rows"], 26)
        self.assertEqual(ledger_counts[
            "data/acquisition_resume/2026-11-02/forum_2012_plus/rawrecords.jsonl"]
            ["known_card_hero_action_events"], 5)
        selected, counts, not_selected = converted._eligible_records([
            ("original", self.old_rows),
            ("forum_2009_2011", self.mid_rows),
            ("forum_2012_plus_2026_11_01", self.plus_rows),
            ("forum_2012_plus_2026_11_02", self.new_plus_rows),
        ])
        self.assertEqual(counts["original_converted_rows"], 14)
        self.assertEqual(counts["original_converted_known_card_complete_after_conflict_filter"], 12)
        self.assertEqual(counts["forum_2009_2011_converted_rows"], 10)
        self.assertEqual(counts["forum_2009_2011_known_card_complete"], 7)
        self.assertEqual(counts["forum_2012_plus_2026_11_02_converted_rows"], 2)
        self.assertEqual(counts["forum_2012_plus_2026_11_02_known_card_complete"], 1)
        excluded = {row["source_record_id"]: row["reason"] for row in not_selected}
        self.assertEqual(excluded["2P2-20130919-post1811"], "source_hero_cards_not_known")
        self.assertEqual(sum(row[0] == "forum_2009_2011" for row in selected), 7)

    def test_real_2009_history_replays_with_source_locators_and_no_future_cards(self):
        report = self._convert("forum_2009_2011", self.mid_rows,
                               "2P2-2009-post1754-converted")
        self.assertEqual(len(report["candidate_decisions"]), 4)
        self.assertEqual(report["candidate_decisions"][0]["expected"],
                         {"action": "raise", "amount": 400000})
        self.assertEqual(report["candidate_decisions"][0]["observations"]["board"], [])
        self.assertEqual(report["candidate_decisions"][0]["observations"]["hole_cards"], ["Kd", "Qd"])
        for row in report["candidate_decisions"]:
            observation = row["observations"]
            self.assertEqual(len(observation["board"]), {"preflop": 0, "flop": 3,
                                                          "turn": 4, "river": 5}[observation["street"]])
            self.assertIn("raw_line", row["strict_action_prefix_identity"]["source_action_locator"])
            self.assertIn("canonical_action_key",
                          row["strict_action_prefix_identity"]["source_action_locator"])
            self.assertNotIn("FullTiltID:", row["canonical_hand_id"])
            self.assertTrue(row["strict_action_prefix_identity"]["prefix_actions_sha256"])
        self.assertTrue(report["candidate_decisions"][0]["inspected_label_no_fresh_holdout_claim"])

    def test_new_2012_source_image_cards_alias_and_pending_terminal_accounting(self):
        report = self._convert("forum_2012_plus_2026_11_02", self.new_plus_rows,
                               "2P2-20130919-post1808")
        self.assertEqual(len(report["candidate_decisions"]), 5)
        self.assertEqual(report["candidate_decisions"][-1]["observations"]["to_call"], 4407700)
        self.assertEqual(report["candidate_decisions"][-1]["observations"]["hole_cards"], ["9h", "9c"])
        self.assertEqual(report["candidate_decisions"][-1]["observations"]["board"],
                         ["Ac", "3d", "5s", "9d", "4h"])
        self.assertEqual(report["terminal_facts"]["accounting_status"],
                         "pending_source_terminal_accounting_not_reported")
        self.assertEqual(report["candidate_decisions"][0]["source_alias_identity"]["source_alias"],
                         "Polarizing")
        shown = report["source_shown_cards_at_showdown"]
        opponent_cards = {card for item in shown if item["player"] != "Phil Ivey"
                          for card in item["cards"]}
        for row in report["candidate_decisions"]:
            self.assertTrue(opponent_cards.isdisjoint(row["observations"]["hole_cards"]))
            self.assertTrue(opponent_cards.isdisjoint(row["observations"]["board"]))
            self.assertEqual(row["admission_status"], "pending_independent_review_and_terminal_accounting")

    def test_full_fact_identity_deduplicates_copy_without_using_record_id(self):
        source = self._record(self.mid_rows, "2P2-2009-post1754-converted")
        copied = copy.deepcopy(source)
        copied["record_id"] = "copied-source-row-id"
        with tempfile.TemporaryDirectory(prefix="converted-forum-dedupe-") as temporary:
            first = converted._convert_one("forum_2009_2011", source, self.identity_basis,
                                           Path(temporary) / "a")
            second = converted._convert_one("forum_2009_2011", copied, self.identity_basis,
                                            Path(temporary) / "b")
        self.assertEqual(first["canonical_hand_id"], second["canonical_hand_id"])
        self.assertTrue(first["canonical_hand_id"].startswith("converted-forum:facts:"))
        self.assertNotIn(source["record_id"], first["canonical_hand_id"])

    def test_all_in_runout_and_unknown_cards_remain_excluded_with_reasons(self):
        runout = self._record(self.mid_rows, "2P2-2009-post1759-converted")
        with tempfile.TemporaryDirectory(prefix="converted-forum-negative-") as temporary:
            with self.assertRaisesRegex(converted.RejectHand,
                                        "unsupported_single_remaining_stack_runout_semantics"):
                converted._convert_one("forum_2009_2011", runout, self.identity_basis,
                                       Path(temporary) / "normalized_phh")
        row = self._record(self.new_plus_rows, "2P2-20130919-post1811")
        with self.assertRaisesRegex(converted.RejectHand, "source_hero_cards_not_known"):
            converted._source_cards(row, "Polarizing", list(row["seats"]))


if __name__ == "__main__":
    unittest.main()
