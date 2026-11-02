import unittest

from pokerbot.imitation import FEATURE_NAMES, _build_tree


class ClassifierSplitRegressionTests(unittest.TestCase):
    def test_minimum_leaf_constraint_does_not_skip_first_label_in_gini_counts(self):
        # The last two samples form the only allowed leaf containing the
        # minority action. Its weighted Gini cost is 1.0 versus 1.6667 for
        # splitting after the first two observations.
        labels = ['call'] * 7 + ['raise']
        examples = []
        for index, action in enumerate(labels):
            x = dict.fromkeys(FEATURE_NAMES, 0.0)
            x[FEATURE_NAMES[0]] = float(index)
            examples.append({'features': x, 'action': action, 'raise_ratio': None})
        tree = _build_tree(examples, list(range(8)), ('call', 'raise'),
                           depth=0, max_depth=1, min_leaf=2)
        self.assertEqual(tree['threshold'], 5.5)
        self.assertEqual(tree['left']['action_counts'], {'call': 6, 'raise': 0})
        self.assertEqual(tree['right']['action_counts'], {'call': 1, 'raise': 1})
