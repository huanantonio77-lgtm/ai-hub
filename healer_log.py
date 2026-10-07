#!/usr/bin/env python3
"""
healer_log.py — s108 A2
Личный журнал лекаря. Пишет одну JSONL-строку в self/healers/<name>.jsonl.

Использование:
    from healer_log import healer_log
    healer_log("disk_janitor", diagnosis="archive=30", action="archive",
               effect=5, outcome="applied")

Fail-open: если журнал сломан, лекарь НЕ падает — ошибка идёт в stderr.
Не CORE, не sensitive. Не требует sign.
"""
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
HEALERS_DIR = ROOT / "self" / "healers"

try:
    from session_meta import current as _session_current
    SESSION = _session_current()
except Exception:
    SESSION = "s108"

OUTCOMES = {"applied", "skipped", "failed", "noop"}


def _ts():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _journal_path(name):
    safe = str(name).strip().replace("/", "_").replace("..", "_")
    if not safe:
        safe = "_unknown"
    return HEALERS_DIR / (safe + ".jsonl")


def _auto_lesson(diagnosis, action, effect, outcome):
    """s111-a12: авто-урок, если лекарь не передал lesson.

    Правила:
      applied + effect>0 -> 'применено, effect=N'
      applied (без effect) -> 'применено'
      failed             -> 'не помогло: <diagnosis>'
      noop/skipped/None  -> None (не засоряем журнал)

    Fallback (как в healer_memory): outcome=None + effect>0 -> applied.
    Ограничение длины: 120 символов.
    """
    eff_num = None
    if effect is not None:
        try:
            eff_num = int(effect)
        except Exception:
            eff_num = None

    eff_outcome = outcome
    if eff_outcome is None and eff_num is not None and eff_num > 0:
        eff_outcome = "applied"

    if eff_outcome == "applied":
        if eff_num is not None and eff_num > 0:
            s = f"применено, effect={eff_num}"
        else:
            s = "применено"
    elif eff_outcome == "failed":
        d = (diagnosis or "—").strip() or "—"
        if len(d) > 90:
            d = d[:87] + "..."
        s = f"не помогло: {d}"
    else:
        return None

    if len(s) > 120:
        s = s[:117] + "..."
    return s


def healer_log(name, diagnosis=None, action=None, effect=None,
               outcome=None, lesson=None, extra=None):
    """Записать одну строку в личный журнал лекаря. Fail-open."""
    try:
        rec = {
            "ts": _ts(),
            "session": SESSION,
            "healer": str(name),
            "diagnosis": diagnosis,
            "action": action,
        }
        if effect is not None:
            try:
                rec["effect"] = int(effect)
            except Exception:
                rec["effect"] = effect
        if outcome is not None:
            rec["outcome"] = str(outcome)
        if lesson:
            rec["lesson"] = str(lesson)
        else:
            _auto = _auto_lesson(diagnosis, action, effect, outcome)
            if _auto:
                rec["lesson"] = _auto
        if extra:
            try:
                rec["extra"] = dict(extra)
            except Exception:
                rec["extra"] = {"_raw": str(extra)}

        p = _journal_path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return True
    except Exception as e:
        print(f"[healer_log] FAIL name={name}: {type(e).__name__}: {e}",
              file=sys.stderr)
        return False


def _selftest():
    import tempfile
    import shutil

    global HEALERS_DIR
    tmp = Path(tempfile.mkdtemp(prefix="healer_log_st_"))
    orig = HEALERS_DIR
    HEALERS_DIR = tmp
    try:
        # 1. Базовая запись
        ok = healer_log("_st_a", diagnosis="x", action="y",
                        effect=3, outcome="applied")
        assert ok is True, "базовая запись вернула False"
        f = tmp / "_st_a.jsonl"
        assert f.exists(), "файл не создан"
        line = f.read_text().strip()
        r = json.loads(line)
        assert r["healer"] == "_st_a"
        assert r["effect"] == 3
        assert r["outcome"] == "applied"
        assert "ts" in r and r["ts"].endswith("+00:00")
        print("  [OK] base_write")

        # 2. Минимум полей
        healer_log("_st_b", action="noop")
        r2 = json.loads((tmp / "_st_b.jsonl").read_text().strip())
        assert r2["healer"] == "_st_b"
        assert "diagnosis" in r2 and r2["diagnosis"] is None
        print("  [OK] minimal_fields")

        # 3. Санитизация имени (path traversal)
        healer_log("../evil", action="x")
        found = list(tmp.glob("*evil*.jsonl"))
        assert len(found) == 1, f"санитизация не сработала: {list(tmp.iterdir())}"
        assert found[0].parent == tmp, "файл не в HEALERS_DIR"
        print("  [OK] name_sanitized")

        # 4. Повторные записи (append)
        healer_log("_st_a", action="y2")
        healer_log("_st_a", action="y3")
        n = len((tmp / "_st_a.jsonl").read_text().strip().split("\n"))
        assert n == 3, f"append работает неверно: {n} строк"
        print("  [OK] append")

        # 5. Fail-open: путь недоступен
        HEALERS_DIR = Path("/nonexistent_ro_xyz/healers")
        ok = healer_log("_st_c", action="fail_expected")
        assert ok is False, "fail-open не сработал"
        print("  [OK] fail_open")

        print("passed 5/5")
        return 0
    finally:
        HEALERS_DIR = orig
        shutil.rmtree(tmp, ignore_errors=True)


def _demo():
    healer_log("_demo", diagnosis="selftest demo",
               action="append_line", effect=1, outcome="applied",
               extra={"purpose": "A2 manual demo"})
    p = _journal_path("_demo")
    print(f"[healer_log] demo wrote to {p}")
    if p.exists():
        print(p.read_text().strip())
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    if a.demo:
        return _demo()
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
