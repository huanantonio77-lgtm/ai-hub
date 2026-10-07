#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""blindness_audit.py (s102-2) - meta-detector: (kind,where) with N occurrences
in 24h and no [repair:*] marker -> auto-create repair_task. Killer of dead sensors."""
import argparse
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
import session_meta as _sm

ROOT = Path(__file__).resolve().parent
ERRORS = ROOT / ".cache" / "system" / "errors.jsonl"
AUTONOMY = ROOT / "self" / "autonomy.jsonl"
AUDIT_MD = ROOT / "strategy" / "blindness_audit.md"
AUTO_SAFE_LOCK = ROOT / ".cache" / "system" / "blindness_audit_auto_safe.ts"

SESSION = _sm.current()
ABS_MIN = 5
ABS_HARD = 20
RATIO_MIN = 0.10
AUTO_SAFE_MAX_TASKS = 3
SKIP_KINDS = {"parse_ok", "parse_salvaged"}

def _safe_token(kind, where):
    t = (str(kind) + "-" + str(where)).lower()
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in t)

def _read_errors_24h():
    out = []
    if not ERRORS.exists():
        return out
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)
    try:
        lines = ERRORS.read_text(encoding="utf-8", errors="replace").splitlines()[-3000:]
    except Exception:
        return out
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue
        ts = e.get("ts") or ""
        try:
            t = datetime.fromisoformat(ts.replace(" ", "T")[:19])
        except Exception:
            continue
        if t < cutoff:
            continue
        out.append(e)
    return out

def _read_next_actions():
    try:
        import memory as _mem
        m = _mem.Memory()
        return list(m.get("next_actions", []) or [])
    except Exception:
        return []

def _has_marker(actions, token):
    needle = "[repair:" + token + "]"
    for a in actions:
        if isinstance(a, str) and needle in a:
            return True
    return False

def detect():
    """{token: {kind, where, count, ratio, has_marker}}."""
    errs = _read_errors_24h()
    total = len([e for e in errs if (e.get("kind") or "") not in SKIP_KINDS])
    counter = Counter()
    for e in errs:
        k = e.get("kind") or "?"
        w = e.get("where") or "?"
        if k in SKIP_KINDS:
            continue
        counter[(k, w)] += 1
    actions = _read_next_actions()
    out = {}
    for (k, w), n in counter.items():
        if n < ABS_MIN:
            continue
        ratio = (n / total) if total > 0 else 0.0
        flag = (n >= ABS_HARD) or (ratio >= RATIO_MIN)
        if not flag:
            continue
        token = _safe_token(k, w)
        out[token] = {
            "kind": k,
            "where": w,
            "count": n,
            "ratio": round(ratio, 4),
            "has_marker": _has_marker(actions, token),
        }
    return out

def _detect_dead_actuators():
    """s107-4: find actuators that are silent or ineffective in last 7d."""
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    ACTUATORS = ["disk_janitor", "registry_audit", "llm_health",
                 "blindness_audit", "llm_models_sync"]
    if not AUTONOMY.exists():
        return {}
    cutoff = _dt.now(_tz.utc) - _td(days=7)
    by = {a: {"total": 0, "applied_eff0": 0, "eff_pos": 0} for a in ACTUATORS}
    try:
        for line in AUTONOMY.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            act = r.get("action")
            if act not in by:
                continue
            ts = r.get("ts") or ""
            try:
                when = _dt.fromisoformat(ts.replace("Z", "+00:00"))
                if when.tzinfo is None:
                    when = when.replace(tzinfo=_tz.utc)
            except Exception:
                continue
            if when < cutoff:
                continue
            by[act]["total"] += 1
            eff = r.get("effect")
            note = str(r.get("note") or "")
            if isinstance(eff, int):
                if eff > 0:
                    by[act]["eff_pos"] += 1
                elif "applied" in note.lower():
                    by[act]["applied_eff0"] += 1
    except Exception:
        return {}
    out = {}
    for a, c in by.items():
        token = "dead_actuator-" + a
        if c["total"] == 0:
            out[token] = {"kind": "dead_actuator", "where": a,
                          "count": 0, "ratio": 0.0, "has_marker": False,
                          "reason": "silent_7d"}
        elif c["eff_pos"] == 0 and c["applied_eff0"] >= 3:
            out[token] = {"kind": "dead_actuator", "where": a,
                          "count": c["applied_eff0"], "ratio": 0.0,
                          "has_marker": False, "reason": "ineffective_7d"}
    if out:
        actions = _read_next_actions()
        for token, info in out.items():
            info["has_marker"] = _has_marker(actions, token)
    return out


def _detect_dead_sensors():
    """s129-t11: dead sensor / dead healer audit.
    Rule s119: detector without truth = dead sensor.
    Features via session_verify.check_feature. Healers via journal mtime.
    """
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    out = {}
    # --- features ---
    try:
        import session_verify as _sv
        fp = ROOT / "strategy" / "_features.json"
        if fp.exists():
            data = json.loads(fp.read_text(encoding="utf-8"))
            recs = data if isinstance(data, list) else data.get("features", [])
            for f in recs:
                if f.get("frozen"):
                    continue
                fid = f.get("id") or "?"
                try:
                    r = _sv.check_feature(f)
                except Exception:
                    continue
                st = (r or {}).get("status")
                if st in ("regression", "unknown"):
                    token = _safe_token("dead_sensor-fid", fid)
                    out[token] = {"kind": "dead_sensor", "where": fid,
                                  "count": 1, "ratio": 0.0,
                                  "has_marker": False,
                                  "reason": "check_" + str(st)}
    except Exception:
        pass
    # --- healers ---
    try:
        hp = ROOT / "strategy" / "healers.json"
        if hp.exists():
            hdata = json.loads(hp.read_text(encoding="utf-8"))
            hs = hdata if isinstance(hdata, list) else hdata.get("healers", [])
            cutoff = _dt.now(_tz.utc) - _td(days=7)
            for h in hs:
                name = h.get("name") or ""
                if not name:
                    continue
                jp = ROOT / "self" / "healers" / (name + ".jsonl")
                token = _safe_token("dead_healer", name)
                if not jp.exists():
                    out[token] = {"kind": "dead_healer", "where": name,
                                  "count": 0, "ratio": 0.0,
                                  "has_marker": False, "reason": "no_journal"}
                    continue
                try:
                    mt = _dt.fromtimestamp(jp.stat().st_mtime, tz=_tz.utc)
                except Exception:
                    continue
                if mt < cutoff:
                    out[token] = {"kind": "dead_healer", "where": name,
                                  "count": 0, "ratio": 0.0,
                                  "has_marker": False, "reason": "silent_7d"}
    except Exception:
        pass
    if out:
        actions = _read_next_actions()
        for token, info in out.items():
            info["has_marker"] = _has_marker(actions, token)
    return out


def _render_report(d, ts=None):
    if ts is None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = ["## " + ts, ""]
    if not d:
        lines.append("No persistent error classes without repair_task.")
        return chr(10).join(lines)
    lines.append("### Classes needing repair_task")
    for token, info in sorted(d.items(), key=lambda x: -x[1]["count"]):
        mark = "OK" if info["has_marker"] else "MISSING"
        lines.append("- " + token + ": count=" + str(info["count"]) +
                     " ratio=" + str(info["ratio"]) + " marker=" + mark)
    return chr(10).join(lines)

def _append_autonomy(note, effect=None):
    from datetime import datetime as _dt, timezone as _tz
    ts = _dt.now(_tz.utc).isoformat(timespec="seconds")
    rec = {"ts": ts, "session": SESSION, "action": "blindness_audit", "note": note}
    if effect is not None:
        rec["effect"] = int(effect)
    try:
        AUTONOMY.parent.mkdir(parents=True, exist_ok=True)
        with AUTONOMY.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + chr(10))
    except Exception as e:
        print("autonomy write failed: " + type(e).__name__)
    # s108 A3: личный журнал лекаря (fail-open)
    try:
        from healer_log import healer_log
        healer_log("blindness_audit", diagnosis=note, effect=effect)
    except Exception:
        pass

def _append_md(text):
    try:
        AUDIT_MD.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_MD.open("a", encoding="utf-8") as f:
            f.write(text + chr(10) + chr(10))
    except Exception as e:
        print("md write failed: " + type(e).__name__)

def _add_repair_tasks(d):
    missing = {t: i for t, i in d.items() if not i["has_marker"]}
    if not missing:
        return 0
    try:
        import memory as _mem
        m = _mem.Memory()
        actions = list(m.get("next_actions", []) or [])
        added = 0
        for token, info in missing.items():
            text = ("[repair:" + token + "] Persistent " + info["kind"] + "/" + info["where"] +
                    ": " + str(info["count"]) + " in 24h (ratio=" + str(info["ratio"]) +
                    "). Investigate root cause.")
            actions.append(text)
            added += 1
        m.update("next_actions", actions)
        return added
    except Exception as e:
        print("repair_task fail: " + type(e).__name__ + ": " + str(e))
        return 0

def run_report(quiet=False):
    d = detect()
    d.update(_detect_dead_actuators())  # s107-4
    d.update(_detect_dead_sensors())  # s129-t11
    text = _render_report(d)
    if not quiet:
        print(text)
    _append_md(text)
    n_total = len(d)
    n_missing = len([1 for i in d.values() if not i["has_marker"]])
    _append_autonomy("classes=" + str(n_total) + " missing_marker=" + str(n_missing))
    if n_missing:
        added = _add_repair_tasks(d)
        if added:
            _append_autonomy("repair_tasks_added=" + str(added), effect=added)
    return d

def auto_safe(quiet=False):
    from datetime import datetime as _dt, timezone as _tz
    today = _dt.now(_tz.utc).strftime("%Y-%m-%d")
    effect = 0
    try:
        already = AUTO_SAFE_LOCK.read_text(encoding="utf-8").strip() == today
    except Exception:
        already = False
    if already:
        reason = "already_today"
    else:
        d = detect()
        missing = [t for t, i in d.items() if not i["has_marker"]]
        if not missing:
            reason = "nothing_to_do"
        elif len(missing) > AUTO_SAFE_MAX_TASKS:
            reason = "too_many_missing_" + str(len(missing))
        else:
            added = _add_repair_tasks(d)
            AUTO_SAFE_LOCK.parent.mkdir(parents=True, exist_ok=True)
            AUTO_SAFE_LOCK.write_text(today, encoding="utf-8")
            reason = "applied_added_" + str(added)
            effect = added
    _append_autonomy("auto_safe reason=" + reason, effect=effect)
    if not quiet:
        print("auto_safe: " + reason)
    return reason
def _selftest():
    ok = 0
    total = 0
    def chk(name, cond):
        nonlocal ok, total
        total += 1
        if cond:
            ok += 1
            print("  [OK] " + name)
        else:
            print("  [FAIL] " + name)
    chk("safe_token", _safe_token("429", "openrouter") == "429-openrouter")
    chk("safe_token_slash", _safe_token("a/b", "c") == "a-b-c")
    chk("has_marker_true", _has_marker(["[repair:429-openrouter] x"], "429-openrouter"))
    chk("has_marker_false", not _has_marker(["[repair:other] x"], "429-openrouter"))
    chk("render_empty", "No persistent" in _render_report({}))
    chk("render_one", "429-openrouter" in _render_report({"429-openrouter": {"kind": "429", "where": "openrouter", "count": 44, "ratio": 0.4, "has_marker": False}}))
    print("passed " + str(ok) + "/" + str(total))
    return 0 if ok == total else 1

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--auto-safe", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    if a.auto_safe:
        return 0 if auto_safe(quiet=a.quiet) else 0
    run_report(quiet=a.quiet)
    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())
