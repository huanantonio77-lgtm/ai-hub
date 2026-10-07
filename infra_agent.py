#!/usr/bin/env python3
"""infra_agent.py — сторож LLM-инфраструктуры ai-hub.

Раз в INTERVAL секунд:
  1. Читает .cache/system/model_cooldowns.json
  2. Проверяет errors.jsonl за последние 5 мин
  3. Проверяет providers_registry.json
  4. По правилам (без LLM) решает:
     - снять stale-429 cooldown (старше 25 мин)
     - предупредить о fanout concentration
     - предупредить о 429-burst
  5. Пишет в knowledge/infra-log.md, обновляет .runtime/infra.heartbeat

НЕ трогает: Chrome/VPN (это agent_daemon), очередь задач (task_daemon),
запущенные orchestrator'ы (task_daemon сам убивает залипшие по heartbeat).

Запуск:
  python3 infra_agent.py --once --dry-run   # посмотреть, ничего не делать
  python3 infra_agent.py --once             # один прогон с действиями
  python3 infra_agent.py --interval 120     # цикл
"""
import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import time
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
               "kind": "silent", "where": "infra_agent",
               "detail": tag + ": " + type(e).__name__ + ": " + str(e)[:100]}
        with log.open("a", encoding="utf-8") as f:
            f.write(_j.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

LOCK_FILE = "/tmp/ainova-infra-agent.lock"
HEARTBEAT = ROOT / ".runtime" / "infra.heartbeat"
INFRA_LOG = ROOT / "knowledge" / "infra-log.md"
COOLDOWNS = ROOT / ".cache" / "system" / "model_cooldowns.json"
ERRORS = ROOT / ".cache" / "system" / "errors.jsonl"
REGISTRY = ROOT / "providers_registry.json"

STALE_429_AGE_SEC = 45 * 60  # порог для hard-release 429 (должен быть > TTL)
COOLDOWN_429_TTL = 30 * 60
FANOUT_WARN_THRESHOLD = 0.70
ERROR_WINDOW_SEC = 5 * 60
ERROR_BURST_THRESHOLD = 5
# --- LLM decision layer (v2, suggest-only) ---
LLM_BUDGET_FILE = ROOT / ".runtime" / "infra-llm-calls.json"
LLM_DECISIONS_FILE = ROOT / ".runtime" / "infra-decisions.jsonl"
LLM_BUDGET_HOUR = 6
LLM_BUDGET_DAY = 20
LLM_TRIGGER_GREY = "cooldown_grey"
GREY_MIN_AGE_SEC = 9 * 60
GREY_MAX_AGE_SEC = 36 * 60
LLM_TRIGGER_REGISTRY = "registry_parse"
REGISTRY_THROTTLE_FILE = ROOT / ".runtime" / "infra-registry-throttle.json"
REGISTRY_THROTTLE_SEC = 30 * 60
PARSE_BURST_WINDOW_SEC = 30 * 60
PARSE_BURST_THRESHOLD = 5
AUTO_APPLY_LOG = ROOT / ".runtime" / "infra-autoapplied.jsonl"
AUTO_APPLY_THROTTLE_FILE = ROOT / ".runtime" / "infra-autoapply-throttle.json"
AUTO_APPLY_MAX_PER_HOUR = 3
AUTO_APPLY_MIN_CONF = 0.9
# Максимум ключей в grey-zone, при котором разрешён all/grey_zone auto-release.
# Защита от массового снятия cooldown'ов одной командой.
ALL_GREY_MAX_KEYS = 2
AUTO_APPLY_PENDING_FILE = ROOT / ".runtime" / "infra-autoapply-pending.json"
AUTO_APPLY_OUTCOMES_FILE = ROOT / ".runtime" / "infra-autoapply-outcomes.jsonl"
AUTO_APPLY_CHECK_WINDOW_SEC = 5 * 60
AUTO_APPLY_RECIDIVE_THRESHOLD = 3
AUTO_APPLY_RECIDIVE_WINDOW = 5
LESSONS_FILE = ROOT / "knowledge" / "lessons.md"
LESSON_THROTTLE_FILE = ROOT / ".runtime" / "infra-lesson-throttle.json"
LESSON_THROTTLE_SEC = 6 * 3600

# Smoke-test LLM (патч A, сессия 35)
SMOKE_THROTTLE_FILE = ROOT / ".runtime" / "infra-smoke-throttle.json"
SMOKE_THROTTLE_SEC = 30 * 60
SMOKE_SYSTEM = 'Ты пинг-тест. Верни JSON: {"ok": true}'
SMOKE_USER = 'ping. Ответь JSON: {"ok": true}' 


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print("[" + ts + "] " + msg, flush=True)


def _read_cooldowns():
    try:
        if COOLDOWNS.exists():
            return json.loads(COOLDOWNS.read_text(encoding="utf-8"))
    except Exception as _e:
        _silent('infra_agent_L93', _e)
    return {}


def _write_cooldowns(d):
    try:
        COOLDOWNS.parent.mkdir(parents=True, exist_ok=True)
        COOLDOWNS.write_text(
            json.dumps(d, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        log("! cooldowns write failed: " + str(e))


def _record(v):
    if isinstance(v, dict):
        return float(v.get("until", 0)), str(v.get("reason", "unknown"))
    if isinstance(v, (int, float)):
        return float(v), "unknown"
    return 0.0, "unknown"


def _stale_parallel_orchestrators():
    """Возвращает PIDs 'лишних' orchestrator'ов (если их >1). Точный cmdline-фильтр."""
    out = []
    me = os.getpid()
    try:
        r = subprocess.run(
            ["ps", "-Ao", "pid=,command="],
            capture_output=True, text=True, timeout=5,
        )
        for line in r.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            pid_s, cmd = parts
            try:
                pid = int(pid_s)
            except ValueError:
                continue
            if pid == me:
                continue
            if " -c " in cmd:
                continue
            if re.search(r"python[0-9.]*\s+.*orchestrator\.py(\s|$)", cmd):
                out.append(pid)
    except Exception as _e:
        _silent('infra_agent_L144', _e)
    if len(out) <= 1:
        return []
    return out


def _recent_429_count(window_sec):
    if not ERRORS.exists():
        return 0
    try:
        now = time.time()
        count = 0
        lines = ERRORS.read_text(
            encoding="utf-8", errors="ignore",
        ).splitlines()[-500:]
        for ln in lines:
            try:
                rec = json.loads(ln)
            except Exception:
                continue
            if rec.get("kind") != "429":
                continue
            try:
                ts = datetime.strptime(
                    rec.get("ts", ""), "%Y-%m-%d %H:%M:%S",
                ).timestamp()
            except Exception:
                continue
            if now - ts < window_sec:
                count += 1
        return count
    except Exception:
        return 0


def _recent_parse_count(window_sec):
    """Считает kind=parse в errors.jsonl за окно."""
    if not ERRORS.exists():
        return 0
    try:
        now = time.time()
        count = 0
        lines = ERRORS.read_text(
            encoding="utf-8", errors="ignore",
        ).splitlines()[-500:]
        for ln in lines:
            try:
                rec = json.loads(ln)
            except Exception:
                continue
            if rec.get("kind") != "parse":
                continue
            try:
                ts = datetime.strptime(
                    rec.get("ts", ""), "%Y-%m-%d %H:%M:%S",
                ).timestamp()
            except Exception:
                continue
            if now - ts < window_sec:
                count += 1
        return count
    except Exception:
        return 0


def _check_registry():
    try:
        if not REGISTRY.exists():
            return False, "missing"
        json.loads(REGISTRY.read_text(encoding="utf-8"))
        return True, "ok"
    except Exception as e:
        return False, "parse error: " + str(e)


def _touch_heartbeat():
    try:
        HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
        HEARTBEAT.write_text(str(int(time.time())), encoding="utf-8")
    except Exception as _e:
        _silent('infra_agent_L224', _e)


def _append_log(actions, warnings, dry_run=False):
    try:
        INFRA_LOG.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().isoformat(timespec="seconds")
        prefix = "[dry-run] " if dry_run else ""
        lines = ["", "## " + ts + " " + prefix + "infra check"]
        for a in actions:
            lines.append("- " + a)
        for w in warnings:
            lines.append("- WARN: " + w)
        with INFRA_LOG.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception as e:
        log("! infra-log write failed: " + str(e))


def _llm_groq(system, user, limit=3):
    """Прямой вызов groq в обход openrouter cooldown. None при провале."""
    try:
        import llm_call
    except Exception as e:
        log("! llm_call недоступен: " + str(e))
        return None
    groq = None
    for p in llm_call.PROVIDERS:
        if p["name"] == "groq":
            groq = p
            break
    if not groq:
        log("! groq не найден в llm_call.PROVIDERS")
        return None
    key = llm_call._read_key(groq["key_file"])
    if not key:
        log("! groq key missing: " + groq["key_file"])
        return None
    errors = []
    attempts = 0
    for model in groq["models"]:
        if attempts >= limit:
            break
        attempts += 1
        try:
            txt = llm_call._openai_style(
                groq["url"], model, key, system, user, True
            )
            if txt:
                return txt
        except Exception as e:
            # 403 или SSL → retry через прокси
            s = str(e)
            is_403 = "403" in s or "Forbidden" in s
            is_ssl = "CERTIFICATE_VERIFY" in s or "SSL" in s
            if (is_403 or is_ssl) and hasattr(llm_call, "_read_proxy") and llm_call._read_proxy():
                try:
                    txt = llm_call._openai_style(
                        groq["url"], model, key, system, user, True,
                        use_proxy=True,
                    )
                    if txt:
                        return txt
                except Exception as e2:
                    errors.append(model + " proxy: " + type(e2).__name__ + " " + str(e2)[:80])
            errors.append(model + ": " + type(e).__name__ + " " + str(e)[:80])
            time.sleep(1)
    log("! groq all models failed: " + " | ".join(errors[-3:]))
    errs = " | ".join(errors[-3:])
    if "403" in errs or "Forbidden" in errs:
        _append_lesson(
            "INFRA",
            "Groq все модели 403 (VPN geo-block?)",
            [
                "Все модели groq вернули 403 Forbidden.",
                "Возможно: VPN в RU/BY/IR/KP/SY/CU.",
                "Проверь: `curl api.ipify.org` + `ipinfo.io/<ip>/json`.",
                "Прокси-fallback не сработал, если proxy.txt пуст или прокси лёг.",
            ],
            key="groq_403",
        )
    return None


def _llm_budget_load():
    try:
        if LLM_BUDGET_FILE.exists():
            return json.loads(LLM_BUDGET_FILE.read_text(encoding="utf-8"))
    except Exception as _e:
        _silent('infra_agent_L313', _e)
    return {"hour": [], "day": []}


def _llm_budget_ok():
    """(ok, reason). 6/час и 20/сутки."""
    now = time.time()
    d = _llm_budget_load()
    hour = [t for t in d.get("hour", []) if now - t < 3600]
    day = [t for t in d.get("day", []) if now - t < 86400]
    if len(hour) >= LLM_BUDGET_HOUR:
        return False, "hour " + str(len(hour)) + "/" + str(LLM_BUDGET_HOUR)
    if len(day) >= LLM_BUDGET_DAY:
        return False, "day " + str(len(day)) + "/" + str(LLM_BUDGET_DAY)
    return True, "ok"


def _llm_budget_inc():
    now = time.time()
    d = _llm_budget_load()
    hour = [t for t in d.get("hour", []) if now - t < 3600]
    day = [t for t in d.get("day", []) if now - t < 86400]
    hour.append(now)
    day.append(now)
    d["hour"] = hour
    d["day"] = day
    try:
        LLM_BUDGET_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = LLM_BUDGET_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        tmp.replace(LLM_BUDGET_FILE)
    except Exception as e:
        log("! budget write failed: " + str(e))


def _smoke_throttle_load():
    try:
        if SMOKE_THROTTLE_FILE.exists():
            return json.loads(SMOKE_THROTTLE_FILE.read_text(encoding="utf-8"))
    except Exception as _e:
        _silent('infra_agent_L353', _e)
    return {}


def _smoke_throttle_ok():
    d = _smoke_throttle_load()
    last = d.get("smoke", 0)
    return (time.time() - last) >= SMOKE_THROTTLE_SEC


def _smoke_throttle_mark():
    d = _smoke_throttle_load()
    d["smoke"] = time.time()
    try:
        SMOKE_THROTTLE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = SMOKE_THROTTLE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        tmp.replace(SMOKE_THROTTLE_FILE)
    except Exception as e:
        log("! smoke throttle write failed: " + str(e))


def _write_error_jsonl(kind, where, detail=""):
    """Пишет строку в errors.jsonl в формате orchestrator.log_error."""
    try:
        ERRORS.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "kind": kind,
            "where": where,
            "detail": (detail or "").replace("\n", " ")[:300],
        }
        with ERRORS.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        log("! errors.jsonl write failed: " + str(e))


def _smoke_llm_check():
    """Один пробный LLM-вызов. Возвращает (ok: bool, note: str)."""
    try:
        txt = _llm_groq(SMOKE_SYSTEM, SMOKE_USER, limit=1)
    except Exception as e:
        return False, "exception: " + type(e).__name__ + " " + str(e)[:120]
    if txt:
        return True, "ok"
    return False, "no response (см. errors.jsonl / llm_call)"


_LLM_SYSTEM = (
    "Ты — инфра-сторож проекта AI NOVA. Решаешь, снимать ли "
    "cooldown 429 у LLM-провайдера, который находится в серой зоне "
    "(возраст 9-36 минут). Отвечай ТОЛЬКО валидным JSON без обёртки "
    "и без markdown: "
    '{"action": "release"|"wait", "target": "<строка>", '
    '"reason": "<кратко, 1 предложение>", "confidence": 0.0-1.0}. '
    "release — если 429-burst утих и нет свежих 429 за последние 5 минут. "
    "wait — если burst продолжается или fanout сконцентрирован. "
    "\n\nЖЁСТКОЕ ПРАВИЛО по target:\n"
    "- если action=release: target ОБЯЗАН быть точным значением "
    "одного из элементов payload.grey_keys[].key. Не придумывай, "
    "не сокращай, не обобщай.\n"
    "- допускается только особое значение \"all/grey_zone\" — если "
    "хочешь освободить все ключи сразу.\n"
    "- примеры НЕВАЛИДНОГО target: \"openrouter\", \"openrouter/all\", "
    "\"openrouter/grey_zone_release\".\n"
    "- если action=wait: target может быть \"none\"."
)

_LLM_SYSTEM_REGISTRY = (
    "Ты — инфра-сторож проекта AI NOVA. У providers_registry.json "
    "parse error: файл повреждён, ни один провайдер не читается. "
    "В payload есть bak_files — список бэкапов. Отвечай ТОЛЬКО "
    "валидным JSON без обёртки: "
    '{"action": "restore_bak"|"manual_review", '
    '"target": "<exact name из bak_files>"|"manual_review", '
    '"reason": "<кратко, 1 предложение>", "confidence": 0.0-1.0}. '
    "restore_bak — если есть свежий бэкап с разумным размером. "
    "manual_review — если ни один бэкап не подходит. "
    "target обязан быть точным именем из bak_files, не выдумывай."
)


def _list_registry_baks():
    """Возвращает [{name, mtime, size}] бэкапов registry, свежие первыми."""
    out = []
    for p in ROOT.glob("providers_registry.json.bak-*"):
        try:
            st = p.stat()
            out.append({
                "name": p.name,
                "mtime": int(st.st_mtime),
                "size": st.st_size,
            })
        except Exception:
            continue
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return out


def _validate_bak_target(target, bak_list):
    """target LLM против списка бэкапов registry."""
    if not target:
        return False, "empty target"
    t = str(target).strip()
    if t in ("manual_review", "none"):
        return True, "special"
    names = [b.get("name", "") for b in (bak_list or [])]
    if not names:
        return False, "no bak_list"
    if t in names:
        return True, "exact"
    return False, "no match: " + t[:80]


def _registry_throttle_load():
    try:
        if REGISTRY_THROTTLE_FILE.exists():
            return json.loads(REGISTRY_THROTTLE_FILE.read_text(encoding="utf-8"))
    except Exception as _e:
        _silent('infra_agent_L473', _e)
    return {}


def _registry_throttle_ok():
    """(ok, last_ago_sec). ok=True если давно не вызывали."""
    d = _registry_throttle_load()
    last = float(d.get(LLM_TRIGGER_REGISTRY, 0))
    now = time.time()
    if last <= 0:
        return True, -1
    ago = int(now - last)
    if ago >= REGISTRY_THROTTLE_SEC:
        return True, ago
    return False, ago


def _registry_throttle_mark():
    d = _registry_throttle_load()
    d[LLM_TRIGGER_REGISTRY] = time.time()
    try:
        REGISTRY_THROTTLE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = REGISTRY_THROTTLE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        tmp.replace(REGISTRY_THROTTLE_FILE)
    except Exception as e:
        log("! registry throttle write failed: " + str(e))


def _validate_target(target, grey_keys):
    """Проверяет, что target LLM соответствует одному из grey_keys.

    Валидным считается:
    - точное совпадение с одним из ключей;
    - target начинается с ключа (например "...:free" vs "...:free/429_burst");
    - спец-значения "all/grey_zone" и "all".

    Возвращает (ok: bool, reason: str).
    """
    if not target:
        return False, "empty target"
    t = str(target).strip()
    if t in ("all/grey_zone", "all", "none"):
        return True, "special"
    keys = [str(g.get("key", "")) for g in (grey_keys or [])]
    if not keys:
        return False, "no grey_keys"
    if t in keys:
        return True, "exact"
    for k in keys:
        if k and t.startswith(k + "/"):
            return True, "prefix"
    return False, "no match: " + t[:80]


def _llm_decide(trigger, payload, dry=False):
    """Вызов groq с бюджетом. Возвращает dict решения или None."""
    ok, why = _llm_budget_ok()
    if not ok:
        log("  . LLM budget exhausted (" + why + "), deferred")
        return None
    sys_prompt = (
        _LLM_SYSTEM_REGISTRY if trigger == LLM_TRIGGER_REGISTRY
        else _LLM_SYSTEM
    )
    user = json.dumps(payload, ensure_ascii=False)
    raw = _llm_groq(sys_prompt, user, limit=3)
    if not raw:
        return None
    if not dry:
        _llm_budget_inc()
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:].lstrip()
    try:
        d = json.loads(raw)
    except Exception as e:
        log("! LLM JSON parse failed: " + str(e) + " raw head: " + raw[:120])
        return None
    if trigger == LLM_TRIGGER_REGISTRY:
        if d.get("action") not in ("restore_bak", "manual_review"):
            log("! LLM bad registry action: " + str(d.get("action")))
            return None
    elif d.get("action") not in ("release", "wait"):
        log("! LLM bad action: " + str(d.get("action")))
        return None
    try:
        d["confidence"] = float(d.get("confidence", 0.0))
    except Exception:
        d["confidence"] = 0.0
    d["trigger"] = trigger
    d["ts"] = datetime.now().isoformat(timespec="seconds")
    if trigger == LLM_TRIGGER_REGISTRY:
        ok_t, why_t = _validate_bak_target(
            d.get("target"), payload.get("bak_files")
        )
    else:
        ok_t, why_t = _validate_target(
            d.get("target"), payload.get("grey_keys")
        )
    d["target_valid"] = ok_t
    if not ok_t:
        d["target_note"] = why_t
    return d


def _log_llm_decision(d):
    """Пишет решение в .runtime/infra-decisions.jsonl и в infra-log."""
    try:
        LLM_DECISIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LLM_DECISIONS_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")
    except Exception as e:
        log("! decisions.jsonl write failed: " + str(e))
    line = ("LLM[" + str(d.get("trigger", "?")) + "]: action="
            + str(d.get("action", "?")) + " target="
            + str(d.get("target", "?")) + " conf="
            + str(d.get("confidence", 0.0)) + " reason="
            + str(d.get("reason", "")))
    return line


def _atomic_write_cooldowns(d):
    """Атомарная запись cooldowns через .tmp + replace."""
    try:
        COOLDOWNS.parent.mkdir(parents=True, exist_ok=True)
        tmp = COOLDOWNS.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(d, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, COOLDOWNS)
        return True, "ok"
    except Exception as e:
        return False, str(e)


def _autoapply_throttle_load():
    try:
        if AUTO_APPLY_THROTTLE_FILE.exists():
            return json.loads(AUTO_APPLY_THROTTLE_FILE.read_text(encoding="utf-8"))
    except Exception as _e:
        _silent('infra_agent_L617', _e)
    return {"events": []}


def _autoapply_throttle_ok():
    """(ok, count_last_hour)."""
    now = time.time()
    d = _autoapply_throttle_load()
    events = [t for t in d.get("events", []) if now - t < 3600]
    if len(events) >= AUTO_APPLY_MAX_PER_HOUR:
        return False, len(events)
    return True, len(events)


def _autoapply_throttle_mark():
    now = time.time()
    d = _autoapply_throttle_load()
    events = [t for t in d.get("events", []) if now - t < 3600]
    events.append(now)
    d["events"] = events
    try:
        AUTO_APPLY_THROTTLE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = AUTO_APPLY_THROTTLE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        tmp.replace(AUTO_APPLY_THROTTLE_FILE)
    except Exception as e:
        log("! autoapply throttle write failed: " + str(e))


def _auto_apply_release(decision, recent_burst_5min=0, grey_keys=None):
    """Guardrails + применение точечного release.

    Возвращает (applied: bool, msg: str).
    Только safe-случай: точный ключ, conf>=0.9, burst=0, <=5 cooldowns.
    """
    snap = _read_cooldowns()
    if not decision:
        return False, "no decision"
    if decision.get("action") != "release":
        return False, "not release"
    if not decision.get("target_valid", False):
        return False, "target invalid"
    try:
        conf = float(decision.get("confidence", 0))
    except Exception:
        conf = 0.0
    if conf < AUTO_APPLY_MIN_CONF:
        return False, "conf " + str(conf) + " < " + str(AUTO_APPLY_MIN_CONF)
    target = str(decision.get("target", "")).strip()
    if target in ("all", "none", ""):
        return False, "target not point-specific: " + target
    if target == "all/grey_zone":
        gk = grey_keys or []
        if not gk:
            return False, "all/grey_zone: no grey_keys in payload"
        if len(gk) > ALL_GREY_MAX_KEYS:
            return False, ("all/grey_zone: " + str(len(gk))
                           + " keys > limit " + str(ALL_GREY_MAX_KEYS))
        keys_to_release = [str(g.get("key", "")) for g in gk]
        keys_to_release = [k for k in keys_to_release if k and k in snap]
        if not keys_to_release:
            return False, "all/grey_zone: no matching keys in cooldowns"
    else:
        if target not in snap:
            return False, "target not in cooldowns: " + target
        keys_to_release = [target]
    if recent_burst_5min > 0:
        return False, "recent burst active: " + str(recent_burst_5min)
    ok_t, n_t = _autoapply_throttle_ok()
    if not ok_t:
        return False, "autoapply throttle " + str(n_t) + "/" + str(AUTO_APPLY_MAX_PER_HOUR)
    # apply
    prev = {k: snap.get(k) for k in keys_to_release}
    new_d = {k: v for k, v in snap.items() if k not in keys_to_release}
    ok_w, msg_w = _atomic_write_cooldowns(new_d)
    if not ok_w:
        return False, "write failed: " + msg_w
    _autoapply_throttle_mark()
    record = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "target": target,
        "prev": prev,
        "conf": conf,
        "reason": decision.get("reason", ""),
    }
    try:
        AUTO_APPLY_LOG.parent.mkdir(parents=True, exist_ok=True)
        with AUTO_APPLY_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        log("! autoapply log write failed: " + str(e))
    _pending_add(target, conf)
    return True, "released " + target


def _lesson_throttle_load():
    try:
        if LESSON_THROTTLE_FILE.exists():
            return json.loads(LESSON_THROTTLE_FILE.read_text(encoding="utf-8"))
    except Exception as _e:
        _silent('infra_agent_L717', _e)
    return {}


def _lesson_throttle_ok(key):
    """(ok, ago_sec). False если урок с этим key писали < 6 часов назад."""
    d = _lesson_throttle_load()
    last = float(d.get(key, 0))
    now = time.time()
    if last <= 0:
        return True, -1
    ago = int(now - last)
    if ago >= LESSON_THROTTLE_SEC:
        return True, ago
    return False, ago


def _lesson_throttle_mark(key):
    d = _lesson_throttle_load()
    d[key] = time.time()
    try:
        LESSON_THROTTLE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = LESSON_THROTTLE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        tmp.replace(LESSON_THROTTLE_FILE)
    except Exception as e:
        log("! lesson throttle write failed: " + str(e))


def _append_lesson(tag, title, body_lines, key=None):
    """Пишет урок в knowledge/lessons.md с throttle.

    tag: 'INFRA', 'FABRICATION', ...
    title: однострочный заголовок.
    body_lines: список строк с '- ' префиксом.
    key: ключ throttle. Если None — title[:40].
    """
    k = key if key else title[:40]
    ok, ago = _lesson_throttle_ok(k)
    if not ok:
        log("  . lesson throttled (" + k + ", " + str(ago) + "s ago)")
        return False
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        block = "\n\n## [" + tag + "] " + ts + ". " + title + "\n"
        for line in body_lines:
            block += "- " + line + "\n"
        LESSONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LESSONS_FILE.open("a", encoding="utf-8") as fh:
            fh.write(block)
        _lesson_throttle_mark(k)
        log("  . lesson written: " + title[:60])
        return True
    except Exception as e:
        log("! lesson write failed: " + str(e))
        return False


def _pending_load():
    try:
        if AUTO_APPLY_PENDING_FILE.exists():
            return json.loads(AUTO_APPLY_PENDING_FILE.read_text(encoding="utf-8"))
    except Exception as _e:
        _silent('infra_agent_L780', _e)
    return {}


def _pending_save(d):
    try:
        AUTO_APPLY_PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = AUTO_APPLY_PENDING_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(AUTO_APPLY_PENDING_FILE)
    except Exception as e:
        log("! pending save failed: " + str(e))


def _pending_add(target, conf):
    """Ставит маркер ожидания для target."""
    d = _pending_load()
    d[target] = {
        "ts": time.time(),
        "conf": float(conf),
    }
    _pending_save(d)


def _outcomes_append(rec):
    try:
        AUTO_APPLY_OUTCOMES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with AUTO_APPLY_OUTCOMES_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        log("! outcomes write failed: " + str(e))


def _outcomes_recent(n):
    """Последние n outcomes."""
    if not AUTO_APPLY_OUTCOMES_FILE.exists():
        return []
    try:
        lines = AUTO_APPLY_OUTCOMES_FILE.read_text(encoding="utf-8").splitlines()
        out = []
        for ln in lines[-n:]:
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except Exception:
                continue
        return out
    except Exception:
        return []


def _check_pending_outcomes(snap, dry_run=False):
    """Сверяет pending с текущим snap. Возвращает список событий для warnings.

    Если target снова в snap → recidive (release был преждевременным).
    Если нет → ok.
    Если последние 5 outcomes содержат 3+ recidive → пишет урок.
    """
    events = []
    pending = _pending_load()
    if not pending:
        return events
    now = time.time()
    to_remove = []
    for target, info in list(pending.items()):
        try:
            ts = float(info.get("ts", 0))
        except Exception:
            ts = 0
        elapsed = now - ts
        if elapsed < AUTO_APPLY_CHECK_WINDOW_SEC:
            continue
        in_snap = target in snap
        outcome = "recidive" if in_snap else "ok"
        rec = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "target": target,
            "outcome": outcome,
            "elapsed_sec": int(elapsed),
            "conf": info.get("conf"),
        }
        if not dry_run:
            _outcomes_append(rec)
        events.append("AUTO-OUTCOME: " + target + " -> " + outcome
                      + " (" + str(int(elapsed)) + "s)")
        to_remove.append(target)
    if to_remove and not dry_run:
        for k in to_remove:
            pending.pop(k, None)
        _pending_save(pending)
    # проверка рецидивов
    recent = _outcomes_recent(AUTO_APPLY_RECIDIVE_WINDOW)
    recidives = [r for r in recent if r.get("outcome") == "recidive"]
    if len(recent) >= AUTO_APPLY_RECIDIVE_WINDOW and len(recidives) >= AUTO_APPLY_RECIDIVE_THRESHOLD:
        events.append("AUTO-RELEASE recidive " + str(len(recidives)) + "/" + str(len(recent)))
        if not dry_run:
            _append_lesson(
                "INFRA",
                "AUTO-RELEASE даёт рецидивы",
                [
                    "За последние " + str(len(recent)) + " auto-apply " + str(len(recidives)) + " вернулись в cooldown за 5 мин.",
                    "Возможно: LLM ошибается с target или release преждевременный.",
                    "Рекомендация: поднять AUTO_APPLY_MIN_CONF или отключить auto-apply.",
                ],
                key="autoapply_recidive",
            )
    return events


def tick(dry_run=False, llm_dry=False, auto_apply=False):
    log("--- infra check ---")
    actions = []
    warnings = []

    # --- СНИМОК ДО любых изменений (для честных предупреждений) ---
    snap = _read_cooldowns()
    now = time.time()

    # fanout concentration -- считаем на снимке
    if snap:
        by_pair = {}
        for key, val in snap.items():
            _, reason = _record(val)
            prov = key.split("/", 1)[0] if "/" in key else "?"
            by_pair[(prov, reason)] = by_pair.get((prov, reason), 0) + 1
        if by_pair:
            top_pair, top_n = max(by_pair.items(), key=lambda x: x[1])
            frac = top_n / len(snap)
            if frac >= FANOUT_WARN_THRESHOLD:
                warnings.append(
                    "FANOUT concentration: " + top_pair[0] + "/" + top_pair[1]
                    + " = " + str(top_n) + "/" + str(len(snap))
                    + " (" + str(int(100 * frac)) + "%)"
                )

    # --- Правило: две категории, разные сообщения ---
    d = dict(snap)  # копия, будем мутировать
    expired_keys = []
    hard_release_keys = []
    for key, val in list(d.items()):
        until, reason = _record(val)
        if until <= now:
            expired_keys.append(key)
            continue
        if reason == "429":
            issued = until - COOLDOWN_429_TTL
            if now - issued > STALE_429_AGE_SEC:
                hard_release_keys.append(key)

    if not dry_run:
        for k in expired_keys + hard_release_keys:
            d.pop(k, None)
        if expired_keys or hard_release_keys:
            _write_cooldowns(d)

    if expired_keys:
        actions.append("expired cleaned: " + str(len(expired_keys)))
    else:
        actions.append("expired cleaned: 0")
    if hard_release_keys:
        actions.append(
            "hard-release 429 (age>" + str(STALE_429_AGE_SEC // 60) + "min): "
            + str(len(hard_release_keys))
        )
    else:
        actions.append("hard-release 429: 0")

    # --- parallel orchestrators (детект, без kill) ---
    pids = _stale_parallel_orchestrators()
    if pids:
        warnings.append("stale parallel orchestrators: " + str(pids))
    else:
        actions.append("parallel orchestrators: ok")

    # --- registry ---
    ok, msg = _check_registry()
    if ok:
        actions.append("registry: " + msg)
    else:
        warnings.append("registry: " + msg)
        # T1: parse error в registry — LLM-совет (suggest-only)
        if "parse error" in msg:
            t_ok, t_ago = _registry_throttle_ok()
            if not t_ok:
                log("  . registry_parse LLM throttled, " + str(t_ago) + "s ago")
            else:
                baks = _list_registry_baks()
                payload = {
                    "trigger": LLM_TRIGGER_REGISTRY,
                    "parse_error": msg[:200],
                    "registry_size": (
                        REGISTRY.stat().st_size if REGISTRY.exists() else 0
                    ),
                    "bak_files": baks,
                }
                decision = _llm_decide(
                    LLM_TRIGGER_REGISTRY, payload, dry=llm_dry
                )
                if decision:
                    if llm_dry:
                        log("  . [llm-dry] " + json.dumps(decision, ensure_ascii=False))
                    else:
                        line = _log_llm_decision(decision)
                        warnings.append(line)
                        _registry_throttle_mark()
                elif llm_dry:
                    log("  . [llm-dry] no registry decision")

    # --- 429 burst ---
    burst = _recent_429_count(ERROR_WINDOW_SEC)
    if burst >= ERROR_BURST_THRESHOLD:
        warnings.append(
            "429 burst: " + str(burst) + " in last "
            + str(ERROR_WINDOW_SEC // 60) + " min"
        )
    parse_burst = _recent_parse_count(PARSE_BURST_WINDOW_SEC)
    if parse_burst >= PARSE_BURST_THRESHOLD:
        warnings.append(
            "parse burst: " + str(parse_burst) + " in last "
            + str(PARSE_BURST_WINDOW_SEC // 60) + " min"
        )

    # --- LLM decision: серая зона 429 (suggest-only) ---
    grey_keys = []
    for key, val in d.items():
        until, reason = _record(val)
        if reason != "429":
            continue
        issued = until - COOLDOWN_429_TTL
        age = now - issued
        if GREY_MIN_AGE_SEC <= age <= GREY_MAX_AGE_SEC:
            grey_keys.append({"key": key, "age_sec": int(age)})
    if grey_keys:
        burst_now = _recent_429_count(ERROR_WINDOW_SEC)
        payload = {
            "trigger": LLM_TRIGGER_GREY,
            "grey_keys": grey_keys,
            "recent_429_burst_5min": burst_now,
            "total_cooldowns": len(snap),
        }
        decision = _llm_decide(LLM_TRIGGER_GREY, payload, dry=llm_dry)
        if llm_dry:
            if decision:
                log("  . [llm-dry] " + json.dumps(decision, ensure_ascii=False))
            else:
                log("  . [llm-dry] no decision")
        elif decision:
            line = _log_llm_decision(decision)
            warnings.append(line)
            if auto_apply:
                applied, msg = _auto_apply_release(
                    decision,
                    recent_burst_5min=payload.get("recent_429_burst_5min", 0),
                    grey_keys=grey_keys,
                )
                if applied:
                    warnings.append("AUTO-RELEASE: " + msg)
                else:
                    log("  . auto-apply skipped: " + msg)
        else:
            warnings.append(
                "LLM[grey] no decision, "
                + str(len(grey_keys)) + " keys deferred"
            )

    # --- outcome tracking ---
    snap_after = _read_cooldowns()
    for ev in _check_pending_outcomes(snap_after, dry_run=dry_run):
        warnings.append(ev)

    # --- smoke-test LLM (патч A, сессия 35) ---
    if not dry_run and not llm_dry and _smoke_throttle_ok():
        ok_b, reason_b = _llm_budget_ok()
        if ok_b:
            _llm_budget_inc()
            _smoke_throttle_mark()
            ok_smoke, note_smoke = _smoke_llm_check()
            if ok_smoke:
                actions.append("smoke LLM: ok")
            else:
                warnings.append("smoke LLM: " + note_smoke)
                _write_error_jsonl("smoke_fail", "groq", note_smoke)
        else:
            actions.append("smoke LLM: skip (budget " + reason_b + ")")

    _append_log(actions, warnings, dry_run=dry_run)
    _touch_heartbeat()

    for a in actions:
        log("  . " + a)
    for w in warnings:
        log("  ! " + w)
    log("--- end ---")


def _acquire_lock():
    try:
        fh = open(LOCK_FILE, "w")
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fh.write(str(os.getpid()))
        fh.flush()
        return fh
    except BlockingIOError:
        return None
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=120)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--llm-dry", action="store_true")
    ap.add_argument("--auto-apply", action="store_true")
    args = ap.parse_args()

    if args.once:
        tick(dry_run=args.dry_run, llm_dry=args.llm_dry, auto_apply=args.auto_apply)
        return

    fh = _acquire_lock()
    if fh is None:
        log("infra_agent already running (lock held), exit")
        return

    log("infra_agent started, interval=" + str(args.interval)
        + "s, dry_run=" + str(args.dry_run))
    try:
        while True:
            try:
                tick(dry_run=args.dry_run, llm_dry=args.llm_dry, auto_apply=args.auto_apply)
            except Exception as e:
                log("! loop error: " + str(e))
            time.sleep(args.interval)
    except KeyboardInterrupt:
        log("stopped by Ctrl+C")
    finally:
        try:
            fh.close()
        except Exception as _e:
            _silent('infra_agent_L1123', _e)


if __name__ == "__main__":
    main()
