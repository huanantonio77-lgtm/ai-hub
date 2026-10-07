#!/usr/bin/env python3
# arbitrage_bot/tests/test_openalex_client_s175.py (s175, non-CORE)
# Mock-based tests for scripts/research/openalex_client.py (no network).
import importlib.util
import json
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "scripts" / "research" / "openalex_client.py"


def _load():
    spec = importlib.util.spec_from_file_location("oa_mod", str(CLIENT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class OpenAlexClientS175(unittest.TestCase):

    def test_build_url_contains_search_and_mailto(self):
        mod = _load()
        url = mod.build_url("RL DEX 2024", 5)
        self.assertIn("api.openalex.org/works", url)
        self.assertIn("search=RL+DEX+2024", url)
        self.assertIn("per_page=5", url)
        self.assertIn("mailto=", url)

    def test_normalize_work_schema(self):
        mod = _load()
        work = {
            "id": "https://openalex.org/W123",
            "display_name": "Foo Bar",
            "publication_year": 2024,
            "doi": "https://doi.org/10.1/x",
            "cited_by_count": 7,
            "primary_location": {"source": {"display_name": "J. Foo"}},
        }
        n = mod.normalize(work)
        self.assertEqual(n["id"], "https://openalex.org/W123")
        self.assertEqual(n["title"], "Foo Bar")
        self.assertEqual(n["year"], 2024)
        self.assertEqual(n["source"], "J. Foo")
        self.assertEqual(n["cited_by"], 7)

    def test_search_works_mocked_no_network(self):
        mod = _load()
        fake = {"results": [{
            "id": "https://openalex.org/W999",
            "display_name": "Mock Paper",
            "publication_year": 2025,
            "doi": None,
            "cited_by_count": 1,
            "primary_location": {"source": {"display_name": "Mock J"}},
        }]}
        class FakeResp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return json.dumps(fake).encode("utf-8")
        with mock.patch("urllib.request.urlopen", return_value=FakeResp()):
            items = mod.search_works("anything", per_page=1, timeout=5)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Mock Paper")


if __name__ == "__main__":
    unittest.main()
