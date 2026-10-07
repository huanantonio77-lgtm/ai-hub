"""Family-audit (s161): auto-detect новых family-классов проблем.

Новый класс автономного действия (Автономность 96 -> 97):
  - TEST-GAP:      публичный класс в arbitrage_bot/app/** без теста
  - SYMMETRY-GAP:  пара модулей a/b, у одного тест есть, у другого нет
  - NAKED-CALLER:  функция без вызовов вне своего модуля
  - MODULE-WITHOUT-E2E: модуль в app/**/*.py, не вызывается из sim.py (нет e2e)

Инварианты (s156-r0):
  R1 — ноль LLM-API.  R2 — ноль ML.  R3 — детерминизм (sorted).
  R4 — ноль сети.     R5 — всё локально.

CLI:
  python3 scripts/family_audit.py --scan arbitrage_bot [--json] [--write]

--write: findings пишутся в self/curator/UNRESOLVED.jsonl (source=family_audit).
         Идемпотентно: повторный запуск не дублирует (dedup по task).
"""

from __future__ import annotations

import argparse
import ast
import datetime as _dt
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

CUR = Path(__file__).resolve().parent.parent
DEFAULT_UNRESOLVED = CUR / "self" / "curator" / "UNRESOLVED.jsonl"


@dataclass
class Finding:
    kind: str
    target: str
    module: str
    task: str
    desc: str
    priority: str = "P2"

    def to_dict(self) -> dict:
        return asdict(self)


def _iter_py(root: Path):
    return sorted(
        p for p in root.rglob("*.py")
        if "__pycache__" not in p.parts and p.name != "__init__.py"
    )


def _snake_to_camel(s: str) -> str:
    """s166-r2: exchange_a -> ExchangeA (для CamelCase-матчинга в sim.py)."""
    return "".join(part.capitalize() for part in s.split("_") if part)


def _is_mentioned(stem: str, text: str) -> bool:
    """s166-r2: true, если stem встречается как есть ИЛИ в CamelCase.

    Precision-фикс s164-r3: exchange_a покрыт, если в sim.py есть ExchangeA.
    """
    if not stem:
        return False
    if stem in text:
        return True
    camel = _snake_to_camel(stem)
    if camel and camel != stem and camel in text:
        return True
    return False


def _parse(path: Path):
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _public_classes(path: Path):
    tree = _parse(path)
    if tree is None:
        return []
    return [n.name for n in tree.body
            if isinstance(n, ast.ClassDef) and not n.name.startswith("_")]


def _public_functions(path: Path):
    tree = _parse(path)
    if tree is None:
        return []
    return [n.name for n in tree.body
            if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")]



def _is_container_class(path: Path, cls_name: str) -> bool:
    """True если класс - dataclass-контейнер.

    C/s171: @dataclass (Name или Call) -> всегда контейнер (DTO, helper-методы
    не мешают). Иначе - только классы без методов (как раньше).
    """
    tree = _parse(path)
    if tree is None:
        return False
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == cls_name:
            # C/s171: @dataclass — контейнер (DTO), helper-методы допустимы.
            for dec in node.decorator_list:
                if isinstance(dec, ast.Name) and dec.id == "dataclass":
                    return True
                if (isinstance(dec, ast.Call)
                        and isinstance(dec.func, ast.Name)
                        and dec.func.id == "dataclass"):
                    return True
            has_method = any(isinstance(b, ast.FunctionDef) for b in node.body)
            return not has_method
    return False


def scan_test_gap(root: Path, tests_root: Path):
    blob = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in tests_root.rglob("*.py")
    ) if tests_root.exists() else ""
    out = []
    for py in _iter_py(root):
        rel = py.relative_to(root.parent).as_posix()
        for cls in _public_classes(py):
            if cls not in blob:
                is_container = _is_container_class(py, cls)
                prio = "P3" if is_container else "P2"
                kind_suffix = " (container)" if is_container else ""
                out.append(Finding(
                    kind="TEST-GAP", target=cls, module=rel,
                    task="family:test-gap:" + cls,
                    desc="класс " + cls + " в " + rel + " не упоминается в тестах" + kind_suffix,
                    priority=prio,
                ))
    return out


def scan_symmetry_gap(root: Path, tests_root: Path):
    out = []
    by_stem = {}
    for py in _iter_py(root):
        by_stem.setdefault(py.stem, py)
    for stem, py in sorted(by_stem.items()):
        if not stem.endswith("_a"):
            continue
        peer = stem[:-2] + "_b"
        if peer not in by_stem:
            continue
        a_has = (tests_root / ("test_" + stem + ".py")).exists()
        b_has = (tests_root / ("test_" + peer + ".py")).exists()
        if a_has != b_has:
            out.append(Finding(
                kind="SYMMETRY-GAP", target=stem + "/" + peer,
                module=py.relative_to(root.parent).as_posix(),
                task="family:symmetry-gap:" + stem,
                desc="пара " + stem + "/" + peer + ": тест есть у одного, нет у другого",
            ))
    return out


def _collect_extra_calls(extra_roots):
    """s194: собрать все вызовы из доп. корней (scripts/)."""
    calls = set()
    if not extra_roots:
        return calls
    for r in extra_roots:
        if not r.exists():
            continue
        for py in _iter_py(r):
            tree = _parse(py)
            if tree is None:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    fn = node.func
                    if isinstance(fn, ast.Name):
                        calls.add(fn.id)
                    elif isinstance(fn, ast.Attribute):
                        calls.add(fn.attr)
                    for kw in node.keywords:
                        v = kw.value
                        if isinstance(v, ast.Name):
                            calls.add(v.id)
                        elif isinstance(v, ast.Attribute):
                            calls.add(v.attr)
    return calls


def _collect_extra_texts(extra_roots):
    """s194: объединённый текст всех .py в доп. корнях."""
    parts = []
    if not extra_roots:
        return ""
    for r in extra_roots:
        if not r.exists():
            continue
        for py in _iter_py(r):
            try:
                parts.append(py.read_text(encoding="utf-8"))
            except OSError:
                continue
    # s194-r-registry-extra: registry.py — источник правды о подключённых биржах.
    # Без него MODULE-WITHOUT-E2E не видит упоминаний клиентов в registry class paths.
    reg = CUR / "arbitrage_bot" / "app" / "exchanges" / "registry.py"
    if reg.exists():
        try:
            parts.append(reg.read_text(encoding="utf-8"))
        except OSError:
            pass
    return "\n".join(parts)


def scan_naked_caller(root: Path, extra_roots=None):
    all_calls = set()
    for py in _iter_py(root):
        tree = _parse(py)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name):
                    all_calls.add(fn.id)
                elif isinstance(fn, ast.Attribute):
                    all_calls.add(fn.attr)
                # s166-r1: kwarg-значения тоже считаются вызовами (fix precision s164-r3)
                for kw in node.keywords:
                    v = kw.value
                    if isinstance(v, ast.Name):
                        all_calls.add(v.id)
                    elif isinstance(v, ast.Attribute):
                        all_calls.add(v.attr)
    all_calls.update(_collect_extra_calls(extra_roots))
    out = []
    for py in _iter_py(root):
        rel = py.relative_to(root.parent).as_posix()
        for fname in _public_functions(py):
            if fname not in all_calls:
                out.append(Finding(
                    kind="NAKED-CALLER", target=fname, module=rel,
                    task="family:naked:" + fname,
                    desc="функция " + fname + " в " + rel + " не вызывается нигде",
                ))
    return out


def scan_module_without_e2e(root: Path, sim_path: Path, extra_roots=None):
    """Модуль в app/**/*.py, чей stem не упомянут в sim.py (нет e2e).

    Детектор e2e-покрытия: если stem модуля не встречается как подстрока
    в sim.py — значит из CLI-demo этот модуль никогда не вызывается.
    P2 (поведенческий, s161-r2), dedup по task (s161-r3).
    """
    app_root = root / "app"
    if not app_root.exists() or not sim_path.exists():
        return []
    sim_text = sim_path.read_text(encoding="utf-8")
    sim_text = sim_text + "\n" + _collect_extra_texts(extra_roots)
    out = []
    for py in _iter_py(app_root):
        # s169-B: 0-B файл - placeholder, а не модуль; детектор их не считает.
        try:
            if py.stat().st_size == 0:
                continue
        except OSError:
            continue
        stem = py.stem
        if _is_mentioned(stem, sim_text):
            continue
        rel = py.relative_to(root.parent).as_posix()
        out.append(Finding(
            kind="MODULE-WITHOUT-E2E", target=stem, module=rel,
            task="family:module-without-e2e:" + stem,
            desc="модуль " + rel + " не вызывается из sim.py (нет e2e-демо)",
            priority="P2",
        ))
    return out


def run_scan(root: Path, tests_root=None, sim_path=None, extra_roots=None):
    tests_root = tests_root or (root / "tests")
    sim_path = sim_path or (root / "sim.py")
    if extra_roots is None:
        extra_roots = []
    findings = []
    findings.extend(scan_test_gap(root, tests_root))
    findings.extend(scan_symmetry_gap(root, tests_root))
    findings.extend(scan_naked_caller(root, extra_roots=extra_roots))
    findings.extend(scan_module_without_e2e(root, sim_path, extra_roots=extra_roots))
    return sorted(findings, key=lambda f: (f.kind, f.task))


def _existing_tasks(path: Path):
    if not path.exists():
        return set()
    out = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        t = rec.get("task")
        if t:
            out.add(t)
    return out


def write_findings(findings, path: Path, session: str) -> int:
    existing = _existing_tasks(path)
    to_write = [
        fd for fd in findings
        if fd.task not in existing and fd.priority == "P2"
    ]
    if not to_write:
        return 0
    ts = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    with path.open("a", encoding="utf-8") as f:
        for fd in to_write:
            rec = {
                "ts": ts, "session": session, "task": fd.task,
                "desc": fd.desc, "status": "open", "priority": fd.priority,
                "source": "family_audit", "kind": fd.kind, "module": fd.module,
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return len(to_write)


def _session_from_state() -> str:
    p = CUR / "self" / "curator" / "STATE.md"
    if not p.exists():
        return "s?"
    for line in p.read_text(encoding="utf-8").splitlines():
        if "Текущая сессия" in line:
            m = re.search(r"\bs(\d+)\b", line)
            if m:
                return "s" + m.group(1)
    return "s?"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="family_audit")
    ap.add_argument("--scan", required=True, help="каталог для сканирования")
    ap.add_argument("--tests", default=None, help="каталог тестов")
    ap.add_argument("--json", action="store_true", help="печатать JSON")
    ap.add_argument("--write", action="store_true", help="писать в UNRESOLVED.jsonl")
    ap.add_argument("--extra-roots", nargs="*", default=None,
                    help="доп. корни для поиска вызовов (default: scripts/)")
    args = ap.parse_args(argv)

    root = Path(args.scan).resolve()
    if not root.exists():
        print("scan: not found: " + str(root), file=sys.stderr)
        return 2
    tests_root = Path(args.tests).resolve() if args.tests else (root / "tests")

    if args.extra_roots is None:
        extra_roots = [CUR / "scripts"]
    else:
        extra_roots = [Path(p).resolve() for p in args.extra_roots]
    findings = run_scan(root, tests_root, extra_roots=extra_roots)

    if args.json:
        print(json.dumps([f.to_dict() for f in findings], ensure_ascii=False, indent=2))
    else:
        for f in findings:
            print(f.kind + "\t" + f.target + "\t" + f.module)

    if args.write:
        n = write_findings(findings, DEFAULT_UNRESOLVED, _session_from_state())
        print("written: " + str(n) + " new findings", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
