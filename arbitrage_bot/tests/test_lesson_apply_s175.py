#!/usr/bin/env python3
# test_lesson_apply_s175.py (s175, non-CORE)
# Behavioral verify for hybrid rerank v2 (composite key + 0.3x cosine + tier).
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable
SCRIPT = ROOT / "scripts" / "lesson_apply.py"
SRC = SCRIPT.read_text(encoding="utf-8")


class HybridRerankV2(unittest.TestCase):

    def test_s175_marker_present(self):
        self.assertIn("s175: hybrid rerank v2", SRC)

    def test_s175_composite_key_replaced_by_id(self):
        self.assertIn("by_key", SRC)
        self.assertNotIn("by_id[r.get", SRC)

    def test_s175_semantic_top5_strictly_descending(self):
        r = subprocess.run(
            [PY, str(SCRIPT), "--suggest", "--top", "5", "--semantic"],
            capture_output=True, text=True, timeout=60, cwd=str(ROOT),
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        scores = [float(m) for m in re.findall(r"\[([0-9.]+)\]", r.stdout)]
        self.assertEqual(len(scores), 5, r.stdout)
        for i in range(4):
            self.assertGreater(scores[i], scores[i + 1],
                               "tie at position %d: %r" % (i, scores))


if __name__ == "__main__":
    unittest.main()
