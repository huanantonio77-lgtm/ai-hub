#!/usr/bin/env python3
"""gepa/auto_evaluate.py - s132-t15 (was s128-t9).

Auto-evaluate GEPA challenger vs incumbent.

Rule:
  - challenger.runs >= MIN_RUNS (3)
  - if challenger.mean_quality >= incumbent.mean_quality -> promote()
  - else -> reject()

Daily lock: .cache/locks/gepa_auto_evaluate.last (mtime < 24h -> skip).
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "gepa") not in sys.path:
    sys.path.insert(0, str(ROOT / "gepa"))

import importlib.util as _iu

def _load_mod(name, path):
    spec = _iu.spec_from_file_location(name, path)
    m = _iu.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

_Score = _load_mod("gepa_score", ROOT / "gepa" / "score.py")
_Reg = _load_mod("gepa_registry", ROOT / "gepa" / "registry.py")
_Step = _load_mod("gepa_step", ROOT / "gepa" / "gepa_step.py")

MIN_RUNS = 3
LOCK = ROOT / ".cache" / "locks" / "gepa_auto_evaluate.last"
JOURNAL = ROOT / "self" / "curator" / "JOURNAL.jsonl"
STATE_MD = ROOT / "self" / "curator" / "STATE.md"


def _daily_ok():
    if not LOCK.exists():
        return True
    try:
        age = time.time() - LOCK.stat().st_mtime
    except Exception:
        return True
    return age >= 86400.0


def _touch_lock():
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    encoding="utf-8")


def _journal(rec):
    try:
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with JOURNAL.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass



def _current_session():
    """Read current session id from self/curator/STATE.md.
    Returns e.g. 's132'. Falls back to 'unknown' if unavailable.
    """
    try:
        for line in STATE_MD.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith("**") and "\u0422\u0435\u043a\u0443\u0449\u0430\u044f \u0441\u0435\u0441\u0441\u0438\u044f" in s:
                tail = s.split("**")[-1].strip().rstrip(".")
                if tail.startswith("s") and tail[1:].isdigit():
                    return tail
    except Exception:
        pass
    return "unknown"


def _decide(inc_m, chl_m, min_runs=MIN_RUNS):
    """Pure decision function. No I/O, no registry writes.

    Returns (action, reason) where action in {"promote", "reject", "skip"}.
    skip    - incumbent or challenger lacks enough tracked (closed) tasks;
              do NOT touch the challenger, let it accumulate data.
    promote - challenger mean_quality >= incumbent mean_quality.
    reject  - challenger mean_quality <  incumbent mean_quality.
    """
    inc_tracked = int((inc_m or {}).get("keys_tracked", 0))
    chl_tracked = int((chl_m or {}).get("keys_tracked", 0))
    if inc_tracked < min_runs:
        return "skip", "inc_undersampled"
    if chl_tracked < min_runs:
        return "skip", "chl_undersampled"
    inc_q = float((inc_m or {}).get("mean_quality", 0.0))
    chl_q = float((chl_m or {}).get("mean_quality", 0.0))
    if chl_q >= inc_q:
        return "promote", "chl_ge_inc"
    return "reject", "chl_lt_inc"

def run(target="self_reflect", quiet=False, daily_lock=False):
    if daily_lock and not _daily_ok():
        if not quiet:
            print("auto_evaluate: daily lock active, skip")
        return {"ok": True, "skipped": "daily_lock"}

    reg = _Reg.load_registry(target=target) or {}
    incumbent = reg.get("incumbent")
    challenger = reg.get("challenger")
    if not challenger:
        if not quiet:
            print("auto_evaluate: no challenger, skip")
        return {"ok": True, "skipped": "no_challenger"}

    sc = _Score.score(target=target)
    inc_m = sc.get(incumbent) or {}
    chl_m = sc.get(challenger) or {}
    inc_q = float(inc_m.get("mean_quality", 0.0))
    chl_q = float(chl_m.get("mean_quality", 0.0))
    inc_tracked = int(inc_m.get("keys_tracked", 0))
    chl_tracked = int(chl_m.get("keys_tracked", 0))

    action, reason = _decide(inc_m, chl_m, MIN_RUNS)

    if action == "skip":
        if not quiet:
            print("auto_evaluate: skip (" + reason + ") inc_tracked=" +
                  str(inc_tracked) + " chl_tracked=" + str(chl_tracked))
        if daily_lock:
            _touch_lock()
        return {"ok": True, "skipped": reason,
                "inc_tracked": inc_tracked, "chl_tracked": chl_tracked}

    if action == "promote":
        result = _Step.promote(target=target)
    else:
        result = _Step.reject(target=target)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    _journal({
        "ts": ts, "session": _current_session(), "action": "gepa_auto_evaluate",
        "target": target, "decision": action, "reason": reason,
        "incumbent": incumbent, "inc_q": inc_q, "inc_tracked": inc_tracked,
        "challenger": challenger, "chl_q": chl_q, "chl_tracked": chl_tracked,
        "result": result,
    })
    if daily_lock:
        _touch_lock()
    if not quiet:
        print("auto_evaluate: " + action + " challenger=" + str(challenger) +
              " (q=" + str(chl_q) + ", tracked=" + str(chl_tracked) + ") vs incumbent=" +
              str(incumbent) + " (q=" + str(inc_q) + ", tracked=" + str(inc_tracked) + ")")
    return {"ok": True, "decision": action, "reason": reason, "result": result,
            "inc_q": inc_q, "chl_q": chl_q,
            "inc_tracked": inc_tracked, "chl_tracked": chl_tracked}


def _selftest():
    """Test the pure _decide function on synthetic metrics.
    Does NOT touch the real registry or state.json.
    """
    a, r = _decide({"keys_tracked": 33, "mean_quality": 0.77},
                    {"keys_tracked": 0, "mean_quality": 0.0}, 3)
    assert a == "skip" and r == "chl_undersampled", (a, r)

    a, r = _decide({"keys_tracked": 0, "mean_quality": 0.0},
                    {"keys_tracked": 5, "mean_quality": 0.5}, 3)
    assert a == "skip" and r == "inc_undersampled", (a, r)

    a, r = _decide({"keys_tracked": 10, "mean_quality": 0.5},
                    {"keys_tracked": 10, "mean_quality": 0.9}, 3)
    assert a == "promote", (a, r)

    a, r = _decide({"keys_tracked": 10, "mean_quality": 0.9},
                    {"keys_tracked": 10, "mean_quality": 0.4}, 3)
    assert a == "reject", (a, r)

    a, r = _decide({"keys_tracked": 5, "mean_quality": 0.5},
                    {"keys_tracked": 5, "mean_quality": 0.5}, 3)
    assert a == "promote", (a, r)

    a, r = _decide({"keys_tracked": 3, "mean_quality": 0.5},
                    {"keys_tracked": 3, "mean_quality": 0.6}, 3)
    assert a == "promote", (a, r)

    print("SELFTEST-PASS auto_evaluate _decide: 6 cases ok")
    return 0



def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="self_reflect")
    ap.add_argument("--daily-lock", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return _selftest()
    out = run(target=args.target, quiet=args.quiet, daily_lock=args.daily_lock)
    print(json.dumps(out, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
