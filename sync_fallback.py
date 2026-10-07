#!/usr/bin/env python3
"""sync_fallback.py — s77-1c: обновление strategy/fallback_providers.json из providers_registry.json.

Логика: отбирает openai_compatible с last_error пусто и validated_at не старше --max-age
(по умолчанию 7 дней), сортирует по latency_ms, берёт top-N (по умолчанию 6).
Пишет strategy/fallback_providers.json в формате, который читает llm_call._get_fallback_providers.

Команды:
  sync_fallback.py             # пишет JSON
  sync_fallback.py --dry       # печатает что записал бы, не пишет
  sync_fallback.py --top N     # top-N, дефолт 6
  sync_fallback.py --max-age D # дней, дефолт 7
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / "providers_registry.json"
FB_JSON = ROOT / "strategy" / "fallback_providers.json"

DEFAULT_TOP = 6
DEFAULT_MAX_AGE_DAYS = 7
TTL_DAYS = 30
_INF_LAT = 10 ** 9


def _age_days(validated_at):
    """Возраст validated_at в днях, или None если невалидно."""
    if not validated_at:
        return None
    try:
        ts = datetime.strptime(validated_at[:19], "%Y-%m-%dT%H:%M:%S")
    except Exception:
        return None
    return (datetime.now() - ts).days


def _strip_secrets_prefix(kf):
    if kf.startswith(".secrets/"):
        return kf[len(".secrets/"):]
    return kf


def _filter(reg, max_age_days):
    """Список кандидатов, отсортированных по latency_ms."""
    provs = reg.get("providers", {}) if isinstance(reg, dict) else {}
    out = []
    for name, p in provs.items():
        if not isinstance(p, dict):
            continue
        if p.get("api_type") != "openai_compatible":
            continue
        if p.get("enabled") is False:
            continue
        if p.get("last_error"):
            continue
        age = _age_days(p.get("validated_at", ""))
        if age is None or age > max_age_days:
            continue
        url = (p.get("api_url") or "").strip()
        kf = (p.get("key_file") or "").strip()
        models = p.get("models") or []
        if not url or not kf or not models:
            continue
        item = {
            "name": name,
            "key_file": _strip_secrets_prefix(kf),
            "models": list(models),
            "url": url,
        }
        eh = p.get("extra_headers")
        if isinstance(eh, dict) and eh:
            item["extra_headers"] = dict(eh)
        lat = p.get("latency_ms")
        item["_lat"] = lat if isinstance(lat, (int, float)) else _INF_LAT
        out.append(item)
    out.sort(key=lambda x: x["_lat"])
    for it in out:
        it.pop("_lat", None)
    return out


def _build_json(candidates, top):
    selected = candidates[:top]
    return {
        "_комментарий": "Fallback LLM-провайдеры. Обновляется sync_fallback.py из providers_registry.json. Ручное редактирование допустимо, но будет перезаписано.",
        "_обновлён": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "_источник": "providers_registry.json",
        "_ttl_дней": TTL_DAYS,
        "providers": selected,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--top", type=int, default=DEFAULT_TOP)
    ap.add_argument("--max-age", type=int, default=DEFAULT_MAX_AGE_DAYS)
    args = ap.parse_args()

    print("=== sync_fallback ===")
    if not REGISTRY.exists():
        print(f"  ERROR: {REGISTRY.name} не найден")
        return 1
    try:
        reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ERROR: registry parse: {type(e).__name__}: {e}")
        return 1

    provs = reg.get("providers", {}) if isinstance(reg, dict) else {}
    print(f"  registry: {len(provs)} провайдеров")

    oai = sum(1 for _, p in provs.items()
              if isinstance(p, dict) and p.get("api_type") == "openai_compatible")
    print(f"  openai_compatible: {oai}")

    cands = _filter(reg, args.max_age)
    print(f"  живых (last_error пусто, age<={args.max_age}d): {len(cands)}")
    for c in cands:
        print(f"    {c['name']:20s} models={len(c['models'])}")

    if not cands:
        print("  ERROR: 0 живых после фильтра. JSON не меняю.")
        return 1

    data = _build_json(cands, args.top)
    print(f"  пишу: {len(data['providers'])} провайдеров (top={args.top})")

    if args.dry:
        print("  --dry: не пишу")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0

    FB_JSON.parent.mkdir(parents=True, exist_ok=True)
    FB_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  OK: {FB_JSON.name} записан")
    return 0


if __name__ == "__main__":
    sys.exit(main())
