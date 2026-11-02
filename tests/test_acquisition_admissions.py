import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import acquisition_admissions as admissions


class AdmissionPortabilityTests(unittest.TestCase):
    def test_legacy_absolute_capture_is_relocated_into_checkout(self):
        root = Path("/checkout/Pokerbot")
        legacy = "/Users/collector/Documents/Pokerbot/data/captures/hand.json"
        self.assertEqual(admissions._provenance_path(root, legacy),
                         root / "data/captures/hand.json")
        for value in ("/outside/hand.json", "../hand.json",
                      "/old/data/../hand.json"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                admissions._provenance_path(root, value)

    def test_real_ledger_never_reads_outside_its_checkout(self):
        root = admissions.ROOT.resolve()
        original = Path.read_bytes
        reads = []

        def confined_read(path):
            self.assertTrue(path.resolve().is_relative_to(root), str(path))
            reads.append(path)
            return original(path)

        with patch.object(Path, "read_bytes", confined_read):
            result = admissions.verify(root)
        self.assertEqual(result["admitted_decisions"], 606)
        self.assertEqual(result["verified_provenance_files"], 816)
        self.assertTrue(reads)


if __name__ == "__main__":
    unittest.main()
