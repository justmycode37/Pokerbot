import copy
import tempfile
import unittest
from pathlib import Path

from pokerbot import ivey


def history(actions, *, players=None, stacks=None, blinds=None, minimum=2):
    return '\n'.join([
        'variant = "NT"', 'ante_trimming_status = true',
        f'players = {players or ["Opponent", "Phil Ivey"]!r}',
        f'starting_stacks = {stacks or [100, 100]!r}',
        f'antes = {[0] * len(players or [0, 1])!r}',
        f'blinds_or_straddles = {blinds or [1, 2]!r}',
        f'min_bet = {minimum}', f'actions = {actions!r}',
    ])


def load_text(source):
    with tempfile.TemporaryDirectory() as folder:
        filename = Path(folder) / 'example.phh'
        filename.write_text(source)
        return ivey.load_decisions(filename)


class ReplayRuleTests(unittest.TestCase):
    def test_heads_up_blinds_reverse_and_button_posts_small_blind(self):
        rows = load_text(history(['d dh p1 KsKh', 'd dh p2 AsAc', 'p2 cc', 'p1 cc']))
        self.assertEqual(len(rows), 1)
        state = rows[0]['state']
        self.assertEqual(state['position'], 'BTN')
        self.assertEqual(state['pot'], 3)
        self.assertEqual(state['current_bet'], 1)
        self.assertEqual(state['to_call'], 1)
        self.assertEqual(state['stack'], 99)
        self.assertEqual(state['min_raise_to'], 4)

    def test_short_all_in_does_not_reopen_prior_raiser(self):
        rows = load_text(history([
            'd dh p1 AsAc', 'd dh p2 KhKd', 'd dh p3 QhQd',
            'p3 cbr 4', 'p1 cbr 10', 'p2 cc', 'p3 cbr 13', 'p1 cc', 'p2 cc'],
            players=['Phil Ivey', 'B', 'C'], stacks=[100, 100, 13], blinds=[1, 2, 0]))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1]['state']['to_call'], 3)
        self.assertNotIn('raise', rows[-1]['state']['legal_actions'])

    def test_all_in_call_uses_accessible_pot(self):
        rows = load_text(history([
            'd dh p1 AsAc', 'd dh p2 KhKd', 'd dh p3 QhQd',
            'p3 cbr 8', 'p1 cc', 'p2 cc'],
            players=['Phil Ivey', 'B', 'C'], stacks=[5, 100, 100], blinds=[1, 2, 0]))
        self.assertEqual(len(rows), 1)
        state = rows[0]['state']
        self.assertEqual(state['to_call'], 4)
        self.assertEqual(state['pot'], 11)
        self.assertEqual(state['contestable_pot'], 8)
        self.assertNotIn('raise', state['legal_actions'])

    def test_fractional_chips_are_scaled_exactly(self):
        rows = load_text(history(['d dh p1 KsKh', 'd dh p2 AsAc', 'p2 cbr 2.5', 'p1 cc'],
                                 stacks=[20.5, 20.5], blinds=[0.5, 1], minimum=1))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['chip_ticks_per_currency_unit'], 10)
        self.assertEqual(rows[0]['state']['pot'], 15)
        self.assertEqual(rows[0]['expected']['amount'], 25)

    def test_corrupt_prefix_and_under_minimum_raise_exclude_whole_file(self):
        source = ivey.DEFAULT_PHH_PATH.read_text()
        self.assertEqual(load_text(source.replace('p3 cbr 7000', 'p3 cbr nope')), [])
        self.assertEqual(ivey.LAST_LOAD_REPORT['files_included'], 0)
        self.assertEqual(ivey.LAST_LOAD_REPORT['files_excluded'], 1)
        self.assertEqual(load_text(history(['d dh p1 KsKh', 'd dh p2 AsAc', 'p2 cbr 3'])), [])

    def test_invalid_toml_is_not_executed(self):
        self.assertEqual(load_text('players = __import__("os").system("false")'), [])
        self.assertEqual(ivey.LAST_LOAD_REPORT['exclusions']['file:invalid_toml'], 1)


class ScorerIntegrityTests(unittest.TestCase):
    def test_illegal_prediction_gets_no_credit_and_report_id_is_hidden(self):
        rows = ivey.load_decisions()[:1]
        preserved = copy.deepcopy(rows)
        def illegal(state):
            self.assertNotIn('hand_id', state)
            state['history'].clear()
            return {'action': 'raise', 'amount': 1}
        result = ivey.compare_decisions(rows, illegal)
        self.assertEqual(rows, preserved)
        self.assertEqual(result['illegal_prediction_count'], 1)
        self.assertEqual(result['action_agreement'], 0)
        self.assertEqual(result['exact_action_and_size_agreement'], 0)

    def test_action_only_does_not_credit_different_size_as_exact(self):
        rows = ivey.load_decisions()[:1]
        result = ivey.compare_decisions(rows, lambda s: {
            'action': 'raise', 'amount': 24000, 'probabilities': {'raise': 0.3, 'fold': 0.7}})
        self.assertEqual(result['action_agreement'], 1)
        self.assertEqual(result['exact_action_and_size_agreement'], 0)
        self.assertEqual(result['mixed_action_comparison']['mean_probability_of_recorded_action_class'], 0.3)
        self.assertIsNone(result['population_confidence_interval'])

    def test_rounded_video_is_not_admitted_to_exact_scoring(self):
        from pokerbot.benchmarks import load_video_reviews
        with self.assertRaisesRegex(ValueError, 'qualitative-only'):
            ivey.compare_decisions(load_video_reviews(), lambda s: {'action': 'fold'})

    def test_boolean_probabilities_are_rejected(self):
        result = ivey.compare_decisions(ivey.load_decisions()[:1], lambda s: {
            'action': 'raise', 'amount': 23000, 'probabilities': {'raise': True, 'fold': False}})
        self.assertEqual(result['mixed_action_comparison']['invalid_distributions'], 1)
        self.assertIsNone(result['mixed_action_comparison']['mean_probability_of_recorded_action_class'])
