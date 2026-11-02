"""Focused tests for the standalone Triton source-prefix pot helper."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.acquisition_pot_eligibility import (  # noqa: E402
    HERO_UUID,
    PrefixPotError,
    _hand_from_document,
    inspect_prefix_pot,
    reproduce_ante_diagnostic,
)


TRITON_ROOT = ROOT / "data/acquisition_resume/2026-11-01"
SAMPLES = {
    "2025_blocked_a": (TRITON_ROOT / "triton_2025/raw/3bc7093a-05a7-41d1-82b4-b76f7a84107e/hands/238da98b-1804-492f-9518-64cb73388dfd.json", 3),
    "2025_blocked_b": (TRITON_ROOT / "triton_2025/raw/3bc7093a-05a7-41d1-82b4-b76f7a84107e/hands/7233ae8e-33b6-4786-a574-8623b63c849b.json", 4),
    "2025_unaffected": (TRITON_ROOT / "triton_2025/raw/3bc7093a-05a7-41d1-82b4-b76f7a84107e/hands/0fe69d0d-c62f-4a47-baac-7770b44b9bdb.json", 7),
    "2026_bba": (TRITON_ROOT / "triton_2026/raw/hands/47e1dbd2-ebd2-484e-b15c-3a5d281b7260.json", 4),
    "2026_multistreet": (TRITON_ROOT / "triton_2026/raw/hands/65a33886-e2fd-47a5-9a96-cb7081b909cb.json", 12),
    "2026_short_reach": (TRITON_ROOT / "triton_2026/raw/hands/9dd266da-35c6-4a6e-992e-7703b663951d.json", 9),
    "2026_unmatched_excess": (TRITON_ROOT / "triton_2026/raw/hands/c3bb5083-4b04-47e2-ac6b-a146a3a9f704.json", 9),
}


def read_hand(path: Path) -> dict[str, Any]:
    return _hand_from_document(json.loads(path.read_text(encoding="utf-8")))


def action(kind: str, player: str, amount: int | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {"type": kind, "userId": player}
    if amount is not None:
        row["amount"] = amount
    return row


def fixture_hand(players: list[tuple[str, int]], rounds: list[dict[str, Any]],
                 *, hand_id: str = "11111111-1111-4111-8111-111111111111") -> dict[str, Any]:
    return {
        "handId": hand_id,
        "pokerVariant": "texas",
        "players": [{"userId": player, "startChips": stack} for player, stack in players],
        "rounds": rounds,
    }


class AcquisitionPotEligibilityTests(unittest.TestCase):
    def test_both_blocked_2025_decisions_restore_big_blind_ante_to_contestable_pot(self) -> None:
        for name in ("2025_blocked_a", "2025_blocked_b"):
            path, ordinal = SAMPLES[name]
            with self.subTest(sample=name):
                result = inspect_prefix_pot(read_hand(path), ordinal)
                self.assertEqual(result["pot"], 375_000)
                self.assertEqual(result["to_call"], 150_000)
                self.assertEqual(result["contestable_pot"], 375_000)
                self.assertEqual(result["dead_antes"], 150_000)
                self.assertEqual(sum(result["live_contributions"].values()), 225_000)

    def test_real_2025_unaffected_and_2026_examples_match_saved_diagnostic(self) -> None:
        expected = {
            "2025_unaffected": (450_000, 450_000, 200_000),
            "2026_bba": (375_000, 375_000, 150_000),
            "2026_multistreet": (1_300_000, 1_300_000, 250_000),
            "2026_short_reach": (7_650_000, 3_550_000, 2_800_000),
            "2026_unmatched_excess": (8_450_000, 2_475_000, 1_875_000),
        }
        for name, (pot, contestable, to_call) in expected.items():
            path, ordinal = SAMPLES[name]
            with self.subTest(sample=name):
                result = inspect_prefix_pot(read_hand(path), ordinal)
                self.assertEqual((result["pot"], result["contestable_pot"], result["to_call"]),
                                 (pot, contestable, to_call))
        multistreet = inspect_prefix_pot(read_hand(SAMPLES["2026_multistreet"][0]), 12)
        self.assertEqual(multistreet["source_round_index"], 1)
        self.assertEqual(multistreet["source_round_action_index"], 1)
        self.assertEqual(multistreet["source_decision_id"],
                         "triton:65a33886-e2fd-47a5-9a96-cb7081b909cb:action:12")
        self.assertEqual(multistreet["stable_source_decision_key"],
                         "triton:65a33886-e2fd-47a5-9a96-cb7081b909cb:round:1:action:1")

    def test_uniform_antes_are_common_dead_money_and_short_stack_tiers_are_clipped(self) -> None:
        hero, short, deep = HERO_UUID, "short", "deep"
        hand = fixture_hand(
            [(hero, 1_000), (short, 100), (deep, 1_000)],
            [{"name": "pre_flop", "actions": [
                action("ante", hero, 5), action("ante", short, 5), action("ante", deep, 5),
                action("small_blind", short, 50), action("big_blind", deep, 100),
                action("call", hero, 100), action("all_in", short, 45), action("check", deep),
            ]}, {"name": "flop", "actions": [action("check", hero)]}],
        )
        result = inspect_prefix_pot(hand, 8)
        self.assertEqual(result["dead_antes"], 15)
        self.assertEqual(result["pot"], 310)
        self.assertEqual(result["to_call"], 0)
        self.assertEqual(result["contestable_pot"], 310)
        self.assertEqual(result["evidence"]["opponent_reach_limits"][short], 95)
        self.assertEqual(result["evidence"]["contestable_live_tiers"], 295)

    def test_folded_money_stays_in_live_contribution_layers(self) -> None:
        hero, folded, active_a, active_b = HERO_UUID, "folded", "active-a", "active-b"
        hand = fixture_hand(
            [(hero, 1_000), (folded, 300), (active_a, 500), (active_b, 1_000)],
            [{"name": "pre_flop", "actions": [
                action("small_blind", folded, 50), action("big_blind", active_a, 100),
                action("fold", folded), action("call", hero, 100), action("call", active_b, 100),
            ]}, {"name": "flop", "actions": [action("check", hero)]}],
        )
        result = inspect_prefix_pot(hand, 5)
        self.assertEqual(result["evidence"]["folded_players"], [folded])
        self.assertEqual(result["live_contributions"][folded], 50)
        self.assertEqual(result["pot"], 350)
        self.assertEqual(result["contestable_pot"], 350)
        self.assertIn(folded, result["evidence"]["tiers"][0]["contributor_ids_including_folded"])

    def test_straddle_is_live_and_changes_preflop_call_price(self) -> None:
        hero, small, big, straddler = HERO_UUID, "small", "big", "straddler"
        hand = fixture_hand(
            [(hero, 1_000), (small, 1_000), (big, 1_000), (straddler, 1_000)],
            [{"name": "pre_flop", "actions": [
                action("small_blind", small, 5), action("big_blind", big, 10),
                action("straddle", straddler, 20), action("check", hero),
            ]}],
        )
        result = inspect_prefix_pot(hand, 3)
        self.assertEqual(result["dead_antes"], 0)
        self.assertEqual(result["pot"], 35)
        self.assertEqual(result["to_call"], 20)
        self.assertEqual(result["contestable_pot"], 35)

    def test_to_call_is_clipped_to_hero_remaining_stack(self) -> None:
        hero, big, raiser = HERO_UUID, "big", "raiser"
        hand = fixture_hand(
            [(hero, 35), (big, 1_000), (raiser, 1_000)],
            [{"name": "pre_flop", "actions": [
                action("ante", hero, 5), action("small_blind", hero, 5),
                action("big_blind", big, 10), action("raise", raiser, 100),
                action("fold", hero),
            ]}],
        )
        result = inspect_prefix_pot(hand, 4)
        self.assertEqual(result["call_amount_due"], 95)
        self.assertEqual(result["to_call"], 25)
        self.assertEqual(result["evidence"]["remaining_stacks"][hero], 25)
        self.assertEqual(result["pot"], 120)
        self.assertEqual(result["contestable_pot"], 50)

    def test_future_cards_terminal_fields_and_target_amount_do_not_change_prefix_result(self) -> None:
        path, ordinal = SAMPLES["2026_short_reach"]
        hand = read_hand(path)
        original = inspect_prefix_pot(hand, ordinal)
        changed = copy.deepcopy(hand)
        target = changed["rounds"][0]["actions"][ordinal]
        target["amount"] = 1
        flat = 0
        for round_row in changed["rounds"]:
            for action_row in round_row["actions"]:
                if flat > ordinal:
                    action_row["type"] = "unsupported future noise"
                    action_row["amount"] = -999
                flat += 1
            round_row["communityCards"] = ["CARD_AS", "CARD_KS", "CARD_QS"]
            round_row["communityCard"] = "CARD_JS"
        for player in changed["players"]:
            player["pocketCards"] = ["CARD_2C", "CARD_3C"]
            player["endChips"] = -999
        changed["pots"] = [{"totalAmount": -999, "potPlayers": "not an array"}]
        self.assertEqual(inspect_prefix_pot(changed, ordinal), original)

    def test_invalid_or_ambiguous_prefixes_fail_closed(self) -> None:
        path, ordinal = SAMPLES["2025_blocked_a"]
        hand = read_hand(path)
        for bad_ordinal in (-1, 10_000, True):
            with self.subTest(ordinal=bad_ordinal), self.assertRaises(PrefixPotError):
                inspect_prefix_pot(hand, bad_ordinal)
        with self.assertRaisesRegex(PrefixPotError, "target_is_not_hero"):
            inspect_prefix_pot(hand, 0)
        with self.assertRaisesRegex(PrefixPotError, "hero_uuid_not_in_players"):
            inspect_prefix_pot(hand, ordinal, hero_id="absent")

        bad = copy.deepcopy(hand)
        bad["rounds"][0]["actions"][0]["type"] = "unknown forced payment"
        with self.assertRaisesRegex(PrefixPotError, "unknown_action_type"):
            inspect_prefix_pot(bad, ordinal)
        non_texas = copy.deepcopy(hand)
        non_texas["pokerVariant"] = "omaha"
        with self.assertRaisesRegex(PrefixPotError, "non_texas"):
            inspect_prefix_pot(non_texas, ordinal)

    def test_canonical_ordinal_must_point_to_hero_decision_not_alias(self) -> None:
        path, ordinal = SAMPLES["2025_blocked_a"]
        hand = read_hand(path)
        result = inspect_prefix_pot(hand, ordinal)
        self.assertEqual(result["source_action_index"], ordinal)
        self.assertEqual(result["source_decision_id"],
                         "triton:238da98b-1804-492f-9518-64cb73388dfd:action:3")
        self.assertEqual(result["stable_source_decision_key"],
                         "triton:238da98b-1804-492f-9518-64cb73388dfd:round:0:action:3")

    def test_saved_ante_diagnostic_reproduces_exact_21_of_50_diff(self) -> None:
        report = reproduce_ante_diagnostic(
            TRITON_ROOT / "ante-eligibility-diagnostic.json", root=ROOT)
        self.assertEqual(report["counts"]["diagnostic_decision_rows"], 50)
        self.assertEqual(report["counts"]["corrected_values_differing_from_old"], 21)
        self.assertEqual(report["counts"]["corrected_2025_values_differing_from_old"], 2)
        self.assertEqual(report["counts"]["corrected_2026_values_differing_from_old"], 19)
        self.assertEqual(report["counts"]["existing_frozen_baseline_decisions"], 45)
        batches = [json.loads(path.read_text()) for path in
                   sorted((TRITON_ROOT / "admissions").glob("batch-*.json"))]
        admitted = [row for batch in batches for row in batch["records"]]
        held = {key for batch in batches for key in batch.get("held_source_decision_ids", [])}
        held.difference_update(row.get("source_decision_id") for row in admitted)
        self.assertEqual(report["counts"]["existing_total_usable_decisions"], 45 + len(admitted))
        self.assertEqual(report["counts"]["existing_new_admitted_decisions"], len(admitted))
        self.assertEqual(report["counts"]["pending_ante_correction_rows_in_existing_ledger"], len(held))
        self.assertEqual(report["counts"]["existing_new_admitted_known_card_decisions"], len(admitted))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
