#!/usr/bin/env python3
# syntax_scan.py (s93-S1) - ast.parse over all .py files in root, gepa/, security/, scripts/.
# Exit 0 if all parse, 1 otherwise. Usage: python3 syntax_scan.py [--quiet]
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SUBDIRS = ["gepa", "security", "scripts"]


def _collect():
    files = []
    for p in sorted(ROOT.glob("*.py")):
        if ".bak-" in p.name or p.name.startswith("_"):
            continue
        files.append(p)
    for sub in SUBDIRS:
        d = ROOT / sub
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.py")):
            if ".bak-" in p.name or p.name.startswith("_"):
                continue
            files.append(p)
    return files


def main(argv=None):
    quiet = "--quiet" in (argv or sys.argv[1:])
    files = _collect()
    ok = 0
    fails = []
    for p in files:
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            fails.append((p, 0, "read: " + type(e).__name__))
            continue
        try:
            ast.parse(src)
            ok += 1
        except SyntaxError as e:
            fails.append((p, e.lineno or 0, str(e.msg or "syntax error")))
    total = len(files)
    if not quiet:
        print("syntax_scan: " + str(ok) + "/" + str(total) + " OK")
        for p, ln, msg in fails:
            try:
                rel = p.relative_to(ROOT)
            except Exception:
                rel = p
            print("  [FAIL] " + str(rel) + " line=" + str(ln) + " " + msg[:100])
    if fails:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
