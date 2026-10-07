#!/usr/bin/env python3
"""
fork_watch.py — s110 A8.
Детектор fork-storm. Читает self/healers/fork_watch.jsonl, считает частоту
fork-событий в окне 60 мин. При >= 3 → finding kind=fork_storm.

Режимы:
  --record    одна строка в журнал (вызывается safe_run.sh при fork)
  --report    read-only, агрегат
  --run       записать heartbeat/findings в журнал
  --selftest  проверки на синтетике
"""
import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
JOURNAL = ROOT / "self" / "healers" / "fork_watch.jsonl"
WINDOW_MIN = 60
THRESHOLD = 3

try:
    from session_meta import current as _session_current
    SESSION = _session_current()
except Exception:
    SESSION = "unknown"

try:
    from healer_log import healer_log as _healer_log
except Exception:
    _healer_log = None


def _ts():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sys_load():
    """Замерить нагрузку в момент fork — чтобы отличить storm от утечки."""
    out = {}
    try:
        a, b, c = os.getloadavg()
        out["load_1"] = round(a, 2)
        out["load_5"] = round(b, 2)
    except Exception:
        pass
    try:
        rc = subprocess.run(["ps", "-Ao", "pid"], capture_output=True, text=True, timeout=3)
        if rc.returncode == 0:
            out["procs"] = len(rc.stdout.strip().splitlines()) - 1
    except Exception:
        pass
    try:
        rc = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True, timeout=3)
        if rc.returncode == 0:
            import re
            m = re.search(r"used\s*=\s*([\d.,]+)M", rc.stdout)
            if m:
                out["swap_used_mb"] = float(m.group(1).replace(",", "."))
    except Exception:
        pass
    return out


def record(rc=1, attempt=1, exhausted=False):
    """Записать одно fork-событие. Fail-open."""
    try:
        rec = {
            "ts": _ts(),
            "session": SESSION,
            "healer": "fork_watch",
            "kind": "fork",
            "rc": rc,
            "attempt": attempt,
            "exhausted": bool(exhausted),
            "sys": _sys_load(),
        }
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with open(JOURNAL, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return True
    except Exception as e:
        print("[fork_watch] record fail:", type(e).__name__, e, file=sys.stderr)
        return False


def _read_events(hours=24):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = []
    if not JOURNAL.exists():
        return rows
    with open(JOURNAL, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                dt = datetime.fromisoformat(r.get("ts", "").replace("Z", "+00:00"))
                if dt >= cutoff:
                    rows.append((dt, r))
            except Exception:
                continue
    return rows


def find_findings(now=None):
    """Найти storm-эпизоды в окне WINDOW_MIN."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=WINDOW_MIN)
    events = [(dt, r) for dt, r in _read_events(hours=24) if dt >= cutoff]
    findings = []
    if len(events) >= THRESHOLD:
        # сгруппировать по exhausted
        kinds = Counter("exhausted" if r.get("exhausted") else "recovered" for _, r in events)
        sw = None
        for _, r in events:
            s = r.get("sys") or {}
            if "swap_used_mb" in s:
                sw = s["swap_used_mb"]
                break
        findings.append({
            "kind": "fork_storm",
            "window_min": WINDOW_MIN,
            "events": len(events),
            "recovered": kinds.get("recovered", 0),
            "exhausted": kinds.get("exhausted", 0),
            "swap_used_mb": sw,
        })
    return findings


def cmd_report():
    events = _read_events(hours=24)
    print("## fork_watch report", _ts())
    print(f"- events_24h: {len(events)}")
    if events:
        latest = events[-1][0].isoformat(timespec="seconds")
        print(f"- last_event: {latest}")
    findings = find_findings()
    print(f"- findings: {len(findings)}")
    if findings:
        for f in findings:
            print(f"  - {f['kind']} events={f['events']} recovered={f['recovered']} exhausted={f['exhausted']} swap_mb={f['swap_used_mb']}")
    else:
        print("### no findings ✅")
    return 0


def cmd_run():
    findings = find_findings()
    if _healer_log is None:
        print("[fork_watch] healer_log недоступен — skip")
    elif findings:
        for f in findings:
            _healer_log("fork_watch", diagnosis=f"storm events={f['events']}",
                        action="record_finding", outcome="failed",
                        lesson="fork_storm_detected",
                        extra=f)
        print(f"[fork_watch] findings={len(findings)} written")
    else:
        _healer_log("fork_watch", diagnosis="run_ok", action="noop",
                    outcome="noop", extra={"findings": 0})
        print("[fork_watch] findings=0 written (heartbeat)")
    return 0


def _selftest():
    import tempfile
    global JOURNAL
    orig = JOURNAL
    tmpdir = Path(tempfile.mkdtemp(prefix="fork_watch_st_"))
    JOURNAL = tmpdir / "fork_watch.jsonl"
    try:
        # 1. Пустой журнал → 0 findings
        assert find_findings() == [], "empty journal → 0 findings"
        print("  [OK] empty_journal")

        # 2. Записываем 1 событие → 0 findings
        record(rc=1, attempt=1)
        assert len(find_findings()) == 0, "1 event → 0 findings"
        print("  [OK] one_event_no_finding")

        # 3. Записываем ещё 2 → 3 события → 1 finding
        record(rc=1, attempt=2)
        record(rc=1, attempt=1)
        f = find_findings()
        assert len(f) == 1, f"3 events → 1 finding, got {len(f)}"
        assert f[0]["kind"] == "fork_storm"
        assert f[0]["events"] == 3
        print("  [OK] three_events_finding")

        # 4. Окно: old event (2h назад) не учитывается
        JOURNAL = tmpdir / "fw2.jsonl"
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(timespec="seconds")
        JOURNAL.write_text(json.dumps({"ts": old_ts, "kind": "fork"}) + "\n")
        record(rc=1)
        assert len(find_findings()) == 0, "old event outside window"
        print("  [OK] window_filter")

        # 5. Fail-open: путь недоступен
        JOURNAL = Path("/nonexistent_ro_xyz/fw.jsonl")
        ok = record(rc=1)
        assert ok is False, "fail-open не сработал"
        print("  [OK] fail_open")

        print("passed 5/5")
        return 0
    finally:
        JOURNAL = orig
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--rc", type=int, default=1)
    ap.add_argument("--attempt", type=int, default=1)
    ap.add_argument("--exhausted", action="store_true")
    a = ap.parse_args()
    if a.record:
        ok = record(rc=a.rc, attempt=a.attempt, exhausted=a.exhausted)
        return 0 if ok else 0  # fail-open: всегда 0
    if a.report:
        return cmd_report()
    if a.run:
        return cmd_run()
    if a.selftest:
        return _selftest()
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
