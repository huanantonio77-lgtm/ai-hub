#!/usr/bin/env python3
# llm_health.py (s93-S-LLM-1) - aggregate LLM errors and cooldowns.
# Answers: what is alive, what is in cooldown, why LLM did not answer.
import json
import re
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
import session_meta as _sm

ROOT = Path(__file__).resolve().parent
ERRORS = ROOT / ".cache" / "system" / "errors.jsonl"
COOLDOWNS = ROOT / ".cache" / "system" / "model_cooldowns.json"


def _read_errors_24h():
    out = []
    if not ERRORS.exists():
        return out
    cutoff = datetime.now() - timedelta(hours=24)
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


def _read_cooldowns():
    if not COOLDOWNS.exists():
        return {}
    try:
        return json.loads(COOLDOWNS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def report():
    errs = _read_errors_24h()
    by_kw = Counter()
    for e in errs:
        by_kw[(e.get("kind") or "?", e.get("where") or "?")] += 1
    now = time.time()
    cd = _read_cooldowns()
    cd_active = 0
    cd_reasons = Counter()
    cd_kinds = Counter()
    for k, v in cd.items():
        until = v.get("until") or 0
        if isinstance(until, (int, float)) and until > now:
            cd_active += 1
            cd_reasons[v.get("reason") or "?"] += 1
            cd_kinds[v.get("kind") or v.get("reason") or "?"] += 1
    return {
        "errors_24h": len(errs),
        "429_recent_30m": _count_429_recent(30),
        "by_kind_where": dict(by_kw),
        "cooldowns_active": cd_active,
        "cooldowns_by_reason": dict(cd_reasons),
        "cooldowns_by_kind": dict(cd_kinds),
        "top_5": by_kw.most_common(5),
    }


def format_line():
    r = report()
    kw = r["by_kind_where"]
    e429 = sum(n for (k, w), n in kw.items() if k.startswith("429"))
    e404 = sum(n for (k, w), n in kw.items() if k.startswith("404"))
    e5xx = sum(n for (k, w), n in kw.items() if k.startswith("5xx"))
    eparse = sum(n for (k, w), n in kw.items() if k == "parse_failed")
    esalv = sum(n for (k, w), n in kw.items() if k == "parse_salvaged")
    etimeout = sum(n for (k, w), n in kw.items() if k == "timeout")
    return ("LLM health 24h: total=" + str(r["errors_24h"])
            + " 429=" + str(e429)
            + " 404=" + str(e404)
            + " 5xx=" + str(e5xx)
            + " parse=" + str(eparse)
            + " salvaged=" + str(esalv)
            + " timeout=" + str(etimeout)
            + " | cooldowns=" + str(r["cooldowns_active"]) + " " + str(r["cooldowns_by_kind"]))

# s100-6: actuator (PRAVILO s100-3)
AUTONOMY = ROOT / "self" / "autonomy.jsonl"

SESSION = _sm.current()
THRESH_429 = 50
THRESH_5XX = 20
THRESH_404 = 1
THRESH_CD  = 5

# s102-3: orphan + parse health
ORPHAN_429_MIN = 20
ORPHAN_429_MIN_30M = 3  # s103-1: 30m window matches TTL 1800s
PARSE_FAILED_MIN = 5
PARSE_UNHEALTHY_RATIO = 0.30
AUTO_SAFE_MAX_TASKS = 2
AUTO_SAFE_LOCK = ROOT / ".cache" / "system" / "llm_health_auto_safe.ts"


def _append_autonomy(note, effect=None):
    try:
        from datetime import datetime, timezone
        AUTONOMY.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rec = {"ts": ts, "session": SESSION, "action": "llm_health", "note": note}
        if effect is not None:
            rec["effect"] = int(effect)
        with AUTONOMY.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + chr(10))
    except Exception:
        pass
    # s108 A3: личный журнал лекаря (fail-open)
    try:
        from healer_log import healer_log
        healer_log("llm_health", diagnosis=note, effect=effect)
    except Exception:
        pass


def _summarize(r):
    kw = r.get("by_kind_where") or {}
    s429 = sum(n for (k, w), n in kw.items() if k.startswith("429"))
    s404 = sum(n for (k, w), n in kw.items() if k.startswith("404"))
    s5xx = sum(n for (k, w), n in kw.items() if k.startswith("5xx"))
    cd = int(r.get("cooldowns_active") or 0)
    return {"429": s429, "404": s404, "5xx": s5xx, "cd": cd}


def _read_active_session():
    """s133-t1b: sNNN from curator STATE.md (Следующая)."""
    try:
        p = ROOT / "self" / "curator" / "STATE.md"
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if "Следующая сессия" in line:
                    m = re.search(r"s(\d+)", line)
                    if m:
                        return "s" + m.group(1)
    except Exception:
        pass
    return SESSION


def _emit_drift(sm, triggers):
    """s133-t1: emit llm_storm to Curator DRIFT_LOG (idempotent 6h)."""
    try:
        from datetime import datetime as _dt3, timezone as _tz3, timedelta as _td3
        now = _dt3.now(_tz3.utc)
        cutoff = now - _td3(hours=6)
        p = ROOT / "self" / "curator" / "DRIFT_LOG.jsonl"
        has_open = False
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("kind") == "llm_storm" and rec.get("status") == "open":
                    ts = rec.get("ts", "")
                    try:
                        t = _dt3.fromisoformat(ts.replace("Z", "+00:00"))
                        if t >= cutoff:
                            has_open = True
                            break
                    except Exception:
                        has_open = True
                        break
        if has_open:
            return False
        rec = {"ts": now.isoformat(timespec="seconds"), "session": _read_active_session(),
               "kind": "llm_storm", "status": "open", "severity": "major",
               "info": ", ".join(triggers),
               "note_extra": "auto-emitted by llm_health._add_repair_task (s133-t1-llm-visibility)"}
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + chr(10))
        return True
    except Exception:
        return False


def _add_repair_task(sm):
    triggers = []
    if sm["429"] >= THRESH_429:
        triggers.append("429=" + str(sm["429"]))
    if sm["5xx"] >= THRESH_5XX:
        triggers.append("5xx=" + str(sm["5xx"]))
    if sm["404"] >= THRESH_404:
        triggers.append("404=" + str(sm["404"]))
    if sm["cd"] >= THRESH_CD:
        triggers.append("cd=" + str(sm["cd"]))
    if not triggers:
        return False
    try:
        _emit_drift(sm, triggers)
    except Exception:
        pass
    marker = "[repair:llm-health]"
    text = marker + " " + ", ".join(triggers) + ". Run: python3 llm_health.py --json"
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


def _close_drift_if_clear(sm):
    """s134-A2B: auto-close llm_storm when thresholds clear.

    Symmetric to _emit_drift. Appends 'closed' if last llm_storm entry is open
    and current thresholds are all below limits. Idempotent.
    """
    try:
        # s134-A2B-fix: use FRESH window (30m), not the 24h window from _summarize.
        # Any 429 in last 30 minutes = storm still alive; else close.
        if _count_429_recent(30) > 0:
            return False
        from datetime import datetime as _dt4, timezone as _tz4
        p = ROOT / "self" / "curator" / "DRIFT_LOG.jsonl"
        if not p.exists():
            return False
        storms = []
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("kind") == "llm_storm":
                storms.append(rec)
        if not storms:
            return False
        last = storms[-1]
        if last.get("status") != "open":
            return False
        sess = _read_active_session()
        now_iso = _dt4.now(_tz4.utc).isoformat(timespec="seconds")
        rec = {"ts": now_iso, "session": sess,
               "kind": "llm_storm", "status": "closed", "severity": "info",
               "closed_in": sess, "closed_ts": now_iso,
               "note_extra": "auto-closed by llm_health._close_drift_if_clear (s134-A2B)"}
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + chr(10))
        return True
    except Exception:
        return False

def run_report(quiet=False):
    r = report()
    sm = _summarize(r)
    if not quiet:
        print(format_line())
    note = "429=" + str(sm["429"]) + " 5xx=" + str(sm["5xx"]) + " 404=" + str(sm["404"]) + " cd=" + str(sm["cd"])
    _append_autonomy(note)
    _add_repair_task(sm)
    _close_drift_if_clear(sm)  # s134-A2B
    return sm


def _count_429_recent(minutes=30):
    """s103-1: count 429s in last N minutes. Window aligned with cooldown TTL 1800s."""
    from datetime import datetime, timezone, timedelta
    if not ERRORS.exists():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    count = 0
    try:
        lines = ERRORS.read_text(encoding="utf-8", errors="replace").splitlines()[-3000:]
    except Exception:
        return 0
    for line in lines:
        try:
            r = json.loads(line)
        except Exception:
            continue
        if not str(r.get("kind", "")).startswith("429"):
            continue
        ts_str = r.get("ts") or ""
        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if ts >= cutoff:
            count += 1
    return count


def _orphan_429(r):
    kw = r.get("by_kind_where") or {}
    n24 = sum(c for (k, w), c in kw.items() if str(k).startswith("429"))
    n_recent = int(r.get("429_recent_30m") or 0)
    cd = int(r.get("cooldowns_active") or 0)
    return (n_recent >= ORPHAN_429_MIN_30M) and (cd == 0), n24, n_recent, cd

def _parse_unhealthy(r):
    kw = r.get("by_kind_where") or {}
    pf = sum(c for (k, w), c in kw.items() if k == "parse_failed")
    ps = sum(c for (k, w), c in kw.items() if k == "parse_salvaged")
    denom = pf + ps
    if pf < PARSE_FAILED_MIN or denom <= 0:
        return False, pf, ps
    return (pf / denom) > PARSE_UNHEALTHY_RATIO, pf, ps

def _add_orphan_tasks(r):
    added = 0
    try:
        import memory as _mem_mod
        m = _mem_mod.Memory()
        actions = list(m.get("next_actions", []) or [])
        o, n24, n_recent, cd = _orphan_429(r)
        if o:
            marker = "[repair:llm-orphan-429]"
            text = marker + " " + str(n24) + " x 429 in 24h, " + str(n_recent) + " in 30m, cd=0. Hypothesis: 429 path bypasses _mark_cooldown OR TTL mismatch." 
            if not any(isinstance(a, str) and marker in a for a in actions):
                actions.append(text)
                added += 1
        pu, pf, ps = _parse_unhealthy(r)
        if pu:
            marker = "[repair:llm-parse-quality]"
            text = marker + " parse_failed=" + str(pf) + " salvaged=" + str(ps) + ". Ratio > 0.30." 
            if not any(isinstance(a, str) and marker in a for a in actions):
                actions.append(text)
                added += 1
        if added:
            m.update("next_actions", actions)
    except Exception as e:
        print("orphan task fail: " + type(e).__name__ + ": " + str(e))
    return added

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
        r = report()
        o, n24, n_recent, cd = _orphan_429(r)
        pu, pf, ps = _parse_unhealthy(r)
        missing = int(o) + int(pu)
        if missing == 0:
            reason = "nothing_to_do"
        elif missing > AUTO_SAFE_MAX_TASKS:
            reason = "too_many_" + str(missing)
        else:
            added = _add_orphan_tasks(r)
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
    r1 = {"by_kind_where": {("429", "x"): 25}, "429_recent_30m": 25, "cooldowns_active": 0}
    r2 = {"by_kind_where": {("429", "x"): 25}, "429_recent_30m": 25, "cooldowns_active": 3}
    r3 = {"by_kind_where": {("429", "x"): 2}, "429_recent_30m": 2, "cooldowns_active": 0}
    chk("orphan_true", _orphan_429(r1)[0])
    chk("orphan_false_cd", not _orphan_429(r2)[0])
    chk("orphan_false_low", not _orphan_429(r3)[0])
    r4 = {"by_kind_where": {("parse_failed", "extract_json"): 8, ("parse_salvaged", "extract_json"): 2}}
    r5 = {"by_kind_where": {("parse_failed", "extract_json"): 8, ("parse_salvaged", "extract_json"): 30}}
    chk("parse_unhealthy", _parse_unhealthy(r4)[0])
    chk("parse_healthy", not _parse_unhealthy(r5)[0])
    print("passed " + str(ok) + "/" + str(total))
    return 0 if ok == total else 1

# s101-1: JSON-safe wrapper (report() returns tuple keys -> not serializable)
def _json_safe(obj):
    """Make report() JSON-safe. Tuple dict keys -> 'k/w' strings.
    top_5 entries ((k,w), n) -> ['k/w', n]. Recurses."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            key = "/".join(str(x) for x in k) if isinstance(k, tuple) else str(k)
            out[key] = _json_safe(v)
        return out
    if isinstance(obj, (list, tuple)):
        out = []
        for item in obj:
            if isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], tuple):
                out.append(["/".join(str(x) for x in item[0]), _json_safe(item[1])])
            else:
                out.append(_json_safe(item))
        return out
    return obj

if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    if "--auto-safe" in sys.argv:
        auto_safe()
        sys.exit(0)
    if "--report" in sys.argv and "--json" not in sys.argv:
        run_report(quiet=False)
        sys.exit(0)
    if "--json" in sys.argv:
        print(json.dumps(_json_safe(report()), ensure_ascii=False, indent=2))
    else:
        # s134-A2B-fix-v3: bare CLI run also triggers auto-close (symmetric to --report path).
        try:
            _close_drift_if_clear(_summarize(report()))
        except Exception:
            pass
        print(format_line())
        print("top 5 issues:")
        for (k, w), n in report()["top_5"]:
            print("  " + str(n).rjust(4) + "  " + str(k) + "/" + str(w))
