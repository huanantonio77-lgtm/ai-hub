#!/usr/bin/env python3
"""
healer_report.py — s108 A4
Сводный отчёт по всем лекарям: кто сколько работал, суммарный effect,
последняя запись, "молчуны" (0 записей за окно).

Не CORE, не sensitive. Sign не нужен.
"""
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parent
HEALERS_JSON = ROOT / "strategy" / "healers.json"
HEALERS_DIR = ROOT / "self" / "healers"


def _load_registry():
    if not HEALERS_JSON.exists():
        return []
    with open(HEALERS_JSON) as f:
        return json.load(f).get("healers", [])


def _parse_ts(ts):
    if not ts:
        return None
    dt = None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        pass
    if dt is None:
        try:
            dt = datetime.strptime(str(ts), "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _read_journal(name, since_hours=168):
    """Читает личный журнал лекаря за окно (по умолчанию 7 дней)."""
    p = HEALERS_DIR / (name + ".jsonl")
    rows = []
    if not p.exists():
        return rows
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    with open(p) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            dt = _parse_ts(r.get("ts"))
            if dt and dt >= cutoff:
                rows.append((dt, r))
    return rows


def _summarize(healers, since_hours=168):
    report = []
    for h in healers:
        name = h["name"]
        rows = _read_journal(name, since_hours)
        total_effect = sum(int(r.get("effect", 0) or 0) for _, r in rows)
        last = rows[-1][1] if rows else None
        report.append({
            "name": name,
            "specialty": h.get("specialty", "?"),
            "role": h.get("role", "?"),
            "records": len(rows),
            "total_effect": total_effect,
            "last_ts": last.get("ts") if last else None,
            "last_note": (last.get("diagnosis") or "")[:60] if last else None,
        })
    return report


def cmd_report(since_hours=168):
    healers = _load_registry()
    report = _summarize(healers, since_hours)
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

    print(f"## healer_report {ts}")
    print(f"- healers registered: {len(healers)}")
    print(f"- window: {since_hours}h")
    print("")

    print("### Summary")
    print(f"{'name':<20} {'role':<10} {'records':>8} {'effect':>8}  last_ts")
    for r in report:
        print(f"{r['name']:<20} {r['role']:<10} {r['records']:>8} {r['total_effect']:>8}  {r['last_ts'] or '-'}")

    print("")
    silent = [r for r in report if r["records"] == 0]
    if silent:
        print(f"### Silent healers ({len(silent)})")
        for r in silent:
            print(f"  ⚠️  {r['name']} ({r['specialty']})")
    else:
        print("### Silent healers: 0 ✅")

    print("")
    print("### Top by effect")
    for r in sorted(report, key=lambda x: -x["total_effect"])[:5]:
        print(f"  {r['name']:<20} effect={r['total_effect']}")

    return 0


def cmd_selftest():
    import tempfile
    import shutil

    global HEALERS_DIR
    tmp = Path(tempfile.mkdtemp(prefix="healer_report_st_"))
    orig = HEALERS_DIR
    HEALERS_DIR = tmp
    try:
        # журнал с 2 записями
        (tmp / "test_a.jsonl").write_text(
            '{"ts": "2026-10-01T10:00:00+00:00", "healer": "test_a", "diagnosis": "x", "effect": 5}\n'
            '{"ts": "2026-10-01T11:00:00+00:00", "healer": "test_a", "diagnosis": "y", "effect": 7}\n'
        )
        # журнал с 0 записей не создаём
        healers = [
            {"name": "test_a", "specialty": "тест", "role": "doctor"},
            {"name": "test_b", "specialty": "тест", "role": "lab"},
        ]
        rep = _summarize(healers, since_hours=24*365)
        assert len(rep) == 2, "ждём 2 строки"
        ra = next(r for r in rep if r["name"] == "test_a")
        rb = next(r for r in rep if r["name"] == "test_b")
        assert ra["records"] == 2, f"test_a records={ra['records']}"
        assert ra["total_effect"] == 12, f"test_a effect={ra['total_effect']}"
        assert rb["records"] == 0, f"test_b records={rb['records']}"
        assert rb["total_effect"] == 0
        print("  [OK] summarize_counts")
        print("  [OK] summarize_effect")
        print("  [OK] silent_detected")
        print("passed 3/3")
        return 0
    finally:
        HEALERS_DIR = orig
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--window", type=int, default=168, help="окно в часах (default 168 = 7 дней)")
    a = ap.parse_args()
    if a.selftest:
        return cmd_selftest()
    return cmd_report(since_hours=a.window)


if __name__ == "__main__":
    sys.exit(main())
