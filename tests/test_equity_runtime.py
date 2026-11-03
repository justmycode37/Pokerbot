from __future__ import annotations

import copy
import hashlib
import itertools
import json
import math
import sys
import tempfile
import unittest
from importlib.resources import as_file, files
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pokerbot import equity_runtime as runtime


FIXTURE_DIRECTORY = ROOT / "tests" / "fixtures"
GOLDEN_PATH = FIXTURE_DIRECTORY / "equity-runtime-golden-v1.json"
MOCK_MODEL_PATH = FIXTURE_DIRECTORY / "equity-runtime-mock-v1.model.json"
MOCK_MODEL_SHA256 = "525c6562a64561a914179998d865c1d3c0d5542b3c03cbb082ed2f50adf9eadd"
PUBLISHED_MODEL_SHA256 = "7dd0457e02c5bf5d3e3d1c9f06b4f3d043c7343a068092b23c3c3bb6ad6e48fd"
TRAINER_SOURCE_SHA256 = "0ec6cdabd27518187b61ee77fadb076fed4beefe2d1937c28add01375f8ce96e"
CARDS_SOURCE_SHA256 = "89a27b217402dd3bccda1d75ac16be52d477484e7e4115896ea135e6ff0efc12"


class EquityRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory(prefix="equity-runtime-test-")
        cls.directory = Path(cls._temporary.name)
        cls.fixture = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        cls.artifact = json.loads(MOCK_MODEL_PATH.read_text(encoding="utf-8"))
        cls.model_path = MOCK_MODEL_PATH
        cls.expected_sha256 = MOCK_MODEL_SHA256
        if cls.fixture["fixture_format"] != "pokerbot-equity-runtime-golden-v1":
            raise AssertionError("unsupported golden fixture format")
        if cls.fixture["state_count"] != 224 or len(cls.fixture["states"]) != 224:
            raise AssertionError("golden fixture must contain exactly 224 states")
        if cls.fixture["mock_model_sha256"] != MOCK_MODEL_SHA256:
            raise AssertionError("golden fixture mock model digest changed")
        if cls.fixture["trainer_source"] != "scripts/train_equity_lookup.py":
            raise AssertionError("golden fixture trainer source identity changed")
        if cls.fixture["trainer_source_sha256"] != TRAINER_SOURCE_SHA256:
            raise AssertionError("golden fixture trainer source digest changed")
        if cls.fixture["cards_source_sha256"] != CARDS_SOURCE_SHA256:
            raise AssertionError("golden fixture card source digest changed")
        if hashlib.sha256(cls.model_path.read_bytes()).hexdigest() != cls.expected_sha256:
            raise AssertionError("golden fixture mock model bytes changed")
        cls.runtime_model = runtime.load_model(
            cls.model_path, expected_sha256=cls.expected_sha256
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    @staticmethod
    def _write_model(artifact: dict[str, object], path: Path) -> str:
        path.write_text(json.dumps(artifact, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _write_variant(self, artifact: dict[str, object], name: str) -> tuple[Path, str]:
        path = self.directory / (name + ".json")
        digest = self._write_model(artifact, path)
        return path, digest

    def test_runtime_matches_frozen_trainer_outputs_on_224_public_states(self) -> None:
        def python_311_sum(values, start=0):
            # Python 3.12 changed float summation. Exercise the earlier order
            # even when this test runs on the fixture's Python 3.12 version.
            result = start
            for value in values:
                result += value
            return result

        observed_streets: set[int] = set()
        observed_players: set[int] = set()
        for index, vector in enumerate(self.fixture["states"]):
            hole = vector["hole_cards"]
            board = vector["board"]
            active = vector["players_active"]
            observed_streets.add(len(board))
            observed_players.add(active)
            with self.subTest(state=index):
                self.assertEqual(
                    tuple(vector["features"]),
                    runtime.extract_features(hole, board, active),
                )
                for name, summation in (("native", sum), ("python_311", python_311_sum)):
                    with self.subTest(summation=name), mock.patch.object(
                        runtime, "sum", summation, create=True
                    ):
                        self.assertAlmostEqual(
                            vector["prediction"],
                            self.runtime_model.predict(hole, board, active),
                            delta=math.ulp(vector["prediction"]),
                        )
                self.assertEqual(
                    runtime.extract_features(tuple(reversed(hole)), tuple(reversed(board)), active),
                    runtime.extract_features(hole, board, active),
                )
        self.assertEqual({3, 4, 5}, observed_streets)
        self.assertEqual(set(range(2, 9)), observed_players)

    def test_all_24_global_suit_maps_preserve_representative_public_states(self) -> None:
        suit_permutations = tuple(itertools.permutations("cdhs"))
        self.assertEqual(24, len(suit_permutations))
        for case_index, case in enumerate(self.fixture["edge_cases"]):
            hole = case["hole_cards"]
            board = case["board"]
            active = case["players_active"]
            expected_features = tuple(case["features"])
            expected_prediction = self.runtime_model.predict(hole, board, active)
            self.assertAlmostEqual(
                case["prediction"], expected_prediction, delta=math.ulp(case["prediction"])
            )
            for permutation in suit_permutations:
                suit_map = dict(zip("cdhs", permutation))
                mapped_hole = [card[0] + suit_map[card[1]] for card in reversed(hole)]
                mapped_board = [card[0] + suit_map[card[1]] for card in reversed(board)]
                with self.subTest(case=case_index, permutation=permutation):
                    self.assertEqual(
                        expected_features,
                        runtime.extract_features(mapped_hole, mapped_board, active),
                    )
                    self.assertEqual(
                        expected_prediction,
                        self.runtime_model.predict(mapped_hole, mapped_board, active),
                    )

    def test_v3_draw_and_blocker_edge_cases(self) -> None:
        open_ended = dict(
            zip(
                runtime.FEATURE_NAMES,
                runtime.extract_features(("9d", "8c"), ("7h", "6s", "2d"), 2),
            )
        )
        gutshot = dict(
            zip(
                runtime.FEATURE_NAMES,
                runtime.extract_features(("9d", "8c"), ("7h", "5s", "2d"), 2),
            )
        )
        self.assertEqual(2.0, open_ended["straight_draw_out_ranks"])
        self.assertEqual(1.0, open_ended["straight_draw_open_ended_like"])
        self.assertEqual(1.0, gutshot["straight_draw_out_ranks"])
        self.assertEqual(0.0, gutshot["straight_draw_open_ended_like"])

        river = dict(
            zip(
                runtime.FEATURE_NAMES,
                runtime.extract_features(
                    ("As", "Kd"), ("2s", "3s", "4s", "8d", "Qh"), 2
                ),
            )
        )
        for name in (
            "flush_draw_outs",
            "flush_draw_present",
            "straight_draw_out_ranks",
            "straight_draw_open_ended_like",
        ):
            self.assertEqual(0.0, river[name], name)
        blocker = dict(
            zip(
                runtime.FEATURE_NAMES,
                runtime.extract_features(("As", "Kd"), ("2s", "3s", "4d"), 2),
            )
        )
        self.assertEqual(2.0, blocker["hole_high_board_suit_count"])
        self.assertEqual(1.0, blocker["hole_low_board_suit_count"])

    def test_public_state_validation_and_private_input_boundary(self) -> None:
        valid_hole = ("As", "Kd")
        valid_board = ("2c", "3d", "4h")
        invalid_cases = (
            ("As", "As"),
            ("As",),
            "AsKd",
            ("As", "bad"),
        )
        for hole in invalid_cases:
            with self.subTest(hole=hole), self.assertRaises(runtime.DataError):
                self.runtime_model.predict(hole, valid_board, 2)  # type: ignore[arg-type]
        for board in (
            ("2c", "3d"),
            ("2c", "3d", "4h", "5s", "6c", "7d"),
            ("2c", "3d", "4h", "As"),
            ("2c", "3d", "bad"),
            "2c3d4h",
        ):
            with self.subTest(board=board), self.assertRaises(runtime.DataError):
                self.runtime_model.predict(valid_hole, board, 2)  # type: ignore[arg-type]
        for active in (True, False, 1, 9, 2.0, "2"):
            with self.subTest(active=active), self.assertRaises(runtime.DataError):
                self.runtime_model.predict(valid_hole, valid_board, active)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            self.runtime_model.predict(valid_hole, valid_board, 2, private_cards=("Qd",))  # type: ignore[call-arg]
        self.assertEqual(
            runtime.extract_features(("10H", " kd "), valid_board, 2),
            runtime.extract_features(("Th", "Kd"), valid_board, 2),
        )

    def test_packaged_model_is_byte_pinned_and_predicts_from_package_resources(self) -> None:
        packaged_model = files("pokerbot").joinpath("models/postflop-equity-v1.json")
        with as_file(packaged_model) as model_path:
            inference = runtime.load_model(
                model_path, expected_sha256=PUBLISHED_MODEL_SHA256
            )
        self.assertEqual(PUBLISHED_MODEL_SHA256, inference.sha256)
        self.assertEqual("public-postflop-features-v3", inference.metadata["feature_version"])
        share = inference.predict(("As", "Kd"), ("2c", "3d", "4h"), 2)
        self.assertGreaterEqual(share, 0.0)
        self.assertLessEqual(share, 1.0)

        manifest_resource = files("pokerbot").joinpath(
            "models/postflop-equity-v1.manifest.json"
        )
        manifest = json.loads(manifest_resource.read_text(encoding="utf-8"))
        self.assertEqual(PUBLISHED_MODEL_SHA256, manifest["artifact"]["sha256"])
        self.assertEqual(176343, manifest["artifact"]["bytes"])
        self.assertEqual(32, manifest["artifact"]["feature_count"])
        self.assertEqual(63, manifest["artifact"]["tree_count"])
        self.assertEqual(6, manifest["artifact"]["max_depth"])

    def test_model_digest_is_required_and_checked_before_json_parsing(self) -> None:
        with self.assertRaises(TypeError):
            runtime.load_model(self.model_path)  # type: ignore[call-arg]
        with mock.patch.object(runtime.json, "loads", side_effect=AssertionError("parsed before digest")):
            with self.assertRaisesRegex(runtime.ArtifactError, "does not match"):
                runtime.load_model(self.model_path, expected_sha256="0" * 64)
        with self.assertRaisesRegex(runtime.ArtifactError, "lowercase SHA-256"):
            runtime.load_model(self.model_path, expected_sha256="not-a-digest")
        self.assertEqual(self.expected_sha256, self.runtime_model.model_sha256)
        self.assertEqual(self.expected_sha256, self.runtime_model.sha256)

    def test_oversized_and_tampered_artifacts_fail_closed(self) -> None:
        oversized = self.directory / "oversized-model.json"
        oversized.write_bytes(b" " * (runtime.MAX_JSON_OBJECT_BYTES + 1))
        oversized_sha = hashlib.sha256(oversized.read_bytes()).hexdigest()
        with self.assertRaisesRegex(runtime.ArtifactError, "4 MiB"):
            runtime.load_model(oversized, expected_sha256=oversized_sha)

        tampered = copy.deepcopy(self.artifact)
        tampered["feature_version"] = "public-postflop-features-v2"
        path, digest = self._write_variant(tampered, "tampered-metadata")
        with self.assertRaisesRegex(runtime.ArtifactError, "feature_version"):
            runtime.load_model(path, expected_sha256=digest)
        with self.assertRaisesRegex(runtime.ArtifactError, "does not match"):
            runtime.load_model(path, expected_sha256=self.expected_sha256)

        malformed = self.directory / "malformed.json"
        malformed.write_bytes(b'{"duplicate":1,"duplicate":2}')
        malformed_sha = hashlib.sha256(malformed.read_bytes()).hexdigest()
        with self.assertRaisesRegex(runtime.ArtifactError, "duplicate key"):
            runtime.load_model(malformed, expected_sha256=malformed_sha)

    def test_artifact_metadata_types_finiteness_and_graph_bounds_are_enforced(self) -> None:
        bad_metadata = copy.deepcopy(self.artifact)
        bad_metadata["format_version"] = True
        variants: list[tuple[str, dict[str, object]]] = [("bool-format", bad_metadata)]

        bad_count = copy.deepcopy(self.artifact)
        bad_count["training_row_count"] = True
        variants.append(("bool-row-count", bad_count))

        for field in ("feature", "value", "left"):
            bad_node = copy.deepcopy(self.artifact)
            bad_node["trees"][0] = [  # type: ignore[index]
                [True, 0.25, 1, 2] if field == "feature" else [0, 0.25, 1, 2],
                [-1, True if field == "value" else 0.25, -1, -1],
                [-1, 0.75, -1, -1],
            ]
            if field == "left":
                bad_node["trees"][0][0][2] = True  # type: ignore[index]
            variants.append(("bool-node-" + field, bad_node))

        too_many_trees = copy.deepcopy(self.artifact)
        too_many_trees["hyperparameters"]["trees"] = runtime.MAX_TREES + 1  # type: ignore[index]
        too_many_trees["trees"] = [[[-1, 0.5, -1, -1]]] * (runtime.MAX_TREES + 1)
        variants.append(("tree-count", too_many_trees))

        too_many_nodes = copy.deepcopy(self.artifact)
        too_many_nodes["trees"][0] = [[-1, 0.5, -1, -1]] * (runtime.MAX_TREE_NODES + 1)  # type: ignore[index]
        variants.append(("node-count", too_many_nodes))

        too_deep = copy.deepcopy(self.artifact)
        too_deep["hyperparameters"]["max_depth"] = 1  # type: ignore[index]
        too_deep["trees"][0] = [  # type: ignore[index]
            [0, 0.0, 1, 2],
            [0, 0.0, 3, 4],
            [-1, 0.6, -1, -1],
            [-1, 0.4, -1, -1],
            [-1, 0.8, -1, -1],
        ]
        variants.append(("depth", too_deep))

        shared_child = copy.deepcopy(self.artifact)
        shared_child["trees"][0] = [  # type: ignore[index]
            [0, 0.0, 1, 2],
            [0, 0.0, 3, 4],
            [0, 0.0, 4, 5],
            [-1, 0.2, -1, -1],
            [-1, 0.4, -1, -1],
            [-1, 0.6, -1, -1],
        ]
        variants.append(("shared-child", shared_child))

        unreachable = copy.deepcopy(self.artifact)
        unreachable["trees"][0] = [  # type: ignore[index]
            [-1, 0.5, -1, -1],
            [-1, 0.6, -1, -1],
        ]
        variants.append(("unreachable", unreachable))

        cycle = copy.deepcopy(self.artifact)
        cycle["trees"][0] = [  # type: ignore[index]
            [0, 0.0, 1, 2],
            [0, 0.0, 2, 3],
            [0, 0.0, 1, 3],
            [-1, 0.5, -1, -1],
        ]
        variants.append(("cycle", cycle))

        for name, artifact in variants:
            with self.subTest(variant=name):
                path, digest = self._write_variant(artifact, "invalid-" + name)
                with self.assertRaises(runtime.ArtifactError):
                    runtime.load_model(path, expected_sha256=digest)

        nonfinite = self.directory / "nonfinite.json"
        raw = json.dumps(self.artifact, sort_keys=True, separators=(",", ":")).replace(
            '"format_version":1', '"format_version":1,"extra":1e999'
        )
        nonfinite.write_text(raw, encoding="utf-8")
        nonfinite_sha = hashlib.sha256(nonfinite.read_bytes()).hexdigest()
        with self.assertRaisesRegex(runtime.ArtifactError, "non-finite"):
            runtime.load_model(nonfinite, expected_sha256=nonfinite_sha)

    def test_inference_object_metadata_and_predictions_are_immutable_and_io_free(self) -> None:
        source_keys = set(self.runtime_model.metadata["source_sha256"])
        self.assertEqual(
            {"scripts/train_equity_lookup.py", "pokerbot/cards.py"}, source_keys
        )
        with self.assertRaises(TypeError):
            self.runtime_model.metadata["new"] = "value"  # type: ignore[index]
        with self.assertRaises(TypeError):
            self.runtime_model.metadata["hyperparameters"]["trees"] = 0  # type: ignore[index]
        with self.assertRaises(TypeError):
            self.runtime_model._trees[0][0][1] = 0.0  # type: ignore[index]

        original_prediction = self.runtime_model.predict(("As", "Kd"), ("2c", "3d", "4h"), 2)
        with mock.patch("builtins.open", side_effect=AssertionError("predict performed I/O")):
            with mock.patch.object(Path, "open", side_effect=AssertionError("predict performed I/O")):
                repeated = self.runtime_model.predict(("As", "Kd"), ("2c", "3d", "4h"), 2)
        self.assertEqual(original_prediction, repeated)
        with self.assertRaises((AttributeError, TypeError)):
            self.runtime_model.model_sha256 = "0" * 64  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
