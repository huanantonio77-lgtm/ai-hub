#!/usr/bin/env python3
# backup_watch.py (s117) -- Safety Layer 12c: freshness of external backup.
#
# Checks: newest dir in archive/external_backup/YYYY-MM-DD/ is not older
# than MAX_AGE_H hours. If older -> finding "stale".
#
# Actuator: stale -> autonomy record (repair_task hook -- separate).
# Journal: self/healers/backup_watch.jsonl.
# Medcard: self/healers/backup_watch.md.
# Not CORE. Not sensitive.

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKUP_DIR = ROOT / "archive" / "external_backup"
ICLOUD_DIR = (Path.home() / "Library" / "Mobile Documents"
              / "com~apple~CloudDocs" / "ai-hub-backup")
MAX_AGE_H = 36
AUTONOMY = ROOT / "self" / "autonomy.jsonl"
HEALER_JOURNAL = ROOT / "self" / "healers" / "backup_watch.jsonl"
AUTOTRIGGER_MARKER = ROOT / "self" / "healers" / ".backup_watch_autotrigger"
AUTOTRIGGER_COOLDOWN_H = 6
BACKUP_SCRIPT = ROOT / "scripts" / "backup_core.py"


def _ts():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _session():
    try:
        import session_meta as _sm
        return _sm.current()
    except Exception:
        return "unknown"


def _scan_dir(base):
    if not base.exists():
        return {"status": "missing", "latest": None, "age_h": None}
    copies = sorted(
        [d for d in base.iterdir()
         if d.is_dir() and d.name[:4].isdigit()],
        key=lambda d: d.name, reverse=True)
    if not copies:
        return {"status": "empty", "latest": None, "age_h": None}
    latest = copies[0]
    try:
        dt = datetime.strptime(latest.name, "%Y-%m-%d").replace(
            tzinfo=timezone.utc)
    except Exception:
        return {"status": "bad_name", "latest": latest.name, "age_h": None}
    now = datetime.now(timezone.utc)
    age_h = (now - dt).total_seconds() / 3600.0
    status = "ok" if age_h <= MAX_AGE_H else "stale"
    return {"status": status, "latest": latest.name, "age_h": round(age_h, 1)}


def scan():
    loc = _scan_dir(BACKUP_DIR)
    icl = _scan_dir(ICLOUD_DIR)
    # overall status: worst of the two; but iCloud missing is a warn-level
    if icl["status"] == "missing":
        combined = loc["status"] if loc["status"] != "ok" else "icloud_missing"
    elif icl["status"] != "ok":
        combined = icl["status"]
    else:
        combined = loc["status"]
    return {
        "status": combined,
        "latest": loc["latest"],
        "age_h": loc["age_h"],
        "local": loc,
        "icloud": icl,
    }


def _maybe_autotrigger(res):
    """Stale/missing backup -> run backup_core once per cooldown window."""
    if res.get("status") == "ok":
        return None
    if AUTOTRIGGER_MARKER.exists():
        age_h = (time.time() - AUTOTRIGGER_MARKER.stat().st_mtime) / 3600.0
        if age_h < AUTOTRIGGER_COOLDOWN_H:
            return {"skipped": "cooldown", "age_h": round(age_h, 1)}
    outcome = "unknown"
    tail = ""
    try:
        r = subprocess.run(
            [sys.executable, str(BACKUP_SCRIPT), "--run", "--apply"],
            capture_output=True, text=True, timeout=180)
        outcome = "ok" if r.returncode == 0 else "fail"
        tail = ((r.stdout or "") + (r.stderr or ""))[-300:]
    except Exception as e:
        outcome = "error"
        tail = str(e)[:300]
    try:
        AUTOTRIGGER_MARKER.parent.mkdir(parents=True, exist_ok=True)
        AUTOTRIGGER_MARKER.write_text(_ts(), encoding="utf-8")
    except Exception:
        pass
    try:
        with HEALER_JOURNAL.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": _ts(), "session": _session(), "healer": "backup_watch",
                "diagnosis": res.get("status"), "action": "autotrigger_backup",
                "effect": 1 if outcome == "ok" else 0,
                "outcome": outcome, "note": tail,
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass
    try:
        with AUTONOMY.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": _ts(), "session": _session(),
                "action": "backup_watch_autotrigger",
                "note": "status=" + str(res.get("status"))
                        + " outcome=" + outcome,
                "effect": 1 if outcome == "ok" else 0,
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return {"triggered": outcome}


def run_report(quiet=False, actuate=False):
    res = scan()
    stale = res["status"] not in ("ok",)
    if not quiet:
        print("backup_watch: status=" + res["status"]
              + " latest=" + str(res["latest"])
              + " age_h=" + str(res["age_h"]))
        loc = res.get("local") or {}
        icl = res.get("icloud") or {}
        print("  local : status=" + str(loc.get("status"))
              + " latest=" + str(loc.get("latest")))
        print("  icloud: status=" + str(icl.get("status"))
              + " latest=" + str(icl.get("latest")))
    if actuate:
        triggered = _maybe_autotrigger(res)
        if triggered and not quiet:
            print("backup_watch autotrigger: " + str(triggered))
    try:
        HEALER_JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": _ts(), "session": _session(), "healer": "backup_watch",
            "diagnosis": res["status"], "action": "report",
            "effect": 1 if stale else 0,
            "outcome": "stale" if stale else "ok",
            "note": "latest=" + str(res["latest"])
                    + " age_h=" + str(res["age_h"]),
        }
        with HEALER_JOURNAL.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
    if stale:
        try:
            rec = {
                "ts": _ts(), "session": _session(),
                "action": "backup_watch_stale",
                "note": "latest=" + str(res["latest"])
                        + " age_h=" + str(res["age_h"]),
                "effect": 2,
            }
            with AUTONOMY.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass
    return 0 if not stale else 1


def main():
    ap = argparse.ArgumentParser(prog="backup_watch.py")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    return run_report(quiet=args.quiet, actuate=args.run)


if __name__ == "__main__":
    sys.exit(main())
