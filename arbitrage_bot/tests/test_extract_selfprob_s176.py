"""s176: тесты extract --self-problem."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

def _load_extract():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "extract_mod", ROOT / "scripts" / "research" / "extract.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestSelfProblem(unittest.TestCase):
    def test_self_proposals_path(self):
        mod = _load_extract()
        self.assertTrue(hasattr(mod, "SELF_PROPOSALS"))
        self.assertIn("SELF_PROPOSALS.jsonl", str(mod.SELF_PROPOSALS))

    def test_formulate_query_fallback_on_error(self):
        mod = _load_extract()
        # _ollama с недостижимым URL вернёт "ERROR: ..."
        q = mod.formulate_query("test problem", model="__nonexistent__")
        # fallback: если ошибка — возвращает problem[:120]
        self.assertTrue(isinstance(q, str))
        self.assertGreater(len(q), 0)


if __name__ == "__main__":
    unittest.main()
