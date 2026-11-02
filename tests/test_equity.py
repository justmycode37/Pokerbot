import unittest

from pokerbot.equity import weighted_equity


class WeightedEquityTests(unittest.TestCase):
    def test_explicit_river_win_loss_and_tie(self):
        board = ["Ac", "Kd", "Qc", "Js", "2d"]
        self.assertEqual(weighted_equity(["Ts", "9s"], board,
            ranges=[[(("Ah", "Ad"), 1)]], samples=10), 1)
        self.assertEqual(weighted_equity(["3s", "4s"], board,
            ranges=[[(("Ah", "Ad"), 1)]], samples=10), 0)
        self.assertEqual(weighted_equity(["Ts", "9s"], board,
            ranges=[[(("Th", "8d"), 1)]], samples=10), 0.5)

    def test_joint_card_collision_is_rejected(self):
        # Exactly two compatible assignments, both lead to a 3-way board tie.
        ranges = [[(("2s", "3s"), 1), (("4s", "5s"), 1)]] * 2
        self.assertAlmostEqual(weighted_equity(["8c", "9c"],
            ["Ac", "Kd", "Qh", "Jd", "Tc"], ranges=ranges, samples=30), 1 / 3)

    def test_blocked_range_and_nonpositive_weight_are_errors(self):
        with self.assertRaises(ValueError):
            weighted_equity(["As", "Ks"], ranges=[[(("As", "Qs"), 1)]], samples=1)
        with self.assertRaises(ValueError):
            weighted_equity(["As", "Ks"], ranges=[[(("2s", "Qs"), 0)]], samples=1)
