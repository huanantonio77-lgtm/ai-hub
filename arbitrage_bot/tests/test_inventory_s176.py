"""s176: тесты завхоза (inventory.py)."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

def _load():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "inv_mod", ROOT / "scripts" / "inventory.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestInventory(unittest.TestCase):
    def test_scans_python_files(self):
        mod = _load()
        inv = mod.build_inventory()
        self.assertGreater(inv["counts"]["py"], 50)
        self.assertGreater(inv["counts"]["json"], 50)

    def test_detects_duplicate_limit_registries(self):
        mod = _load()
        inv = {
            "json_files": [
                "provider_limits.json",
                ".cache/system/token_limits.json",
                "other.json",
            ]
        }
        gaps = mod.detect_duplicate_registries(inv)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["kind"], "DUPLICATE-LIMIT-REGISTRY")

    def test_search_finds_limits(self):
        mod = _load()
        inv = mod.build_inventory()
        hits = mod._search(inv, "limit")
        self.assertGreaterEqual(len(hits), 3)


if __name__ == "__main__":
    unittest.main()
