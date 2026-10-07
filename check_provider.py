#!/usr/bin/env python3
"""check_provider.py — проверка бесплатного LLM-провайдера.

Использование:
    python3 check_provider.py --name "Pollinations" \\
        --url "https://text.pollinations.ai/openai"

    python3 check_provider.py --name "LLM7" \\
        --url "https://api.llm7.io/v1/chat/completions" \\
        --key unused --model codestral-latest

Что делает:
    1. Пробует GET /v1/models (если URL заканчивается на /v1 или /openai — иначе пропускает).
    2. Делает POST /v1/chat/completions с тестовым сообщением "Say OK".
    3. Возвращает OK / FAIL и печатает сырой ответ (первые 300 символов).

Коды возврата:
    0 — работает (есть поле "choices" в ответе)
    1 — не работает (ошибка, таймаут, пусто)
"""
import argparse
import json
import sys
import requests


def _try_models(url: str, key: str | None, timeout: int = 15) -> None:
    base = url.rstrip("/")
    # убираем /chat/completions если есть
    if base.endswith("/chat/completions"):
        base = base[: -len("/chat/completions")]
    models_url = base + "/models"
    print(f"  GET {models_url}")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        r = requests.get(models_url, headers=headers, timeout=timeout)
        print(f"    HTTP {r.status_code}")
        if r.status_code == 200:
            try:
                data = r.json()
                models = data.get("data") or data.get("models") or []
                names = [m.get("id") or m.get("name") for m in models if isinstance(m, dict)]
                if names:
                    print(f"    моделей: {len(names)}, первые: {names[:5]}")
            except Exception:
                print(f"    тело: {r.text[:200]!r}")
    except Exception as e:
        print(f"    {type(e).__name__}: {e}")


def _try_chat(url: str, key: str | None, model: str, timeout: int = 20) -> bool:
    print(f"  POST {url}")
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Say OK"}],
        "max_tokens": 10,
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=timeout)
        print(f"    HTTP {r.status_code}")
        body = r.text[:300]
        print(f"    тело: {body!r}")
        if r.status_code == 200:
            try:
                data = r.json()
                if data.get("choices"):
                    return True
            except Exception:
                pass
        return False
    except Exception as e:
        print(f"    {type(e).__name__}: {e}")
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="человеческое имя провайдера")
    ap.add_argument("--url", required=True, help="полный URL до /chat/completions или базы")
    ap.add_argument("--key", default=None, help="API-ключ (если не нужен — не передавать)")
    ap.add_argument("--model", default="default", help="модель для теста")
    ap.add_argument("--skip-models", action="store_true", help="не дёргать /v1/models")
    args = ap.parse_args()

    print(f"=== Проверка: {args.name} ===")
    print(f"  URL:  {args.url}")
    print(f"  Ключ: {'<задан>' if args.key else '<нет>'}")
    print(f"  Модель: {args.model}")

    url = args.url
    # если URL не содержит /chat/completions — допишем
    if not url.rstrip("/").endswith("/chat/completions"):
        url = url.rstrip("/") + "/chat/completions"

    if not args.skip_models:
        _try_models(args.url, args.key)

    ok = _try_chat(url, args.key, args.model)
    print()
    if ok:
        print(f"РЕЗУЛЬТАТ: \U0001F7E2 {args.name} — РАБОТАЕТ")
        return 0
    else:
        print(f"РЕЗУЛЬТАТ: \U0001F534 {args.name} — НЕ РАБОТАЕТ")
        return 1


if __name__ == "__main__":
    sys.exit(main())
