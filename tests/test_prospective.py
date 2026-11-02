import copy
import unittest

from pokerbot.benchmarks import load_ivey_corpus
from pokerbot.corpus import split_rows
from pokerbot.prospective import assert_new_groups


class ProspectiveBoundaryTests(unittest.TestCase):
    def test_reused_hand_is_rejected_even_if_source_url_changes(self):
        rows,_ = load_ivey_corpus()
        prior = split_rows(rows)
        incoming = copy.deepcopy(rows)
        incoming[0]['source'] = 'https://example.com/rebroadcast'
        with self.assertRaisesRegex(ValueError, 'already inspected'):
            assert_new_groups(incoming, prior)

    def test_new_hand_in_same_session_is_not_an_independent_holdout(self):
        rows,_ = load_ivey_corpus()
        for r in rows:r['session_id'] = 'one-session'
        prior = split_rows(rows)
        incoming = copy.deepcopy(rows[:1])
        incoming[0]['hand_id'] = 'different-hand'
        with self.assertRaisesRegex(ValueError, 'already inspected'):
            assert_new_groups(incoming, prior)
