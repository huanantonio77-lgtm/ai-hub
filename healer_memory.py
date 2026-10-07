#!/usr/bin/env python3
"""
healer_memory.py — s109 Milestone B (B2)
Личная медкарта лекаря. Читает self/healers/<name>.jsonl,
пишет сводку в self/healers/<name>.md.

Использование:
    python3 healer_memory.py --selftest
    python3 healer_memory.py --report              # dry
    python3 healer_memory.py --run                 # только role=doctor
    python3 healer_memory.py --run --all           # все

Не CORE. Fail-open. Не требует sign.
"""
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
HEALERS_DIR = ROOT / "self" / "healers"
HEALERS_JSON = ROOT / "strategy" / "healers.json"


def _load_registry():
    try:
        return json.loads(HEALERS_JSON.read_text(encoding="utf-8")).get("healers", [])
    except Exception as e:
        print(f"[memory] registry fail: {e}", file=sys.stderr)
        return []


def _read_journal(name):
    safe = str(name).strip().replace("/", "_").replace("..", "_")
    p = HEALERS_DIR / (safe + ".jsonl")
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def _summarize(records):
    applied = []
    failed = []
    lessons = []
    # s109-b3fix-fallback: если outcome не заполнен, но effect>0 -> applied.
    # Если outcome=failed -> failed. Если outcome=applied/ok -> applied.
    for r in records:
        outcome = r.get("outcome")
        eff = r.get("effect")
        eff_num = eff if isinstance(eff, (int, float)) else 0
        is_applied = (
            outcome in ("applied", "ok")
            or (outcome is None and eff_num > 0)
        )
        is_failed = (outcome == "failed")
        if is_applied and not is_failed:
            applied.append({
                "ts": r.get("ts", ""),
                "diagnosis": r.get("diagnosis") or "—",
                "action": r.get("action") or "—",
                "effect": eff_num,
            })
        elif is_failed:
            failed.append({
                "ts": r.get("ts", ""),
                "diagnosis": r.get("diagnosis") or "—",
                "action": r.get("action") or "—",
            })
        if r.get("lesson"):
            lessons.append({"ts": r.get("ts", ""), "lesson": r["lesson"]})
    effects = [a["effect"] for a in applied if isinstance(a["effect"], (int, float)) and a["effect"] > 0]
    avg = round(sum(effects) / len(effects), 1) if effects else 0
    last_ts = records[-1].get("ts", "") if records else ""
    return {
        "n": len(records),
        "n_applied": len(applied),
        "n_failed": len(failed),
        "avg_effect": avg,
        "last_ts": last_ts,
        "applied": applied[-10:],
        "failed": failed[-5:],
        "lessons": lessons[-10:],
    }


def _render_md(name, healer, summary):
    role = healer.get("role", "?")
    spec = healer.get("specialty", "?")
    scope = healer.get("scope", "")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    L = []
    L.append(f"# {name} — {spec}")
    L.append("")
    L.append(f"_{scope}_")
    L.append(f"_Роль: {role}. Обновлено: {now}._")
    L.append("")
    L.append("## Что помогало (applied)")
    if summary["applied"]:
        L.append("| ts | симптом | действие | effect |")
        L.append("|---|---|---|---|")
        for a in summary["applied"]:
            ts_short = a["ts"][-8:] if a["ts"] else "—"
            L.append(f"| {ts_short} | {a['diagnosis']} | {a['action']} | {a['effect']} |")
    else:
        L.append("_Пока нет успешных приёмов._")
    L.append("")
    L.append("## Уроки (lesson)")
    if summary["lessons"]:
        for les in summary["lessons"]:
            ts_short = les["ts"][-8:] if les["ts"] else "—"
            L.append(f"- `{ts_short}` — {les['lesson']}")
    else:
        L.append("_Лекарь пока не оставил ни одного урока._")
    L.append("")
    if summary["failed"]:
        L.append("## Что не помогало (failed)")
        L.append("| ts | симптом | действие |")
        L.append("|---|---|---|")
        for f in summary["failed"]:
            ts_short = f["ts"][-8:] if f["ts"] else "—"
            L.append(f"| {ts_short} | {f['diagnosis']} | {f['action']} |")
        L.append("")
    L.append("## Статистика")
    L.append(f"- Всего записей: {summary['n']}")
    L.append(f"- Успешных (applied): {summary['n_applied']}")
    L.append(f"- Не помогло (failed): {summary['n_failed']}")
    L.append(f"- Средний effect: {summary['avg_effect']}")
    L.append(f"- Последний приём: {summary['last_ts'] or '—'}")
    return "\n".join(L) + "\n"


def build_one(healer, dry=False):
    name = healer.get("name")
    if not name:
        return ("skip", str(name), "no name")
    records = _read_journal(name)
    if not records:
        return ("skip", name, "no records")
    summary = _summarize(records)
    md = _render_md(name, healer, summary)
    out = HEALERS_DIR / (name + ".md")
    old = out.read_text(encoding="utf-8") if out.exists() else ""
    if old == md:
        return ("noop", name, "unchanged")
    if dry:
        return ("would_write", name, f"lines={md.count(chr(10))}")
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".md.tmp")
        tmp.write_text(md, encoding="utf-8")
        tmp.replace(out)
        return ("written", name, f"lines={md.count(chr(10))}")
    except Exception as e:
        return ("error", name, f"{type(e).__name__}: {e}")


def build_all(dry=False, only_doctor=False):
    reg = _load_registry()
    results = []
    for h in reg:
        if only_doctor and h.get("role") != "doctor":
            continue
        results.append(build_one(h, dry=dry))
    return results


def _selftest():
    import tempfile
    import shutil
    global HEALERS_DIR, HEALERS_JSON
    tmp = Path(tempfile.mkdtemp(prefix="healer_mem_st_"))
    orig_dir, orig_json = HEALERS_DIR, HEALERS_JSON
    HEALERS_DIR = tmp
    HEALERS_JSON = tmp / "healers.json"
    HEALERS_JSON.write_text(json.dumps({"healers": [
        {"name": "_t1", "role": "doctor", "specialty": "\u0442\u0435\u0441\u0442", "scope": "scope 1"},
        {"name": "_t2", "role": "lab", "specialty": "\u043b\u0430\u0431", "scope": "scope 2"},
    ]}), encoding="utf-8")
    try:
        r = build_one({"name": "_none", "role": "doctor", "specialty": "x", "scope": "y"})
        assert r[0] == "skip", f"\u043e\u0436\u0438\u0434\u0430\u043b skip, \u043f\u043e\u043b\u0443\u0447\u0438\u043b {r}"
        print("  [OK] skip_no_journal")

        (tmp / "_t1.jsonl").write_text(
            json.dumps({"ts": "2026-10-01T10:00:00+00:00", "healer": "_t1",
                        "diagnosis": "d1", "action": "a1", "effect": 5,
                        "outcome": "applied"}) + "\n" +
            json.dumps({"ts": "2026-10-01T11:00:00+00:00", "healer": "_t1",
                        "diagnosis": "d2", "action": "a2",
                        "outcome": "failed"}) + "\n" +
            json.dumps({"ts": "2026-10-01T12:00:00+00:00", "healer": "_t1",
                        "diagnosis": "d3", "action": "a3",
                        "outcome": "applied", "effect": 9,
                        "lesson": "\u043f\u043e\u043c\u043e\u0433\u043b\u043e \u0432\u043e\u0442 \u044d\u0442\u043e"}) + "\n",
            encoding="utf-8"
        )
        r = build_one({"name": "_t1", "role": "doctor", "specialty": "\u0442\u0435\u0441\u0442", "scope": "scope 1"}, dry=True)
        assert r[0] == "would_write", f"\u043e\u0436\u0438\u0434\u0430\u043b would_write, \u043f\u043e\u043b\u0443\u0447\u0438\u043b {r}"
        print("  [OK] dry_would_write")

        r = build_one({"name": "_t1", "role": "doctor", "specialty": "\u0442\u0435\u0441\u0442", "scope": "scope 1"}, dry=False)
        assert r[0] == "written", f"\u043e\u0436\u0438\u0434\u0430\u043b written, \u043f\u043e\u043b\u0443\u0447\u0438\u043b {r}"
        md = (tmp / "_t1.md").read_text(encoding="utf-8")
        assert "Что помогало" in md
        assert "d1" in md and "a1" in md
        assert "\u043f\u043e\u043c\u043e\u0433\u043b\u043e \u0432\u043e\u0442 \u044d\u0442\u043e" in md
        assert "\u0421\u0440\u0435\u0434\u043d\u0438\u0439 effect: 7.0" in md, f"avg fail: {md}"
        assert "\u0412\u0441\u0435\u0433\u043e \u0437\u0430\u043f\u0438\u0441\u0435\u0439: 3" in md
        print("  [OK] write_real")

        r = build_one({"name": "_t1", "role": "doctor", "specialty": "\u0442\u0435\u0441\u0442", "scope": "scope 1"}, dry=False)
        assert r[0] == "noop", f"\u043e\u0436\u0438\u0434\u0430\u043b noop, \u043f\u043e\u043b\u0443\u0447\u0438\u043b {r}"
        print("  [OK] idempotency")

        results = build_all(dry=True, only_doctor=True)
        names = [r[1] for r in results]
        assert "_t2" not in names, f"_t2 \u043d\u0435 \u0434\u043e\u043b\u0436\u0435\u043d \u0431\u044b\u0442\u044c: {names}"
        print("  [OK] only_doctor_filter")

        print("passed 5/5")
        return 0
    finally:
        HEALERS_DIR, HEALERS_JSON = orig_dir, orig_json
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--report", action="store_true", help="dry-run")
    ap.add_argument("--run", action="store_true", help="записать md")
    ap.add_argument("--all", action="store_true", help="включая lab")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    if a.run or a.report:
        results = build_all(dry=not a.run, only_doctor=not a.all)
        for status, name, detail in results:
            print(f"  {status:12s} {name:20s} {detail}")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    main()
