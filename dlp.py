#!/usr/bin/env python3
# dlp.py (s118) -- Safety Layer 9 v1 healer: Data Leak Prevention.
#
# Detector + actuator:
#   --report : scan logs + self/*.jsonl + self/healers/*.jsonl, journal finding.
#   --run    : same + auto-redact hits in non-CORE targets (cooldown 6h).
#
# Rights: record_finding, add_repair_task, redact_file.
# Cannot: mutate_core, delete_file, set_cooldown, touch_secrets_dir.
#
# Journal: self/healers/dlp.jsonl
# Medcard: self/healers/dlp.md
# Not CORE. Not sensitive.

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AUTONOMY = ROOT / "self" / "autonomy.jsonl"
HEALER_JOURNAL = ROOT / "self" / "healers" / "dlp.jsonl"
AUTOTRIGGER_MARKER = ROOT / "self" / "healers" / ".dlp_autotrigger"
AUTOTRIGGER_COOLDOWN_H = 6
SCAN_TARGETS = [
    "self/autonomy.jsonl",
    "self/hitl_pending.jsonl",
    "self/research_log.jsonl",
]
SCAN_DIRS = [
    "self/healers",
]


def _ts():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _session():
    try:
        import session_meta as _sm
        return _sm.current()
    except Exception:
        return "unknown"


def _scan_one(target):
    p = ROOT / target
    if not p.exists():
        return {"target": target, "hits": 0, "kinds": {}}
    try:
        r = subprocess.run(
            [sys.executable, "dlp_scan.py", "--scan-file", str(p), "--json"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=60)
        d = json.loads(r.stdout or "{}")
    except Exception as e:
        return {"target": target, "error": str(e)[:200]}
    return {
        "target": target,
        "hits": d.get("total_hits", 0),
        "kinds": d.get("per_kind", {}),
    }


SERVICE_JOURNALS = {
    "self/autonomy.jsonl",
    "self/hitl_pending.jsonl",
    "self/research_log.jsonl",
}


def scan_all():
    """Returns real (unexpected) hits + service journal hits (expected).

    Service journals legitimately contain paths like .secrets/... in their
    metadata (HITL target field, autonomy notes). These are NOT leaks — they
    are metadata about attempts. Only real files (healers, etc.) count for
    status/rc.
    """
    out = []
    for t in SCAN_TARGETS:
        r = _scan_one(t)
        r["service"] = t in SERVICE_JOURNALS
        out.append(r)
    for d in SCAN_DIRS:
        p = ROOT / d
        if not p.exists():
            continue
        for f in sorted(p.glob("*.jsonl")):
            rel = str(f.relative_to(ROOT))
            r = _scan_one(rel)
            r["service"] = rel in SERVICE_JOURNALS
            out.append(r)
    real_dirty = [x for x in out if x.get("hits", 0) > 0 and not x.get("service")]
    service_dirty = [x for x in out if x.get("hits", 0) > 0 and x.get("service")]
    real_total = sum(x.get("hits", 0) for x in real_dirty)
    service_total = sum(x.get("hits", 0) for x in service_dirty)
    return {
        "total_hits": real_total,
        "service_hits": service_total,
        "files": out,
        "dirty": real_dirty,
        "service_dirty": service_dirty,
    }


def _autotrigger(dirty):
    if not dirty:
        return None
    if AUTOTRIGGER_MARKER.exists():
        age = time.time() - AUTOTRIGGER_MARKER.stat().st_mtime
        if age < AUTOTRIGGER_COOLDOWN_H * 3600:
            return {"skipped": "cooldown", "age_h": round(age / 3600, 1)}
    redacted = 0
    # dirty уже отфильтрован от service journals (см. scan_all)
    for d in dirty:
        t = d.get("target")
        if not t:
            continue
        # skip CORE
        if t in ("strategy/_features.json", "strategy/00_rules.md"):
            continue
        # skip service journals: alert-only, do not auto-redact
        if t in SERVICE_JOURNALS:
            continue
        try:
            r = subprocess.run(
                [sys.executable, "dlp_scan.py", "--redact", t],
                cwd=str(ROOT), capture_output=True, text=True, timeout=60)
            if r.returncode == 0 and "redacted" in (r.stdout or ""):
                redacted += 1
        except Exception:
            pass
    try:
        AUTOTRIGGER_MARKER.parent.mkdir(parents=True, exist_ok=True)
        AUTOTRIGGER_MARKER.write_text(_ts(), encoding="utf-8")
    except Exception:
        pass
    return {"redacted_files": redacted}


def run_report(quiet=False, actuate=False):
    res = scan_all()
    total = res["total_hits"]
    service = res.get("service_hits", 0)
    dirty = res["dirty"]
    if not quiet:
        print("dlp: hits=" + str(total) + " dirty_files=" + str(len(dirty))
              + " (service_meta=" + str(service) + ")")
        for d in dirty[:5]:
            print("  " + d["target"] + " hits=" + str(d["hits"]))
        if service and not total:
            print("  (service journals have " + str(service)
                  + " metadata-only hits — not counted)")
    # journal
    try:
        HEALER_JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with HEALER_JOURNAL.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": _ts(), "session": _session(), "healer": "dlp",
                "diagnosis": "leak" if total else "clean",
                "action": "report",
                "effect": 1 if total else 0,
                "outcome": "dirty" if total else "ok",
                "note": "hits=" + str(total) + " dirty=" + str(len(dirty))
                        + " service_meta=" + str(service),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass
    if total:
        try:
            with AUTONOMY.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": _ts(), "session": _session(),
                    "action": "dlp_finding",
                    "note": "hits=" + str(total) + " files=" + str(len(dirty)),
                    "effect": 2,
                }, ensure_ascii=False) + "\n")
        except Exception:
            pass
    if actuate:
        triggered = _autotrigger(dirty)
        if triggered and not quiet:
            print("dlp autotrigger: " + str(triggered))
    return 0 if total == 0 else 1


def main():
    ap = argparse.ArgumentParser(prog="dlp.py")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    return run_report(quiet=args.quiet, actuate=args.run)


if __name__ == "__main__":
    sys.exit(main())
