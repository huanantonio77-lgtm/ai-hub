#!/usr/bin/env python3
# arbitrage_bot/tests/test_lesson_apply.py  (s168-A1.4, non-CORE)
# Behavioral verify V1..V8 for scripts/lesson_apply.py via CLI subprocess (s166-r1).
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import importlib.util
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable
SCRIPT = ROOT / "scripts" / "lesson_apply.py"
APPS = ROOT / "knowledge" / "lesson_applications.jsonl"
SUGGEST = ROOT / "self" / "curator"


def run_cli(*args, env_extra=None, timeout=30):
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [PY, str(SCRIPT), *args],
        capture_output=True, text=True, timeout=timeout,
        cwd=str(ROOT), env=env,
    )




def _load_module():
    spec = importlib.util.spec_from_file_location("lesson_apply_mod", str(SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestLessonApply(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._apps_bak = APPS.read_bytes() if APPS.exists() else None

    @classmethod
    def tearDownClass(cls):
        if cls._apps_bak is not None:
            APPS.write_bytes(cls._apps_bak)
        elif APPS.exists():
            APPS.unlink()

    def test_v1_suggest_runs(self):
        r = run_cli("--suggest", "--top", "3", "--session", "sTEST")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("lesson_apply:", r.stdout)

    def test_v2_suggest_writes_file(self):
        run_cli("--suggest", "--top", "3", "--session", "sTEST")
        sf = SUGGEST / "lesson_suggest_sTEST.json"
        self.assertTrue(sf.exists(), "suggest file not written")
        d = json.loads(sf.read_text(encoding="utf-8"))
        self.assertEqual(d["session"], "sTEST")
        self.assertIsInstance(d["ids"], list)
        sf.unlink(missing_ok=True)

    def test_v3_mark_appends(self):
        # работаем на временном APPS через подмену родительской папки невозможно —
        # используем реальный файл, восстановим в tearDownClass.
        before = APPS.read_text(encoding="utf-8").count("\n") if APPS.exists() else 0
        r = run_cli("--mark", "sTEST-id", "--evidence", "test", "--session", "sTEST")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("marked", r.stdout)
        after = APPS.read_text(encoding="utf-8").count("\n")
        self.assertEqual(after, before + 1)

    def test_v4_mark_without_id_fails(self):
        r = run_cli("--mark", "")
        self.assertNotEqual(r.returncode, 0)

    def test_v5_stats_counts(self):
        run_cli("--mark", "sTEST-x", "--evidence", "e", "--session", "sTEST")
        run_cli("--mark", "sTEST-y", "--evidence", "e", "--session", "sTEST")
        r = run_cli("--stats")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("lesson_apply: total=", r.stdout)
        self.assertIn("by_source", r.stdout)

    def test_v6_auto_close_writes_summary(self):
        run_cli("--suggest", "--top", "2", "--session", "sTEST")
        r = run_cli("--auto-close", "--session", "sTEST")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("auto-close", r.stdout)
        # последняя строка должна быть source=auto_close
        last = APPS.read_text(encoding="utf-8").strip().splitlines()[-1]
        d = json.loads(last)
        self.assertEqual(d["source"], "auto_close")
        self.assertEqual(d["session"], "sTEST")

    def test_v7_jsonl_valid(self):
        run_cli("--mark", "sTEST-z", "--evidence", "e", "--session", "sTEST")
        for ln in APPS.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            d = json.loads(ln)
            for k in ("ts", "session", "lesson_id", "source"):
                self.assertIn(k, d)

    def test_v8_mutual_exclusion(self):
        r = run_cli("--suggest", "--stats")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not allowed", r.stderr.lower() + r.stdout.lower())


    def test_v9_auto_close_excludes_session_summary(self):
        # s170-A1 / s168-r8: _session_summary не должен попадать в marked_ids.
        run_cli("--mark", "sTEST-real", "--evidence", "e", "--session", "sTEST")
        r = run_cli("--auto-close", "--session", "sTEST")
        self.assertEqual(r.returncode, 0, r.stderr)
        last = APPS.read_text(encoding="utf-8").strip().splitlines()[-1]
        d = json.loads(last)
        self.assertNotIn("_session_summary", d["marked_ids"])
        self.assertIn("sTEST-real", d["marked_ids"])

    def test_v10_auto_close_filters_underscore_ids(self):
        # s170-A1: любой _-префиксный id вычищается из marked_ids.
        run_cli("--mark", "_internal", "--evidence", "e", "--session", "sTEST")
        run_cli("--mark", "sTEST-norm", "--evidence", "e", "--session", "sTEST")
        r = run_cli("--auto-close", "--session", "sTEST")
        self.assertEqual(r.returncode, 0, r.stderr)
        last = APPS.read_text(encoding="utf-8").strip().splitlines()[-1]
        d = json.loads(last)
        self.assertNotIn("_internal", d["marked_ids"])
        self.assertIn("sTEST-norm", d["marked_ids"])

    def test_v11_score_zero_on_no_hits(self):
        # s170-A1 P2: _score -> 0 при hits==0, бонусы не спасают.
        mod = _load_module()
        entry = {"id": "sTEST", "title": "foo bar baz",
                 "tags": [], "related": [],
                 "style": "session", "category": "self_docs"}
        self.assertEqual(mod._score(entry, {"nomatchtoken"}), 0)
        self.assertGreater(mod._score(entry, {"foo"}), 0)

    def test_v12_session_keywords_next_only(self):
        # s170-A1 P1: только NEXT_SESSION.md, PLAN.md игнорируется.
        mod = _load_module()
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            nextf = tdp / "NEXT.md"
            planf = tdp / "PLAN.md"
            nextf.write_text("unique_next_token_xyz s170", encoding="utf-8")
            planf.write_text("unique_plan_token_qqq s169", encoding="utf-8")
            with mock.patch.object(mod, "NEXT", nextf):
                with mock.patch.object(mod, "PLAN", planf):
                    kws = mod._session_keywords()
        self.assertIn("unique_next_token_xyz", kws)
        self.assertNotIn("unique_plan_token_qqq", kws)



    def test_v13_title_hit_weighted_x2(self):
        # s172-A3: title hit -> x2 (position-weighting).
        mod = _load_module()
        entry = {"id": "sT13", "title": "foo bar", "tags": [],
                 "related": [], "style": "legacy", "category": "misc"}
        self.assertEqual(mod._score(entry, {"foo"}), 2)

    def test_v14_tags_hit_weighted_x1(self):
        # s172-A3: tags hit -> x1.
        mod = _load_module()
        entry = {"id": "sT14", "title": "alpha", "tags": ["beta"],
                 "related": [], "style": "legacy", "category": "misc"}
        self.assertEqual(mod._score(entry, {"beta"}), 1)

    def test_v15_related_hit_weighted_x1(self):
        # s172-A3: related hit -> x1.
        mod = _load_module()
        entry = {"id": "sT15", "title": "alpha", "tags": [],
                 "related": ["gamma"], "style": "legacy", "category": "misc"}
        self.assertEqual(mod._score(entry, {"gamma"}), 1)

    def test_v16_title_plus_tags_composite(self):
        # s172-A3: title (x2) + tags (x1) = 3.
        mod = _load_module()
        entry = {"id": "sT16", "title": "foo", "tags": ["bar"],
                 "related": [], "style": "legacy", "category": "misc"}
        self.assertEqual(mod._score(entry, {"foo", "bar"}), 3)

    def test_v17_bonuses_still_apply_on_weighted(self):
        # s172-A3: title (x2) + style=session (+2) + category!=misc (+1) = 5.
        mod = _load_module()
        entry = {"id": "sT17", "title": "foo", "tags": [],
                 "related": [], "style": "session", "category": "python_syntax"}
        self.assertEqual(mod._score(entry, {"foo"}), 5)

if __name__ == "__main__":
    unittest.main()
