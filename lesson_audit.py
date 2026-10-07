#!/usr/bin/env python3
"""lesson_audit.py — s112-b3. Лекарь-архивариус.

Проверяет: у каждой фичи со свежим closed_in == _features.updated
есть ли урок (строкой id) в knowledge/lessons.md.

Правило s112-rule-lesson-after-close: закрыл фичу -> напиши урок с её id.
Актуатор: miss -> _add_repair_task -> memory.mem.next_actions.
Журнал: self/healers/lesson_audit.jsonl (через healer_log).
"""

import sys
import json
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FEATURES = ROOT / "strategy" / "_features.json"
LESSONS = ROOT / "knowledge" / "lessons.md"


def _load_features():
    try:
        f = json.loads(FEATURES.read_text(encoding="utf-8"))
        return f.get("features") or [], f.get("updated") or ""
    except Exception:
        return [], ""


def _load_lessons_text():
    try:
        return LESSONS.read_text(encoding="utf-8")
    except Exception:
        return ""


def _check_one(fid, closed_in, updated, lessons_text):
    """True = miss (урок не найден), False = ok/skip."""
    if not fid or not updated:
        return False
    if closed_in != updated:
        return False
    if fid in lessons_text:
        return False
    return True


def _audit():
    feats, updated = _load_features()
    text = _load_lessons_text()
    if not updated:
        return []
    misses = []
    for f in feats:
        fid = f.get("id") or ""
        cin = f.get("closed_in") or ""
        if _check_one(fid, cin, updated, text):
            misses.append({
                "id": fid,
                "closed_in": cin,
                "reason": "no lesson with feature id in lessons.md",
            })
    return misses


def _add_repair_task(misses):
    try:
        from memory import mem
        na = mem.get("next_actions", []) or []
        for m in misses:
            msg = ("[repair:lesson_audit] нет урока для " + m["id"]
                   + " (closed_in=" + m["closed_in"] + ")")
            if msg not in na:
                na.append(msg)
        mem.set("next_actions", na)
        return True
    except Exception:
        return False


def cmd_report():
    misses = _audit()
    if not misses:
        print("[lesson_audit] no miss — все свежие фичи имеют уроки")
    else:
        print("[lesson_audit] miss=" + str(len(misses)))
        for m in misses:
            print("  - " + m["id"] + " (" + m["reason"] + ")")
    return misses


def cmd_run():
    misses = cmd_report()
    try:
        from healer_log import healer_log
        if not misses:
            healer_log("lesson_audit", diagnosis="run_ok", action="noop",
                       outcome="noop", extra={"findings": 0})
        else:
            lesson = "фичи без урока: " + ", ".join(m["id"] for m in misses[:5])
            healer_log("lesson_audit",
                       diagnosis="miss=" + str(len(misses)),
                       action="finding",
                       outcome="applied",
                       effect=len(misses),
                       lesson=lesson,
                       extra={"findings": misses})
    except Exception as e:
        print("[lesson_audit] healer_log fail: " + str(e), file=sys.stderr)
        return 1

    if misses:
        _add_repair_task(misses)
    return 0


def cmd_selftest():
    tests = []
    assert _check_one("a", "sX", "sX", "text a text") is False
    tests.append("hit")
    assert _check_one("a", "sX", "sX", "no id here") is True
    tests.append("miss")
    assert _check_one("a", "sOld", "sNew", "no id") is False
    tests.append("skip_old_session")
    assert _check_one("", "sX", "sX", "anything") is False
    tests.append("skip_empty_id")
    assert _check_one("a", "sX", "", "anything") is False
    tests.append("skip_no_updated")
    print(" ".join("[OK] " + t for t in tests))
    print("passed " + str(len(tests)) + "/" + str(len(tests)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        cmd_selftest()
        return 0
    if args.run:
        return cmd_run()
    return 0 if cmd_report() is not None else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
