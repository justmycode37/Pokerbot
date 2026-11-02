import copy
import unittest

from pokerbot.benchmarks import load_ivey_corpus
from pokerbot.review import review_packet, packet_markdown


class QualitativeReviewTests(unittest.TestCase):
    def test_policy_receives_only_observation_and_cannot_mutate_evidence(self):
        corpus, _ = load_ivey_corpus()
        preserved = copy.deepcopy(corpus)
        received = []
        def policy(state):
            self.assertNotIn("expected", state)
            self.assertNotIn("source", state)
            self.assertNotIn("hand_id", state)
            received.append(copy.deepcopy(state))
            state["history"].append({"action": "fake"})
            return {"action": "fold", "probabilities": {"fold": 0.5, "raise": 0.5}}
        packet = review_packet(corpus, policy)
        self.assertEqual(corpus, preserved)
        self.assertEqual(len(packet["decisions"]), 4)
        self.assertTrue(all(r["bot_probability_of_recorded_action"] == 0.5 for r in packet["decisions"]))
        self.assertIn("one sampled disagreement", packet["decisions"][0]["review_hypotheses_not_verdicts"][0])
        self.assertIn("unknown", packet_markdown(packet).lower())

    def test_size_comparison_uses_increment_beyond_call(self):
        corpus, _ = load_ivey_corpus()
        packet = review_packet(corpus[:1], lambda s: {"action": "call"})
        row = packet["decisions"][0]
        self.assertEqual(row["ivey_sizing"]["extra_chips"], 22000)
        self.assertAlmostEqual(row["ivey_sizing"]["raise_over_call_fraction_of_pot_after_call"],
                               16000 / 17500)

    def test_video_snapshots_stay_in_qualitative_tier(self):
        from pokerbot.benchmarks import load_video_reviews
        rows = load_video_reviews()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["expected"]["action"], "fold")
        self.assertIn("rounded", rows[0]["evidence_tier"])
        self.assertIn("125s", rows[0]["source"])
        packet = review_packet(rows, lambda s: {"action": "call"})
        self.assertTrue(packet["decisions"][0]["source_limitations"])
