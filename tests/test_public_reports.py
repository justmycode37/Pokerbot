import unittest

from pokerbot.public_reports import load_public_report_decisions
from pokerbot.state import Observation
from pokerbot.ivey import _legal_prediction


class PublicReportTests(unittest.TestCase):
    def test_all_snapshots_have_valid_observations_and_separate_legal_labels(self):
        rows = load_public_report_decisions()
        self.assertEqual(len({r['hand_id'] for r in rows}), 4)
        for r in rows:
            Observation.from_dict(r['state'])
            self.assertTrue(_legal_prediction(r['expected'], r['state']))
            self.assertNotIn('expected', r['state'])
            self.assertEqual(r['state']['player_id'], 'Phil Ivey')

    def test_hu_completion_is_paid_before_facing_a_shove(self):
        rows = [r for r in load_public_report_decisions() if 'haxton' in r['hand_id']]
        self.assertEqual(len(rows), 2)
        state = rows[1]['state']
        self.assertEqual(state['pot'], 2380000)
        self.assertEqual(state['current_bet'], 160000)
        self.assertEqual(state['to_call'], 2020000)
        self.assertEqual(state['stack'], 9120000)
        self.assertEqual(state['legal_actions'], ['fold', 'call'])

    def test_quoss_call_uses_street_total_and_remaining_stack(self):
        rows = [r for r in load_public_report_decisions() if 'quoss' in r['hand_id']]
        self.assertEqual(rows[-1]['state']['pot'], 2070000)
        self.assertEqual(rows[-1]['state']['to_call'], 880000)
        self.assertEqual(rows[-1]['state']['stack'], 2180000)
        self.assertEqual(rows[-1]['expected'], {'action': 'call'})

    def test_prior_checkers_are_not_future_pending_actors(self):
        rows = [r for r in load_public_report_decisions() if 'sochi' in r['hand_id']]
        self.assertTrue(all(r['state']['players_to_act'] == 0 for r in rows))
        bonomo = next(r for r in load_public_report_decisions() if 'bonomo' in r['hand_id'])
        self.assertEqual(bonomo['state']['players_active'], 4)
