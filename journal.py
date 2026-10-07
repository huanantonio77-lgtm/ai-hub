#!/usr/bin/env python3
"""journal.py - запись событий агента в структурированный журнал (JSON Lines).

Используют: browser_actions.py, browser_learn.py, skills/*.

Формат записи (одна строка = один JSON):
  {"ts": "2026-09-20T22:50:00", "site": "5sim.net", "action": "click",
   "target": "Sign up", "strategy": "role=button", "result": "ok"}
"""
import json
from datetime import datetime
from pathlib import Path


def _silent(tag, e):
    """s105-3: emit silent except to errors.jsonl (K1 emission)."""
    try:
        from datetime import datetime as _dt, timezone as _tz
        import json as _j
        _root = Path(__file__).resolve().parent
        log = _root / ".cache" / "system" / "errors.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": _dt.now(_tz.utc).strftime("%Y-%m-%d %H:%M:%S"),
               "kind": "silent", "where": "journal",
               "detail": tag + ": " + type(e).__name__ + ": " + str(e)[:100]}
        with log.open("a", encoding="utf-8") as f:
            f.write(_j.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass

JOURNAL = Path("strategy/_journal.log")
ALERTS = Path("strategy/ALERTS.md")


def _append_alert_if_needed(rec):
    """Если result in (fail, error, warn) — append в ALERTS.md.
    Идемпотентно: такой же (level+site/action+note) за последние 180 сек — skip.
    Возвращает True если записали."""
    import re as _re
    result = rec.get("result")
    if result not in ("fail", "error", "warn"):
        return False
    level = {"fail": "FAIL", "error": "ERROR", "warn": "WARN"}[result]
    site = rec.get("site", "?")
    action = rec.get("action", "?")
    note = rec.get("note", "")
    key = "**`" + level + "`** `" + str(site) + "/" + str(action) + "`"
    if note:
        key = key + " — " + str(note)

    now = datetime.now()
    if ALERTS.exists():
        try:
            lines = ALERTS.read_text(encoding="utf-8").splitlines()[-50:]
            for ln in reversed(lines):
                if key in ln:
                    m = _re.match(r"- `\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]`", ln)
                    if m:
                        try:
                            old_ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M")
                            if (now - old_ts).total_seconds() < 180:
                                return False
                        except Exception as _e:
                            _silent('journal_L46', _e)
                    break
        except Exception as _e:
            _silent('journal_L49', _e)

    try:
        ALERTS.parent.mkdir(parents=True, exist_ok=True)
        ts_str = now.strftime("%Y-%m-%d %H:%M")
        with ALERTS.open("a", encoding="utf-8") as fh:
            fh.write("- `[" + ts_str + "]` " + key + chr(10))
        return True
    except Exception:
        return False


def log_event(site=None, action=None, target=None, strategy=None,
              result=None, value=None, note=None):
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": datetime.now().isoformat(timespec="seconds")}
    for k, v in [("site", site), ("action", action), ("target", target),
                 ("strategy", strategy), ("result", result),
                 ("value", value), ("note", note)]:
        if v is not None:
            rec[k] = v
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    _append_alert_if_needed(rec)
    return rec


def resolve_alert(site=None, action=None, note=None):
    key = "**`FAIL`** `" + str(site) + "/" + str(action) + "`"
    if note:
        key = key + " — " + str(note)
    if not ALERTS.exists():
        return 0
    try:
        txt = ALERTS.read_text(encoding="utf-8")
        lns = txt.splitlines()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        marker = " [RESOLVED " + now_str + "]"
        count = 0
        out = []
        for ln in lns:
            if key in ln and "[RESOLVED" not in ln:
                ln = ln + marker
                count += 1
            out.append(ln)
        if count > 0:
            ALERTS.write_text(chr(10).join(out) + chr(10), encoding="utf-8")
        return count
    except Exception:
        return 0


def tail(n=20):
    if not JOURNAL.exists():
        return []
    lines = JOURNAL.read_text(encoding="utf-8").strip().splitlines()
    return lines[-n:]


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "tail":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        for line in tail(n):
            print(line)
    else:
        print("Использование: python3 journal.py tail [N]")
