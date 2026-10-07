#!/usr/bin/env python3
"""window_audit.py (s104-0) - K2: sverka okon detektorov s vremenem zhizni obektov.

Klass oshibki orphan_429: detektor smotrit v okno 24h, obekt (cooldown) zhivet 30min.
Fiksim sam klass cherez audit vseh par detektor/obekt.

Pravilo: window / ttl > RATIO_WARN -> warning, > RATIO_FAIL -> critical.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SESSION = "s104"
SYSTEM = ROOT / ".cache" / "system"
REPORT_PATH = SYSTEM / "window_audit.json"
AUTONOMY = ROOT / "self" / "autonomy.jsonl"

# Vremya zhizni obektov (sek)
OBJECT_TTL = {
    "model_cooldowns_429": 1800,      # 30 min
    "model_cooldowns_402": 21600,     # 6 h
    "model_cooldowns_404": 604800,    # 7 d
    "errors_24h": 86400,              # 24 h agregat
    "token_usage_24h": 86400,         # 24 h
    "models_sync_daily": 86400,       # lock
}

# Pary: detektor smotrit v okno window_sec po obektu object
WINDOW_REGISTRY = [
    {"detector": "llm_health._read_errors_24h", "window_sec": 86400, "object": "errors_24h"},
    {"detector": "llm_health._orphan_429", "window_sec": 1800, "object": "model_cooldowns_429"},
    {"detector": "blindness_audit.scan", "window_sec": 86400, "object": "errors_24h"},
    {"detector": "token_tracker.summary", "window_sec": 86400, "object": "token_usage_24h"},
    {"detector": "llm_models_sync.auto_safe_lock", "window_sec": 86400, "object": "models_sync_daily"},
]

RATIO_WARN = 4.0
RATIO_FAIL = 24.0


def _check_pair(entry):
    obj = entry.get("object")
    ttl = OBJECT_TTL.get(obj)
    if not ttl:
        return {"detector": entry["detector"], "object": obj,
                "status": "unknown", "reason": "no ttl for " + str(obj)}
    w = int(entry["window_sec"])
    ratio = w / float(ttl)
    rec = {"detector": entry["detector"], "object": obj,
           "window_sec": w, "ttl_sec": ttl, "ratio": round(ratio, 2)}
    if ratio > RATIO_FAIL:
        rec["status"] = "critical"
        rec["reason"] = "window >> ttl (" + str(round(ratio, 1)) + "x)"
    elif ratio > RATIO_WARN:
        rec["status"] = "warning"
        rec["reason"] = "window > ttl (" + str(round(ratio, 1)) + "x)"
    else:
        rec["status"] = "ok"
        rec["reason"] = "aligned"
    return rec


def scan():
    rows = [_check_pair(e) for e in WINDOW_REGISTRY]
    n_ok = sum(1 for r in rows if r["status"] == "ok")
    n_warn = sum(1 for r in rows if r["status"] == "warning")
    n_crit = sum(1 for r in rows if r["status"] == "critical")
    n_unk = sum(1 for r in rows if r["status"] == "unknown")
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "session": SESSION,
        "rows": rows,
        "ok": n_ok, "warning": n_warn, "critical": n_crit, "unknown": n_unk,
        "total": len(rows),
    }


def _append_autonomy(note):
    from datetime import datetime as _dt, timezone as _tz
    ts = _dt.now(_tz.utc).isoformat(timespec="seconds")
    rec = {"ts": ts, "session": SESSION, "action": "window_audit", "note": note}
    AUTONOMY.parent.mkdir(parents=True, exist_ok=True)
    with AUTONOMY.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def run_report(quiet=False):
    r = scan()
    SYSTEM.mkdir(parents=True, exist_ok=True)
    try:
        REPORT_PATH.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print("window_audit: write fail: " + type(e).__name__ + ": " + str(e)[:120])
    note = "ok=" + str(r["ok"]) + " warn=" + str(r["warning"]) + " crit=" + str(r["critical"])
    _append_autonomy(note)
    # s123-lab-healers-wired: lab journal
    try:
        from healer_log import healer_log
        healer_log("window_audit", diagnosis="scan_completed",
                   action="report", outcome="recorded")
    except Exception:
        pass
    if not quiet:
        print("## " + r["ts"])
        print("### Window audit (K2)")
        print("- total pairs:", r["total"])
        print("- ok:", r["ok"], " warning:", r["warning"], " critical:", r["critical"], " unknown:", r["unknown"])
        print("### Rows")
        for row in r["rows"]:
            print("  [" + row["status"].upper() + "]",
                  row.get("detector", "?"), "->", row.get("object", "?"),
                  " ratio=" + str(row.get("ratio", "?")),
                  " (" + row.get("reason", "") + ")")
    return note


def _selftest():
    passed = 0
    failed = 0

    def chk(name, ok):
        nonlocal passed, failed
        if ok:
            print("  [OK]", name); passed += 1
        else:
            print("  [FAIL]", name); failed += 1

    # case 1: ok - 30m vs 30m
    r = _check_pair({"detector": "x", "window_sec": 1800, "object": "model_cooldowns_429"})
    chk("ok_30m_vs_30m", r["status"] == "ok")

    # case 2: ok - 24h vs 24h
    r = _check_pair({"detector": "x", "window_sec": 86400, "object": "errors_24h"})
    chk("ok_24h_vs_24h", r["status"] == "ok")

    # case 3: warning - 4h vs 30m (8x)
    r = _check_pair({"detector": "x", "window_sec": 14400, "object": "model_cooldowns_429"})
    chk("warn_4h_vs_30m", r["status"] == "warning")

    # case 4: critical - 24h vs 30m (48x) = klass orphan_429
    r = _check_pair({"detector": "x", "window_sec": 86400, "object": "model_cooldowns_429"})
    chk("crit_24h_vs_30m", r["status"] == "critical")

    # case 5: unknown object
    r = _check_pair({"detector": "x", "window_sec": 100, "object": "no_such"})
    chk("unknown_object", r["status"] == "unknown")

    # case 6: full scan runs
    s = scan()
    chk("scan_runs", isinstance(s.get("rows"), list) and s["total"] == len(WINDOW_REGISTRY))

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
        print(json.dumps(scan(), ensure_ascii=False, indent=2)); return 0
    if a.report:
        run_report(quiet=False); return 0
    ap.print_help(); return 0


if __name__ == "__main__":
    raise SystemExit(main())
