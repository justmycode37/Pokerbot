from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import random
import unittest
from unittest import mock

from pokerbot import corrected_calibrated_bot as corrected
from pokerbot import evolution_strategies


ROOT = Path(__file__).resolve().parents[1]


def preflop_observation(**updates):
    raw = {
        "hole_cards": ["As", "Kd"],
        "board": [],
        "pot": 30,
        "to_call": 0,
        "stack": 1000,
        "current_bet": 0,
        "min_raise_to": 20,
        "max_raise_to": 1000,
        "big_blind": 10,
        "position": "BTN",
        "players_active": 2,
        "players_to_act": 1,
        "legal_actions": ["fold", "raise"],
        "seed": 73,
    }
    raw.update(updates)
    return raw


def postflop_observation(**updates):
    raw = {
        "hole_cards": ["Ad", "Kc"],
        "board": ["Ah", "7d", "2c"],
        "pot": 100,
        "to_call": 10,
        "stack": 1000,
        "current_bet": 0,
        "min_raise_to": 0,
        "max_raise_to": 0,
        "big_blind": 10,
        "position": "BTN",
        "players_active": 2,
        "players_to_act": 1,
        "legal_actions": ["fold", "call"],
        "seed": 73,
    }
    raw.update(updates)
    return raw


def corrected_genome(bot_id: str = "corrected-policy"):
    return evolution_strategies.Genome(bot_id, family="corrected-calibrated")


class CorrectedCalibratedBotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_model = corrected._MODEL
        self.previous_correction = corrected._CORRECTION
        corrected._MODEL = None
        corrected._CORRECTION = None

    def tearDown(self) -> None:
        corrected._MODEL = self.previous_model
        corrected._CORRECTION = self.previous_correction

    def test_packaged_artifacts_and_real_audit_predictions_are_pinned(self) -> None:
        model_bytes = corrected.MODEL_PATH.read_bytes()
        correction_bytes = corrected.CORRECTION_PATH.read_bytes()
        self.assertEqual(hashlib.sha256(model_bytes).hexdigest(), corrected.BASE_MODEL_SHA256)
        self.assertEqual(hashlib.sha256(correction_bytes).hexdigest(), corrected.CORRECTION_FILE_SHA256)

        model, curve = corrected._load_assets()
        self.assertEqual(model.model_sha256, corrected.BASE_MODEL_SHA256)
        self.assertEqual(curve.candidate_sha256, corrected.CANDIDATE_SHA256)
        self.assertEqual(curve.portable_transform_sha256, corrected.PORTABLE_TRANSFORM_SHA256)

        # The first public state in the reviewed report has a preserved raw
        # prediction; the runtime model and v2 transform reproduce both.
        raw_share = model.predict(("7s", "As"), ("Th", "Ts", "5h"), 2)
        self.assertEqual(round(raw_share, 10), 0.3123885884)
        self.assertEqual(round(curve.correct(raw_share, 2), 12), 0.430822035846)

        fixture_path = ROOT / "tests/fixtures/equity-correction-v2-golden.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        first_by_players = {row["players_active"]: row for row in fixture["rows"]}
        self.assertEqual(set(first_by_players), set(range(2, 9)))
        for active, row in first_by_players.items():
            actual = curve.correct(row["raw_share"], active)
            self.assertAlmostEqual(actual, float(row["corrected_share"]), delta=5e-12)

    def test_invalid_or_missing_correction_fails_without_fallback(self) -> None:
        raw = corrected.CORRECTION_PATH.read_bytes()
        with self.assertRaisesRegex(corrected.CorrectionArtifactError, "SHA-256"):
            corrected._parse_correction_bytes(raw[:-1])
        with mock.patch.object(corrected, "CORRECTION_FILE_SHA256", hashlib.sha256(b"{}").hexdigest()):
            with self.assertRaisesRegex(corrected.CorrectionArtifactError, "top-level schema"):
                corrected._parse_correction_bytes(b"{}")

        with mock.patch.object(corrected, "CORRECTION_PATH", ROOT / "missing-v2-correction.json"):
            with self.assertRaisesRegex(RuntimeError, "missing or invalid"):
                corrected.make_corrected_calibrated_policy(corrected_genome())
        self.assertIsNone(corrected._MODEL)
        self.assertIsNone(corrected._CORRECTION)

    def test_invalid_base_model_fails_without_publishing_partial_cache(self) -> None:
        with mock.patch.object(
            corrected.equity_runtime,
            "load_model",
            side_effect=corrected.equity_runtime.ArtifactError("model digest mismatch"),
        ) as loader:
            with self.assertRaisesRegex(RuntimeError, "base model.*missing or invalid"):
                corrected.make_corrected_calibrated_policy(corrected_genome("bad-base-model"))
        loader.assert_called_once_with(
            corrected.MODEL_PATH,
            expected_sha256=corrected.BASE_MODEL_SHA256,
        )
        self.assertIsNone(corrected._MODEL)
        self.assertIsNone(corrected._CORRECTION)

    def test_candidate_serialization_and_hashes_are_explicitly_pinned(self) -> None:
        genome = corrected_genome("serialized-corrected-candidate")
        restored = evolution_strategies.Genome.from_dict(json.loads(json.dumps(genome.to_dict())))
        self.assertEqual(restored, genome)
        self.assertEqual(restored.family, "corrected-calibrated")
        self.assertEqual(corrected.BASE_MODEL_SHA256,
                         "7dd0457e02c5bf5d3e3d1c9f06b4f3d043c7343a068092b23c3c3bb6ad6e48fd")
        self.assertEqual(corrected.CANDIDATE_SHA256,
                         "d8321112b47ed593d61f036d40ca9a3a29869ff3a02d04dd735f055d7ea734d3")
        self.assertEqual(corrected.CORRECTION_FILE_SHA256,
                         "3dfb27cfa15e12da01b94c9a69851ae1b0f4e4f3833743b1f740fef54bc51b0d")
        self.assertEqual(corrected.PORTABLE_TRANSFORM_SHA256,
                         "64b4efb1ef361d7b631206f8707815868186336f3030409b08f70633492934d6")

    def test_preflop_matches_original_evolved_policy_and_keeps_bot_id_salt(self) -> None:
        corrected_policy = corrected.make_corrected_calibrated_policy(
            corrected_genome("same-original-bot-id")
        )
        evolved_policy = evolution_strategies.policy_for(
            evolution_strategies.Genome("same-original-bot-id", family="evolved")
        )
        fixtures = (
            preflop_observation(hole_cards=["As", "Ah"], position="BB",
                                legal_actions=["check", "raise"]),
            preflop_observation(hole_cards=["8s", "7s"], position="CO",
                                to_call=80, current_bet=80, pot=300,
                                min_raise_to=180, max_raise_to=1080,
                                legal_actions=["fold", "call", "raise"]),
            preflop_observation(hole_cards=["Kc", "Qd"], position="BB",
                                players_active=5, to_call=40, current_bet=40,
                                pot=200, min_raise_to=100, max_raise_to=1040,
                                legal_actions=["fold", "call", "raise"]),
        )
        for fixture in fixtures:
            for seed in (0, 1, 73, 191, 2**31 - 1):
                raw = {**fixture, "seed": seed}
                with self.subTest(cards=fixture["hole_cards"], seed=seed):
                    self.assertEqual(corrected_policy(raw), evolved_policy(raw))

    def test_multiway_uses_the_matching_curve_once_and_outputs_bounded_share(self) -> None:
        model, curve = corrected._load_assets()
        calls = []

        class FixedModel:
            model_sha256 = corrected.BASE_MODEL_SHA256

            @staticmethod
            def predict(hole_cards, board, players_active):
                calls.append((hole_cards, board, players_active))
                return 0.60

        corrected._MODEL = FixedModel()
        policy = corrected.make_corrected_calibrated_policy(corrected_genome("multiway"))
        raw = postflop_observation(players_active=8, players_to_act=7)
        decision = policy(raw)
        details = decision["diagnostics"]

        expected = curve.correct(0.60, 8)
        self.assertEqual(calls, [(('Ad', 'Kc'), ('Ah', '7d', '2c'), 8)])
        self.assertEqual(details["estimator_raw_share"], expected)
        self.assertEqual(details["opponents_in_pot"], 7)
        self.assertEqual(details["multiway_equity_subtraction"], 0.0)
        self.assertGreaterEqual(details["estimator_raw_share"], 0.0)
        self.assertLessEqual(details["estimator_raw_share"], 1.0)
        self.assertNotEqual(curve.correct(0.60, 2), curve.correct(0.60, 8))
        self.assertIn(decision["action"], raw["legal_actions"])

    def test_assets_load_once_policies_are_fresh_and_decisions_do_no_file_io(self) -> None:
        original_read_bytes = Path.read_bytes
        reads = []

        def count_correction_reads(path):
            if path == corrected.CORRECTION_PATH:
                reads.append(path)
            return original_read_bytes(path)

        genome = corrected_genome("fresh-policy")
        runtime_loader = corrected.equity_runtime.load_model
        with mock.patch.object(Path, "read_bytes", autospec=True, side_effect=count_correction_reads), \
             mock.patch.object(corrected.equity_runtime, "load_model", wraps=runtime_loader) as loader:
            first = corrected.make_corrected_calibrated_policy(genome)
            second = corrected.make_corrected_calibrated_policy(genome)
        self.assertIsNot(first, second)
        self.assertEqual(len(reads), 1)
        loader.assert_called_once_with(corrected.MODEL_PATH, expected_sha256=corrected.BASE_MODEL_SHA256)

        with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("decision performed file I/O")):
            first_result = first(postflop_observation())
            first_result["diagnostics"]["model_metadata"]["correction_candidate_sha256"] = "changed"
            second_result = second(postflop_observation())
        self.assertEqual(
            second_result["diagnostics"]["model_metadata"]["correction_candidate_sha256"],
            corrected.CANDIDATE_SHA256,
        )

    def test_runtime_module_has_no_training_or_reference_imports(self) -> None:
        source = Path(corrected.__file__).read_text(encoding="utf-8")
        parsed = ast.parse(source)
        imported = set()
        for node in ast.walk(parsed):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        self.assertFalse(any(name.startswith(("scripts", "train", "generate_equity")) for name in imported))

    def test_registry_deploys_and_breeds_the_parameterized_corrected_family(self) -> None:
        genome = evolution_strategies.Genome(
            "registered-correction", family="corrected-calibrated",
            params={"call_frequency": 0.83, "bet_size": 0.25},
        )
        child = evolution_strategies.breed(
            genome, None, random.Random(73), "corrected-child", 1,
        )
        self.assertEqual(child.family, "corrected-calibrated")
        self.assertEqual(child.parents, (genome.bot_id,))
        self.assertEqual(len(child.params), len(evolution_strategies.PARAMETER_BOUNDS))
        policy = evolution_strategies.policy_for(genome)
        decision = policy(postflop_observation())
        self.assertEqual(
            decision["diagnostics"]["model_metadata"]["correction_candidate_sha256"],
            corrected.CANDIDATE_SHA256,
        )


if __name__ == "__main__":
    unittest.main()
