#!/usr/bin/env python3
"""coverage_audit.py (s103-0c) - K5: karta slepyh zon.

Skaniruet .py na silent emission (except: pass / except: return None).
Klassificiruet po tiram T1 (CORE, prioritet) / T2 (ostalnoe).
Pishet karta v .cache/system/coverage_map.json.
"""
import argparse
import ast
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SESSION = "s103"
SYSTEM = ROOT / ".cache" / "system"
COVERAGE_MAP = SYSTEM / "coverage_map.json"
AUTONOMY = ROOT / "self" / "autonomy.jsonl"

SKIP_DIRS = {".git", "archive", "__pycache__", "node_modules", "venv", ".venv"}

CORE_FILES = {
    "orchestrator.py", "self_apply.py", "session_verify.py",
    "catchup.py", "limits.py",
    "security/signing.py", "security/enforcer.py", "security/audit.py",
}


def _skip(p):
    for part in p.parts:
        if part in SKIP_DIRS:
            return True
    if ".bak" in p.name:
        return True
    return False


def _scan_file(p):
    try:
        src = p.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(p))
    except Exception:
        return []
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if len(node.body) != 1:
            continue
        n = node.body[0]
        if isinstance(n, ast.Pass):
            hits.append((node.lineno, "except_pass"))
        elif isinstance(n, ast.Return):
            v = n.value
            if v is None or (isinstance(v, ast.Constant) and v.value is None):
                hits.append((node.lineno, "except_return_none"))
    return hits


def scan():
    files = [p for p in ROOT.rglob("*.py") if not _skip(p)]
    t1 = []
    t2 = []
    for p in files:
        rel = str(p.relative_to(ROOT))
        for lineno, pat in _scan_file(p):
            entry = {"file": rel, "line": lineno, "pattern": pat}
            if rel in CORE_FILES:
                t1.append(entry)
            else:
                t2.append(entry)
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "session": SESSION,
        "files_scanned": len(files),
        "t1_count": len(t1),
        "t2_count": len(t2),
        "t1": t1[:200],
        "t2": t2[:500],
    }


def _append_autonomy(note):
    from datetime import datetime as _dt, timezone as _tz
    ts = _dt.now(_tz.utc).isoformat(timespec="seconds")
    rec = {"ts": ts, "session": SESSION, "action": "coverage_audit", "note": note}
    AUTONOMY.parent.mkdir(parents=True, exist_ok=True)
    with AUTONOMY.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def run_report(quiet=False):
    r = scan()
    SYSTEM.mkdir(parents=True, exist_ok=True)
    try:
        COVERAGE_MAP.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print("coverage_audit: write fail: " + type(e).__name__ + ": " + str(e)[:120])
    note = "files=" + str(r["files_scanned"]) + " t1=" + str(r["t1_count"]) + " t2=" + str(r["t2_count"])
    _append_autonomy(note)
    # s123-lab-healers-wired: lab journal
    try:
        from healer_log import healer_log
        healer_log("coverage_audit", diagnosis="scan_completed",
                   action="report", outcome="recorded")
    except Exception:
        pass
    if not quiet:
        print("## " + r["ts"])
        print("### Coverage (silent emission)")
        print("- files_scanned:", r["files_scanned"])
        print("- T1 (CORE, priority):", r["t1_count"])
        print("- T2 (non-CORE):", r["t2_count"])
        if r["t1"]:
            print("### T1 samples:")
            for e in r["t1"][:10]:
                print("  -", e["file"] + ":" + str(e["line"]), e["pattern"])
    return note


def _selftest():
    passed = 0
    failed = 0

    def chk(name, ok):
        nonlocal passed, failed
        if ok:
            print("  [OK]", name)
            passed += 1
        else:
            print("  [FAIL]", name)
            failed += 1

    r = scan()
    chk("scan_returns_dict", isinstance(r, dict))
    chk("scan_has_ts", "ts" in r)
    chk("scan_has_t1_count", "t1_count" in r)
    chk("t1_int", isinstance(r["t1_count"], int))
    chk("t2_int", isinstance(r["t2_count"], int))
    print("passed " + str(passed) + "/" + str(passed + failed))
    return 0 if failed == 0 else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    if a.json:
        print(json.dumps(scan(), ensure_ascii=False, indent=2))
        return 0
    if a.report:
        run_report(quiet=False)
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
