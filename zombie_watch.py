"""zombie_watch.py — s111 A7. Лекарь-патологоанатом зомби-процессов.

Зомби (stat начинается на Z) — процесс, который завершился, но родитель
не сделал wait(). Убить зомби нельзя (он уже мёртв). Варианты:
  - родитель наш (python/bash/launchd/ai-hub) -> мягкий SIGTERM родителю
  - родитель чужой (Яндекс.Браузер, Safari, ...) -> только finding + repair_task

Порог: зомби старше 6ч (ZOMBIE_MIN_AGE_H).
Журнал: self/healers/zombie_watch.jsonl (через healer_log).
"""

import sys
import os
import json
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
HEALERS_DIR = ROOT / "self" / "healers"
JOURNAL = HEALERS_DIR / "zombie_watch.jsonl"

OUR_MARKERS = ("python3", "python", "bash", "ai-hub", "launchd")
ZOMBIE_MIN_AGE_H = 6


def _ts():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_etime(s):
    """'04-08:07:58' -> секунды. Формат: [[DD-]HH:]MM:SS."""
    try:
        s = (s or "").strip()
        days = 0
        if "-" in s:
            d, s = s.split("-", 1)
            days = int(d)
        parts = s.split(":")
        if len(parts) == 3:
            h, m, sec = int(parts[0]), int(parts[1]), int(parts[2])
        elif len(parts) == 2:
            h, m, sec = 0, int(parts[0]), int(parts[1])
        else:
            return 0
        return days * 86400 + h * 3600 + m * 60 + sec
    except Exception:
        return 0


def _ps_zombies():
    """Список зомби: [{pid, ppid, stat, etime, age_sec, user, comm, parent_comm}]."""
    try:
        r = subprocess.run(
            ["ps", "-Ao", "pid,ppid,stat,etime,user,comm"],
            capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return []
        lines = r.stdout.splitlines()
    except Exception:
        return []

    pid_to_comm = {}
    parsed = []
    for line in lines[1:]:
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        pid_s, ppid_s, stat, etime, user, comm = parts
        try:
            pid = int(pid_s)
            ppid = int(ppid_s)
        except Exception:
            continue
        pid_to_comm[pid] = comm
        parsed.append((pid, ppid, stat, etime, user, comm))

    zombies = []
    for pid, ppid, stat, etime, user, comm in parsed:
        if not stat.startswith("Z"):
            continue
        age_sec = _parse_etime(etime)
        zombies.append({
            "pid": pid,
            "ppid": ppid,
            "stat": stat,
            "etime": etime,
            "age_sec": age_sec,
            "user": user,
            "comm": comm,
            "parent_comm": pid_to_comm.get(ppid, "?"),
        })
    return zombies


def _classify(z):
    """'ours' или 'foreign' по comm родителя."""
    pc = (z.get("parent_comm") or "").lower()
    for m in OUR_MARKERS:
        if m in pc:
            return "ours"
    return "foreign"


def cmd_report():
    zombies = _ps_zombies()
    old = [z for z in zombies if z["age_sec"] >= ZOMBIE_MIN_AGE_H * 3600]
    print("## zombie_watch report " + _ts())
    print("- total zombies: " + str(len(zombies)))
    print("- old (>=" + str(ZOMBIE_MIN_AGE_H) + "h): " + str(len(old)))
    for z in old:
        cls = _classify(z)
        print("  PID " + str(z["pid"]) + "  ppid=" + str(z["ppid"])
              + " (" + (z["parent_comm"] or "?")[:40] + ")"
              + "  age=" + z["etime"] + "  [" + cls + "]")
    if not old:
        print("### no findings")
    return old


def _add_repair_task(ours):
    """repair_task в memory для наших зомби."""
    try:
        from memory import mem
        na = mem.get("next_actions", []) or []
        msg = "[repair:zombie] " + str(len(ours)) + " зомби с нашим родителем: pids=" + str([f["pid"] for f in ours])
        if msg not in na:
            na.append(msg)
            mem.set("next_actions", na)
            return True
    except Exception:
        pass
    return False


def cmd_run():
    old = cmd_report()
    findings = []
    for z in old:
        cls = _classify(z)
        findings.append({
            "kind": "zombie_process",
            "pid": z["pid"],
            "ppid": z["ppid"],
            "parent_comm": z["parent_comm"],
            "age_sec": z["age_sec"],
            "etime": z["etime"],
            "classification": cls,
        })

    try:
        from healer_log import healer_log
        if not findings:
            healer_log("zombie_watch", diagnosis="run_ok", action="noop",
                       outcome="noop", extra={"findings": 0})
        else:
            oldest = findings[0]
            lesson = ("зомби: " + str(len(findings)) + " шт., старший "
                      + oldest["etime"] + " (родитель "
                      + (oldest["parent_comm"] or "?")[:40] + ")")
            healer_log("zombie_watch",
                       diagnosis="zombies=" + str(len(findings)),
                       action="finding",
                       outcome="applied",
                       effect=len(findings),
                       lesson=lesson,
                       extra={"findings": findings})
    except Exception as e:
        print("[zombie_watch] healer_log fail: " + str(e), file=sys.stderr)
        return 1

    ours = [f for f in findings if f["classification"] == "ours"]
    if ours:
        _add_repair_task(ours)

    print("[zombie_watch] findings=" + str(len(findings))
          + " (ours=" + str(len(ours))
          + ", foreign=" + str(len(findings) - len(ours)) + ")")
    return 0


def cmd_selftest():
    tests = []
    assert _parse_etime("01:00") == 60
    tests.append("parse_1m")
    assert _parse_etime("01:00:00") == 3600
    tests.append("parse_1h")
    assert _parse_etime("04-08:07:58") == 4 * 86400 + 8 * 3600 + 7 * 60 + 58
    tests.append("parse_4d8h")
    assert _parse_etime("00:00") == 0
    tests.append("parse_zero")
    assert _classify({"parent_comm": "python3"}) == "ours"
    tests.append("classify_ours")
    assert _classify({"parent_comm": "Yandex"}) == "foreign"
    tests.append("classify_foreign")
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
