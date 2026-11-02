"""Regression tests for integrated heads-up and provenance conversion.

Controlled HU engine states are test fixtures only; tests never write candidate
rows outside isolated temporary directories.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from typing import Any


FIXES_DIR = Path(__file__).resolve().parent
ROOT = FIXES_DIR.parent
sys.path.insert(0, str(ROOT))

FIXED_CONVERTER_PATH = ROOT / "scripts/acquisition_triton_convert.py"
spec = importlib.util.spec_from_file_location("fixed_acquisition_triton_convert",
                                              FIXED_CONVERTER_PATH)
assert spec is not None and spec.loader is not None
triton_convert = importlib.util.module_from_spec(spec)
spec.loader.exec_module(triton_convert)
# The private copy lives below data/, so point its read-only source root back
# at the shared checkout. No project file is imported through the wrong path.
triton_convert.ROOT = ROOT


HERO_UUID = "3970ce21-3d14-4bdc-97ca-98df8220d040"
POSITIVE_CAPTURE = ROOT / (
    "data/acquisition_resume/2026-11-01/triton_2026/raw/hands/"
    "020feecc-0093-4fb8-a809-9be768f821b8.json")
NEGATIVE_CAPTURE = ROOT / (
    "data/acquisition_resume/2026-11-01/triton_2023_2024/raw/episodes/"
    "04163006-dee0-4abe-82b8-a5807d40ff2e/hands/"
    "32c3cc8a-fb62-43e3-ad25-64c2c2dc0bd0.GetHand.json")
MULTISTREET_CAPTURE = ROOT / (
    "data/acquisition_resume/2026-11-01/triton_2026/raw/hands/"
    "65a33886-e2fd-47a5-9a96-cb7081b909cb.json")
UNSORTED_FLOP_CAPTURE = ROOT / (
    "data/acquisition_resume/2026-11-01/triton_2026/raw/hands/"
    "2d41c50f-b038-4e92-8b2c-43ca82cec126.json")
EXISTING_47 = ROOT / (
    "data/acquisition_resume/2026-11-01/triton_2026_conversion/batch-003/"
    "candidates-with-provenance.json")
TRITON_2026_MANIFEST = ROOT / "data/acquisition_resume/2026-11-01/triton_2026/manifest.json"
TRITON_2026_SUMMARY = ROOT / (
    "data/acquisition_resume/2026-11-01/triton_2026_conversion/batch-003/summary.json")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_hand(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return next(iter(triton_convert._find_hands(value)))[0]


class TritonConverterFixTests(unittest.TestCase):
    def convert_paths(self, paths: list[Path], *, session_id: str = "converter-fix-test"
                      ) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="triton-fix-output-", dir=FIXES_DIR) as temp:
            output = Path(temp) / "candidates.json"
            return triton_convert.convert(paths, output, session_id=session_id)

    def convert_document(self, document: Any, *, session_id: str = "converter-fix-test"
                        ) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="triton-fix-input-", dir=FIXES_DIR) as temp:
            source = Path(temp) / "capture.json"
            source.write_text(json.dumps(document), encoding="utf-8")
            return self.convert_paths([source], session_id=session_id)

    def test_cached_positive_row_has_exact_response_and_request_provenance(self) -> None:
        self.assertTrue(POSITIVE_CAPTURE.is_file())
        request_path = POSITIVE_CAPTURE.with_suffix(".request.json")
        request_bytes = request_path.read_bytes()
        request = json.loads(request_bytes)

        result = self.convert_paths([POSITIVE_CAPTURE])

        self.assertEqual(result["counts"]["validated_candidate_decisions"], 1)
        self.assertEqual(result["counts"]["newly_admitted_decisions"], 0)
        self.assertEqual(result["counts"]["known_card_ivey_decisions"], 1)
        self.assertEqual(result["counts"]["unknown_card_ivey_decisions"], 0)
        row = result["records"][0]
        capture_bytes = POSITIVE_CAPTURE.read_bytes()
        self.assertEqual(row["source_capture_path"], str(POSITIVE_CAPTURE.resolve()))
        self.assertEqual(row["source_capture_sha256"], sha256(capture_bytes))
        self.assertEqual(row["source_payload_sha256"],
                         triton_convert._sha256(triton_convert._canonical_json(read_hand(POSITIVE_CAPTURE))))
        self.assertNotEqual(row["source_capture_sha256"], row["source_payload_sha256"])
        self.assertEqual(row["source_request_path"], str(request_path.resolve()))
        self.assertEqual(row["source_request_sha256"], sha256(request_bytes))
        self.assertEqual(row["source_request_operation_name"], request["operationName"])
        self.assertEqual(row["source_request_variables"], request["variables"])
        self.assertEqual(row["source_request_query"], request["query"])
        self.assertEqual(row["source_query_sha256"], sha256(request["query"].encode("utf-8")))
        self.assertEqual(row["source_request_episode_id"], request["variables"].get("episodeId"))
        self.assertFalse({"source_capture_path", "source_capture_sha256",
                          "source_request_query", "stable_source_decision_key"}
                         & set(row["state"]))

    def test_cached_negative_unknown_card_hand_is_not_a_candidate(self) -> None:
        self.assertTrue(NEGATIVE_CAPTURE.is_file())

        result = self.convert_paths([NEGATIVE_CAPTURE])

        self.assertEqual(result["records"], [])
        self.assertEqual(result["counts"]["validated_candidate_decisions"], 0)
        self.assertEqual(result["counts"]["newly_admitted_decisions"], 0)
        self.assertEqual(result["counts"]["known_card_ivey_decisions"], 0)
        self.assertEqual(result["counts"]["unknown_card_ivey_decisions"], 1)
        report = result["hand_reports"][0]
        self.assertFalse(report["hero_cards_known"])
        self.assertEqual(report["exclusion"], "hero_hole_cards_missing_at_decision")
        self.assertEqual(report["source_capture_sha256"], sha256(NEGATIVE_CAPTURE.read_bytes()))
        self.assertEqual(report["source_request_sha256"],
                         sha256(NEGATIVE_CAPTURE.with_suffix(".request.json").read_bytes()))

    def test_missing_request_sidecar_stays_unknown(self) -> None:
        raw = POSITIVE_CAPTURE.read_bytes()
        document = json.loads(raw)
        with tempfile.TemporaryDirectory(prefix="triton-no-request-", dir=FIXES_DIR) as temp:
            capture = Path(temp) / "without-request.json"
            capture.write_bytes(raw)
            result = self.convert_paths([capture])

        row = result["records"][0]
        self.assertEqual(row["source_capture_sha256"], sha256(raw))
        self.assertIsNone(row["source_request_path"])
        self.assertIsNone(row["source_request_sha256"])
        self.assertIsNone(row["source_request_operation_name"])
        self.assertIsNone(row["source_request_variables"])
        self.assertIsNone(row["source_request_query"])
        self.assertIsNone(row["source_request_episode_id"])
        self.assertEqual(document["data"]["handV2"]["handId"], row["hand_id"].removeprefix("triton:"))

    def test_request_hand_id_must_match_the_cached_hand(self) -> None:
        raw = POSITIVE_CAPTURE.read_bytes()
        hand_id = read_hand(POSITIVE_CAPTURE)["handId"]
        with tempfile.TemporaryDirectory(prefix="triton-mismatched-request-", dir=FIXES_DIR) as temp:
            capture = Path(temp) / "capture.json"
            capture.write_bytes(raw)
            request = {
                "operationName": "GetHand",
                "variables": {"handId": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"},
                "query": "query GetHand($handId: String!) { handV2(handId: $handId) { handId } }",
            }
            capture.with_suffix(".request.json").write_text(
                json.dumps(request), encoding="utf-8")
            result = self.convert_paths([capture])

        self.assertEqual(result["records"], [])
        self.assertEqual(result["hand_reports"][0]["source_hand_uuid"], hand_id)
        self.assertEqual(result["hand_reports"][0]["rejection"],
                         "source_request_hand_uuid_mismatch")

    def test_null_request_hand_id_is_retained_as_unknown(self) -> None:
        raw = POSITIVE_CAPTURE.read_bytes()
        with tempfile.TemporaryDirectory(prefix="triton-null-request-id-", dir=FIXES_DIR) as temp:
            capture = Path(temp) / "capture.json"
            capture.write_bytes(raw)
            request = {
                "operationName": "GetHand",
                "variables": {"handId": None},
                "query": "query GetHand($handId: String) { handV2(handId: $handId) { handId } }",
            }
            capture.with_suffix(".request.json").write_text(
                json.dumps(request), encoding="utf-8")
            result = self.convert_paths([capture])

        self.assertEqual(result["counts"]["validated_candidate_decisions"], 1)
        self.assertIsNone(result["records"][0]["source_request_variables"]["handId"])

    def test_optional_null_min_chip_and_max_flop_reveal_cutoff_are_preserved(self) -> None:
        for mode in ("missing", "null"):
            with self.subTest(min_chip=mode):
                hand = copy.deepcopy(read_hand(POSITIVE_CAPTURE))
                if mode == "missing":
                    hand["blindLevel"].pop("minChip", None)
                else:
                    hand["blindLevel"]["minChip"] = None
                result = self.convert_document([hand])
                self.assertEqual(result["counts"]["validated_candidate_decisions"], 1)

        hand = copy.deepcopy(read_hand(UNSORTED_FLOP_CAPTURE))
        flop = hand["rounds"][1]
        self.assertNotEqual(flop["communityCardTimestamps"],
                            sorted(flop["communityCardTimestamps"]))
        self.assertLess(max(flop["communityCardTimestamps"]),
                        flop["actions"][0]["timestamp"])
        result = self.convert_document([hand])
        self.assertGreater(result["counts"]["validated_candidate_decisions"], 0)

        invalid = copy.deepcopy(hand)
        invalid_flop = invalid["rounds"][1]
        invalid_flop["communityCardTimestamps"][0] = (
            invalid_flop["actions"][0]["timestamp"] + 1)
        result = self.convert_document([invalid])
        self.assertEqual(result["records"], [])
        self.assertEqual(result["hand_reports"][0]["rejection"],
                         "action_precedes_public_board_reveal")

    def test_multistreet_original_positions_preserve_tied_timestamp_order(self) -> None:
        hand = copy.deepcopy(read_hand(MULTISTREET_CAPTURE))
        for round_row in hand["rounds"]:
            if round_row["name"].lower() == "flop":
                round_row["communityCardTimestamps"] = [2_000_000_000] * 3
            for action in round_row["actions"]:
                action["timestamp"] = 2_000_000_000

        result = self.convert_document([hand])

        self.assertEqual(result["counts"]["validated_candidate_decisions"], 2)
        rows = result["records"]
        self.assertEqual([(r["source_round_index"], r["source_round_action_index"],
                           r["source_action_index"]) for r in rows], [(0, 10, 10), (1, 1, 12)])
        for row in rows:
            ri = row["source_round_index"]
            ai = row["source_round_action_index"]
            raw_action = hand["rounds"][ri]["actions"][ai]
            expected_flat = ai + sum(len(r["actions"]) for r in hand["rounds"][:ri])
            self.assertEqual(row["source_action_index"], expected_flat)
            self.assertEqual(row["source_decision_id"],
                             f"triton:{hand['handId']}:action:{expected_flat}")
            self.assertEqual(row["stable_source_decision_key"],
                             f"triton:{hand['handId']}:round:{ri}:action:{ai}")
            self.assertEqual(raw_action["userId"], HERO_UUID)
            self.assertEqual(raw_action["timestamp"], 2_000_000_000)
            self.assertEqual(row["source_request_path"], None)
        self.assertEqual(rows[0]["source_decision_id"],
                         "triton:65a33886-e2fd-47a5-9a96-cb7081b909cb:action:10")

    @staticmethod
    def heads_up_hand(hero_role: str) -> tuple[dict[str, Any], dict[str, str]]:
        sb_id = HERO_UUID if hero_role == "SB" else "villain-sb"
        bb_id = "villain-bb" if hero_role == "SB" else HERO_UUID
        sb_stack, bb_stack = 1_000, 1_800
        sb_ante, bb_ante = 20, 40
        sb_seat, bb_seat = 5, 2  # Intentionally not sorted by source array or seat.
        players = [
            {"userId": bb_id, "seatNo": bb_seat, "startChips": bb_stack,
             "endChips": bb_stack - bb_ante - 100 + 260,
             "user": {"uuid": bb_id},
             "pocketCards": ["CARD_9S", "CARD_9C"] if bb_id == HERO_UUID else []},
            {"userId": sb_id, "seatNo": sb_seat, "startChips": sb_stack,
             "endChips": sb_stack - sb_ante - 50 - 50,
             "user": {"uuid": sb_id},
             "pocketCards": ["CARD_9S", "CARD_9C"] if sb_id == HERO_UUID else []},
        ]
        hand = {
            "handId": "bbaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" if hero_role == "SB"
                      else "bbbaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "pokerVariant": "texas", "noOfRuns": 1, "noOfSeats": 6,
            "blindLevel": {"smallBlind": 50, "bigBlind": 100, "minChip": 50},
            "dealerSeatNo": sb_seat, "tournamentId": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            "players": players,
            "rounds": [
                {"name": "pre_flop", "actions": [
                    {"timestamp": 1, "userId": bb_id, "type": "ante", "amount": bb_ante},
                    {"timestamp": 2, "userId": sb_id, "type": "ante", "amount": sb_ante},
                    {"timestamp": 3, "userId": sb_id, "type": "small_blind", "amount": 50},
                    {"timestamp": 4, "userId": bb_id, "type": "big_blind", "amount": 100},
                    {"timestamp": 5, "userId": sb_id, "type": "call", "amount": 50},
                    {"timestamp": 6, "userId": bb_id, "type": "check"},
                ]},
                {"name": "flop", "communityCards": ["CARD_2C", "CARD_3D", "CARD_4H"],
                 "communityCardTimestamps": [7, 8, 9], "actions": [
                    {"timestamp": 10, "userId": bb_id, "type": "check"},
                    {"timestamp": 11, "userId": sb_id, "type": "check"},
                ]},
                {"name": "turn", "communityCard": "CARD_5S",
                 "communityCardTimestamp": 12, "actions": [
                    {"timestamp": 13, "userId": bb_id, "type": "check"},
                    {"timestamp": 14, "userId": sb_id, "type": "check"},
                ]},
                {"name": "river", "communityCard": "CARD_6C",
                 "communityCardTimestamp": 15, "actions": [
                    {"timestamp": 16, "userId": bb_id, "type": "check"},
                    {"timestamp": 17, "userId": sb_id, "type": "check"},
                ]},
            ],
            "pots": [{"totalAmount": 260,
                      "potPlayers": [{"userId": sb_id, "amount": 120},
                                     {"userId": bb_id, "amount": 140}],
                      "hi": {"totalAmount": 260, "sidePlayers": [
                          {"userId": sb_id, "amount": 120, "isWinner": False, "winAmount": 0},
                          {"userId": bb_id, "amount": 140, "isWinner": True, "winAmount": 260},
                      ]}}],
        }
        return hand, {"SB": sb_id, "BB": bb_id}

    def test_heads_up_mapping_matches_frozen_positions_for_both_hero_blinds(self) -> None:
        from pokerkit import Automation, Mode, NoLimitTexasHoldem
        from pokerbot.simulation import _positions

        automations = tuple(getattr(Automation, name) for name in (
            "ANTE_POSTING", "BET_COLLECTION", "BLIND_OR_STRADDLE_POSTING",
            "RUNOUT_COUNT_SELECTION", "HAND_KILLING", "CHIPS_PUSHING", "CHIPS_PULLING"))
        self.assertEqual(_positions(2), ["BB", "BTN"])
        for hero_role in ("SB", "BB"):
            with self.subTest(hero_role=hero_role):
                hand, roles = self.heads_up_hand(hero_role)
                prepared = triton_convert._prepare(hand, "heads-up-controlled-test-only")
                invalid_button = copy.deepcopy(hand)
                invalid_button["dealerSeatNo"] = 6  # Empty physical seat, not the SB/button.
                with self.assertRaisesRegex(
                        triton_convert.RejectHand, "heads_up_button_conflicts_with_explicit_blinds"):
                    triton_convert._prepare(invalid_button, "heads-up-controlled-test-only")
                self.assertEqual(prepared["ordered_ids"], [roles["BB"], roles["SB"]])
                self.assertEqual(prepared["starting"], [1_800, 1_000])
                # PokerKit raw HU antes and blinds follow forced posting order.
                self.assertEqual(prepared["antes"], [20, 40])
                self.assertEqual(prepared["blinds"], [50, 100])
                state = NoLimitTexasHoldem.create_state(
                    automations, False, prepared["antes"], prepared["blinds"],
                    prepared["big_blind"], prepared["starting"], 2, mode=Mode.CASH_GAME)
                for index, user_id in enumerate(prepared["ordered_ids"]):
                    cards = "9s9c" if user_id == HERO_UUID else "????"
                    state.deal_hole(cards, index)
                self.assertEqual(state.bets, [100, 50])
                self.assertEqual(state.stacks, [1_660, 930])
                self.assertEqual(state.actor_index, 1)
                self.assertEqual(prepared["ordered_ids"][state.actor_index], roles["SB"])
                self.assertEqual(_positions(2)[state.actor_index], "BTN")
                if hero_role == "SB":
                    self.assertEqual(prepared["ordered_ids"][state.actor_index], HERO_UUID)

                state.check_or_call()  # SB/button completes the preflop action.
                self.assertEqual(state.actor_index, 0)
                self.assertEqual(prepared["ordered_ids"][state.actor_index], roles["BB"])
                if hero_role == "BB":
                    self.assertEqual(prepared["ordered_ids"][state.actor_index], HERO_UUID)
                state.check_or_call()  # BB closes preflop.
                self.assertIsNone(state.actor_index)
                if state.can_burn_card():
                    state.burn_card("??")
                state.deal_board("2c3d4h")
                self.assertEqual(state.actor_index, 0)
                self.assertEqual(prepared["ordered_ids"][state.actor_index], roles["BB"])
                self.assertEqual(_positions(2)[state.actor_index], "BB")
                if hero_role == "BB":
                    self.assertEqual(prepared["ordered_ids"][state.actor_index], HERO_UUID)

                decisions, hand_report = triton_convert._convert_one(
                    hand, "heads-up-controlled-test-only")
                self.assertTrue(hand_report["replay"]["action_order_and_legal_transitions_verified"])
                self.assertEqual(len(decisions), 4)
                expected_position = "BTN" if hero_role == "SB" else "BB"
                expected_player = "p1" if hero_role == "SB" else "p0"
                self.assertTrue(all(row["state"]["position"] == expected_position
                                    for row in decisions))
                self.assertTrue(all(row["state"]["player_id"] == expected_player
                                    for row in decisions))
                self.assertEqual([row["source_round_index"] for row in decisions], [0, 1, 2, 3])
                self.assertEqual(decisions[0]["state"]["stack"],
                                 930 if hero_role == "SB" else 1_660)
                if hero_role == "SB":
                    for row in decisions[1:]:
                        self.assertEqual(row["state"]["history"][-1]["position"], "BB")
                        self.assertEqual(row["state"]["history"][-1]["player"], "p0")
                else:
                    self.assertEqual(decisions[0]["state"]["history"][-1]["position"], "BTN")
                    self.assertEqual(decisions[0]["state"]["history"][-1]["player"], "p1")

    def test_game_wrapper_request_without_hand_id_is_preserved_as_written(self) -> None:
        response_path = ROOT / (
            "data/acquisition_sprint_1h/triton_historical/"
            "38079fcb-7ae3-4662-9cbf-388c654b17dd/"
            "game-be2ea48e-589a-47ab-a4fa-9acc5bbb4b99.GetGameWithHands.json")
        request_path = response_path.with_suffix(".request.json")
        response = json.loads(response_path.read_text(encoding="utf-8"))
        request_bytes = request_path.read_bytes()
        request = json.loads(request_bytes)
        self.assertEqual(request["operationName"], "GetGameWithHands")
        self.assertNotIn("handId", request["variables"])
        self.assertIn("gameId", request["variables"])
        self.assertIn("handsSize", request["variables"])

        metadata = triton_convert._source_provenance(
            response_path, sha256(response_path.read_bytes()), "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")

        self.assertEqual(metadata["source_request_path"], str(request_path.resolve()))
        self.assertEqual(metadata["source_request_sha256"], sha256(request_bytes))
        self.assertEqual(metadata["source_request_operation_name"], request["operationName"])
        self.assertEqual(metadata["source_request_variables"], request["variables"])
        self.assertEqual(metadata["source_request_query"], request["query"])
        self.assertEqual(metadata["source_query_sha256"], sha256(request["query"].encode()))
        self.assertIsNone(metadata["source_request_episode_id"])
        self.assertIsInstance(response, dict)

    def test_converter_includes_big_blind_ante_in_reachable_pot(self) -> None:
        for hand_id in ("238da98b-1804-492f-9518-64cb73388dfd",
                        "7233ae8e-33b6-4786-a574-8623b63c849b"):
            with self.subTest(hand=hand_id):
                capture = ROOT / (
                    "data/acquisition_resume/2026-11-01/triton_2025/raw/"
                    "3bc7093a-05a7-41d1-82b4-b76f7a84107e/hands/" + hand_id + ".json")
                result = self.convert_paths([capture])
                self.assertEqual(result["counts"]["validated_candidate_decisions"], 1)
                row = result["records"][0]
                self.assertEqual(row["state"]["pot"], 375_000)
                self.assertEqual(row["state"]["contestable_pot"], 375_000)
                self.assertEqual(row["state"]["to_call"], 150_000)
                self.assertEqual(row["source_prefix_pot_check"]["dead_antes"], 150_000)
                self.assertNotIn("source_prefix_pot_check", row["state"])

    def test_independent_source_ledger_must_match_engine_prefix(self) -> None:
        derive = triton_convert.inspect_prefix_pot
        cases = (("pot", "source_prefix_pot_differs_from_engine"),
                 ("to_call", "source_prefix_call_differs_from_engine"),
                 ("stack", "source_prefix_stack_differs_from_engine"))
        for field, reason in cases:
            with self.subTest(field=field):
                def inconsistent(hand, ordinal, **kwargs):
                    prefix = derive(hand, ordinal, **kwargs)
                    if field == "stack":
                        prefix["evidence"]["remaining_stacks"][HERO_UUID] += 1
                    else:
                        prefix[field] += 1
                    return prefix
                with patch.object(triton_convert, "inspect_prefix_pot", inconsistent):
                    result = self.convert_paths([POSITIVE_CAPTURE])
                self.assertEqual(result["records"], [])
                self.assertEqual(result["hand_reports"][0]["rejection"], reason)

    def test_only_reviewed_ante_pots_change_existing_candidate_states(self) -> None:
        existing = json.loads(EXISTING_47.read_text(encoding="utf-8"))
        manifest = json.loads(TRITON_2026_MANIFEST.read_text(encoding="utf-8"))
        summary = json.loads(TRITON_2026_SUMMARY.read_text(encoding="utf-8"))
        inputs = [ROOT / hand["source"]["path"] for hand in manifest["hands"]]
        result = self.convert_paths(inputs, session_id="must-use-captured-session-context")

        self.assertEqual(summary["baseline_admitted_decisions"], 45)
        self.assertEqual(result["counts"]["newly_admitted_decisions"], 0)
        self.assertEqual(result["counts"]["validated_candidate_decisions"], 47)
        self.assertEqual(result["counts"]["known_card_ivey_decisions"], 47)
        self.assertEqual(result["counts"]["unknown_card_ivey_decisions"], 0)
        old_rows = {(row["hand_id"], row["source_action_index"]): row
                    for row in existing["records"]}
        new_rows = {(row["hand_id"], row["source_action_index"]): row
                    for row in result["records"]}
        self.assertEqual(set(old_rows), set(new_rows))
        diagnostic = json.loads((ROOT / (
            "data/acquisition_resume/2026-11-01/ante-eligibility-diagnostic.json")).read_text())
        corrections = {row["source_decision_id"]: row["expected_from_live_tiers_plus_dead_antes"]
                       for row in diagnostic["rows_needing_correction"] if row["batch"] == "2026"}
        changed = set()
        for key, old in old_rows.items():
            new = new_rows[key]
            with self.subTest(decision=key):
                expected_state = copy.deepcopy(old["state"])
                if old["source_decision_id"] in corrections:
                    expected_state["contestable_pot"] = corrections[old["source_decision_id"]]
                    changed.add(old["source_decision_id"])
                    self.assertNotEqual(new["decision_id"], old["decision_id"])
                else:
                    self.assertEqual(new["decision_id"], old["decision_id"])
                self.assertEqual(new["state"], expected_state)
                self.assertEqual(new["expected"], old["expected"])
                self.assertEqual(new["source_decision_id"], old["source_decision_id"])
                self.assertEqual(new["source_action_index"], old["source_action_index"])
                self.assertTrue(new["stable_source_decision_key"].startswith(
                    f"{new['canonical_hand_id']}:round:"))
                self.assertTrue(new["source_capture_path"].endswith(
                    old["source_capture_path"]))
                self.assertEqual(new["source_capture_sha256"], old["source_capture_sha256"])
                self.assertEqual(new["source_payload_sha256"], old["source_payload_sha256"])
                self.assertTrue(new["source_request_path"].endswith(
                    old["source_request_path"]))
                self.assertEqual(new["source_request_sha256"], old["source_request_sha256"])
        self.assertEqual(changed, set(corrections))
        self.assertEqual(len(changed), 19)

        # validate_rows hashes top-level provenance metadata while leaving the
        # state-derived decision identity stable.
        probe = copy.deepcopy(result["records"][0])
        original_decision_id = probe["decision_id"]
        original_record_hash = probe["record_hash"]
        probe["source_capture_sha256"] = "0" * 64
        revalidated = triton_convert.validate_rows([probe])[0]
        self.assertEqual(revalidated["decision_id"], original_decision_id)
        self.assertNotEqual(revalidated["record_hash"], original_record_hash)


if __name__ == "__main__":
    unittest.main()
