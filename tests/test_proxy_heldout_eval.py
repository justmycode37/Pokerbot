import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("proxy_heldout_eval", ROOT / "scripts" / "proxy_heldout_eval.py")
proxy = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(proxy)


class ProxyHeldoutEvalGuardTests(unittest.TestCase):
    def test_rejects_canonical_pool_and_eval_domains(self):
        for domain in ("validation-pool", "confirmation-pool", "training-opponents", "ns:validation-pool"):
            with self.assertRaises(ValueError):
                proxy.evaluate([], 1, 1, pool_domain=domain)
        for domain in ("training", "validation", "confirmation", "run-a:validation"):
            with self.assertRaises(ValueError):
                proxy.evaluate([], 1, 1, eval_domain=domain)

    def test_rejects_duplicate_candidate_ids(self):
        candidate = {"bot_id": "duplicate-id", "family": "fast", "params": {}, "parents": [], "generation": 0}
        other = dict(candidate, family="tight-passive")
        with self.assertRaisesRegex(ValueError, "duplicate candidate id"):
            proxy.evaluate([candidate, other], 1, 1)


if __name__ == "__main__":
    unittest.main()
