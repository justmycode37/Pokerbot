import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pokerbot.map_policy import decide as map_decide
from pokerbot.postflop_policy import (
    _DEFAULT_THRESHOLDS,
    decide,
    fit_model,
    load_model,
)


def observation(**updates):
    raw = {
        "hole_cards": ["Ks", "Qd"],
        "board": ["Kc", "7h", "2s"],
        "pot": 100,
        "contestable_pot": 100,
        "to_call": 0,
        "stack": 500,
        "current_bet": 0,
        "min_raise_to": 20,
        "max_raise_to": 500,
        "big_blind": 10,
        "position": "BTN",
        "players_active": 2,
        "players_to_act": 0,
        "legal_actions": ["check", "raise"],
        "history": [],
        "player_id": "hero",
        "seed": 123,
    }
    raw.update(updates)
    return raw


def empty_model():
    return {
        "schema_version": 1,
        "algorithm": "public-state-postflop-threshold-policy-v1",
        "feature_version": "public-postflop-state-v1",
        "thresholds": dict(_DEFAULT_THRESHOLDS),
        "metadata": {
            "training_decisions": 0,
            "training_postflop_decisions": 0,
            "partitions_used": [],
            "development_included_explicitly": False,
            "regularization": 3.0,
            "default_thresholds": dict(_DEFAULT_THRESHOLDS),
        },
    }


def training_row(state, action, *, partition="train", group="source", amount=40, **metadata):
    expected = {"action": action}
    if action == "raise":
        expected["amount"] = amount
    row = {
        "state": state,
        "expected": expected,
        "partition": partition,
        "group_id": group,
    }
    row.update(metadata)
    return row


class PostflopPolicyTests(unittest.TestCase):
    def test_preflop_decision_is_the_existing_fast_map_result(self):
        raw = observation(
            board=[], street="preflop", hole_cards=["As", "Ah"],
            to_call=10, current_bet=10, min_raise_to=30,
            legal_actions=["fold", "call", "raise"],
        )
        result = decide(raw, empty_model())
        baseline = map_decide(raw)
        self.assertEqual(result["action"], baseline["action"])
        self.assertEqual(result["amount"], baseline["amount"])
        self.assertEqual(result["probabilities"], baseline["probabilities"])

    def test_previous_street_aggressor_can_cbet_after_opponent_checks(self):
        state = observation(history=[
            {"street": "preflop", "player": "hero", "position": "BTN", "action": "raise"},
            {"street": "preflop", "player": "villain", "position": "BB", "action": "call"},
            {"street": "flop", "player": "villain", "position": "BB", "action": "check"},
        ], hole_cards=["7s", "6d"])
        with_initiative = decide(state, empty_model())
        without_initiative = copy.deepcopy(state)
        without_initiative["history"] = [without_initiative["history"][1], without_initiative["history"][2]]
        without_initiative = decide(without_initiative, empty_model())
        self.assertEqual(with_initiative["action"], "raise")
        self.assertEqual(with_initiative["diagnostics"]["reason"], "in-position continuation bet with initiative")
        self.assertEqual(without_initiative["action"], "check")

    def test_top_pair_can_make_a_thin_value_bet_after_a_check_through(self):
        state = observation(history=[
            {"street": "flop", "player": "villain", "position": "BB", "action": "check"},
        ])
        result = decide(state, empty_model())
        self.assertEqual(result["action"], "raise")
        self.assertEqual(result["diagnostics"]["reason"], "thin value after a check-through")

    def test_unknown_check_actor_does_not_count_as_checked_to_hero(self):
        state = observation(player_id=None, history=[{"street": "flop", "action": "check"}])
        result = decide(state, empty_model())
        self.assertEqual(result["action"], "check")
        self.assertFalse(result["diagnostics"]["checked_to_hero"])

    def test_shared_middle_position_label_does_not_identify_a_hero(self):
        state = observation(
            position="MP", player_id=None, table_size=8,
            hole_cards=["7s", "6d"],
            history=[
                {"street": "preflop", "position": "MP", "action": "raise"},
                {"street": "flop", "position": "BB", "action": "check"},
            ],
        )
        result = decide(state, empty_model())
        self.assertFalse(result["diagnostics"]["hero_last_aggressor_previous"])

    def test_facing_price_uses_legal_call_fold_and_raise_actions(self):
        state = observation(
            hole_cards=["As", "Ks"], board=["Qs", "Js", "Ts", "2d", "3c"],
            pot=100, contestable_pot=100, to_call=25, current_bet=25,
            min_raise_to=75, max_raise_to=500,
            legal_actions=["fold", "call", "raise"], players_to_act=0,
            history=[{"street": "river", "player": "villain", "position": "BB",
                      "action": "bet", "amount": 25, "added": 25}],
        )
        result = decide(state, empty_model())
        self.assertEqual(result["action"], "raise")
        self.assertIn(result["action"], state["legal_actions"])
        self.assertGreaterEqual(result["amount"], state["min_raise_to"])
        self.assertLessEqual(result["amount"], state["max_raise_to"])
        self.assertAlmostEqual(sum(result["probabilities"].values()), 1.0)

    def test_re_raise_after_hero_aggression_adds_public_range_pressure(self):
        base = observation(
            to_call=25, current_bet=25, min_raise_to=75,
            legal_actions=["fold", "call", "raise"],
            history=[{"street": "flop", "player": "villain", "position": "BB", "action": "bet"}],
        )
        raised_back = copy.deepcopy(base)
        raised_back["history"] = [
            {"street": "flop", "player": "hero", "position": "BTN", "action": "bet"},
            {"street": "flop", "player": "villain", "position": "BB", "action": "raise"},
        ]
        first_bet = decide(base, empty_model())
        re_raise = decide(raised_back, empty_model())
        self.assertEqual(re_raise["diagnostics"]["hero_aggressed_current"], True)
        self.assertGreater(re_raise["diagnostics"]["range_pressure_discount"],
                           first_bet["diagnostics"]["range_pressure_discount"])

    def test_model_fitting_rejects_evaluation_partial_and_unreviewed_pending_rows(self):
        base = observation()
        with self.assertRaisesRegex(ValueError, "evaluation"):
            fit_model([training_row(base, "check", partition="evaluation")])
        with self.assertRaisesRegex(ValueError, "include_development"):
            fit_model([training_row(base, "check", partition="development")])
        explicitly_opted_in = fit_model(
            [training_row(base, "check", partition="train")], include_development=True,
        )
        self.assertTrue(explicitly_opted_in["metadata"]["development_included_explicitly"])
        for metadata in (
            {"admission_status": "partial_review"},
            {"admission_status": "pending_independent_review"},
            {"evidence_tier": "history_pending_source_review"},
        ):
            with self.subTest(metadata=metadata), self.assertRaisesRegex(ValueError, "partial or pending"):
                fit_model([training_row(base, "check", **metadata)])

    def test_reviewed_admission_supersedes_stale_acquisition_pending_tier(self):
        row = training_row(
            observation(), "check", partition="development",
            evidence_tier="acquired_history_pending_independent_source_review",
            admission_status="admitted_source_reviewed_development_only",
            policy_use="development_only", fresh_holdout=False,
        )
        model = fit_model([row], include_development=True)
        self.assertEqual(model["metadata"]["training_decisions"], 1)

    def test_fit_model_json_roundtrip_and_legal_deterministic_output(self):
        state = observation()
        model = fit_model([
            training_row(state, "raise", amount=40, group="one"),
            training_row(observation(hole_cards=["2c", "3d"], board=["Kc", "7h", "2s"]),
                         "check", group="two"),
        ])
        json.dumps(model, allow_nan=False)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            path.write_text(json.dumps(model), encoding="utf-8")
            loaded = load_model(path)
        self.assertEqual(loaded, model)
        result = decide(state, loaded)
        self.assertIn(result["action"], state["legal_actions"])
        self.assertAlmostEqual(sum(result["probabilities"].values()), 1.0)
        self.assertEqual(set(result["probabilities"]), set(state["legal_actions"]))
        self.assertTrue(all(type(value) is float for value in result["probabilities"].values()))

    def test_source_record_and_seed_changes_do_not_change_fitted_policy(self):
        rows = [
            training_row(observation(), "raise", amount=40, group="source-one"),
            training_row(observation(hole_cards=["2c", "3d"]), "check", group="source-two"),
        ]
        relabeled = copy.deepcopy(rows)
        for index, row in enumerate(relabeled):
            row["group_id"] = f"renamed-{index}"
            row["decision_id"] = f"changed-decision-{index}"
            row["record_id"] = f"changed-record-{index}"
            row["state"]["seed"] += 1000
        self.assertEqual(fit_model(rows), fit_model(relabeled))
        model = fit_model(rows)
        changed_seed = copy.deepcopy(rows[0]["state"])
        changed_seed["seed"] += 999
        self.assertEqual(decide(rows[0]["state"], model), decide(changed_seed, model))

    def test_extreme_chip_counts_keep_price_math_finite(self):
        huge = 10 ** 500
        state = observation(
            hole_cards=["As", "Ks"], board=["Qs", "Js", "Ts", "2d", "3c"],
            pot=huge, contestable_pot=huge,
            to_call=huge, stack=2 * huge, current_bet=0,
            min_raise_to=huge + 1, max_raise_to=2 * huge,
            legal_actions=["fold", "call", "raise"], players_to_act=0,
            history=[{"street": "river", "player": "villain", "position": "BB",
                      "action": "bet", "amount": huge, "added": huge}],
        )
        result = decide(state, empty_model())
        self.assertEqual(result["action"], "raise")
        self.assertEqual(result["amount"], 2 * huge)


if __name__ == "__main__":
    unittest.main()
