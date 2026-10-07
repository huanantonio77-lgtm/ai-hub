#!/usr/bin/env python3
"""api_health.py — health-check API-ключей (s176-P1b)."""
import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CUR = ROOT / "self" / "curator"
API_LOG = CUR / "API_HEALTH.jsonl"
UNRESOLVED = CUR / "UNRESOLVED.jsonl"
SECRETS = Path.home() / ".ai-hub-secrets.env"

PROVIDERS = {
    "openalex": {
        "url": "https://api.openalex.org/works?search=test&per_page=1",
        "env_key": "OPENALEX_API_KEY",
        "severity": "P1",
    },
    "ollama": {
        "url": "http://127.0.0.1:11434/api/tags",
        "env_key": None,
        "severity": "P0",
    },
}

DEFAULT_TIMEOUT = 10
BACKOFF = [1, 3]


def _ssl_ctx():
    import ssl
    for ca in ("/etc/ssl/cert.pem",
               "/etc/ssl/certs/ca-certificates.crt"):
        if Path(ca).exists():
            return ssl.create_default_context(cafile=ca)
    return ssl.create_default_context()


def _now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(
        timespec="seconds")


def _load_key_from_secrets(key_name):
    if not SECRETS.exists():
        return None
    try:
        for line in SECRETS.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[len("export "):]
            if line.startswith(key_name + "="):
                v = line.split("=", 1)[1].strip()
                return v.strip("'").strip('"')
    except Exception:
        pass
    return None





def _track(provider, status, tokens_in=0, tokens_out=0):
    try:
        import sys as _s
        import os as _os
        root = _os.path.dirname(_os.path.dirname(
            _os.path.abspath(__file__)))
        if str(root) not in _s.path:
            _s.path.insert(0, str(root))
        import limits as _lim
        _lim.record_call(provider, status,
                         tokens_in=tokens_in, tokens_out=tokens_out)
    except Exception:
        pass


def ping(name, cfg, timeout=DEFAULT_TIMEOUT):
    t0 = time.monotonic()
    url = cfg["url"]
    key = None
    if cfg.get("env_key"):
        key = os.environ.get(cfg["env_key"], "") \
              or _load_key_from_secrets(cfg["env_key"]) or ""
        if key:
            sep = "&" if "?" in url else "?"
            url = url + sep + "api_key=" + key
    req = urllib.request.Request(
        url, headers={"User-Agent": "ai-hub-api-health/1.0"})
    try:
        with urllib.request.urlopen(
                req, timeout=timeout, context=_ssl_ctx()) as r:
            code = r.status
            _ = r.read(2048)
        ms = int((time.monotonic() - t0) * 1000)
        _track(name, "ok" if code == 200 else "error")
        return {"ok": code == 200, "ms": ms, "code": code,
                "last_error": None,
                "key_len": len(key) if key else 0}
    except urllib.error.HTTPError as e:
        ms = int((time.monotonic() - t0) * 1000)
        _track(name, "429" if e.code == 429 else "error")
        return {"ok": False, "ms": ms, "code": e.code,
                "last_error": "HTTP " + str(e.code),
                "key_len": len(key) if key else 0}
    except Exception as e:
        ms = int((time.monotonic() - t0) * 1000)
        _track(name, "error")
        msg = type(e).__name__ + ": " + str(e)[:150]
        return {"ok": False, "ms": ms, "code": None,
                "last_error": msg,
                "key_len": len(key) if key else 0}


def _reload_env_from_secrets():
    out = {}
    if not SECRETS.exists():
        return out
    try:
        for line in SECRETS.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[len("export "):]
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip("'").strip('"')
    except Exception:
        pass
    return out


def autofix(name, cfg):
    import subprocess
    actions = []
    for delay in BACKOFF:
        time.sleep(delay)
        r = ping(name, cfg)
        actions.append({"action": "retry", "delay": delay,
                        "ok": r["ok"]})
        if r["ok"]:
            return True, actions
    env = _reload_env_from_secrets()
    key = cfg.get("env_key")
    if key and key in env:
        os.environ[key] = env[key]
    r = ping(name, cfg)
    actions.append({"action": "reload_env", "ok": r["ok"]})
    if r["ok"]:
        return True, actions
    agent = cfg.get("restart_agent")
    if agent:
        try:
            uid = os.getuid()
            subprocess.run(
                ["launchctl", "kickstart", "-k",
                 f"gui/{uid}/{agent}"],
                check=False, timeout=15, capture_output=True,
            )
            time.sleep(3)
            r = ping(name, cfg)
            actions.append({"action": "restart_agent",
                            "agent": agent, "ok": r["ok"]})
            if r["ok"]:
                return True, actions
        except Exception as e:
            actions.append({"action": "restart_agent",
                            "error": str(e)[:120]})
    return False, actions


def append_api_log(record):
    API_LOG.parent.mkdir(parents=True, exist_ok=True)
    with API_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def escalate(name, cfg, last_error):
    rec = {
        "ts": _now_iso(),
        "session": "s176",
        "task": "api_health_" + name,
        "desc": name + " ping FAIL: " + (last_error or "unknown"),
        "status": "open",
        "priority": cfg.get("severity", "P1"),
        "severity": cfg.get("severity", "P1"),
    }
    try:
        UNRESOLVED.parent.mkdir(parents=True, exist_ok=True)
        with UNRESOLVED.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return rec


def check_all(no_fix=False, dry=False, verbose=True):
    results = {}
    for name, cfg in PROVIDERS.items():
        r = ping(name, cfg)
        actions = []
        if not r["ok"] and not no_fix:
            fixed, actions = autofix(name, cfg)
            if fixed:
                r["after_fix"] = True
            else:
                r["escalated"] = escalate(
                    name, cfg, r.get("last_error"))
        elif not r["ok"]:
            r["escalated"] = escalate(
                name, cfg, r.get("last_error"))
        r["actions"] = actions
        results[name] = r
        if verbose:
            status = "OK  " if r["ok"] else "FAIL"
            print("  {:10s} {}  ms={}  code={}  key_len={}".format(
                name, status, r.get("ms"), r.get("code"),
                r.get("key_len")))
            if r.get("last_error"):
                print("             error: " + str(r["last_error"]))
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="API-health healer (s176)")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--no-fix", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    if not args.check:
        ap.print_help()
        return 2
    results = check_all(no_fix=args.no_fix, dry=args.dry,
                        verbose=not args.quiet)
    record = {"ts": _now_iso(), "results": results}
    if not args.dry:
        append_api_log(record)
    bad = any(not r["ok"] for r in results.values())
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
