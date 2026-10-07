#!/usr/bin/env python3
# scripts/research/_common.py (s180, non-CORE) — shared helpers.
import json, os, ssl, sys, urllib.request
DEFAULT_OUT = "knowledge/research_index.json"

def _root():
    return os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))

def _track(provider, status, ti=0, to=0):
    try:
        r = _root()
        if r not in sys.path: sys.path.insert(0, r)
        import scripts.limits_gateway as g
        g.track(provider, status, tokens_in=ti, tokens_out=to)
    except Exception: pass

def _do_search(url, timeout=15):
    req = urllib.request.Request(url, headers={
        "User-Agent": "ai-hub/1.0",
        "Accept": "application/json",
    })
    ctx = ssl.create_default_context()
    for cp in ("/etc/ssl/cert.pem", "/usr/local/etc/openssl/cert.pem"):
        if os.path.exists(cp):
            try: ctx = ssl.create_default_context(cafile=cp); break
            except Exception: pass
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return json.loads(r.read().decode("utf-8"))

def _http_log(provider, url, status, ms=0.0, err=None):
    """s184: raw HTTP audit log (JSONL, append-only). Never raises."""
    try:
        import datetime as _dt
        r = _root()
        lp = os.path.join(r, "logs", "http.log")
        os.makedirs(os.path.dirname(lp), exist_ok=True)
        rec = {
            "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "provider": provider,
            "url": (url or "")[:300],
            "status": status,
            "ms": int(ms),
        }
        if err is not None:
            rec["error"] = str(err)[:200]
        with open(lp, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def gateway_call(provider, url, timeout=15):
    # s180-r1: gateway.call tracks ok/error/429 internally.
    # s184: raw HTTP audit log (logs/http.log, JSONL).
    import time as _t
    r = _root()
    if r not in sys.path: sys.path.insert(0, r)
    import scripts.limits_gateway as g
    t0 = _t.monotonic()
    try:
        data = g.call(provider, _do_search, url, timeout=timeout)
        _http_log(provider, url, "ok", (_t.monotonic() - t0) * 1000.0)
        return data
    except Exception as e:
        _http_log(provider, url, "error",
                  (_t.monotonic() - t0) * 1000.0, err=e)
        raise

def write_index(items, path=DEFAULT_OUT, query=""):
    import pathlib
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        try: existing = json.loads(p.read_text(encoding="utf-8"))
        except Exception: existing = {"version": 1, "items": []}
    else: existing = {"version": 1, "items": []}
    seen = {it.get("id") for it in existing.get("items", [])}
    added = 0
    for it in items:
        if it.get("id") and it["id"] not in seen:
            existing["items"].append(it); seen.add(it["id"]); added += 1
    existing["last_query"] = query
    existing["count"] = len(existing["items"])
    p.write_text(json.dumps(existing, ensure_ascii=False, indent=2),
                 encoding="utf-8")
    return added, existing["count"]


def _do_search_text(url, timeout=15):
    """s184: raw text fetch (for XML/Atom endpoints like arXiv)."""
    req = urllib.request.Request(url, headers={"User-Agent": "ai-hub/1.0"})
    ctx = ssl.create_default_context()
    for cp in ("/etc/ssl/cert.pem", "/usr/local/etc/openssl/cert.pem"):
        if os.path.exists(cp):
            try: ctx = ssl.create_default_context(cafile=cp); break
            except Exception: pass
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read().decode("utf-8")


def gateway_call_text(provider, url, timeout=15):
    """s184: gateway + http.log, returns raw text (no JSON parse)."""
    import time as _t
    r = _root()
    if r not in sys.path: sys.path.insert(0, r)
    import scripts.limits_gateway as g
    t0 = _t.monotonic()
    try:
        data = g.call(provider, _do_search_text, url, timeout=timeout)
        _http_log(provider, url, "ok", (_t.monotonic() - t0) * 1000.0)
        return data
    except Exception as e:
        _http_log(provider, url, "error",
                  (_t.monotonic() - t0) * 1000.0, err=e)
        raise
