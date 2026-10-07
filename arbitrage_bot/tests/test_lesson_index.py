#!/usr/bin/env python3
# arbitrage_bot/tests/test_lesson_index.py  (s168-C1.2, non-CORE)
# Behavioral verify V1..V8 for scripts/lesson_index.py via CLI subprocess (s166-r1).
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable
SCRIPT = ROOT / "scripts" / "lesson_index.py"
INDEX = ROOT / "knowledge" / "lessons_index.json"


def run_cli(*args, timeout=30):
    return subprocess.run(
        [PY, str(SCRIPT), *args],
        capture_output=True, text=True, timeout=timeout, cwd=str(ROOT),
    )


class TestLessonIndex(unittest.TestCase):
    def setUp(self):
        self._saved = INDEX.read_bytes() if INDEX.exists() else None

    def tearDown(self):
        if self._saved is not None:
            INDEX.write_bytes(self._saved)
        elif INDEX.exists():
            INDEX.unlink()

    def test_v1_build_creates_index(self):
        INDEX.unlink(missing_ok=True)
        r = run_cli("--build")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("built count=", r.stdout)
        self.assertTrue(INDEX.exists())

    def test_v2_check_ok_after_build(self):
        run_cli("--build")
        r = run_cli("--check")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("OK", r.stdout)

    def test_v3_check_missing(self):
        INDEX.unlink(missing_ok=True)
        r = run_cli("--check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("MISSING", r.stdout)

    def test_v4_check_stale(self):
        run_cli("--build")
        d = json.loads(INDEX.read_text(encoding="utf-8"))
        d["source_sha256_short"] = "0" * 16
        INDEX.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        r = run_cli("--check")
        self.assertEqual(r.returncode, 2)
        self.assertIn("STALE", r.stdout)

    def test_v5_stat_shape(self):
        run_cli("--build")
        r = run_cli("--stat")
        self.assertEqual(r.returncode, 0)
        self.assertIn("by_style", r.stdout)
        self.assertIn("by_category", r.stdout)

    def test_v6_idempotency_sha(self):
        run_cli("--build")
        s1 = json.loads(INDEX.read_text(encoding="utf-8"))["source_sha256_short"]
        run_cli("--build")
        s2 = json.loads(INDEX.read_text(encoding="utf-8"))["source_sha256_short"]
        self.assertEqual(s1, s2)

    def test_v7_entry_schema(self):
        run_cli("--build")
        d = json.loads(INDEX.read_text(encoding="utf-8"))
        req = {"id", "title", "line_start", "line_end", "style", "category"}
        for e in d["entries"]:
            self.assertTrue(req.issubset(e.keys()), e.get("id"))

    def test_v8_count_sane(self):
        run_cli("--build")
        d = json.loads(INDEX.read_text(encoding="utf-8"))
        self.assertGreaterEqual(d["count"], 100)
        self.assertEqual(d["count"], len(d["entries"]))


    def test_v9_auto_log_category(self):
        # s170-B: auto_log содержит \u2265 50 dated-\u0437\u0430\u043f\u0438\u0441\u0435\u0439 (\u043b\u043e\u0433\u0438 \u0430\u0432\u0442\u043e\u0441\u0435\u0441\u0441\u0438\u0439).
        run_cli("--build")
        d = json.loads(INDEX.read_text(encoding="utf-8"))
        auto = [e for e in d["entries"] if e["category"] == "auto_log"]
        self.assertGreaterEqual(len(auto), 50, "auto_log=%d < 50" % len(auto))
        for e in auto:
            self.assertEqual(e["style"], "dated", e["id"])

    def test_v10_python_syntax_picks_targets(self):
        # s170-B: python_syntax keywords л\u043e\u0432\u044f\u0442 f-string/re.search/argparse.
        run_cli("--build")
        d = json.loads(INDEX.read_text(encoding="utf-8"))
        by_id = {e["id"]: e for e in d["entries"]}
        for i in ("s153-r1", "s153-r3", "s168-r5"):
            self.assertEqual(by_id[i]["category"], "python_syntax", i)

    def test_v11_misc_ratio_below_40(self):
        # s170-B guard (s179: ratio instead of absolute threshold).
        run_cli("--build")
        d = json.loads(INDEX.read_text(encoding="utf-8"))
        total = len(d["entries"])
        misc = sum(1 for e in d["entries"] if e["category"] == "misc")
        ratio = misc / total if total else 0.0
        self.assertLessEqual(ratio, 0.40,
                             "misc_ratio=%.3f (misc=%d/%d) > 0.40" % (ratio, misc, total))

    def test_v12_category_set_has_new(self):
        # s170-B: \u043d\u043e\u0432\u044b\u0435 \u043a\u0430\u0442\u0435\u0433\u043e\u0440\u0438\u0438 \u043f\u0440\u0438\u0441\u0443\u0442\u0441\u0442\u0432\u0443\u044e\u0442.
        run_cli("--build")
        d = json.loads(INDEX.read_text(encoding="utf-8"))
        cats = set(e["category"] for e in d["entries"])
        self.assertIn("auto_log", cats)
        self.assertIn("python_syntax", cats)


if __name__ == "__main__":
    unittest.main()
