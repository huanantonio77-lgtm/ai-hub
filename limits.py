"""
limits.py — учёт и контроль лимитов бесплатных тарифов.
Читает provider_limits.json, пишет журнал в .cache/limits_usage.json.
НЕ трогает orchestrator.py — просто модуль, который orchestrator импортирует.

Обновлено: добавлены when_available, reset_schedule, _fmt_secs.
Теперь знает НЕ ТОЛЬКО «лимит исчерпан», но и «через сколько откроется».
"""
import json
import threading
import time
from pathlib import Path

AI_HUB = Path.home() / "Desktop" / "ai-hub"
LIMITS_FILE = AI_HUB / "provider_limits.json"
USAGE_FILE = AI_HUB / ".cache" / "limits_usage.json"

_lock = threading.Lock()

_ALIASES = {
    "gemini": "gemini",
    "openrouter": "openrouter",
    "mistral": "mistral",
    "cloudflare": "cloudflare",
    "cohere": "cohere",
    "huggingface": "huggingface",
    "hf": "huggingface",
    "groq": "groq",
}


def _norm(name: str) -> str:
    """'Gemini (с поиском)' -> 'gemini'. 'OpenRouter' -> 'openrouter'."""
    key = name.lower().split()[0].split("(")[0].strip()
    return _ALIASES.get(key, key)


def load_limits() -> dict:
    if not LIMITS_FILE.exists():
        return {}
    try:
        return json.loads(LIMITS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"limits.py: не смог прочитать {LIMITS_FILE}: {e}")
        return {}


def _load_usage() -> dict:
    if not USAGE_FILE.exists():
        return {}
    try:
        return json.loads(USAGE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_usage(data: dict) -> None:
    USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = USAGE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(USAGE_FILE)


def record_call(provider: str, status: str, tokens_in: int = None,
                tokens_out: int = None) -> None:
    """status: 'ok' | '429' | 'error'. Пишет событие в журнал.

    tokens_in / tokens_out — необязательные. Если переданы как int >= 0,
    сохраняются в event для подсчёта tokens_day_used / tokens_month_used.
    Обратная совместимость: record_call(p, status) работает как раньше.
    """
    p = _norm(provider)
    now = time.time()
    with _lock:
        data = _load_usage()
        entry = data.setdefault(p, {"events": [], "last_429": 0.0})
        ev = {"ts": now, "status": status}
        if isinstance(tokens_in, int) and tokens_in >= 0:
            ev["tokens_in"] = tokens_in
        if isinstance(tokens_out, int) and tokens_out >= 0:
            ev["tokens_out"] = tokens_out
        entry["events"].append(ev)
        if status == "429":
            entry["last_429"] = now
        cutoff = now - 31 * 86400
        entry["events"] = [e for e in entry["events"] if e["ts"] >= cutoff]
        if len(entry["events"]) > 5000:
            entry["events"] = entry["events"][-5000:]
        _save_usage(data)


def _count(events: list, window_sec: float, status: str = None,
           exclude_status: str = None) -> int:
    cutoff = time.time() - window_sec
    n = 0
    for e in events:
        if exclude_status and e.get('status') == exclude_status:
            continue
        if e["ts"] >= cutoff:
            if status is None or e.get("status") == status:
                n += 1
    return n


def _sum_tokens(events: list, window_sec: float) -> int:
    """Сумма токенов (in + out) за окно window_sec. Пропускает events без токенов."""
    cutoff = time.time() - window_sec
    total = 0
    for e in events:
        if e.get("ts", 0) < cutoff:
            continue
        tin = e.get("tokens_in")
        tout = e.get("tokens_out")
        if isinstance(tin, int) and tin > 0:
            total += tin
        if isinstance(tout, int) and tout > 0:
            total += tout
    return total


def usage_snapshot(provider: str) -> dict:
    """Сколько запросов сделано за минуту / сутки / неделю / 30 дней."""
    p = _norm(provider)
    data = _load_usage()
    entry = data.get(p, {"events": [], "last_429": 0.0})
    ev = entry["events"]
    return {
        "rpm": _count(ev, 60),
        "rpd": _count(ev, 86400, exclude_status="error"),
        "rpw": _count(ev, 7 * 86400, exclude_status="error"),
        "rpm_month": _count(ev, 30 * 86400, exclude_status="error"),
        "count_429_day": _count(ev, 86400, status="429"),
        "tokens_day_used": _sum_tokens(ev, 86400),
        "tokens_month_used": _sum_tokens(ev, 30 * 86400),
        "last_429_ago_sec": (
            int(time.time() - entry["last_429"]) if entry.get("last_429") else None
        ),
    }


# ============================================================
# НОВОЕ: расчёт "когда откроется"
# ============================================================

# Окна: (ключ_лимита, длина_окна_сек, человеческое_имя)
_WINDOWS = [
    ("rpm",       60,         "минута"),
    ("rpd",       86400,      "сутки"),
    ("rpw",       7 * 86400,  "неделя"),
    ("rpm_month", 30 * 86400, "месяц"),
]


def _oldest_in_window(events: list, window_sec: float) -> float:
    """Самый старый event в окне. Его уход за границу освободит один слот."""
    cutoff = time.time() - window_sec
    oldest = None
    for e in events:
        ts = e.get("ts", 0)
        if ts >= cutoff:
            if oldest is None or ts < oldest:
                oldest = ts
    return oldest


def _fmt_secs(s: float) -> str:
    """0 -> 'сейчас', 45 -> '45 сек', 3700 -> '1 ч 1 мин'."""
    s = int(s)
    if s <= 0:
        return "сейчас"
    if s < 60:
        return f"{s} сек"
    if s < 3600:
        return f"{s // 60} мин {s % 60} сек"
    if s < 86400:
        return f"{s // 3600} ч {(s % 3600) // 60} мин"
    return f"{s // 86400} дн {(s % 86400) // 3600} ч"


def time_until_slot_frees(provider: str, window_key: str) -> int:
    """Сколько секунд до освобождения одного слота в указанном окне.
    Если окно не заполнено — 0."""
    p = _norm(provider)
    data = _load_usage()
    ev = data.get(p, {"events": []}).get("events", [])
    for key, window_sec, _ in _WINDOWS:
        if key == window_key:
            oldest = _oldest_in_window(ev, window_sec)
            if oldest is None:
                return 0
            return max(0, int(oldest + window_sec - time.time()) + 1)
    return 0


def when_available(provider: str) -> dict:
    """Когда провайдер снова доступен.

    Возвращает dict:
      available       — bool, можно ли звать сейчас
      reason          — str, почему закрыт (или 'ok')
      wait_sec        — int, сколько секунд ждать (0 если доступен)
      wait_human      — str, то же человекочитаемо
      limiting_window — str | None, какое окно ограничивает
    """
    p = _norm(provider)
    limits = load_limits().get(p)
    if not limits:
        return {
            "available": True,
            "reason": "нет данных о лимитах — не блокирую",
            "wait_sec": 0,
            "wait_human": "сейчас",
            "limiting_window": None,
        }

    data = _load_usage()
    ev = data.get(p, {"events": [], "last_429": 0.0}).get("events", [])
    snap = usage_snapshot(p)

    # 1) Кулдаун после 429 (60 сек) — самый быстрый тормоз
    ago = snap["last_429_ago_sec"]
    if ago is not None and ago < 60:
        wait = 60 - ago
        return {
            "available": False,
            "reason": f"кулдаун после 429 ({ago}с назад)",
            "wait_sec": wait,
            "wait_human": _fmt_secs(wait),
            "limiting_window": "429-кулдаун",
        }

    # 2) Основные окна: rpm -> rpd -> rpw -> rpm_month
    for key, window_sec, human in _WINDOWS:
        limit = limits.get(key)
        if not isinstance(limit, int):
            continue
        used = snap[key]
        if used >= limit:
            oldest = _oldest_in_window(ev, window_sec)
            if oldest is None:
                wait = 0
            else:
                wait = max(0, int(oldest + window_sec - time.time()) + 1)
            return {
                "available": False,
                "reason": f"лимит {key} ({used}/{limit} за {human})",
                "wait_sec": wait,
                "wait_human": _fmt_secs(wait),
                "limiting_window": key,
            }

    return {
        "available": True,
        "reason": "ok",
        "wait_sec": 0,
        "wait_human": "сейчас",
        "limiting_window": None,
    }


def reset_schedule(provider: str) -> dict:
    """По каждому окну — когда освободится один слот.

    Возвращает {window_key: {...}}. Только окна с числовым лимитом.
    """
    p = _norm(provider)
    limits = load_limits().get(p)
    if not limits:
        return {}
    data = _load_usage()
    ev = data.get(p, {"events": []}).get("events", [])
    snap = usage_snapshot(p)
    out = {}
    for key, window_sec, human in _WINDOWS:
        limit = limits.get(key)
        if not isinstance(limit, int):
            continue
        oldest = _oldest_in_window(ev, window_sec)
        if oldest is None:
            wait = 0
        else:
            wait = max(0, int(oldest + window_sec - time.time()) + 1)
        out[key] = {
            "limit": limit,
            "used": snap[key],
            "window": human,
            "next_slot_in_sec": wait,
            "next_slot_human": _fmt_secs(wait),
        }
    return out


def is_available(provider: str) -> tuple:
    """(bool, причина). True — можно звать. False — лимит исчерпан.
    Совместимо со старым API. Причина теперь содержит и ETA."""
    info = when_available(provider)
    if info["available"]:
        return True, info["reason"]
    return False, f"{info['reason']}, доступен через {info['wait_human']}"


def report() -> str:
    """Человекочитаемый отчёт по всем провайдерам."""
    limits = load_limits()
    lines = ["=== Лимиты и расход ==="]
    for p, lim in limits.items():
        if p.startswith("_"):
            continue
        snap = usage_snapshot(p)
        info = when_available(p)
        if info["available"]:
            flag = "OK  "
            eta = "сейчас"
        else:
            flag = "СТОП"
            eta = f"через {info['wait_human']}"
        lines.append(
            f"[{flag}] {lim.get('label', p)}\n"
            f"        расход: мин {snap['rpm']}/{lim.get('rpm')}, "
            f"сутки {snap['rpd']}/{lim.get('rpd')}, "
            f"неделя {snap['rpw']}/{lim.get('rpw')}, "
            f"месяц {snap['rpm_month']}/{lim.get('rpm_month')}\n"
            f"        429 за сутки: {snap['count_429_day']}, "
            f"причина: {info['reason']}, "
            f"доступен: {eta}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    print(report())
