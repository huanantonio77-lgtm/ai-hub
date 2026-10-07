#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""awake_tracker.py - s86-2: учёт времени бодрствования Mac.

Считает не wall-clock, а секунды реального бодрствования.
State: strategy/_awake_state.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

STATE_FILE = Path("strategy/_awake_state.json")
MAX_GAP_S = 5400  # 90 мин: порог бодрствования


def _now_utc():
    return datetime.now(timezone.utc)


def _now_iso():
    return _now_utc().isoformat(timespec="seconds")


def _parse_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _load_state():
    if not STATE_FILE.exists():
        return {"version": 1, "last_tick_ts": None, "awake_total_s": 0}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "last_tick_ts": None, "awake_total_s": 0}


def _atomic_write(path, text):
    d = path.parent
    d.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".awake_", dir=str(d))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def _save_state(state):
    _atomic_write(STATE_FILE, json.dumps(state, ensure_ascii=False))


def tick(by="manual", max_gap_s=MAX_GAP_S):
    state = _load_state()
    now = _now_utc()
    last = _parse_iso(state.get("last_tick_ts"))
    delta = 0
    if last is not None:
        delta = int((now - last).total_seconds())
        if 0 <= delta <= max_gap_s:
            state["awake_total_s"] = int(state.get("awake_total_s", 0)) + delta
    state["last_tick_ts"] = _now_iso()
    state["version"] = 1
    state["last_by"] = by
    _save_state(state)
    return {"delta_s": delta, "awake_total_s": state["awake_total_s"]}


def current():
    return int(_load_state().get("awake_total_s", 0))


def _test():
    import time as _t
    from datetime import timedelta
    import tempfile as _tf
    global STATE_FILE
    orig = STATE_FILE
    try:
        with _tf.TemporaryDirectory() as d:
            STATE_FILE = Path(d) / "_awake_state.json"
            assert current() == 0, "T1"
            r = tick(by="test")
            assert STATE_FILE.exists(), "T2a"
            assert r["delta_s"] == 0, "T2b"
            _t.sleep(2)
            r = tick(by="test")
            assert 1 <= r["delta_s"] <= 5, "T3a: " + str(r["delta_s"])
            assert current() >= 2, "T3b"
            s = _load_state()
            s["last_tick_ts"] = (_now_utc() - timedelta(hours=5)).isoformat(timespec="seconds")
            _save_state(s)
            before = current()
            r = tick(by="test")
            after = current()
            assert r["delta_s"] >= 17000, "T4a: " + str(r["delta_s"])
            assert after == before, "T4b"
            print("UNIT-OK 4/4")
    finally:
        STATE_FILE = orig


def main():
    ap = argparse.ArgumentParser(prog="awake_tracker.py")
    ap.add_argument("--tick", action="store_true")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--by", default="manual")
    args = ap.parse_args()
    if args.test:
        _test()
        return 0
    if args.tick:
        r = tick(by=args.by)
        print("tick: delta=" + str(r["delta_s"]) + "s total=" + str(r["awake_total_s"]) + "s")
        return 0
    if args.show:
        print("awake_total_s=" + str(current()))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
