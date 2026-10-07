"""Tests for scripts/lesson_embed.py (s174).

Verifies: module loads, MODEL=bge-m3, no prefixes, cosine math,
body extraction, MAX_CHARS constant, embeddings file validity.
"""
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "lesson_embed.py"
EMB_PATH = ROOT / "knowledge" / "lessons_embeddings.jsonl"


def _load_module():
    spec = importlib.util.spec_from_file_location("lesson_embed_mod", str(SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestLessonEmbed(unittest.TestCase):

    def test_v1_module_loads(self):
        mod = _load_module()
        self.assertTrue(hasattr(mod, "MODEL"))
        self.assertTrue(hasattr(mod, "cosine"))
        self.assertTrue(hasattr(mod, "embed"))
        self.assertTrue(hasattr(mod, "_extract_body"))

    def test_v2_model_is_bge_m3(self):
        mod = _load_module()
        self.assertEqual(mod.MODEL, "bge-m3")

    def test_v3_no_prefixes_for_bge_m3(self):
        mod = _load_module()
        self.assertEqual(mod.DOC_PREFIX, "")
        self.assertEqual(mod.QUERY_PREFIX, "")

    def test_v4_cosine_identical(self):
        mod = _load_module()
        v = [1.0, 2.0, 3.0, 4.0]
        self.assertAlmostEqual(mod.cosine(v, v), 1.0, places=9)

    def test_v5_cosine_orthogonal(self):
        mod = _load_module()
        self.assertAlmostEqual(mod.cosine([1.0, 0.0], [0.0, 1.0]), 0.0, places=9)

    def test_v6_cosine_zero_vector(self):
        mod = _load_module()
        self.assertEqual(mod.cosine([0.0, 0.0], [1.0, 1.0]), 0.0)
        self.assertEqual(mod.cosine([], [1.0]), 0.0)
        self.assertEqual(mod.cosine([1.0, 2.0], [1.0]), 0.0)

    def test_v7_extract_body(self):
        mod = _load_module()
        lines = ["skip0", "skip1", "line2", "line3", "line4", "line5"]
        # 1-based inclusive: 3..5 -> "line2\nline3\nline4"
        body = mod._extract_body(lines, 3, 5)
        self.assertEqual(body, "line2\nline3\nline4")

    def test_v8_max_chars_constant(self):
        mod = _load_module()
        self.assertGreater(mod.MAX_CHARS, 0)
        self.assertLessEqual(mod.MAX_CHARS, 2048)

    def test_v9_embeddings_file_valid(self):
        if not EMB_PATH.exists():
            self.skipTest("embeddings file not built yet")
        with EMB_PATH.open("r", encoding="utf-8") as f:
            meta_line = f.readline().strip()
        obj = json.loads(meta_line)
        m = obj.get("_meta")
        self.assertIsNotNone(m)
        self.assertEqual(m.get("model"), "bge-m3")
        self.assertEqual(m.get("dim"), 1024)
        self.assertGreater(m.get("count", 0), 0)
        self.assertEqual(m.get("skipped_count"), 0)


if __name__ == "__main__":
    unittest.main()
