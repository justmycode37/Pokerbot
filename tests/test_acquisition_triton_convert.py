"""Regression checks for source-backed Triton conversion boundaries.

The positive path uses the saved official sample response. Synthetic
source-shaped fixtures are confined to tests that need a state not present in
that sample; they are never stored as candidate or corpus rows.
"""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from scripts import acquisition_triton_convert as triton_convert


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PATH = ROOT / "data/acquisition_sprint_1h/triton_public/sample-final-table.json"
HERO_UUID = "3970ce21-3d14-4bdc-97ca-98df8220d040"
KNOWN_SAMPLE_UUID = "485c77c7-8ff8-4a55-922c-09b8883819dc"


def find_keys(value: Any, wanted: set[str]) -> set[str]:
    """Collect keys recursively without relying on converter internals."""
    found: set[str] = set()
    if isinstance(value, dict):
        found.update(wanted.intersection(value))
        for child in value.values():
            found.update(find_keys(child, wanted))
    elif isinstance(value, list):
        for child in value:
            found.update(find_keys(child, wanted))
    return found


class TritonConverterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with SAMPLE_PATH.open(encoding="utf-8") as source:
            cls.sample_document = json.load(source)
        cls.sample_hands = cls.sample_document["data"]["game"]["hands"]
        cls.known_hand = next(hand for hand in cls.sample_hands
                              if hand["handId"] == KNOWN_SAMPLE_UUID)

    def convert_documents(self, *documents: Any,
                          session_id: str | None = "test-session") -> dict[str, Any]:
        """Run the public file converter against isolated temporary inputs."""
        with tempfile.TemporaryDirectory(prefix="triton-convert-test-") as temp_dir:
            root = Path(temp_dir)
            sources = []
            for index, document in enumerate(documents):
                source = root / f"source-{index}.json"
                source.write_text(json.dumps(document), encoding="utf-8")
                sources.append(source)
            output = root / "candidates.json"
            result = triton_convert.convert(sources, output, session_id=session_id)
            # Read the serialized report as well as the returned mapping so
            # the CLI-facing artifact is covered by these cases.
            return json.loads(output.read_text(encoding="utf-8"))

    def convert_document(self, document: Any,
                         *, session_id: str | None = "test-session") -> dict[str, Any]:
        return self.convert_documents(document, session_id=session_id)

    def test_saved_real_sample_yields_only_one_pending_decision(self) -> None:
        result = self.convert_document(self.sample_document, session_id=None)

        self.assertEqual(result["counts"]["raw_hand_records_found"], 19)
        self.assertEqual(result["counts"]["ivey_decisions_seen"], 7)
        self.assertEqual(result["counts"]["validated_candidate_decisions"], 1)
        self.assertEqual(result["counts"]["newly_admitted_decisions"], 0)
        self.assertEqual(len(result["records"]), 1)
        record = result["records"][0]
        self.assertEqual(record["admission_status"],
                         "pending_independent_source_and_conversion_review")
        self.assertEqual(record["state"]["hole_cards"], ["9h", "9c"])
        self.assertEqual(record["expected"], {"action": "raise", "amount": 3_300_000})
        source_action = self.known_hand["rounds"][0]["actions"][record["source_action_index"]]
        self.assertEqual(source_action["type"], "all_in")

    def test_missing_or_empty_hero_cards_never_emit_decisions(self) -> None:
        for card_field in ("missing", "empty", "null"):
            with self.subTest(card_field=card_field):
                hand = copy.deepcopy(self.known_hand)
                hero = next(player for player in hand["players"]
                            if player["userId"] == HERO_UUID)
                if card_field == "missing":
                    hero.pop("pocketCards", None)
                elif card_field == "empty":
                    hero["pocketCards"] = []
                else:
                    hero["pocketCards"] = None

                result = self.convert_document([hand])
                self.assertEqual(result["records"], [])
                self.assertEqual(result["counts"]["ivey_decisions_seen"], 1)
                self.assertEqual(result["counts"]["validated_candidate_decisions"], 0)
                report = result["hand_reports"][0]
                self.assertFalse(report["hero_cards_known"])
                self.assertEqual(report["exclusion"], "hero_hole_cards_missing_at_decision")

    def test_identical_hand_uuid_is_counted_once(self) -> None:
        hand = copy.deepcopy(self.known_hand)
        result = self.convert_documents(hand, copy.deepcopy(hand))

        self.assertEqual(result["counts"]["raw_hand_records_found"], 2)
        self.assertEqual(result["counts"]["unique_hand_uuids"], 1)
        self.assertEqual(result["counts"]["duplicate_hand_payloads_removed"], 1)
        self.assertEqual(result["counts"]["validated_candidate_decisions"], 1)
        self.assertEqual(len(result["records"]), 1)

    def test_conflicting_variant_for_same_hand_uuid_fails_closed(self) -> None:
        original = copy.deepcopy(self.known_hand)
        conflicting_variant = copy.deepcopy(original)
        conflicting_variant["pokerVariant"] = "short_deck"

        result = self.convert_documents(original, conflicting_variant)

        self.assertEqual(result["records"], [])
        self.assertEqual(result["counts"]["conflicting_hand_uuids_excluded"], 1)
        self.assertEqual(result["counts"]["validated_candidate_decisions"], 0)
        self.assertIn("conflicting_duplicate_hand_uuid",
                      {rejection.get("reason") for rejection in result["rejections"]})

    def test_optional_chip_denomination_can_be_unknown_but_not_invalid(self) -> None:
        for mode in ("missing", "null"):
            with self.subTest(mode=mode):
                hand = copy.deepcopy(self.known_hand)
                if mode == "missing":
                    hand["blindLevel"].pop("minChip", None)
                else:
                    hand["blindLevel"]["minChip"] = None
                result = self.convert_document([hand])
                self.assertEqual(result["counts"]["validated_candidate_decisions"], 1)
                self.assertEqual(result["records"][0]["expected"],
                                 {"action": "raise", "amount": 3_300_000})
        for invalid in (0, -1, True, "25000"):
            with self.subTest(invalid=invalid):
                hand = copy.deepcopy(self.known_hand)
                hand["blindLevel"]["minChip"] = invalid
                result = self.convert_document([hand])
                self.assertEqual(result["records"], [])
                self.assertEqual(result["hand_reports"][0]["rejection"], "invalid_min_chip")

    def test_incremental_raise_adds_to_hero_blind_before_emitting_raise_to(self) -> None:
        # A small, source-shaped three-player orbit isolates the amount rule:
        # Ivey posts 50, then adds 950 on a raise. The completed street total
        # is 1,000; the raw source raise remains the incremental 950.
        hand = {
            "handId": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "pokerVariant": "texas",
            "noOfRuns": 1,
            "noOfSeats": 4,
            "blindLevel": {"smallBlind": 50, "bigBlind": 100, "minChip": 50},
            "dealerSeatNo": 4,
            "tournamentId": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "players": [
                {"userId": HERO_UUID, "seatNo": 1, "startChips": 1000,
                 "endChips": 1100, "user": {"uuid": HERO_UUID},
                 "pocketCards": ["CARD_9H", "CARD_9C"]},
                {"userId": "bb-player", "seatNo": 2, "startChips": 1000,
                 "endChips": 900, "user": {"uuid": "bb-player"}},
                {"userId": "button-player", "seatNo": 4, "startChips": 1000,
                 "endChips": 1000, "user": {"uuid": "button-player"}},
            ],
            "rounds": [{"name": "pre_flop", "actions": [
                {"timestamp": 1, "userId": HERO_UUID, "type": "small_blind", "amount": 50},
                {"timestamp": 2, "userId": "bb-player", "type": "big_blind", "amount": 100},
                {"timestamp": 3, "userId": "button-player", "type": "fold"},
                {"timestamp": 4, "userId": HERO_UUID, "type": "raise", "amount": 950},
                {"timestamp": 5, "userId": "bb-player", "type": "fold"},
            ]}],
            "pots": [
                {"totalAmount": 200,
                 "potPlayers": [{"userId": HERO_UUID, "amount": 100},
                                {"userId": "bb-player", "amount": 100}],
                 "hi": {"totalAmount": 200, "sidePlayers": [
                     {"userId": HERO_UUID, "amount": 100, "isWinner": True,
                      "winAmount": 200},
                     {"userId": "bb-player", "amount": 100, "isWinner": False,
                      "winAmount": 0},
                 ]}},
                {"totalAmount": 900,
                 "potPlayers": [{"userId": HERO_UUID, "amount": 900}],
                 "hi": {"totalAmount": 900, "sidePlayers": [
                     {"userId": HERO_UUID, "amount": 900, "isWinner": True,
                      "winAmount": 900},
                 ]}},
            ],
        }

        result = self.convert_document([hand])

        self.assertEqual(result["counts"]["validated_candidate_decisions"], 1)
        record = result["records"][0]
        self.assertEqual(record["state"]["current_bet"], 50)
        self.assertEqual(record["state"]["stack"], 950)
        self.assertEqual(record["expected"], {"action": "raise", "amount": 1000})
        self.assertEqual(record["source_action_index"], 3)

    def test_pre_action_view_hides_current_label_future_cards_and_terminal_result(self) -> None:
        result = self.convert_document([self.known_hand])
        record = result["records"][0]
        state = record["state"]

        self.assertEqual(record["source_action_index"], 6)
        self.assertEqual(record["source_decision_id"],
                         f"triton:{KNOWN_SAMPLE_UUID}:action:6")
        self.assertEqual(state["board"], [])
        self.assertEqual(state["hole_cards"], ["9h", "9c"])
        self.assertNotIn("all_in", {item["action"] for item in state["history"]})
        self.assertNotIn(state["player_id"], {item["player"] for item in state["history"]})
        # The source reveals J♠ J♦ at showdown; neither opponent cards nor
        # later street cards belong in the predecision observation.
        observation_text = json.dumps(state).lower()
        self.assertNotIn("js", observation_text)
        self.assertNotIn("jd", observation_text)
        self.assertFalse(find_keys(state, {
            "pots", "payout", "winAmount", "isWinner", "terminal", "showdown",
            "source_action_index", "expected",
        }))

    def test_malformed_terminal_award_is_rejected(self) -> None:
        hand = copy.deepcopy(self.known_hand)
        hand["pots"][0]["hi"]["sidePlayers"][0]["winAmount"] += 1

        result = self.convert_document([hand])

        self.assertEqual(result["records"], [])
        self.assertEqual(result["counts"]["hands_rejected"], 1)
        self.assertEqual(result["counts"]["validated_candidate_decisions"], 0)
        self.assertEqual(result["hand_reports"][0]["rejection"],
                         "terminal_pot_awards_do_not_sum_to_total")

    def test_physical_capacity_does_not_create_empty_player_seats(self) -> None:
        result = self.convert_document([self.known_hand])
        record = result["records"][0]

        self.assertEqual(record["source_physical_capacity"], 9)
        self.assertEqual(record["source_actual_player_count"], 7)
        self.assertEqual(record["state"]["table_size"], 7)
        self.assertLess(record["state"]["table_size"], record["source_physical_capacity"])

    def test_flop_card_reveal_positions_need_not_be_time_sorted(self) -> None:
        source = ROOT / (
            "data/acquisition_resume/2026-11-01/triton_2026/raw/hands/"
            "2d41c50f-b038-4e92-8b2c-43ca82cec126.json")
        hand = json.loads(source.read_text())["data"]["handV2"]
        flop = hand["rounds"][1]
        self.assertNotEqual(flop["communityCardTimestamps"],
                            sorted(flop["communityCardTimestamps"]))
        self.assertLess(max(flop["communityCardTimestamps"]),
                        flop["actions"][0]["timestamp"])
        result = self.convert_document([hand])
        self.assertGreater(result["counts"]["validated_candidate_decisions"], 0)

        invalid = copy.deepcopy(hand)
        invalid_flop = invalid["rounds"][1]
        invalid_flop["communityCardTimestamps"][0] = invalid_flop["actions"][0]["timestamp"] + 1
        result = self.convert_document([invalid])
        self.assertEqual(result["records"], [])
        self.assertEqual(result["hand_reports"][0]["rejection"],
                         "action_precedes_public_board_reveal")


if __name__ == "__main__":
    unittest.main()
