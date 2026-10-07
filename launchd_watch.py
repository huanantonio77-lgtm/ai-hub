#!/usr/bin/env python3
# launchd_watch.py (s115-E1) — детектор свежести плановых launchd-задач.
#
# Смотрит: ~/Library/LaunchAgents/com.ainova.*.plist
# Для каждой задачи считает ОЖИДАЕМОЕ время последнего запуска
# (по StartCalendarInterval или StartInterval) и сравнивает с mtime лога.
# Если лог старше ожидаемого + grace -> finding "stale".
#
# Демоны без расписания (только RunAtLoad) — пропускаются.
# launchctl exit=N НЕ используется как сигнал (правило s114-rule-launchctl-exit).
#
# Актюатор (s100-3): stale -> repair_task через memory.Memory().
# Журнал: self/healers/launchd_watch.jsonl.
# Медкарта: self/healers/launchd_watch.md.
# Не CORE. Не sensitive. Без sign.

import json
import sys
import plistlib
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parent

try:
    import session_meta as _sm
    SESSION = _sm.current()
except Exception:
    SESSION = "s115"

try:
    from healer_log import healer_log
except Exception:
    def healer_log(*a, **k):
        return False

AUTONOMY = ROOT / "self" / "autonomy.jsonl"
LA_DIR = Path.home() / "Library" / "LaunchAgents"
PREFIX = "com.ainova."

CAL_GRACE_MIN = 15
INTERVAL_GRACE_FACTOR = 0.5
WINDOW_DAYS = 30


def _ts():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _append_autonomy(note):
    try:
        AUTONOMY.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": _ts(), "session": SESSION,
               "action": "launchd_watch", "note": note}
        with AUTONOMY.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _plist_files():
    if not LA_DIR.exists():
        return []
    return sorted(LA_DIR.glob(PREFIX + "*.plist"))


def _load_plist(path):
    try:
        with open(path, "rb") as f:
            return plistlib.load(f)
    except Exception:
        return None


def _log_path(pl):
    for k in ("StandardOutPath", "StandardErrorPath"):
        v = pl.get(k)
        if isinstance(v, str) and v:
            return v
    return None


def _expand_ints(v):
    if isinstance(v, dict):
        return [v]
    if isinstance(v, list):
        return [x for x in v if isinstance(x, dict)]
    return []


def _get_int(d, k, default=None):
    v = d.get(k)
    if isinstance(v, int):
        return v
    return default


def _last_fire_local(now_local, cal):
    minute = _get_int(cal, "Minute", 0)
    hour = _get_int(cal, "Hour")
    day = _get_int(cal, "Day")
    month = _get_int(cal, "Month")
    weekday = _get_int(cal, "Weekday")
    if hour is None:
        return None
    for delta in range(0, WINDOW_DAYS + 1):
        cand_date = now_local - timedelta(days=delta)
        py_wd = cand_date.weekday()
        mac_wd = (py_wd + 1) % 7
        if weekday is not None and mac_wd != weekday:
            continue
        if day is not None and cand_date.day != day:
            continue
        if month is not None and cand_date.month != month:
            continue
        cand = cand_date.replace(hour=hour, minute=minute,
                                 second=0, microsecond=0)
        if cand <= now_local:
            return cand
    return None


def _expected(pl, now_local):
    cal = pl.get("StartCalendarInterval")
    if cal:
        best = None
        for c in _expand_ints(cal):
            dt = _last_fire_local(now_local, c)
            if dt is not None and (best is None or dt > best):
                best = dt
        return ("calendar", best, timedelta(minutes=CAL_GRACE_MIN))

    iv = pl.get("StartInterval")
    if isinstance(iv, int) and iv > 0:
        grace = timedelta(seconds=int(iv * INTERVAL_GRACE_FACTOR))
        return ("interval", now_local - timedelta(seconds=iv), grace)

    return (None, None, None)


def scan():
    now_local = datetime.now().astimezone()
    now_utc = now_local.astimezone(timezone.utc)
    findings = []

    for p in _plist_files():
        pl = _load_plist(p)
        if not pl:
            findings.append({
                "label": p.stem, "level": "warn",
                "reason": "plist_unreadable", "log": None,
                "expected": None, "actual": None, "delta_h": None,
            })
            continue

        label = pl.get("Label") or p.stem
        log_path = _log_path(pl)
        kind, exp_local, grace = _expected(pl, now_local)

        if kind is None:
            continue

        if log_path is None:
            findings.append({
                "label": label, "level": "warn",
                "reason": "no_log_path", "log": None,
                "expected": exp_local.isoformat() if exp_local else None,
                "actual": None, "delta_h": None,
            })
            continue

        lp = Path(log_path)
        if not lp.exists():
            findings.append({
                "label": label, "level": "warn",
                "reason": "log_missing", "log": str(lp),
                "expected": exp_local.isoformat() if exp_local else None,
                "actual": None, "delta_h": None,
            })
            continue

        try:
            mtime = datetime.fromtimestamp(lp.stat().st_mtime, tz=timezone.utc)
        except Exception:
            findings.append({
                "label": label, "level": "warn",
                "reason": "log_stat_failed", "log": str(lp),
                "expected": exp_local.isoformat() if exp_local else None,
                "actual": None, "delta_h": None,
            })
            continue

        if exp_local is None:
            continue

        exp_utc = exp_local.astimezone(timezone.utc)

        if mtime >= exp_utc:
            continue
        if now_utc < exp_utc + grace:
            continue

        delta_h = (now_utc - mtime).total_seconds() / 3600.0
        findings.append({
            "label": label, "level": "stale",
            "reason": "log_not_refreshed",
            "log": str(lp),
            "expected": exp_utc.isoformat(),
            "actual": mtime.isoformat(),
            "delta_h": round(delta_h, 2),
        })

    return findings


def _add_repair_task(findings):
    if not findings:
        return False
    marker = "[repair:launchd-watch]"
    parts = [f"{f['label']}({f.get('reason')})" for f in findings[:6]]
    text = marker + " " + str(len(findings)) + " jobs: " + ", ".join(parts)
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


def run_report(quiet=False):
    findings = scan()
    stale = [f for f in findings if f.get("level") == "stale"]
    warn = [f for f in findings if f.get("level") == "warn"]

    if not quiet:
        print(f"launchd_watch: {len(findings)} findings "
              f"(stale={len(stale)} warn={len(warn)})")
        for f in findings:
            print("  " + json.dumps(f, ensure_ascii=False))

    _append_autonomy(f"stale={len(stale)} warn={len(warn)}")

    if findings:
        _add_repair_task(findings)

    diag = f"stale={len(stale)} warn={len(warn)}"
    try:
        if findings:
            healer_log("launchd_watch", diagnosis=diag, action="report",
                       effect=len(findings), outcome="applied",
                       extra={"labels": [f["label"] for f in findings[:6]]})
        else:
            healer_log("launchd_watch", diagnosis="all_fresh",
                       action="report", effect=0, outcome="noop")
    except Exception:
        pass

    return findings


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    if a.report or a.run:
        run_report(quiet=a.quiet)
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
