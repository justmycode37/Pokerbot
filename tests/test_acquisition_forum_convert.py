from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts import acquisition_forum_convert as forum_convert


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/acquisition_sprint_1h/online_forum/records.jsonl"
BASELINE = ROOT / "data/corpus_splits/development-after-prospective-v1.json"


def _records() -> list[dict]:
    return [json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines() if line.strip()]


class ForumConversionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.records = _records()
        cls.known = next(record for record in cls.records
                         if record["record_id"] == "2P2-20080427-6204278652")
        cls.unknown = next(record for record in cls.records
                           if record["record_id"] == "2P2-20080427-6204248501")

    def process(self, record: dict, output: Path) -> dict:
        return forum_convert._process_fulltilt_record(
            record,
            str(record["hand_id"]),
            forum_convert._sha_text(record["raw_source_text"]),
            output,
            forum_convert._baseline_observations(BASELINE),
        )

    def test_actual_source_history_replays_with_exact_cents_and_terminal_facts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = self.process(self.known, Path(temporary) / "normalized")

        self.assertEqual(result["status"], "replayed_pending_independent_review")
        self.assertEqual(result["strict_replay_report"]["files_included"], 1)
        self.assertEqual(result["terminal_facts"]["chip_ticks_per_currency_unit"], 100)
        self.assertEqual(result["terminal_facts"]["source_total_pot_currency"], "138997")
        self.assertEqual(result["terminal_facts"]["source_rake_currency"], "0.50")
        self.assertEqual(result["terminal_facts"]["replayed_gross_pot_ticks"], 13_899_700)
        self.assertEqual(result["terminal_facts"]["source_awards_plus_rake_check"],
                         "summary_awards_match_total_pot_plus_rake")
        self.assertEqual(len(result["candidate_decisions"]), 3)

        first = result["candidate_decisions"][0]
        self.assertEqual(first["expected"], {"action": "raise", "amount": 900_000})
        self.assertEqual(first["observations"]["stack"], 6_849_850)
        self.assertEqual(first["source_url"], self.known["source"]["url"])
        self.assertEqual(first["source_record_id"], self.known["record_id"])
        self.assertEqual(first["raw_extract_sha256"], forum_convert._sha_text(self.known["raw_source_text"]))
        self.assertEqual(first["source_evidence"]["raw_source_text"], self.known["raw_source_text"])
        self.assertEqual(first["source_evidence"]["classification"], self.known["classification"])

    def test_unknown_hero_cards_replay_but_emit_no_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = self.process(self.unknown, Path(temporary) / "normalized")

        self.assertEqual(result["status"], "replayed_no_known_hero_decisions")
        self.assertEqual(result["strict_replay_report"]["files_excluded"], 1)
        self.assertEqual(result["strict_replay_report"]["exclusions"]["file:no_usable_ivey_decisions"], 1)
        self.assertGreater(result["strict_replay_report"]["decisions_excluded"], 0)
        self.assertEqual(result["candidate_decisions"], [])

    def test_rake_precision_extends_integer_unit_without_truncation(self) -> None:
        record = next(row for row in self.records if row["record_id"] == "2P2-5257208324")
        with tempfile.TemporaryDirectory() as temporary:
            result = self.process(record, Path(temporary) / "normalized")

        facts = result["terminal_facts"]
        self.assertEqual(facts["replay_chip_ticks_per_currency_unit"], 1)
        self.assertEqual(facts["chip_ticks_per_currency_unit"], 100)
        self.assertEqual(facts["replay_to_money_scale_factor"], 100)
        self.assertEqual(facts["source_rake_currency"], "0.50")
        self.assertEqual(facts["source_awards_plus_rake_check"],
                         "summary_awards_match_total_pot_plus_rake")
        self.assertTrue(result["candidate_decisions"])
        for decision in result["candidate_decisions"]:
            self.assertEqual(decision["chip_ticks_per_currency_unit"], 100)
            self.assertEqual(decision["observations"]["stack"] % 100, 0)
            if decision["expected"]["action"] == "raise":
                self.assertEqual(decision["expected"]["amount"] % 100, 0)

    def test_unmatched_return_is_subtracted_when_terminal_fold_awards_the_pot(self) -> None:
        record = next(row for row in self.records if row["record_id"] == "2P2-9326810433")
        with tempfile.TemporaryDirectory() as temporary:
            result = self.process(record, Path(temporary) / "normalized")

        self.assertEqual(result["status"], "replayed_no_known_hero_decisions")
        self.assertEqual(result["terminal_facts"]["source_total_pot_currency"], "22000")
        self.assertEqual(result["terminal_facts"]["replayed_gross_pot_ticks"], 2_200_000)
        self.assertEqual(result["terminal_facts"]["source_rake_currency"], "0")

    def test_preaction_boundaries_keep_current_label_and_future_facts_out_of_observation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            decisions = self.process(self.known, Path(temporary) / "normalized")["candidate_decisions"]

        first, flop_bet, flop_call = decisions
        self.assertEqual(first["strict_action_prefix_identity"]["action_index"], 3)
        self.assertEqual(first["observations"]["board"], [])
        self.assertEqual(first["observations"]["history"][-1]["player"], "p1")
        self.assertEqual(first["expected"], {"action": "raise", "amount": 900_000})

        self.assertEqual(flop_bet["strict_action_prefix_identity"]["action_index"], 6)
        self.assertEqual(flop_bet["observations"]["board"], ["5s", "6d", "7h"])
        self.assertEqual(flop_bet["expected"], {"action": "raise", "amount": 1_300_000})
        self.assertEqual(flop_call["observations"]["board"], ["5s", "6d", "7h"])
        self.assertEqual(flop_call["expected"], {"action": "call"})

        for decision in decisions:
            observation = decision["observations"]
            serialized = json.dumps(observation)
            self.assertNotIn('"Ad"', serialized)
            self.assertNotIn('"As"', serialized)
            self.assertNotIn('"Ts"', serialized)
            self.assertNotIn('"3d"', serialized)
            self.assertNotIn("expected", observation)
            self.assertNotIn("source_action_index", observation)
            self.assertIn("prefix_actions_sha256", decision["strict_action_prefix_identity"])

    def test_exact_identity_copies_deduplicate_and_conflicting_copies_fail_closed(self) -> None:
        duplicate = copy.deepcopy(self.known)
        duplicate["record_id"] = "forum-alias-copy"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "duplicate.jsonl"
            input_path.write_text("\n".join(json.dumps(row) for row in (self.known, duplicate)) + "\n")
            result = forum_convert.convert(input_path, root / "dedup", BASELINE)
        self.assertEqual(result["counts"]["unique_fulltilt_hand_ids"], 1)
        self.assertEqual(result["counts"]["duplicate_exact_hand_aliases_removed"], 1)
        self.assertEqual(result["counts"]["unique_replayable_known_card_decisions"], 3)
        self.assertEqual(len(result["records"]), 3)
        self.assertEqual(len(result["records"][0]["source_aliases"]), 1)

        conflicting = copy.deepcopy(self.known)
        conflicting["record_id"] = "forum-conflict-copy"
        conflicting["raw_source_text"] = conflicting["raw_source_text"].replace(
            "Phil Ivey raises to $9,000", "Phil Ivey raises to $9,100", 1)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "conflict.jsonl"
            input_path.write_text("\n".join(json.dumps(row) for row in (self.known, conflicting)) + "\n")
            result = forum_convert.convert(input_path, root / "conflict-out", BASELINE)
        self.assertEqual(result["counts"]["conflicting_payload_identities_excluded"], 1)
        self.assertEqual(result["records"], [])
        self.assertIn("conflicting_source_payloads_for_exact_fulltilt_hand_id",
                      {item.get("reason") for item in result["rejections"]})

    def test_saved_batch_source_counts_include_converted_histories_as_pending(self) -> None:
        record_count = len(self.records)
        exact_ids = {forum_convert._exact_fulltilt_id(record) for record in self.records}
        known_complete = [record for record in self.records
                          if record["classification"].get("complete_candidate") is True
                          and forum_convert._known_hero_cards(record) is not None
                          and "conflict" not in str(record["classification"].get("card_consistency", "")).casefold()]
        self.assertEqual(record_count, 71)
        self.assertEqual(len(exact_ids - {None}), 57)
        self.assertEqual(len(known_complete), 43)
        self.assertEqual(sum(forum_convert._exact_fulltilt_id(record) is None
                             for record in known_complete), 12)


if __name__ == "__main__":
    unittest.main()
