import unittest

from pokerbot.benchmarks import load_ivey_corpus


class CorpusTests(unittest.TestCase):
    def test_primary_and_reconstructed_evidence_are_separate(self):
        primary, _ = load_ivey_corpus()
        all_rows, report = load_ivey_corpus(include_reconstructed=True)
        self.assertEqual(len(primary), 4)
        self.assertEqual(len(all_rows), 9)
        self.assertEqual(len({r["hand_id"] for r in all_rows}), 2)
        self.assertEqual(report["additional_reconstructed_decisions"], 5)

    def test_reported_hand_pot_and_stack_derive_from_forced_bets_and_prefix(self):
        rows, _ = load_ivey_corpus(include_reconstructed=True)
        rows = [r for r in rows if r["format"] == "tournament_nlhe"]
        self.assertEqual([r["state"]["pot"] for r in rows], [103000, 134000, 134000, 284000, 1064000])
        self.assertEqual([r["state"]["stack"] for r in rows], [2882000, 2851000, 2851000, 2776000, 2576000])
        # River raise is to 580k, so the minimum reraise is to 960k and
        # hero, already in for 200k, faces 380k rather than 580k.
        self.assertEqual(rows[-1]["state"]["min_raise_to"], 960000)
        self.assertEqual(rows[-1]["state"]["to_call"], 380000)
        self.assertTrue(all("disclosed" in r["evidence_tier"] for r in rows))

    def test_video_reconstruction_preserves_exact_header_stacks_and_pots(self):
        rows, report = load_ivey_corpus(include_verified_video=True)
        video = [r for r in rows if r["evidence_tier"].startswith("video_reconstructed")]
        self.assertEqual(len(video), 6)
        self.assertEqual(report["additional_verified_video_decisions"], 6)
        self.assertEqual([r["state"]["pot"] for r in video], [450000,550000,680000,810000,1410000,2620000])
        self.assertEqual(video[-1]["state"]["stack"], 5980000)
        self.assertEqual(video[-1]["state"]["legal_actions"], ["fold", "call"])
        self.assertEqual(video[-1]["expected"], {"action": "fold"})
        self.assertEqual(len({r["hand_id"] for r in video}), 1)
