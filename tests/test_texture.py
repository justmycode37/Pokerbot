import itertools
import math
import unittest

from pokerbot.cards import estimate_equity, rank_hand
from pokerbot.state import Observation
from pokerbot.texture import suited_board_equity


def observation(hole, board, players=2):
    return Observation.from_dict({
        "hole_cards": list(hole),
        "board": list(board),
        "pot": 100,
        "to_call": 0,
        "stack": 100,
        "current_bet": 0,
        "min_raise_to": 2,
        "max_raise_to": 100,
        "big_blind": 2,
        "position": "BTN",
        "players_active": players,
        "players_to_act": players - 1,
        "legal_actions": ["check"],
    })


class SuitedBoardEquityTests(unittest.TestCase):
    def test_weak_four_suit_flush_exactly_accounts_for_multiway_blockers(self):
        board = ("Jc", "9c", "Tc", "Ac", "2d")
        for opponents in (1, 3, 7):
            with self.subTest(opponents=opponents):
                actual = suited_board_equity(
                    observation(("8s", "4c"), board, opponents + 1)
                )
                expected = math.comb(39, 2 * opponents) / math.comb(45, 2 * opponents)
                self.assertAlmostEqual(actual, expected, places=12)

    def test_flush_blockers_and_nut_straight_flush(self):
        board = ("Jc", "9c", "Tc", "Ac", "2d")
        weak = suited_board_equity(observation(("8s", "4c"), board, 5))
        stronger_blocker = suited_board_equity(observation(("8s", "8c"), board, 5))
        royal = suited_board_equity(observation(("Kc", "Qc"), board, 8))
        expected_blocked = math.comb(43, 8) / math.comb(45, 8)
        self.assertLess(weak, stronger_blocker)
        self.assertAlmostEqual(stronger_blocker, expected_blocked, places=12)
        self.assertEqual(royal, 1.0)

    def test_playing_board_flush_shares_ties_multiway(self):
        board = ("Ac", "Kc", "9c", "6c", "3c")
        for opponents in (1, 2, 5):
            with self.subTest(opponents=opponents):
                actual = suited_board_equity(
                    observation(("As", "Kd"), board, opponents + 1)
                )
                # Seven remaining clubs beat the board flush; all other deals
                # leave every player sharing the board flush.
                chance_of_tie = math.comb(38, 2 * opponents) / math.comb(
                    45, 2 * opponents
                )
                self.assertAlmostEqual(
                    actual, chance_of_tie / (opponents + 1), places=12
                )

    def test_five_suited_board_can_be_improved_by_hero_blocker(self):
        actual = suited_board_equity(
            observation(("Qc", "2h"), ("Ac", "Kc", "9c", "6c", "3c"), 8)
        )
        self.assertEqual(actual, 1.0)

    def test_ace_high_straight_flush_beats_straight_flush_on_board(self):
        actual = suited_board_equity(
            observation(("Ac", "2d"), ("9c", "Tc", "Jc", "Qc", "Kc"), 8)
        )
        self.assertEqual(actual, 1.0)

    def test_two_card_straight_flush_threat_matches_exhaustive_heads_up(self):
        hole = ("Kc", "As")
        board = ("4c", "5c", "6c", "Tc", "Kd")
        actual = suited_board_equity(observation(hole, board))
        known = set(hole + board)
        deck = [rank + suit for rank in "23456789TJQKA" for suit in "cdhs"]
        remaining = [card for card in deck if card not in known]
        hero_rank = rank_hand(hole + board)
        share_total = 0.0
        for opponent_hole in itertools.combinations(remaining, 2):
            opponent_rank = rank_hand(opponent_hole + board)
            if hero_rank > opponent_rank:
                share_total += 1.0
            elif hero_rank == opponent_rank:
                share_total += 0.5
        expected = share_total / math.comb(len(remaining), 2)
        self.assertAlmostEqual(actual, expected, places=12)

    def test_disjoint_pair_threats_are_counted_without_reusing_a_card(self):
        # Ac alone beats Kc. Three additional winning pairs are (2c,3c),
        # (3c,7c), (7c,8c); only the first and third can occur together.
        hole = ("Kc", "As")
        board = ("4c", "5c", "6c", "Tc", "Kd")
        for opponents in (2, 7):
            probability_no_ace = math.comb(44, 2 * opponents) / math.comb(45, 2 * opponents)
            no_pair = (1 - 3 * opponents / math.comb(44, 2)
                       + opponents * (opponents - 1) / (math.comb(44, 2) * math.comb(42, 2)))
            self.assertAlmostEqual(suited_board_equity(observation(hole, board, opponents + 1)),
                                   probability_no_ace * no_pair, places=12)

    def test_turn_example_returns_a_conservative_low_flush_estimate(self):
        actual = suited_board_equity(
            observation(("8s", "4c"), ("Jc", "9c", "Tc", "Ac"), 8)
        )
        self.assertIsNotNone(actual)
        self.assertGreater(actual, 0.02)
        self.assertLess(actual, 0.10)

    def test_turn_royal_flush_is_unbeatable_even_on_paired_runouts(self):
        actual = suited_board_equity(
            observation(("Kc", "Qc"), ("Jc", "9c", "Tc", "Ac"), 8)
        )
        self.assertEqual(actual, 1.0)

    def test_turn_high_non_straight_flush_is_left_unsupported(self):
        self.assertIsNone(
            suited_board_equity(
                observation(("Kc", "2c"), ("Jc", "9c", "Tc", "Ac"), 4)
            )
        )

    def test_turn_estimate_is_below_uniform_monte_carlo_on_fixed_state(self):
        hole = ("8s", "4c")
        board = ("Jc", "9c", "Tc", "Ac")
        actual = suited_board_equity(observation(hole, board, 8))
        reference = estimate_equity(
            hole, board, opponents=7, samples=60000, seed=8127
        )
        # The turn path deliberately drops paired river runouts and safe deals
        # involving suit-card ties, so it is a lower bound rather than an MC
        # approximation centered on the reference.
        self.assertLessEqual(actual, reference + 0.005)
        self.assertLess(reference - actual, 0.035)

    def test_unsupported_board_textures_return_none(self):
        self.assertIsNone(
            suited_board_equity(
                observation(("As", "Kd"), ("2c", "5c", "8c", "Tc", "Qd"))
            )
        )
        self.assertIsNone(
            suited_board_equity(
                observation(("8s", "4c"), ("Jc", "9c", "Tc", "Ac", "Ad"))
            )
        )
        self.assertIsNone(
            suited_board_equity(observation(("As", "Kd"), ("2c", "5c", "8c")))
        )


if __name__ == "__main__":
    unittest.main()
