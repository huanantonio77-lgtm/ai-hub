#!/usr/bin/env python3
"""self_lint.py (s210) - 6th axis: code self-check.

Checks 4 classes of issues:
1. dead_code      - if False, if 0, while False, unreachable
2. placeholder    - placeholder, TODO, FIXME, HACK, XXX, stub ...
3. unused_import  - imported but never used
4. core_whitespace - trailing ws / TODO in CORE files

Usage:
  python3 scripts/self_lint.py --check          # exit 0 clean, 1 issues
  python3 scripts/self_lint.py --json           # machine-readable
  python3 scripts/self_lint.py --target FILE    # single file
"""
from __future__ import annotations
import argparse
import ast
import pathlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ["scripts", "paper_trading"]
SCAN_TOP = ["curator.py"]
CORE_HINTS = ["security/", "curator.py", "self/curator"]
SKIP_DIRS = {"__pycache__", ".git", "node_modules", "archive", "legacy",
             ".runtime", "drafts", "tests"}

PLACEHOLDER_RE = re.compile(
    r"\b(placeholder|PLACEHOLDER|TODO|FIXME|HACK|XXX|stub)\b", re.ASCII)
DEAD_IF = re.compile(r"^\s*if\s+(False|0)\s*:", re.MULTILINE)
DEAD_WHILE = re.compile(r"^\s*while\s+(False|0)\s*:", re.MULTILINE)
NOQA = re.compile(r"#\s*(lint:ignore|noqa)", re.IGNORECASE)

def _is_comment_or_string(line: str) -> bool:
    s = line.strip()
    return s.startswith("#") or s.startswith('"""') or s.startswith("'''")

def _in_core(path: Path) -> bool:
    rel = str(path.relative_to(ROOT)) if path.is_absolute() else str(path)
    return any(h in rel for h in CORE_HINTS)

def check_dead_code(path: Path, text: str) -> list[dict]:
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        if NOQA.search(line):
            continue
        if DEAD_IF.match(line) or DEAD_WHILE.match(line):
            out.append({"file": str(path.relative_to(ROOT)),
                        "line": i, "kind": "dead_code",
                        "msg": "dead branch (if/while False|0)",
                        "sample": line.strip()[:80]})
    return out

def check_placeholder(path: Path, text: str) -> list[dict]:
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        if NOQA.search(line):
            continue
        if _is_comment_or_string(line) and "#" not in line[:2]:
            pass
        m = PLACEHOLDER_RE.search(line)
        if m and not _is_comment_or_string(line):
            out.append({"file": str(path.relative_to(ROOT)),
                        "line": i, "kind": "placeholder",
                        "msg": f"placeholder marker: {m.group(0)}",
                        "sample": line.strip()[:80]})
    return out

def check_unused_imports(path: Path, text: str) -> list[dict]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    imported: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                nm = a.asname or a.name.split(".")[0]
                imported[nm] = node.lineno
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name == "*":
                    continue
                nm = a.asname or a.name
                imported[nm] = node.lineno
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            n = node
            while isinstance(n, ast.Attribute):
                n = n.value
            if isinstance(n, ast.Name):
                used.add(n.id)
    out = []
    for nm, ln in imported.items():
        if nm == "_" or nm.startswith("_"):
            continue
        if nm in used:
            continue
        if nm in ("annotations",):
            continue
        line_txt = text.splitlines()[ln - 1] if 0 < ln <= len(text.splitlines()) else ""
        if NOQA.search(line_txt):
            continue
        out.append({"file": str(path.relative_to(ROOT)),
                    "line": ln, "kind": "unused_import",
                    "msg": f"unused import: {nm}",
                    "sample": line_txt.strip()[:80]})
    return out

def check_core_whitespace(path: Path, text: str) -> list[dict]:
    if not _in_core(path):
        return []
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        if line != line.rstrip():
            out.append({"file": str(path.relative_to(ROOT)),
                        "line": i, "kind": "core_whitespace",
                        "msg": "trailing whitespace",
                        "sample": line[:80]})
        if PLACEHOLDER_RE.search(line) and _is_comment_or_string(line):
            if not NOQA.search(line):
                out.append({"file": str(path.relative_to(ROOT)),
                            "line": i, "kind": "core_todo",
                            "msg": "TODO in CORE comment",
                            "sample": line.strip()[:80]})
    return out

CHECKS = [check_dead_code, check_placeholder,
          check_unused_imports, check_core_whitespace]

def iter_files(target):
    if target is not None:
        yield target
        return
    seen = set()
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            if any(s in p.parts for s in SKIP_DIRS):
                continue
            if p in seen:
                continue
            seen.add(p)
            yield p
    for f in SCAN_TOP:
        p = ROOT / f
        if p.exists() and p not in seen:
            seen.add(p)
            yield p

def run(target=None):
    findings = []
    SELF_PATH = pathlib.Path(__file__).resolve()
    for p in iter_files(target):
        if p.resolve() == SELF_PATH:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for fn in CHECKS:
            try:
                findings.extend(fn(p, text))
            except Exception as e:
                findings.append({"file": str(p.relative_to(ROOT)),
                                 "line": 0, "kind": "checker_error",
                                 "msg": f"{fn.__name__}: {e}", "sample": ""})
    return findings

def main():
    import argparse, json as _json, sys as _sys
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--target", type=Path, default=None)
    args = ap.parse_args()
    findings = run(args.target)
    if args.json:
        print(_json.dumps({"total": len(findings), "findings": findings}, indent=2))
    else:
        by_kind = {}
        for f in findings:
            by_kind[f["kind"]] = by_kind.get(f["kind"], 0) + 1
        print(f"self_lint: total={len(findings)}  by_kind={by_kind}")
        for f in findings[:30]:
            print(f"  {f['kind']:16s} {f['file']}:{f['line']}  {f['msg']}")
        if len(findings) > 30:
            print(f"  ... +{len(findings)-30} more")
    _sys.exit(1 if findings and args.check else 0)

if __name__ == "__main__":
    main()
