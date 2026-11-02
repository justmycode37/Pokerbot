import itertools
import random
import unittest

from pokerbot.cards import estimate_equity, normalize_card, rank_hand


class NormalizeCardTests(unittest.TestCase):
    def test_canonicalizes_case_whitespace_and_ten(self):
        self.assertEqual(normalize_card(" aS "), "As")
        self.assertEqual(normalize_card("10H"), "Th")
        self.assertEqual(normalize_card("tc"), "Tc")

    def test_rejects_malformed_cards(self):
        for value in ("", "1c", "10", "Ax", "Asd", "A s"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_card(value)
        with self.assertRaises(TypeError):
            normalize_card(10)


class RankHandTests(unittest.TestCase):
    def test_categories_and_kickers(self):
        examples = [
            (["As", "Kd", "Jh", "8c", "4s"], 0),
            (["As", "Ad", "Kc", "Qh", "2s"], 1),
            (["As", "Ad", "Kc", "Kh", "2s"], 2),
            (["As", "Ad", "Ac", "Kh", "2s"], 3),
            (["As", "2d", "3c", "4h", "5s"], 4),
            (["Ah", "Jh", "9h", "5h", "2h"], 5),
            (["As", "Ad", "Ac", "Kh", "Kd"], 6),
            (["As", "Ad", "Ac", "Ah", "Kd"], 7),
            (["9s", "8s", "7s", "6s", "5s"], 8),
        ]
        ranks = [rank_hand(cards) for cards, _ in examples]
        self.assertEqual([rank[0] for rank in ranks], list(range(9)))
        self.assertEqual(ranks, sorted(ranks))

    def test_straight_edges_and_best_seven_card_hand(self):
        self.assertEqual(rank_hand(["As", "2d", "3c", "4h", "5s"]), (4, 5))
        self.assertEqual(rank_hand(["As", "Kd", "Qc", "Jh", "Ts"]), (4, 14))
        # The wheel loses to a six-high straight; duplicate ranks do not break it.
        self.assertEqual(
            rank_hand(["As", "2d", "3c", "4h", "5s", "6d", "6c"]),
            (4, 6),
        )
        self.assertLess((4, 5), (4, 6))

    def test_full_house_uses_second_trip_as_pair_and_flush_uses_best_five(self):
        self.assertEqual(
            rank_hand(["As", "Ad", "Ac", "Ks", "Kd", "Kc", "2h"]),
            (6, 14, 13),
        )
        self.assertEqual(
            rank_hand(["Ah", "Kh", "Qh", "9h", "7h", "3h", "2c"]),
            (5, 14, 13, 12, 9, 7),
        )

    def test_random_seven_card_ranks_match_best_five_card_subset(self):
        rng = random.Random(4182)
        deck = [rank + suit for rank in "23456789TJQKA" for suit in "cdhs"]
        for _ in range(250):
            cards = rng.sample(deck, 7)
            expected = max(rank_hand(subset) for subset in itertools.combinations(cards, 5))
            with self.subTest(cards=cards):
                self.assertEqual(rank_hand(cards), expected)

    def test_validates_card_count_and_duplicates(self):
        for cards in (["As"] * 4, ["As"] * 8):
            with self.assertRaises(ValueError):
                rank_hand(cards)
        with self.assertRaises(ValueError):
            rank_hand(["As", "as", "Kd", "Qc", "Jh"])
        with self.assertRaises(TypeError):
            rank_hand("As Kd Qc Jh 9s")


class EstimateEquityTests(unittest.TestCase):
    def test_board_royal_straight_is_a_guaranteed_tie(self):
        equity = estimate_equity(
            ["2h", "3d"], ["Ah", "Kd", "Qs", "Jc", "Tc"], samples=40, seed=7
        )
        self.assertEqual(equity, 0.5)

    def test_multiway_tie_shares_the_pot_with_all_winners(self):
        equity = estimate_equity(
            ["2h", "3d"],
            ["Ah", "Kd", "Qs", "Jc", "Tc"],
            opponents=2,
            samples=40,
            seed=7,
        )
        self.assertAlmostEqual(equity, 1 / 3)

    def test_seed_is_reproducible_and_result_is_fractional_equity(self):
        args = (["As", "Kd"], ["2c", "7h", "9s"], 2, 200)
        first = estimate_equity(
            args[0], args[1], opponents=args[2], samples=args[3], seed=91
        )
        second = estimate_equity(
            args[0], args[1], opponents=args[2], samples=args[3], seed=91
        )
        self.assertEqual(first, second)
        self.assertGreaterEqual(first, 0.0)
        self.assertLessEqual(first, 1.0)

    def test_validates_inputs(self):
        with self.assertRaises(ValueError):
            estimate_equity(["As"], samples=1)
        with self.assertRaises(ValueError):
            estimate_equity(["As", "Kd"], ["As"], samples=1)
        with self.assertRaises(ValueError):
            estimate_equity(["As", "Kd"], ["2c"] * 6, samples=1)
        for opponents in (0, 8):
            with self.subTest(opponents=opponents), self.assertRaises(ValueError):
                estimate_equity(["As", "Kd"], opponents=opponents, samples=1)
        for samples in (0, -1):
            with self.subTest(samples=samples), self.assertRaises(ValueError):
                estimate_equity(["As", "Kd"], samples=samples)
        with self.assertRaises(ValueError):
            estimate_equity(["As", "Kd"], samples=1, opponent_ranges={})


if __name__ == "__main__":
    unittest.main()
