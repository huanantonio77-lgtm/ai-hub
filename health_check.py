#!/usr/bin/env python3
"""Проверка работоспособности системы ai-hub.
Запуск: python3 health_check.py
Проверяет: ключи, прокси, каждого провайдера (короткий ping).
"""
import json, pathlib, time, sys
import requests
import urllib3


def _silent(tag, e):
    """s105-3: emit silent except to errors.jsonl (K1 emission)."""
    try:
        from datetime import datetime as _dt, timezone as _tz
        import json as _j
        _root = Path(__file__).resolve().parent
        log = _root / ".cache" / "system" / "errors.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": _dt.now(_tz.utc).strftime("%Y-%m-%d %H:%M:%S"),
               "kind": "silent", "where": "health_check",
               "detail": tag + ": " + type(e).__name__ + ": " + str(e)[:100]}
        with log.open("a", encoding="utf-8") as f:
            f.write(_j.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
urllib3.disable_warnings()

HOME = pathlib.Path.home()
HUB  = HOME / "Desktop" / "ai-hub"
SEC  = HUB / ".secrets"

ok_count = 0
fail_count = 0

def line(icon, name, detail=""):
    global ok_count, fail_count
    if icon == "OK":
        ok_count += 1
        print(f"  ✓ {name}: {detail}")
    else:
        fail_count += 1
        print(f"  ✗ {name}: {detail}")

# ---------- 1. КЛЮЧИ ----------
print("\n[1/3] Ключи")
keys = [
    ("Gemini",      SEC / "gemini_api_key.txt"),
    ("Tavily",      SEC / "tavily_api_key.txt"),
    ("OpenRouter",  SEC / "providers" / "openrouter.txt"),
    ("Mistral",     SEC / "providers" / "mistral.txt"),
    ("Cloudflare",  SEC / "providers" / "cloudflare.txt"),
    ("Cohere",      SEC / "providers" / "cohere.txt"),
    ("HuggingFace", SEC / "providers" / "huggingface.txt"),
    ("Proxy",       SEC / "proxy.txt"),
]
for name, path in keys:
    if path.exists() and path.read_text(encoding="utf-8").strip():
        line("OK", name, f"{len(path.read_text().strip())} символов")
    else:
        line("ERR", name, "файл отсутствует или пустой")

# ---------- 2. ПРОКСИ ----------
print("\n[2/3] Прокси")
proxy_path = SEC / "proxy.txt"
proxies = None
if proxy_path.exists():
    url = proxy_path.read_text(encoding="utf-8").strip()
    proxies = {"http": url, "https": url}
    try:
        t = time.time()
        r = requests.get("https://api.ipify.org?format=json",
                         proxies=proxies, timeout=15, verify=False)
        dt = time.time() - t
        ip = r.json().get("ip", "?")
        line("OK", "Прокси живой", f"IP {ip}, {dt:.1f}с")
    except Exception as e:
        line("ERR", "Прокси", str(e)[:80])
else:
    line("ERR", "Прокси", "файл не найден")

# ---------- 3. ПРОВАЙДЕРЫ ----------
print("\n[3/3] Провайдеры (короткий ping)")

def note_429(provider, model):
    """Пишет 429 ТОЛЬКО в model_cooldowns.json (errors.jsonl не трогаем — диагностика)."""
    import json as _j, time as _t
    sys_dir = HUB / ".cache" / "system"
    sys_dir.mkdir(parents=True, exist_ok=True)
    try:
        rec = {
            "ts": _t.strftime("%Y-%m-%d %H:%M:%S"),
            "kind": "429",
            "where": provider,
            "detail": model,
        }
        # errors.jsonl больше не пишем — диагностика не должна плодить баги
        pass
    except Exception as _e:
        _silent('health_check_L81', _e)
    try:
        cd_file = sys_dir / "model_cooldowns.json"
        cds = {}
        if cd_file.exists():
            try:
                cds = _j.loads(cd_file.read_text(encoding="utf-8"))
            except Exception:
                cds = {}
        cds[f"{provider}/{model}"] = {"until": _t.time() + 30 * 60, "reason": "429"}
        cd_file.write_text(_j.dumps(cds, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as _e:
        _silent('health_check_L93', _e)


class _SkipCooldown(Exception):
    """s111-a10: сигнал пропустить ping, модель в cooldown."""
    pass


def _cooldown_active(provider, model):
    """s111-a10: True, если model в активном cooldown."""
    try:
        import json as _j, time as _t
        cd_file = HUB / ".cache" / "system" / "model_cooldowns.json"
        if not cd_file.exists():
            return False
        cds = _j.loads(cd_file.read_text(encoding="utf-8"))
        entry = cds.get(str(provider) + "/" + str(model))
        if not entry:
            return False
        if isinstance(entry, dict):
            until = float(entry.get("until", 0) or 0)
        else:
            until = float(entry or 0)
        return until > _t.time()
    except Exception:
        return False


def ping_gemini():
    key = (SEC / "gemini_api_key.txt").read_text().strip()
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           "gemini-3.6-flash:generateContent?key=" + key)
    body = {"contents":[{"parts":[{"text":"ping"}]}]}
    r = requests.post(url, json=body, timeout=30,
                      proxies=proxies, verify=False)
    return r.status_code, r.text[:120]

def ping_openai_compatible(name, url, key, model):
    h = {"Authorization": f"Bearer {key}", "Content-Type": "application/json",
         "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"}
    body = {"model": model, "messages": [{"role":"user","content":"ping"}], "max_tokens": 5}
    r = requests.post(url, headers=h, json=body, timeout=30, verify=False)
    return r.status_code, r.text[:120]

# Gemini
try:
    if _cooldown_active("gemini", "gemini-3.6-flash"):
        raise _SkipCooldown("cooldown")
    code, txt = ping_gemini()
    if code == 429:
        note_429("gemini", "gemini-3.6-flash")
    line("OK" if code == 200 else "ERR", "Gemini", f"HTTP {code}")
except _SkipCooldown:
    line("OK", "Gemini", "skip — cooldown")
except Exception as e:
    line("ERR", "Gemini", str(e)[:80])

# OpenRouter
try:
    if _cooldown_active("openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free"):
        raise _SkipCooldown("cooldown")
    key = (SEC / "providers" / "openrouter.txt").read_text().strip()
    code, txt = ping_openai_compatible("OpenRouter",
        "https://openrouter.ai/api/v1/chat/completions",
        key, "nvidia/nemotron-3-ultra-550b-a55b:free")
    if code == 429:
        note_429("openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free")
    line("OK" if code == 200 else "ERR", "OpenRouter", f"HTTP {code}")
except _SkipCooldown:
    line("OK", "OpenRouter", "skip — cooldown")
except Exception as e:
    line("ERR", "OpenRouter", str(e)[:80])

# Mistral
try:
    if _cooldown_active("mistral", "open-mistral-nemo"):
        raise _SkipCooldown("cooldown")
    key = (SEC / "providers" / "mistral.txt").read_text().strip()
    code, txt = ping_openai_compatible("Mistral",
        "https://api.mistral.ai/v1/chat/completions",
        key, "open-mistral-nemo")
    if code == 429:
        note_429("mistral", "open-mistral-nemo")
    line("OK" if code == 200 else "ERR", "Mistral", f"HTTP {code}")
except _SkipCooldown:
    line("OK", "Mistral", "skip — cooldown")
except Exception as e:
    line("ERR", "Mistral", str(e)[:80])

# HuggingFace
try:
    if _cooldown_active("huggingface", "meta-llama/Llama-3.3-70B-Instruct"):
        raise _SkipCooldown("cooldown")
    key = (SEC / "providers" / "huggingface.txt").read_text().strip()
    code, txt = ping_openai_compatible("HuggingFace",
        "https://router.huggingface.co/v1/chat/completions",
        key, "meta-llama/Llama-3.3-70B-Instruct")
    if code == 429:
        note_429("huggingface", "meta-llama/Llama-3.3-70B-Instruct")
    line("OK" if code == 200 else "ERR", "HuggingFace", f"HTTP {code}")
except _SkipCooldown:
    line("OK", "HuggingFace", "skip — cooldown")
except Exception as e:
    line("ERR", "HuggingFace", str(e)[:80])

# Cohere
try:
    if _cooldown_active("cohere", "command-r-08-2024"):
        raise _SkipCooldown("cooldown")
    key = (SEC / "providers" / "cohere.txt").read_text().strip()
    h = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    body = {"model": "command-r-08-2024",
            "messages": [{"role":"user","content":"ping"}]}
    r = requests.post("https://api.cohere.com/v2/chat",
                      headers=h, json=body, timeout=30, verify=False)
    if r.status_code == 429:
        note_429("cohere", "command-r-08-2024")
    line("OK" if r.status_code == 200 else "ERR", "Cohere", f"HTTP {r.status_code}")
except _SkipCooldown:
    line("OK", "Cohere", "skip — cooldown")
except Exception as e:
    line("ERR", "Cohere", str(e)[:80])

# Cloudflare (особый формат)
try:
    if _cooldown_active("cloudflare", "@cf/meta/llama-3.3-70b-instruct-fp8-fast"):
        raise _SkipCooldown("cooldown")
    raw = (SEC / "providers" / "cloudflare.txt").read_text().strip()
    token = ""
    account = ""
    for ln in raw.splitlines():
        if "=" in ln:
            k, v = ln.split("=", 1)
            k = k.strip(); v = v.strip()
            if k == "token": token = v
            elif k == "account_id": account = v
    url = (f"https://api.cloudflare.com/client/v4/accounts/{account}"
           f"/ai/run/@cf/meta/llama-3.3-70b-instruct-fp8-fast")
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"messages": [{"role":"user","content":"ping"}]}
    r = requests.post(url, headers=h, json=body, timeout=30, verify=False)
    if r.status_code == 429:
        note_429("cloudflare", "@cf/meta/llama-3.3-70b-instruct-fp8-fast")
    line("OK" if r.status_code == 200 else "ERR", "Cloudflare", f"HTTP {r.status_code}")
except _SkipCooldown:
    line("OK", "Cloudflare", "skip — cooldown")
except Exception as e:
    line("ERR", "Cloudflare", str(e)[:80])

# ---------- 4. ЛИМИТЫ И COOLDOWN ----------
print("\n[4/5] Лимиты и cooldown")
try:
    sys.path.insert(0, str(HUB))
    import limits as _lim
    for p_name in ["gemini", "openrouter", "mistral", "cloudflare", "cohere", "huggingface"]:
        info = _lim.when_available(p_name)
        snap = _lim.usage_snapshot(p_name)
        if info["available"]:
            detail = f"rpm {snap['rpm']}, rpd {snap['rpd']} — доступен сейчас"
            line("OK", f"limit {p_name}", detail)
        else:
            line("ERR", f"limit {p_name}",
                 f"{info['reason']}, через {info['wait_human']}")
except Exception as e:
    line("ERR", "limits.py", str(e)[:80])

# Cooldown-модели после 429
try:
    cd_file = HUB / ".cache" / "system" / "model_cooldowns.json"
    if cd_file.exists():
        cds = json.loads(cd_file.read_text(encoding="utf-8"))
        now_ts = time.time()
        active = {}
        for k, v in cds.items():
            if isinstance(v, dict):
                until = float(v.get("until", 0) or 0)
            else:
                try:
                    until = float(v)
                except Exception:
                    continue
            if until > now_ts:
                active[k] = int(until - now_ts)
        if active:
            for k, left in sorted(active.items()):
                h, m, s = left // 3600, (left % 3600) // 60, left % 60
                line("ERR", f"cooldown {k}", f"ещё {h}ч {m}м {s}с")
        else:
            line("OK", "cooldown", "пусто — все модели доступны")
    else:
        line("OK", "cooldown", "файла нет — все модели доступны")
except Exception as e:
    line("ERR", "cooldown", str(e)[:80])

# ---------- 5. НОВЫЕ ОШИБКИ С ПРОШЛОГО ЗАПУСКА ----------
print("\n[5/5] Новые ошибки с прошлого запуска")
try:
    err_file = HUB / ".cache" / "system" / "errors.jsonl"
    mark_file = HUB / ".cache" / "system" / "last_bugs_seen_health.json"

    total = 0
    if err_file.exists():
        with err_file.open("r", encoding="utf-8") as f:
            total = sum(1 for _ in f)

    prev = 0
    if mark_file.exists():
        try:
            prev = int(json.loads(mark_file.read_text(encoding="utf-8")).get("count", 0))
        except Exception:
            prev = 0

    diff = total - prev
    if diff > 0:
        print(f"  \u26a0 новых: +{diff} (всего {total})")
        try:
            with err_file.open("r", encoding="utf-8") as f:
                all_lines = f.readlines()
            for ln in all_lines[-min(diff, 5):]:
                print(f"    {ln.rstrip()}")
        except Exception:
            pass
    else:
        print(f"  \u2713 новых нет (всего {total})")

    mark_file.parent.mkdir(parents=True, exist_ok=True)
    mark_file.write_text(json.dumps({"count": total, "ts": time.time()}), encoding="utf-8")
except Exception as e:
    print(f"  \u2717 ошибка блока: {str(e)[:80]}")

# ---------- ИТОГ ----------
print(f"\n=== ИТОГ: OK {ok_count}, ОШИБОК {fail_count} ===")
sys.exit(0 if fail_count == 0 else 1)
