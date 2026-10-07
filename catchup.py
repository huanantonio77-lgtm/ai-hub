#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""catchup.py - ПРАВИЛО №01: состояние на диске, детект пропусков.

Знает, когда каждая критичная задача последний раз успешно отработала,
честно считает пропуски (Mac спал, свет, сеть). Догон - s85-3b.
"""
from __future__ import annotations
import argparse, json, os, sys
from datetime import datetime, timezone
from pathlib import Path


def _silent(tag, e):
    """s104-2c: emit silent except to errors.jsonl (K1 emission)."""
    try:
        from datetime import datetime as _dt, timezone as _tz
        log = Path(__file__).resolve().parent / ".cache" / "system" / "errors.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": _dt.now(_tz.utc).strftime("%Y-%m-%d %H:%M:%S"),
               "kind": "silent", "where": "catchup.py",
               "detail": tag + ": " + type(e).__name__ + ": " + str(e)[:100]}
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as _e:
        _silent("catchup_outer", _e)

STATE_FILE = Path("strategy/_catchup_state.json")
HISTORY_LIMIT = 10
AUTONOMY_FILE = Path("self/autonomy.jsonl")
TASKS = {
    "selfcheck":          {"interval_s": 3600,  "grace_s": 1800},
    "self-reflect":       {"interval_s": 86400, "grace_s": 7200},
    "self-apply":         {"interval_s": 86400, "grace_s": 7200},
    "validate-providers": {"interval_s": 86400, "grace_s": 7200},
}
def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _parse_iso(s):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.strip())
    except (ValueError, AttributeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def _atomic_write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    txt = json.dumps(data, ensure_ascii=False, indent=2)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(txt)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

def _load_state():
    if not STATE_FILE.exists():
        return {"version": 1, "updated": None, "tasks": {}}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "updated": None, "tasks": {}}

def _save_state(state):
    _atomic_write_json(STATE_FILE, state)

def record(task_name, ts=None, by="manual"):
    if task_name not in TASKS:
        raise ValueError("unknown task: " + task_name)
    state = _load_state()
    tasks = state.setdefault("tasks", {})
    entry = tasks.get(task_name, {})
    if ts is None:
        ts = _now_iso()
    entry["last_success_ts"] = ts
    entry["last_record_by"] = by
    # s86-2-record-awake
    try:
        import awake_tracker as _awt
        entry["last_ok_awake_s"] = _awt.current()
    except Exception as _e:
        _silent("catchup_outer", _e)
    hist = entry.get("history", [])
    hist.insert(0, ts)
    entry["history"] = hist[:HISTORY_LIMIT]
    tasks[task_name] = entry
    state["tasks"] = tasks
    state["updated"] = ts
    _save_state(state)
    return entry
def report():
    state = _load_state()
    now = datetime.now(timezone.utc)
    out = {}
    for task, cfg in TASKS.items():
        entry = state.get("tasks", {}).get(task, {})
        lst = entry.get("last_success_ts")
        last = _parse_iso(lst)
        if last is None:
            out[task] = {
                "last_success_ts": None,
                "gap_s": None,
                "expected_s": cfg["interval_s"],
                "missed_count": 0,
                "status": "unknown",
            }
            continue
        gap_s = int((now - last).total_seconds())
        # s86-2-report-awake
        wall_gap_s = gap_s
        awake_gap_s = gap_s
        _last_ok_awake = entry.get("last_ok_awake_s")
        if _last_ok_awake is not None:
            try:
                import awake_tracker as _awt
                _cur_awake = _awt.current()
                awake_gap_s = max(0, int(_cur_awake - _last_ok_awake))
            except Exception as _e:
                _silent("catchup_inner", _e)
        expected = cfg["interval_s"]
        grace = cfg["grace_s"]
        if awake_gap_s <= expected + grace:
            status = "alive"
            missed = 0
        else:
            status = "regression"
            missed = max(0, int((awake_gap_s - grace) / expected))
        out[task] = {
            "last_success_ts": lst,
            "gap_s": awake_gap_s,
            "wall_gap_s": wall_gap_s,
            "awake_gap_s": awake_gap_s,
            "expected_s": expected,
            "missed_count": missed,
            "status": status,
        }
    return out

def _append_autonomy(note, **extra):
    """s108-wake-autonomy: метки автономности catchup (fail-open)."""
    try:
        try:
            from session_meta import current as _sess_cur
            _sess = _sess_cur()
        except Exception:
            _sess = "s108"
        rec = {"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
               "session": _sess, "action": "catchup", "note": note}
        rec.update(extra)
        AUTONOMY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with AUTONOMY_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + chr(10))
    except Exception as _e:
        _silent("catchup_autonomy", _e)


def detect():
    rep = report()
    return {k: v for k, v in rep.items() if v["status"] == "regression"}

CATCHUP_SCRIPTS = {
    "self-reflect":       ["python3", "self_reflect.py", "--run"],
    "self-apply":         ["python3", "self_apply.py", "--run"],
    "validate-providers": ["python3", "validate_providers.py"],
}
CATCHUP_WINDOW_HOURS = (22, 8)
CATCHUP_LIMIT_PER_CALL = 4
CATCHUP_TIMEOUT_S = 300


def _in_window(now=None):
    if now is None:
        now = datetime.now()
    h = now.hour
    start, end = CATCHUP_WINDOW_HOURS
    if start <= end:
        return start <= h < end
    return h >= start or h < end


def due(only=None):
    # s99-rule03: catch-up без окна - Mac/интернет не гарантированы.
    # _in_window() остаётся для validate_providers.py (s86-1b-gate).
    rep = report()
    result = []
    for task in TASKS:
        if task not in CATCHUP_SCRIPTS:
            continue
        if only is not None and task not in only:
            continue
        if rep.get(task, {}).get("status") != "regression":
            continue
        result.append(task)
    return result


def run_due(only=None, dry=False):
    import subprocess, time as _time
    targets = due(only=only)
    if not targets:
        return []
    targets = targets[:CATCHUP_LIMIT_PER_CALL]
    out = []
    for task in targets:
        cmd = CATCHUP_SCRIPTS[task]
        if dry:
            out.append((task, "dry", 0.0))
            continue
        t0 = _time.time()
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=CATCHUP_TIMEOUT_S)
            elapsed = _time.time() - t0
            if r.returncode == 0:
                record(task, by="catchup-run")
                _rep2 = report()
                _gap2 = _rep2.get(task, {}).get("gap_s")
                _append_autonomy("catchup_wake", reason="wake", task=task, gap_s=_gap2)
                try:
                    from journal import log_event
                    log_event(site="catchup", action="run", target=task, result="ok")
                except Exception as _e:
                    _silent("catchup_inner2", _e)
                out.append((task, "ok", elapsed))
            else:
                try:
                    from journal import log_event
                    log_event(site="catchup", action="run", target=task, result="fail")
                except Exception as _e:
                    _silent("catchup_inner2", _e)
                out.append((task, "fail:" + str(r.returncode), elapsed))
        except Exception as e:
            out.append((task, "error:" + type(e).__name__, _time.time() - t0))
            _append_autonomy("catchup_offline", reason="offline", task=task, err=type(e).__name__)
    return out


def main():
    ap = argparse.ArgumentParser(prog="catchup.py")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--record", metavar="TASK")
    g.add_argument("--report", action="store_true")
    g.add_argument("--detect", action="store_true")
    g.add_argument("--run-due", dest="run_due", action="store_true")
    ap.add_argument("--by", default="cli")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--only", nargs="*", default=None)
    args = ap.parse_args()

    if args.record:
        try:
            entry = record(args.record, by=args.by)
        except ValueError as e:
            print("ERROR: " + str(e), file=sys.stderr)
            sys.exit(1)
        print("recorded: " + args.record + " ts=" + entry["last_success_ts"])
        sys.exit(0)

    if args.report:
        rep = report()
        for task, v in rep.items():
            gap = v["gap_s"]
            gap_s = "-" if gap is None else str(gap)
            print("{:22s} status={:10s} gap_s={:>8s} missed={}".format(
                task, v["status"], gap_s, v["missed_count"]))
        sys.exit(0)

    if args.detect:
        d = detect()
        for task, v in d.items():
            print("[MISS] {:22s} gap_s={} missed={}".format(
                task, v["gap_s"], v["missed_count"]))
        sys.exit(2 if d else 0)

    if getattr(args, "run_due", False):
        try:
            res = run_due(only=args.only, dry=args.dry)
        except Exception as e:
            print("ERROR: " + type(e).__name__ + ": " + str(e))
            sys.exit(1)
        if not res:
            print("run-due: nothing due")
        else:
            for task, status, elapsed in res:
                print("run-due: " + task + " -> " + status + " (" + ("{:.1f}s".format(elapsed)) + ")")
        sys.exit(0)

if __name__ == "__main__":
    main()
