#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""api_health.py -- s124-stage7.2: API-keys health healer (21st).

Daily ping all enabled APIs from strategy/api_registry.json.
History: self/healers/api_health.jsonl.
Journal: self/healers/api_health.md.

Rights: record_finding, add_repair_task.
Cannot: mutate_core, delete_file, touch_secrets_content.

Rule s124-rule-no-lazy-decisions: ping endpoints are free (no LLM tokens).
"""
import argparse
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REG = ROOT / "strategy" / "api_registry.json"
JOURNAL = ROOT / "self" / "healers" / "api_health.jsonl"
AUDIT_MD = ROOT / "strategy" / "api_health.md"
AUTONOMY = ROOT / "self" / "autonomy.jsonl"
LOCK = ROOT / ".cache" / "system" / "api_health_daily.ts"
TIMEOUT = 15

_CTX = ssl._create_unverified_context()
_UA = "ai-nova-api-health/1.0"

def _silent(tag, e):
    try:
        log = ROOT / ".cache" / "system" / "errors.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
               "kind": "silent", "where": "api_health",
               "detail": tag + ": " + type(e).__name__ + ": " + str(e)[:100]}
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass

def _read_key(rel):
    p = ROOT / rel
    if not p.exists():
        return None
    try:
        v = p.read_text(encoding="utf-8").strip()
        return v or None
    except Exception as _e:
        _silent("read_key", _e)
        return None

def _proxy_handler():
    p = ROOT / ".secrets" / "proxy.txt"
    try:
        if p.exists():
            v = p.read_text().strip()
            if v:
                return urllib.request.ProxyHandler({"http": v, "https": v})
    except Exception:
        pass
    return None

def _http(method, url, headers=None, body=None):
    req = urllib.request.Request(url, method=method)
    req.add_header("User-Agent", _UA)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    opener = None
    ph = _proxy_handler()
    if ph:
        opener = urllib.request.build_opener(ph, urllib.request.HTTPSHandler(context=_CTX))
    try:
        if opener:
            with opener.open(req, data=data, timeout=TIMEOUT) as r:
                return r.status, r.read(200)
        with urllib.request.urlopen(req, data=data, timeout=TIMEOUT, context=_CTX) as r:
            return r.status, r.read(200)
    except urllib.error.HTTPError as e:
        return e.code, (e.read(200) if hasattr(e, "read") else b"")
    except Exception as e:
        return None, (type(e).__name__ + ": " + str(e)[:160]).encode()

def ping_one(name, spec):
    t0 = time.monotonic()
    out = {"name": name, "type": spec.get("type"),
           "ok": False, "status": None, "latency_ms": 0, "error": None}
    if not spec.get("enabled"):
        out["error"] = "disabled"
        return out
    if not spec.get("ping_url"):
        out["error"] = "no_ping_url"
        return out
    key = _read_key(spec.get("key_file") or "")
    if spec.get("ping_auth") != "none" and not key:
        out["error"] = "no_key"
        out["latency_ms"] = int((time.monotonic() - t0) * 1000)
        return out
    headers = {}
    body = None
    auth = spec.get("ping_auth")
    if auth == "bearer" and key:
        headers["Authorization"] = "Bearer " + key
    elif auth == "json_body" and spec.get("ping_body"):
        body = dict(spec["ping_body"])
        for k, v in list(body.items()):
            if isinstance(v, str) and "{{KEY}}" in v:
                body[k] = v.replace("{{KEY}}", key or "")
    if "github" in name.lower():
        headers["Accept"] = "application/vnd.github+json"
    status, raw = _http(spec.get("ping_method", "GET"), spec.get("ping_url"),
                        headers=headers, body=body)
    out["latency_ms"] = int((time.monotonic() - t0) * 1000)
    out["status"] = status
    expected = spec.get("expect_status", 200)
    if status == expected:
        out["ok"] = True
    else:
        try:
            out["error"] = raw.decode("utf-8", errors="replace")[:160]
        except Exception:
            out["error"] = str(raw)[:160]
    return out

def ping_all():
    try:
        data = json.loads(REG.read_text(encoding="utf-8"))
    except Exception as e:
        return {"error": "registry read: " + type(e).__name__, "results": []}
    apis = data.get("apis") or {}
    results = []
    for name, spec in apis.items():
        if not isinstance(spec, dict):
            continue
        try:
            results.append(ping_one(name, spec))
        except Exception as e:
            results.append({"name": name, "ok": False,
                            "error": type(e).__name__ + ": " + str(e)[:80]})
    return {"results": results}

def _history_write(results):
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    try:
        with JOURNAL.open("a", encoding="utf-8") as f:
            for r in results:
                rec = {"ts": ts, "name": r.get("name"),
                       "ok": r.get("ok"), "status": r.get("status"),
                       "latency_ms": r.get("latency_ms", 0),
                       "error": r.get("error")}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as _e:
        _silent("history_write", _e)

def _append_autonomy(note, effect=None):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    ev = {"ts": ts, "session": "s124", "action": "api_health", "note": note}
    if effect is not None:
        ev["effect"] = int(effect)
    try:
        with AUTONOMY.open("a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except Exception as _e:
        _silent("autonomy", _e)
    try:
        from healer_log import healer_log
        healer_log("api_health", diagnosis=note, effect=effect)
    except Exception:
        pass

def _render_report(d, ts=None):
    ts = ts or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = ["## " + ts, ""]
    res = d.get("results") or []
    if d.get("error"):
        lines.append("ERR: " + str(d["error"]))
        return "\n".join(lines)
    ok_n = sum(1 for r in res if r.get("ok"))
    fail = [r for r in res if not r.get("ok") and r.get("error") != "disabled"]
    disabled = [r for r in res if r.get("error") == "disabled"]
    lines.append("- total=" + str(len(res)) + " ok=" + str(ok_n)
                 + " fail=" + str(len(fail))
                 + " disabled=" + str(len(disabled)))
    if fail:
        lines.append("")
        lines.append("### Failing")
        for r in fail:
            err = str(r.get("error") or "")[:100]
            lines.append("  - " + str(r.get("name"))
                         + " status=" + str(r.get("status"))
                         + " err=" + err)
    return "\n".join(lines)

def run_report(quiet=False, force=False):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not force:
        try:
            already = LOCK.exists() and LOCK.read_text(encoding="utf-8").strip() == today
        except Exception:
            already = False
        if already:
            if not quiet:
                print("api_health: already_today")
            return {"reason": "already_today"}
    d = ping_all()
    text = _render_report(d)
    if not quiet:
        print(text)
    try:
        AUDIT_MD.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_MD.open("a", encoding="utf-8") as f:
            f.write(text + "\n\n")
    except Exception as _e:
        _silent("audit_md", _e)
    res = d.get("results") or []
    _history_write(res)
    ok_n = sum(1 for r in res if r.get("ok"))
    fail_n = sum(1 for r in res if not r.get("ok") and r.get("error") != "disabled")
    _append_autonomy("ok=" + str(ok_n) + " fail=" + str(fail_n)
                     + " total=" + str(len(res)),
                     effect=ok_n)
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(today, encoding="utf-8")
    return d

def _selftest():
    ok = 0; total = 0
    def chk(n, c):
        nonlocal ok, total
        total += 1
        if c:
            ok += 1; print("  [OK] " + n)
        else:
            print("  [FAIL] " + n)
    chk("registry_exists", REG.exists())
    try:
        d = json.loads(REG.read_text(encoding="utf-8"))
        apis = d.get("apis") or {}
        chk("has_apis", len(apis) >= 8)
        chk("has_llm", any(k.startswith("llm_") for k in apis))
        chk("has_tavily", "tavily" in apis)
        chk("has_github", "github" in apis)
    except Exception:
        chk("registry_parse", False)
    print("passed " + str(ok) + "/" + str(total))
    return 0 if ok == total else 1

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    run_report(quiet=a.quiet, force=a.force)
    return 0

if __name__ == "__main__":
    sys.exit(main())
