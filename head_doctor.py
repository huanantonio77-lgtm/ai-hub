#!/usr/bin/env python3
"""
head_doctor.py — s108 A1.5-module
Главврач: контроль лекарей. НЕ лечит — только находит нарушения.

Проверки v1 (по self/autonomy.jsonl за 24h):
  1. out_of_scope  — в note лекаря есть имя файла из его cannot
  2. cross_domain  — note упоминает другого лекаря
  3. loop          — (action, note) повторяется >=5 за 60 мин
  4. self_target   — note упоминает healer/head_doctor/archivist

Режимы:
  --report   read-only, показать findings
  --selftest тест на синтетике (5 проверок)
  --run      записать findings в self/healers/head_doctor.jsonl
"""
import json
import sys
import argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict

ROOT = Path(__file__).resolve().parent
HEALERS_JSON = ROOT / "strategy" / "healers.json"
AUTONOMY = ROOT / "self" / "autonomy.jsonl"
JOURNAL = ROOT / "self" / "healers" / "head_doctor.jsonl"

try:
    from session_meta import current as _session_current
    SESSION = _session_current()
except Exception:
    SESSION = "s108"

try:
    from healer_log import healer_log as _healer_log
except Exception:
    _healer_log = None


CORE_FILES = [
    "orchestrator.py", "security/signing.py", "self_apply.py",
    "session_verify.py", "catchup.py", "limits.py",
    "security/enforcer.py", "security/audit.py",
    "strategy/00_rules.md", "strategy/_features.json",
]
CANNOT_TRIGGERS = {
    "mutate_core":     CORE_FILES,
    "touch_sensitive": ["strategy/_closed.json"],
    "delete_file":     ["delete_file", "unlink("],
    "set_cooldown":    ["set_cooldown"],
    "patch_healer":    ["head_doctor.py", "archivist.py"],
}
SELF_TARGET_KEYWORDS = ["healer", "head_doctor", "archivist", "главврач", "лекарь"]
LOOP_WINDOW_MIN = 60
LOOP_THRESHOLD = 10
SILENT_DEFAULT_H = 24  # s110-n1: порог 'молчания' по умолчанию (часы)


def _load_healers():
    with open(HEALERS_JSON) as f:
        d = json.load(f)
    return d["healers"]


def _parse_ts(ts):
    if not ts:
        return None
    dt = None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        pass
    if dt is None:
        try:
            dt = datetime.strptime(str(ts), "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _read_autonomy_since(hours=24):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = []
    if not AUTONOMY.exists():
        return rows
    with open(AUTONOMY) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            dt = _parse_ts(r.get("ts"))
            if dt and dt >= cutoff:
                rows.append((dt, r))
    return rows


def _check_out_of_scope(healer, note_l):
    for c in healer.get("cannot", []):
        for trig in CANNOT_TRIGGERS.get(c, []):
            if trig.lower() in note_l:
                return (c, trig)
    return None


def _check_cross_domain(healer, note_l, all_names):
    me = healer["name"].lower()
    for other in all_names:
        if other.lower() != me and other.lower() in note_l:
            return other
    return None


def _check_self_target(note_l):
    for kw in SELF_TARGET_KEYWORDS:
        if kw in note_l:
            return kw
    return None



def _check_silent(healers, hours_override=None):
    """s110-n1: silent doctors detector. Threshold: silent_after_h (default SILENT_DEFAULT_H)."""
    findings = []
    now = datetime.now(timezone.utc)
    for h in healers:
        if h.get("role") != "doctor":
            continue
        name = h["name"]
        jrel = h.get("journal") or f"self/healers/{name}.jsonl"
        j = ROOT / jrel
        try:
            h_hours = int(hours_override) if hours_override is not None else int(h.get("silent_after_h", SILENT_DEFAULT_H))
        except Exception:
            h_hours = SILENT_DEFAULT_H
        cutoff = now - timedelta(hours=h_hours)
        reason = None
        last_ts = None
        if not j.exists():
            reason = "no_journal"
        else:
            try:
                mtime = datetime.fromtimestamp(j.stat().st_mtime, tz=timezone.utc)
                last_ts = mtime.isoformat(timespec="seconds")
                if mtime < cutoff:
                    reason = "stale"
            except Exception as e:
                reason = f"stat_error:{type(e).__name__}"
        if reason:
            findings.append({
                "kind": "silent_healer",
                "healer": name,
                "reason": reason,
                "last_ts": last_ts,
                "threshold_h": h_hours,
            })
    return findings

def _check_loop(rows):
    buckets = defaultdict(list)
    for dt, r in rows:
        buckets[(r.get("action"), r.get("note"))].append(dt)
    out = []
    for key, times in buckets.items():
        times.sort()
        for i in range(len(times)):
            end = times[i] + timedelta(minutes=LOOP_WINDOW_MIN)
            cnt = sum(1 for t in times[i:] if t <= end)
            if cnt >= LOOP_THRESHOLD:
                out.append({"kind": "loop", "action": key[0],
                            "note": (key[1] or "")[:80], "count": cnt,
                            "window_min": LOOP_WINDOW_MIN})
                break
    return out


def scan(rows, healers):
    all_names = [h["name"] for h in healers]
    by_name = {h["name"]: h for h in healers}
    findings = []
    for dt, r in rows:
        action = r.get("action")
        if action is None:
            continue
        h = by_name.get(action)
        if not h:
            continue
        if h.get("role") == "supervisor":
            continue
        note_l = (r.get("note") or "").lower()

        oos = _check_out_of_scope(h, note_l)
        if oos:
            findings.append({"kind": "out_of_scope", "healer": action,
                             "violated": oos[0], "trigger": oos[1],
                             "note": note_l[:80], "ts": r.get("ts")})
        cd = _check_cross_domain(h, note_l, all_names)
        if cd:
            findings.append({"kind": "cross_domain", "healer": action,
                             "other": cd, "note": note_l[:80], "ts": r.get("ts")})
        st = _check_self_target(note_l)
        if st:
            findings.append({"kind": "self_target", "healer": action,
                             "keyword": st, "note": note_l[:80], "ts": r.get("ts")})
    for f in _check_loop(rows):
        findings.append(f)
    return findings


def _fmt(f):
    k = f["kind"]
    if k == "out_of_scope":
        return f"🟠 out_of_scope[{f['healer']}] cannot={f['violated']} trigger={f['trigger']}"
    if k == "cross_domain":
        return f"🟡 cross_domain[{f['healer']}] mentions={f['other']}"
    if k == "loop":
        return f"🟠 loop[{f['action']}] count={f['count']} window={f['window_min']}m"
    if k == "self_target":
        return f"🔴 self_target[{f['healer']}] kw={f['keyword']}"
    return f"❓ {f}"


def cmd_report():
    healers = _load_healers()
    rows = _read_autonomy_since(hours=24)
    findings = scan(rows, healers)
    findings.extend(_check_silent(healers))  # s110-n1
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"## head_doctor report {ts}")
    print(f"- healers: {len(healers)}")
    _mem_total = sum(1 for h in healers if h.get("memory"))
    _mem_doc = sum(1 for h in healers if h.get("role") == "doctor" and h.get("memory"))
    _doc_total = sum(1 for h in healers if h.get("role") == "doctor")
    print(f"- memories: {_mem_total}/{len(healers)} (doctors: {_mem_doc}/{_doc_total})")  # s110-b5
    print(f"- autonomy rows (24h): {len(rows)}")
    print(f"- findings: {len(findings)}")
    if not findings:
        print("### no findings ✅")
        return 0
    print("### findings")
    for f in findings:
        print("  " + _fmt(f))
    return 0


def cmd_selftest():
    healers = [
        {"name": "disk_janitor", "role": "doctor",
         "cannot": ["mutate_core", "touch_sensitive"]},
        {"name": "llm_health", "role": "doctor",
         "cannot": ["mutate_core", "delete_file"]},
        {"name": "head_doctor", "role": "supervisor", "cannot": ["mutate_core"]},
    ]
    now = datetime.now(timezone.utc)
    rows = [
        (now, {"action": "disk_janitor", "note": "touched orchestrator.py"}),
        (now, {"action": "llm_health", "note": "called disk_janitor helper"}),
        (now, {"action": "disk_janitor", "note": "healer cleanup"}),
        (now, {"action": "disk_janitor", "note": "archive=5 delete_only=0"}),
        (now, {"action": "head_doctor", "note": "scan"}),
    ]
    for i in range(LOOP_THRESHOLD + 1):
        rows.append((now + timedelta(seconds=i),
                     {"action": "llm_health", "note": "auto_safe reason=already_today"}))

    findings = scan(rows, healers)
    kinds = Counter(f["kind"] for f in findings)
    print("selftest:")
    print(f"  total_findings: {len(findings)}")
    print(f"  by_kind: {dict(kinds)}")

    assert kinds.get("out_of_scope", 0) >= 1, "out_of_scope not found"
    assert kinds.get("cross_domain", 0) >= 1, "cross_domain not found"
    assert kinds.get("loop", 0) >= 1, "loop not found"
    assert kinds.get("self_target", 0) >= 1, "self_target not found"
    assert not any(f.get("healer") == "head_doctor" for f in findings), "supervisor skipped"

    print("  [OK] out_of_scope")
    print("  [OK] cross_domain")
    print("  [OK] loop")
    print("  [OK] self_target")
    print("  [OK] supervisor_skipped")
    print("passed 5/5")
    return 0


def cmd_run():
    healers = _load_healers()
    rows = _read_autonomy_since(hours=24)
    findings = scan(rows, healers)
    findings.extend(_check_silent(healers))  # s110-n1
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with open(JOURNAL, "a") as f:
        for fnd in findings:
            f.write(json.dumps({"ts": ts, "session": SESSION,
                                "healer": "head_doctor",
                                "finding": fnd}, ensure_ascii=False) + "\n")
    # s110-n2-heartbeat: heartbeat v журнал — «молчит» != «сломан»
    if not findings and _healer_log is not None:
        try:
            _healer_log("head_doctor", diagnosis="run_ok", action="noop",
                        outcome="noop",
                        extra={"findings": 0, "scope": "healers"})
        except Exception as _hbe:
            print(f"[head_doctor] heartbeat failed: {type(_hbe).__name__}: {_hbe}")

    print(f"[head_doctor] findings={len(findings)} written to {JOURNAL}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return cmd_selftest()
    if a.run:
        return cmd_run()
    return cmd_report()


if __name__ == "__main__":
    sys.exit(main())
