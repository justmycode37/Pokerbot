import unittest

from pokerbot.evaluation_baselines import majority_action_policy


class MajorityBaselineTests(unittest.TestCase):
    def test_training_majority_is_masked_to_legal_actions_without_card_features(self):
        rows = [{'expected': {'action': 'raise'}}] * 5 + [{'expected': {'action': 'call'}}]
        policy = majority_action_policy(rows)
        state = dict(hole_cards=['7c','2d'],board=[],pot=150,to_call=100,stack=1000,
                     current_bet=0,min_raise_to=200,max_raise_to=1000,big_blind=100,
                     position='UTG',players_active=8,players_to_act=7,
                     legal_actions=['fold','call','raise'])
        self.assertEqual(policy(state)['amount'], 200)
        state['legal_actions'] = ['fold','call']
        self.assertEqual(policy(state)['action'], 'call')
