#!/usr/bin/env python3
"""
netcheck.py — диагностика сети для ai-hub с определением режима сети (VPN RU+proxy или direct).
"""

import sys, json, socket, time, os
from pathlib import Path
import urllib.request, urllib.error, ssl
import concurrent.futures


def _silent(tag, e):
    """s105-3: emit silent except to errors.jsonl (K1 emission)."""
    try:
        from datetime import datetime as _dt, timezone as _tz
        import json as _j
        _root = Path(__file__).resolve().parent
        log = _root / ".cache" / "system" / "errors.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": _dt.now(_tz.utc).strftime("%Y-%m-%d %H:%M:%S"),
               "kind": "silent", "where": "netcheck",
               "detail": tag + ": " + type(e).__name__ + ": " + str(e)[:100]}
        with log.open("a", encoding="utf-8") as f:
            f.write(_j.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass

ROOT = Path.home() / "Desktop" / "ai-hub"
SECRETS = ROOT / ".secrets"
PROXY_FILE = SECRETS / "proxy.txt"
GROQ_KEY_FILE = SECRETS / "groq_api_key.txt"
GEMINI_KEY_FILE = SECRETS / "gemini_api_key.txt"

TIMEOUT = 8

# Страны, из которых Groq/OpenAI/Anthropic отдают 403 (geo-block)
LLM_BLOCKED_COUNTRIES = {"RU", "BY", "IR", "KP", "SY", "CU"}

# --- Утилиты ---

def _ssl_ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()

def _get(url, timeout=TIMEOUT, headers=None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as r:
        return r.status, r.read().decode("utf-8", errors="replace")

def _read(p):
    try:
        return p.read_text(encoding="utf-8").strip()
    except Exception:
        return None

def is_llm_blocked(country):
    """True если Groq/OpenAI/Anthropic дают 403 из этой страны."""
    if not country:
        return False
    return str(country).upper() in LLM_BLOCKED_COUNTRIES

def load_proxy():
    url = _read(PROXY_FILE)
    if not url:
        return None
    return {"http": url, "https": url}

# --- 1. VPN ---
def check_vpn():
    """Возвращает (ok, ip, country, org, note)."""
    try:
        _, ip = _get("https://api.ipify.org")
        ip = ip.strip()
    except Exception as e:
        return False, None, None, None, f"нет интернета: {e}"
    try:
        _, body = _get(f"https://ipinfo.io/{ip}/json")
        data = json.loads(body)
        return True, ip, data.get("country"), data.get("org"), None
    except Exception as e:
        return True, ip, None, None, f"страну не определил: {e}"

# --- 2. Прокси ---
def check_proxy():
    """Возвращает (ok, note)."""
    proxy = load_proxy()
    if not proxy:
        return False, "proxy.txt пустой или нет"
    try:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler(proxy),
            urllib.request.HTTPSHandler(context=_ssl_ctx()),
        )
        req = urllib.request.Request("https://api.ipify.org",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with opener.open(req, timeout=TIMEOUT) as r:
            proxy_ip = r.read().decode().strip()
        if proxy_ip:
            return True, f"работает, исходящий IP: {proxy_ip}"
        return False, "прокси не вернул IP"
    except Exception as e:
        return False, f"не отвечает: {type(e).__name__}: {e}"

# --- Network mode (RU+proxy / direct) ---
NET_MODE_CACHE_FILE = ROOT / ".runtime" / "net-mode-cache.json"
NET_MODE_TTL_SEC = 300  # 5 минут

def get_network_mode():
    """Определяет режим сети и возвращает его в формате для verify."""
    ok, ip, country, org, note = check_vpn()
    if not ok:
        return "unknown"
    blocked = is_llm_blocked(country)
    if not blocked:
        return "direct"
    p_ok, p_note = check_proxy()
    if p_ok:
        return "RU+proxy"
    return "RU no-proxy!"

def get_network_mode_cached(force=False):
    """Возвращает 4-tuple (mode, country, proxy_ok, detail). Кэш на TTL."""
    now = time.time()
    if not force and NET_MODE_CACHE_FILE.exists():
        try:
            d = json.loads(NET_MODE_CACHE_FILE.read_text(encoding="utf-8"))
            if now - float(d.get("ts", 0)) < NET_MODE_TTL_SEC:
                return (
                    d.get("mode", "unknown"),
                    d.get("country", ""),
                    bool(d.get("proxy_ok", False)),
                    d.get("detail", ""),
                )
        except Exception as _e:
            _silent('netcheck_L120', _e)

    mode = get_network_mode()
    country = ""
    proxy_ok = False
    detail = ""
    try:
        _vpn_ok, _ip, _country, _org, _note = check_vpn()
        country = _country or ""
    except Exception as _e:
        _silent('netcheck_L130', _e)
    try:
        proxy_ok, _p_note = check_proxy()
        proxy_ok = bool(proxy_ok)
        detail = _p_note or ""
    except Exception as _e:
        _silent('netcheck_L136', _e)

    try:
        NET_MODE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        NET_MODE_CACHE_FILE.write_text(
            json.dumps({
                "ts": now,
                "mode": mode,
                "country": country,
                "proxy_ok": proxy_ok,
                "detail": detail,
            }),
            encoding="utf-8",
        )
    except Exception as _e:
        _silent('netcheck_L151', _e)

    return mode, country, proxy_ok, detail

def full_report(quick=False):
    print("=" * 60)
    print("NETCHECK — диагностика сети ai-hub")
    print("=" * 60)
    
    # VPN
    print("\n[1] VPN / внешний IP:")
    ok, ip, country, org, note = check_vpn()
    if ok:
        flag = "✓" if country and country not in ("GE",) else "⚠"
        print(f"    {flag} IP: {ip}")
        print(f"      Страна: {country or '?'}")
        if country == "GE":
            print("      ⚠ VPN скорее всего ВЫКЛЮЧЕН — Groq/OpenAI дадут 403")
    else:
        print(f"    ✗ {note}")
    
    # Proxy
    print("\n[2] Прокси (.secrets/proxy.txt):")
    p_ok, p_note = check_proxy()
    flag = "✓" if p_ok else "✗"
    print(f"    {flag} {p_note}")
    
    if quick:
        print("\n(quick — LLM-проверки пропущены)")
        return
    
    # Network mode
    mode = get_network_mode()
    print(f"\n[3] Режим сети: {mode}")
    
    # Диагноз
    print("\n" + "=" * 60)
    print("ДИАГНОЗ:")
    print("=" * 60)
    if not ok:
        print("  → Нет интернета вообще. Проверь Wi-Fi.")
    elif country == "GE":
        print("  → VPN ВЫКЛЮЧЕН. Включи его: Groq и OpenAI без VPN дадут 403.")
    elif mode == "RU+proxy":
        print("  → Используется VPN из блокируемой страны с прокси.")
    elif mode == "RU no-proxy!":
        print("  → VPN из блокируемой страны, но прокси не работает.")
    else:
        print("  → Прямое подключение (VPN не в блокируемой стране).")
    
    print()

PROXIES_TRUSTED_FILE = SECRETS / "proxies_trusted.txt"
PROXIES_PUBLIC_FILE = SECRETS / "proxies_public.txt"


def list_proxies(path):
    """Читает файл со списком прокси. Игнорирует пустые строки и #-комменты.

    Возвращает список строк (URL вида http://user:pass@ip:port).
    Файл может не существовать — тогда возвращает [].
    """
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        out.append(ln)
    return out


def check_one(proxy_url, timeout=None):
    """Проверяет один прокси. Возвращает dict:
    {ok: bool, latency_ms: int, ip: str, note: str, proxy: str}.
    """
    t0 = time.time()
    to = timeout if timeout is not None else TIMEOUT
    try:
        proxy = {"http": proxy_url, "https": proxy_url}
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler(proxy),
            urllib.request.HTTPSHandler(context=_ssl_ctx()),
        )
        req = urllib.request.Request("https://api.ipify.org",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with opener.open(req, timeout=to) as r:
            ip = r.read().decode().strip()
        latency = int((time.time() - t0) * 1000)
        if ip:
            return {"ok": True, "latency_ms": latency, "ip": ip,
                    "note": "ok " + str(latency) + "ms", "proxy": proxy_url}
        return {"ok": False, "latency_ms": latency, "ip": None,
                "note": "no ip", "proxy": proxy_url}
    except Exception as e:
        latency = int((time.time() - t0) * 1000)
        return {"ok": False, "latency_ms": latency, "ip": None,
                "note": type(e).__name__, "proxy": proxy_url}


def check_all(proxies, timeout=None, workers=8):
    """Параллельно проверяет список прокси. Возвращает список dict."""
    if not proxies:
        return []
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(check_one, pr, timeout): pr for pr in proxies}
        for fut in concurrent.futures.as_completed(futs):
            try:
                results.append(fut.result())
            except Exception as e:
                results.append({"ok": False, "latency_ms": 0, "ip": None,
                                "note": "future:" + type(e).__name__,
                                "proxy": futs[fut]})
    results.sort(key=lambda r: (not r["ok"], r["latency_ms"]))
    return results


def _mask(p):
    """Скрывает user:pass в URL прокси."""
    if "@" in p:
        return "***@" + p.split("@", 1)[1]
    return p


def _cli_check_all():
    """CLI: python3 netcheck.py --check-all [--file path]"""
    file_path = None
    for i, a in enumerate(sys.argv):
        if a == "--file" and i + 1 < len(sys.argv):
            file_path = sys.argv[i + 1]
    paths = []
    if file_path:
        paths.append((file_path, "custom"))
    else:
        paths.append((PROXIES_TRUSTED_FILE, "trusted"))
        paths.append((PROXIES_PUBLIC_FILE, "public"))
        paths.append((PROXY_FILE, "legacy-proxy.txt"))
    grand = 0
    for path, label in paths:
        lst = list_proxies(path)
        if not lst:
            print("[" + label + "] " + str(path) + " — пусто или нет файла")
            continue
        print("[" + label + "] " + str(path) + " — " + str(len(lst)) + " шт., проверяю...")
        res = check_all(lst, timeout=TIMEOUT, workers=8)
        ok = sum(1 for r in res if r["ok"])
        print("  живы: " + str(ok) + "/" + str(len(res)))
        for r in res:
            flag = "OK " if r["ok"] else "MISS"
            print("  " + flag + "  " + str(r["latency_ms"]).rjust(6) + "ms  "
                  + _mask(r["proxy"]) + "  " + r["note"])
        grand += ok
    print("ИТОГО живых: " + str(grand))


def main():
    quick = "--quick" in sys.argv
    full_report(quick=quick)

if __name__ == "__main__":
    if "--check-all" in sys.argv:
        _cli_check_all()
    else:
        mode, _country, _proxy_ok, _detail = get_network_mode_cached()
        print(f"mode: {mode}")
        main()
