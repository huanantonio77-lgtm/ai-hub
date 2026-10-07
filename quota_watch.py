#!/usr/bin/env python3
# quota_watch.py (s119) -- Safety Layer 5 v2 healer: Rate Limiting & Quotas.
#
# Detector + actuator for per-provider/model quota pressure.
# Reads forecasts from token_tracker (24h window), compares to provider_limits.json.
#
# Levels:
#   ok    : pct < WARN_PCT (80)
#   warn  : 80 <= pct < CRIT_PCT (95)
#   crit  : pct >= CRIT_PCT or over explicit budget
#
# Actuator (--run):
#   crit  -> autonomy.jsonl (effect=2) + repair_task via memory.next_actions, cooldown 1h.
#   warn  -> journal only.
#
# Rights: record_finding, add_repair_task.
# Cannot: mutate_core, delete_file, set_cooldown, touch_secrets_dir.
#
# Journal: self/healers/quota_watch.jsonl
# Medcard: self/healers/quota_watch.md
# Not CORE. Not sensitive.

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AUTONOMY = ROOT / "self" / "autonomy.jsonl"
HEALER_JOURNAL = ROOT / "self" / "healers" / "quota_watch.jsonl"
AUTOTRIGGER_MARKER = ROOT / "self" / "healers" / ".quota_watch_trigger"
AUTOTRIGGER_COOLDOWN_H = 1
WARN_PCT = 80
CRIT_PCT = 95
LIMITS_FILE = ROOT / "provider_limits.json"


def _ts():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _session():
    try:
        import session_meta as _sm
        return _sm.current()
    except Exception:
        return "unknown"


def _rpd_limits():
    try:
        d = json.loads(LIMITS_FILE.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    out = {}
    for p, v in d.items():
        if isinstance(p, str) and p.startswith("_"):
            continue
        if isinstance(v, dict):
            out[p] = v
    return out


def _forecast():
    try:
        import token_tracker as tt
        rows = tt.forecast(24)
    except Exception as e:
        return [{"error": str(e)[:200]}]
    lim = _rpd_limits()
    for r in rows:
        if r.get("error"):
            continue
        cfg = lim.get(r.get("provider")) or {}
        rpd = cfg.get("rpd")
        r["rpd"] = rpd
        if isinstance(rpd, int) and rpd > 0:
            calls = r.get("calls") or 0
            r["pct_rpd"] = round(100.0 * calls / rpd, 1)
        else:
            r["pct_rpd"] = None
    return rows


def _effective_pct(r):
    vals = []
    if isinstance(r.get("pct"), (int, float)):
        vals.append(r["pct"])
    if isinstance(r.get("pct_rpd"), (int, float)):
        vals.append(r["pct_rpd"])
    return max(vals) if vals else None


def _classify(rows):
    warn = []
    crit = []
    unknown = []
    for r in rows:
        if r.get("error"):
            unknown.append(r)
            continue
        pct = _effective_pct(r)
        if pct is None:
            unknown.append(r)
            continue
        if pct >= CRIT_PCT:
            r["effective_pct"] = pct
            crit.append(r)
        elif pct >= WARN_PCT:
            r["effective_pct"] = pct
            warn.append(r)
    return warn, crit, unknown


def _add_repair_task(crit):
    if not crit:
        return False
    marker = "[repair:quota-watch]"
    parts = []
    for c in crit[:5]:
        p = c.get("provider") or "?"
        m = c.get("model") or "?"
        pct = c.get("effective_pct")
        rpd = c.get("rpd")
        parts.append(p + "/" + m + "(" + str(pct) + "% of " + str(rpd) + " rpd)")
    text = marker + " " + str(len(crit)) + " over quota: " + ", ".join(parts)
    try:
        import memory as _mem_mod
        _m = _mem_mod.Memory()
        actions = list(_m.get("next_actions", []) or [])
        replaced = False
        for i, a in enumerate(actions):
            if isinstance(a, str) and a.startswith(marker):
                actions[i] = text
                replaced = True
                break
        if not replaced:
            actions.append(text)
        _m.update("next_actions", actions)
        return True
    except Exception:
        return False


def run_report(quiet=False, actuate=False):
    rows = _forecast()
    warn, crit, unknown = _classify(rows)
    level = "crit" if crit else ("warn" if warn else "ok")
    if not quiet:
        print("quota_watch: providers=" + str(len(rows))
              + " warn=" + str(len(warn)) + " crit=" + str(len(crit))
              + " unknown=" + str(len(unknown))
              + " level=" + level)
        for r in crit[:5]:
            print("  [CRIT] " + r.get("provider", "?") + "/" + r.get("model", "?")
                  + " pct=" + str(r.get("effective_pct"))
                  + " (rpd=" + str(r.get("rpd", "?")) + ")"
                  + " calls=" + str(r.get("calls", 0)))
        for r in warn[:5]:
            print("  [WARN] " + r.get("provider", "?") + "/" + r.get("model", "?")
                  + " pct=" + str(r.get("effective_pct"))
                  + " (rpd=" + str(r.get("rpd", "?")) + ")"
                  + " calls=" + str(r.get("calls", 0)))

    # journal
    try:
        HEALER_JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with HEALER_JOURNAL.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": _ts(), "session": _session(), "healer": "quota_watch",
                "diagnosis": level,
                "action": "report",
                "effect": 2 if crit else (1 if warn else 0),
                "outcome": level,
                "note": "warn=" + str(len(warn)) + " crit=" + str(len(crit)),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass

    if crit:
        try:
            with AUTONOMY.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": _ts(), "session": _session(),
                    "action": "quota_watch_crit",
                    "note": "crit=" + str(len(crit)) + " warn=" + str(len(warn)),
                    "effect": 2,
                }, ensure_ascii=False) + "\n")
        except Exception:
            pass

    if actuate and crit:
        _actuate(crit, quiet)

    return 0 if level == "ok" else 1


def _actuate(crit, quiet):
    if AUTOTRIGGER_MARKER.exists():
        age = time.time() - AUTOTRIGGER_MARKER.stat().st_mtime
        if age < AUTOTRIGGER_COOLDOWN_H * 3600:
            if not quiet:
                print("quota_watch actuator: skipped (cooldown "
                      + str(round(age/3600, 1)) + "h)")
            return
    try:
        AUTOTRIGGER_MARKER.parent.mkdir(parents=True, exist_ok=True)
        AUTOTRIGGER_MARKER.write_text(_ts(), encoding="utf-8")
    except Exception:
        pass
    # v2 actuator: autonomy record + repair_task via memory.next_actions.
    # Does NOT touch CORE/FROZEN (llm_call, limits). Cannot set cooldown.
    rt_ok = _add_repair_task(crit)
    try:
        with AUTONOMY.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": _ts(), "session": _session(),
                "action": "quota_watch_actuated",
                "note": "crit=" + str(len(crit)) + " rt=" + ("1" if rt_ok else "0")
                        + " providers: "
                        + ",".join((c.get("provider") or "?") + "/" + (c.get("model") or "?")
                                   for c in crit[:5]),
                "effect": 2 if rt_ok else 1,
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass
    if not quiet:
        print("quota_watch actuator: signed crit (" + str(len(crit))
              + " entries, repair_task=" + ("yes" if rt_ok else "no") + ")")


def main():
    ap = argparse.ArgumentParser(prog="quota_watch.py")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    return run_report(quiet=args.quiet, actuate=args.run)


if __name__ == "__main__":
    sys.exit(main())
