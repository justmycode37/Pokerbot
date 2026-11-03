from __future__ import annotations

import copy
import unittest

from pokerbot import evolution
from pokerbot.evolution_strategies import DEFAULT_PARAMS, PARAMETER_BOUNDS, Genome
from scripts.seed_evolution import generate_proposal, project_training_report


def _training_rows() -> list[dict[str, object]]:
    rows = []
    for index in range(8):
        family = "evolved" if index % 2 == 0 else "adaptive"
        params = dict(DEFAULT_PARAMS)
        params.update({
            "opening_shift": -0.105 + index * 0.027,
            "opening_frequency": 0.50 + index * 0.055,
            "call_margin": -0.075 + index * 0.022,
            "postflop_call_margin": -0.015 + index * 0.012,
            "call_frequency": 0.47 + index * 0.061,
            "value_raise_threshold": 0.57 + index * 0.031,
            "raise_frequency": 0.24 + index * 0.093,
            "bet_size": 0.18 + index * 0.081,
            "bluff_frequency": 0.01 + index * 0.021,
            "short_stack_bb": 4.5 + index * 1.5,
            "short_stack_cutoff": 0.47 + index * 0.036,
            "multiway_penalty": 0.02 + index * 0.009,
            "position_sensitivity": 0.002 + index * 0.005,
        })
        rows.append({
            "bot_id": f"round6-candidate-{index + 1:02d}",
            "family": family,
            "params": params,
            "parents": [f"ancestor-{index + 1:02d}"],
            "played": 128,
            "won": 28 - index,
            "rank": index + 1,
            "status": "survived",
        })
    return rows


class SeedEvolutionTests(unittest.TestCase):
    def test_deterministic_canonical_bounded_diverse_proposal(self):
        rounds = {6: _training_rows()}
        first, first_metadata = generate_proposal(rounds)
        second, second_metadata = generate_proposal(rounds)

        self.assertEqual(first, second)
        self.assertEqual(first_metadata, second_metadata)
        self.assertEqual(len(first), 8)
        self.assertEqual(first_metadata["candidate_family_counts"], {"adaptive": 4, "evolved": 4})

        identifiers = [genome["bot_id"] for genome in first]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        genotypes = [tuple(sorted(genome["params"].items())) for genome in first]
        self.assertEqual(len(genotypes), len(set(genotypes)))

        for raw in first:
            genome = Genome.from_dict(raw)
            self.assertEqual(genome.to_dict(), raw)
            for name, value in genome.params.items():
                low, high = PARAMETER_BOUNDS[name]
                self.assertGreaterEqual(value, low)
                self.assertLessEqual(value, high)

        elite_ids = [entry["bot_id"] for entry in first_metadata["exact_elites"]]
        self.assertEqual(elite_ids[0], "round6-candidate-01")
        self.assertEqual(len(elite_ids), 4)
        self.assertEqual(
            [entry["within_round_training_rank"] for entry in first_metadata["exact_elites"]],
            [1, 8, 5, 2],
        )

        variants = first_metadata["variants"]
        self.assertEqual(len(variants), 4)
        self.assertEqual([item["mutation_seed"] for item in variants], [20261202, 20261302, 20261402, 20261502])
        for item in variants:
            self.assertEqual(len(item["changed_parameters"]), 3)
            self.assertIn("exploration hypothesis", item["label"])
            self.assertIn(item["parent_ids"][0], elite_ids)

    def test_training_projection_ignores_validation_and_confirmation(self):
        rows = _training_rows()
        original = {"bots": copy.deepcopy(rows)}
        contaminated = {"bots": copy.deepcopy(rows)}
        contaminated["validation"] = {"heldout": [{"outcome": "must be ignored"}]}
        contaminated["confirmation"] = {"heldout": [{"outcome": "must be ignored"}]}
        for row in contaminated["bots"]:
            row["validation"] = {"outcome": "must be ignored"}
            row["confirmation"] = {"outcome": "must be ignored"}
            row["nested_private_data"] = {"outcome": "must be ignored"}

        original_projection = project_training_report(original)
        contaminated_projection = project_training_report(contaminated)
        self.assertEqual(original_projection, contaminated_projection)
        self.assertTrue(all(set(row) == set((
            "bot_id", "family", "params", "parents", "played", "won", "rank", "status",
        )) for row in contaminated_projection))

        original_seeds, _ = generate_proposal({6: original_projection})
        contaminated_seeds, _ = generate_proposal({6: contaminated_projection})
        self.assertEqual(original_seeds, contaminated_seeds)

    def test_successor_parser_accepts_proposal_with_population_capacity(self):
        seeds, _ = generate_proposal({6: _training_rows()})
        config = evolution._validate_config({
            "players": 8,
            "population": 16,
            "matches": 128,
            "validation_matches": 128,
            "confirmation_matches": 512,
            "seed": 20261102,
            "evaluation_namespace": "evolution-next-20261102-seed-v1",
            "seed_genomes": seeds,
        })
        self.assertEqual(len(config["seed_genomes"]), 8)
        self.assertLessEqual(5 + len(config["seed_genomes"]), config["population"])


if __name__ == "__main__":
    unittest.main()
