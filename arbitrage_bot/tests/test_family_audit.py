"""Тесты family_audit (scripts/family_audit.py, s161 + C2-fix).

5 уровней verify (s151-r4):
  V1 POSITIVE   — класс С МЕТОДОМ без теста → TEST-GAP P2
  V2 INVARIANT  — пустой проект → []
  V3 NEG-init   — только __init__.py → []
  V4 NEG-idem   — write_findings дважды для P2 → второй раз 0
  V5 EDGE-prio  — dataclass-контейнер (только поля) → P3, НЕ пишется
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
import family_audit  # type: ignore


def _mk(root: Path, files: dict) -> None:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


BEHAVIORAL = "class Actor:\n    def run(self):\n        return 1\n"
CONTAINER = "class PureData:\n    x: int = 0\n"


class TestFamilyAudit(unittest.TestCase):

    def test_v1_positive_test_gap_p2(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk(root, {"app/mod.py": BEHAVIORAL, "tests/__init__.py": ""})
            fs = family_audit.run_scan(root, root / "tests")
            gaps = [f for f in fs if f.kind == "TEST-GAP" and f.target == "Actor"]
            self.assertEqual(len(gaps), 1)
            self.assertEqual(gaps[0].priority, "P2")
            self.assertEqual(gaps[0].task, "family:test-gap:Actor")

    def test_v2_invariant_empty_project(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fs = family_audit.run_scan(root, root / "tests")
            self.assertEqual(fs, [])

    def test_v3_neg_only_init(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk(root, {"app/__init__.py": "", "tests/__init__.py": ""})
            fs = family_audit.run_scan(root, root / "tests")
            self.assertEqual(fs, [])

    def test_v4_neg_idempotent_write_p2(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk(root, {"app/mod.py": BEHAVIORAL, "tests/__init__.py": ""})
            fs = family_audit.run_scan(root, root / "tests")
            up = root / "UNRESOLVED.jsonl"
            n1 = family_audit.write_findings(fs, up, "s161")
            self.assertGreater(n1, 0, "P2 должен быть записан")
            n2 = family_audit.write_findings(fs, up, "s161")
            self.assertEqual(n2, 0, "повторная запись должна быть 0")
            recs = [json.loads(l) for l in up.read_text().splitlines() if l.strip()]
            self.assertEqual(len(recs), n1)
            self.assertTrue(all(r.get("source") == "family_audit" for r in recs))
            self.assertTrue(all(r.get("priority") == "P2" for r in recs))

    def test_v5_edge_container_p3_not_written(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk(root, {"app/pure.py": CONTAINER, "tests/__init__.py": ""})
            fs = family_audit.run_scan(root, root / "tests")
            cont = [f for f in fs if f.kind == "TEST-GAP" and f.target == "PureData"]
            self.assertEqual(len(cont), 1)
            self.assertEqual(cont[0].priority, "P3", "контейнер → P3")
            up = root / "UNRESOLVED.jsonl"
            n = family_audit.write_findings(fs, up, "s161")
            self.assertEqual(n, 0, "P3 НЕ должен писаться")
            if up.exists():
                lines = [l for l in up.read_text().splitlines() if l.strip()]
                self.assertEqual(lines, [], "файл не должен содержать записей")


    def test_v6_positive_module_without_e2e(self):
        """V6 POSITIVE: app/foo.py без упоминания в sim.py -> Finding P2."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk(root, {
                "app/foo.py": BEHAVIORAL,
                "sim.py": "# entry, no imports\n",
                "tests/__init__.py": "",
            })
            fs = family_audit.run_scan(root, root / "tests", root / "sim.py")
            e2e = [f for f in fs if f.kind == "MODULE-WITHOUT-E2E" and f.target == "foo"]
            self.assertEqual(len(e2e), 1)
            self.assertEqual(e2e[0].priority, "P2")
            self.assertEqual(e2e[0].task, "family:module-without-e2e:foo")

    def test_v7_invariant_no_sim(self):
        """V7 INVARIANT: root без sim.py -> []."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk(root, {"app/foo.py": BEHAVIORAL, "tests/__init__.py": ""})
            fs = family_audit.run_scan(root, root / "tests", root / "sim.py")
            e2e = [f for f in fs if f.kind == "MODULE-WITHOUT-E2E"]
            self.assertEqual(e2e, [])

    def test_v8_neg_import_in_sim(self):
        """V8 NEG-import: 'foo' упомянут в sim.py -> нет Finding."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk(root, {
                "app/foo.py": BEHAVIORAL,
                "sim.py": "import arbitrage_bot.app.foo\n",
                "tests/__init__.py": "",
            })
            fs = family_audit.run_scan(root, root / "tests", root / "sim.py")
            e2e = [f for f in fs if f.kind == "MODULE-WITHOUT-E2E" and f.target == "foo"]
            self.assertEqual(e2e, [])

    def test_v9_neg_init_skipped(self):
        """V9 NEG-init: только __init__.py -> нет Finding."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk(root, {
                "app/__init__.py": "",
                "sim.py": "# no imports\n",
                "tests/__init__.py": "",
            })
            fs = family_audit.run_scan(root, root / "tests", root / "sim.py")
            e2e = [f for f in fs if f.kind == "MODULE-WITHOUT-E2E"]
            self.assertEqual(e2e, [])

    def test_v10_write_path_module_without_e2e(self):
        """V10 WRITE-PATH: write_findings пишет MODULE-WITHOUT-E2E."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk(root, {
                "app/foo.py": BEHAVIORAL,
                "sim.py": "# no imports\n",
                "tests/__init__.py": "",
            })
            fs = family_audit.run_scan(root, root / "tests", root / "sim.py")
            up = root / "UNRESOLVED.jsonl"
            n = family_audit.write_findings(fs, up, "s164")
            self.assertGreater(n, 0)
            recs = [json.loads(l) for l in up.read_text().splitlines() if l.strip()]
            e2e = [r for r in recs if r.get("kind") == "MODULE-WITHOUT-E2E"]
            self.assertEqual(len(e2e), 1)
            self.assertEqual(e2e[0]["priority"], "P2")

    def test_v11_naked_caller_kwarg_not_flagged(self):
        """V11 POSITIVE (s166-r1): kwarg-значение считается вызовом."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk(root, {
                "app/foo.py": (
                    "def handler(cb):\n"
                    "    return cb\n"
                    "\n"
                    "def fake():\n"
                    "    return None\n"
                    "\n"
                    "x = handler(cb=fake)\n"
                ),
            })
            fs = family_audit.scan_naked_caller(root)
            naked = [f for f in fs if f.target == "fake"]
            self.assertEqual(naked, [])

    def test_v12_module_without_e2e_camelcase(self):
        """V12 POSITIVE (s166-r2): exchange_a покрыт через ExchangeA в sim.py."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk(root, {
                "app/exchange_a.py": BEHAVIORAL,
                "sim.py": "from app.exchanges import ExchangeA\nExchangeA()\n",
                "tests/__init__.py": "",
            })
            fs = family_audit.run_scan(root, root / "tests", root / "sim.py")
            e2e = [f for f in fs
                   if f.kind == "MODULE-WITHOUT-E2E" and f.target == "exchange_a"]
            self.assertEqual(e2e, [])

    def test_v13_naked_caller_negative_still_flags(self):
        """V13 NEG-1 (s166): orphan без вызовов -> Finding остаётся."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk(root, {
                "app/foo.py": (
                    "def orphan():\n"
                    "    return None\n"
                ),
            })
            fs = family_audit.scan_naked_caller(root)
            naked = [f for f in fs if f.target == "orphan"]
            self.assertEqual(len(naked), 1)
            self.assertEqual(naked[0].kind, "NAKED-CALLER")

    def test_v14_module_without_e2e_negative(self):
        """V14 NEG-2 (s166): foo_bar без упоминаний -> Finding остаётся."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk(root, {
                "app/foo_bar.py": BEHAVIORAL,
                "sim.py": "# unrelated comment\n",
                "tests/__init__.py": "",
            })
            fs = family_audit.run_scan(root, root / "tests", root / "sim.py")
            e2e = [f for f in fs
                   if f.kind == "MODULE-WITHOUT-E2E" and f.target == "foo_bar"]
            self.assertEqual(len(e2e), 1)


    def test_v15_zero_byte_module_skipped(self):
        """s169-B: 0-B файл — placeholder, детектор MODULE-WITHOUT-E2E его игнорирует."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk(root, {
                "app/hedge_manager.py": "",           # 0 B — placeholder
                "app/real.py": BEHAVIORAL,             # непустой, без e2e
                "sim.py": "",
            })
            fs = family_audit.run_scan(root, root / "tests", root / "sim.py")
            mwe = [f for f in fs if f.kind == "MODULE-WITHOUT-E2E"]
            targets = sorted(f.target for f in mwe)
            self.assertIn("real", targets,
                          "непустой модуль без e2e должен быть пойман")
            self.assertNotIn("hedge_manager", targets,
                             "0-B placeholder не должен флагаться (s169-B)")

    def test_v16_nonzero_byte_uncovered_still_flagged(self):
        """s169-B регрессия: непустой модуль без e2e по-прежнему флагается."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk(root, {
                "app/features.py": "",                 # 0 B
                "app/normalizer.py": BEHAVIORAL,       # непустой, без e2e
                "sim.py": "",
            })
            fs = family_audit.run_scan(root, root / "tests", root / "sim.py")
            mwe = [f for f in fs if f.kind == "MODULE-WITHOUT-E2E"]
            targets = sorted(f.target for f in mwe)
            self.assertEqual(targets, ["normalizer"],
                             "только непустой normalizer должен флагаться, "
                             "0-B features — нет (s169-B)")




    # ---------- C/s171: @dataclass precision (v17..v20) ----------

    def test_v17_dataclass_with_helper_method_is_container(self):
        """@dataclass + helper-метод -> контейнер (P3), не P2."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk(root, {"app/learning/backtest.py": (
                "from dataclasses import dataclass, field\n"
                "\n"
                "@dataclass\n"
                "class BacktestResult:\n"
                "    snapshots: int\n"
                "    trades: list = field(default_factory=list)\n"
                "\n"
                "    def equity_curve(self):\n"
                "        return [0.0]\n"
            )})
            cls = root / "app" / "learning" / "backtest.py"
            self.assertTrue(
                family_audit._is_container_class(cls, "BacktestResult"),
                "@dataclass + helper-метод должен быть контейнером",
            )

    def test_v18_dataclass_frozen_call_form_is_container(self):
        """@dataclass(frozen=True) (Call-форма) -> контейнер."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk(root, {"app/risk/limits.py": (
                "from dataclasses import dataclass\n"
                "\n"
                "@dataclass(frozen=True)\n"
                "class RiskDecision:\n"
                "    allow: bool\n"
                "    reason: str = \"\"\n"
                "\n"
                "    def is_allow(self):\n"
                "        return self.allow\n"
            )})
            cls = root / "app" / "risk" / "limits.py"
            self.assertTrue(
                family_audit._is_container_class(cls, "RiskDecision"),
                "@dataclass(frozen=True) должен быть контейнером",
            )

    def test_v19_plain_class_with_method_not_container(self):
        """Не-@dataclass класс с методом -> не контейнер (P2)."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk(root, {"app/service.py": (
                "class Service:\n"
                "    def run(self):\n"
                "        return 1\n"
            )})
            cls = root / "app" / "service.py"
            self.assertFalse(
                family_audit._is_container_class(cls, "Service"),
                "класс без @dataclass с методом НЕ должен быть контейнером",
            )

    def test_v20_dataclass_no_methods_still_container(self):
        """@dataclass без методов -> контейнер (регресс-инвариант)."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk(root, {"app/dto.py": (
                "from dataclasses import dataclass\n"
                "\n"
                "@dataclass\n"
                "class PureData:\n"
                "    x: int = 0\n"
            )})
            cls = root / "app" / "dto.py"
            self.assertTrue(
                family_audit._is_container_class(cls, "PureData"),
                "@dataclass без методов должен быть контейнером",
            )


if __name__ == "__main__":
    unittest.main()


class TestFamilyAuditRealRepo(unittest.TestCase):
    """s203-r1: golden-set на реальном arbitrage_bot.

    Регрессионный якорь против слома detector'а:
    - canary не срабатывает (TEST-GAP target НЕ начинается с 'Test')
    - findings не пустые (иначе scan вообще не работает)
    - scan_test_gap не сканирует сам tests_root
    """

    def test_v21_scan_real_repo_no_Test_targets(self):
        repo = Path(__file__).resolve().parents[2]
        app = repo / "arbitrage_bot"
        tests = repo / "arbitrage_bot" / "tests"
        findings = family_audit.scan_test_gap(app, tests)
        # canary: skip tests должен исключать все Test*-классы
        bad = [f.target for f in findings if f.target.startswith("Test")]
        self.assertEqual(bad, [],
            f"canary failed: TEST-GAP has Test* targets {bad[:5]} (scanner broken)")
        # sanity: если 0 findings при 100+ классах — detector подозрительно мёртв
        self.assertGreater(len(findings), 0,
            "scan_test_gap returned 0 — detector may be broken")
