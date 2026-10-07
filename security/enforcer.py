"""security/enforcer.py — deny-by-default policy check (s88-1.1a, v0.1.0)."""
import json
import re
import sys
from datetime import datetime
import time
from urllib.parse import urlparse
import socket
from pathlib import Path


def _silent(tag, e):
    """s104-2d: emit silent except to errors.jsonl (K1 emission)."""
    try:
        from datetime import datetime as _dt, timezone as _tz
        log = Path(__file__).resolve().parent / ".cache" / "system" / "errors.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": _dt.now(_tz.utc).strftime("%Y-%m-%d %H:%M:%S"),
               "kind": "silent", "where": "security/enforcer.py",
               "detail": tag + ": " + type(e).__name__ + ": " + str(e)[:100]}
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as _e:
        _silent("enf_pass", _e)

SEC_DIR = Path(__file__).resolve().parent  # s1.1c
ROOT = SEC_DIR.parent
MANIFEST = SEC_DIR / "tool_manifest.json"
LOG = ROOT / "strategy" / "_security_log.jsonl"

_CACHE = {"mtime": None, "data": None}

_RATE_LIMIT = {}  # s1.1b: {host: [ts, ...]}


def _log(kind, tool, action, reason, args=None):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": datetime.now().isoformat(timespec="seconds"),
               "kind": kind, "tool": tool, "action": action, "reason": reason}
        if args:
            rec["args"] = {k: str(args[k])[:200] for k in ("path", "url", "host") if k in args}
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + chr(10))
    except Exception as _e:
        _silent("enf_pass", _e)


def _load_manifest():
    try:
        st = MANIFEST.stat()
    except Exception as _e:
        _silent("enf_return_none", _e)
        return None
    if _CACHE["mtime"] == st.st_mtime and _CACHE["data"] is not None:
        return _CACHE["data"]
    try:
        d = json.loads(MANIFEST.read_text(encoding="utf-8"))
        _CACHE["mtime"] = st.st_mtime
        _CACHE["data"] = d
        return d
    except Exception as _e:
        _silent("enf_return_none", _e)
        return None


def _handler_fs_read(conf, args):
    raw = args.get("path")
    if raw is None:
        return (False, "no path arg")
    try:
        rp = Path(str(raw)).resolve()
    except Exception as e:
        return (False, "resolve fail: " + str(e)[:80])
    try:
        rel = str(rp.relative_to(ROOT.resolve()))
    except ValueError:
        return (False, "outside ai-hub root")
    for pat in conf.get("denied_patterns") or []:
        try:
            if re.search(pat, rel):
                return (False, "denied by pattern " + pat)
        except re.error as _e:
            _silent("enf_re", _e)
    max_b = conf.get("max_bytes")
    if max_b and rp.exists():
        try:
            if rp.stat().st_size > max_b:
                return (False, "file too large")
        except Exception as _e:
            _silent("enf_inner_pass", _e)
    return (True, "inside root, no deny match")


def _handler_http_get(conf, args):
    raw = args.get("url")
    if raw is None:
        return (False, "no url arg")
    u = str(raw)
    max_len = conf.get("max_url_len", 2048)
    if len(u) > max_len:
        return (False, "url too long: " + str(len(u)))
    try:
        pr = urlparse(u)
    except Exception as e:
        return (False, "urlparse fail: " + str(e)[:80])
    scheme = (pr.scheme or "").lower()
    allowed_s = conf.get("allowed_schemes") or ["http", "https"]
    if scheme not in allowed_s:
        return (False, "scheme not allowed: " + scheme)
    host = (pr.hostname or "").lower()
    if not host:
        return (False, "no host")
    allowed_h = conf.get("allowed_hosts")
    if allowed_h and host not in allowed_h:
        return (False, "host not in allowlist: " + host)
    denied_d = conf.get("denied_domains") or []
    if host in denied_d:
        return (False, "denied domain: " + host)
    denied_p = conf.get("denied_prefixes") or []
    for dp in denied_p:
        if host.startswith(dp):
            return (False, "denied prefix: " + dp)
    try:
        ip = socket.gethostbyname(host)
    except Exception:
        ip = ""
    if ip:
        for dp in denied_p:
            if ip.startswith(dp):
                return (False, "ip denied: " + ip)
    mpm = conf.get("max_per_minute")
    if mpm:
        now = time.time()
        bucket = _RATE_LIMIT.setdefault(host, [])
        bucket[:] = [x for x in bucket if now - x < 60]
        if len(bucket) >= mpm:
            return (False, "rate limit: " + host)
        bucket.append(now)
    return (True, "ok")


def _handler_llm_call(conf, args):
    raw = args.get("url")
    if raw is None:
        return (False, "no url arg")
    host = ""
    try:
        from urllib.parse import urlparse
        host = (urlparse(str(raw)).hostname or "").lower()
    except Exception as e:
        return (False, "urlparse fail: " + str(e)[:80])
    if not host:
        return (False, "no host")
    allowed_h = conf.get("allowed_hosts")
    if allowed_h and host not in allowed_h:
        return (False, "host not in allowlist: " + host)
    pc = args.get("prompt_chars")
    max_pc = conf.get("max_prompt_chars")
    if max_pc and pc is not None:
        try:
            if int(pc) > int(max_pc):
                return (False, "prompt too large: " + str(pc) + " > " + str(max_pc))
        except Exception as _e:
            _silent("enf_inner_pass", _e)
    mpm = conf.get("max_per_minute")
    if mpm:
        now = time.time()
        bucket = _RATE_LIMIT.setdefault(host, [])
        bucket[:] = [x for x in bucket if now - x < 60]
        if len(bucket) >= mpm:
            return (False, "rate limit: " + host)
        bucket.append(now)
    return (True, "ok")


_KIND_HANDLERS = {"fs_read": _handler_fs_read, "http_get": _handler_http_get, "llm_call": _handler_llm_call}


def check(tool, action, args=None):
    args = args or {}
    m = _load_manifest()
    if m is None:
        _log("fail-open", tool, action, "manifest unavailable")
        return {"allow": True, "reason": "manifest unavailable", "kind": "fail-open"}
    conf = (m.get("tools") or {}).get(tool)
    if conf is None:
        _log("deny", tool, action, "no manifest entry")
        return {"allow": False, "reason": "no manifest entry", "kind": "deny"}
    declared = conf.get("kind")
    if declared != action:
        _log("deny", tool, action, "kind mismatch: " + str(declared))
        return {"allow": False, "reason": "kind mismatch: " + str(declared), "kind": "deny"}
    handler = _KIND_HANDLERS.get(declared)
    if handler is None:
        _log("deny", tool, action, "no handler for kind")
        return {"allow": False, "reason": "no handler for kind " + str(declared), "kind": "deny"}
    ok, reason = handler(conf, args)
    enforce = conf.get("enforce", True)
    if ok:
        return {"allow": True, "reason": reason, "kind": "allow"}
    if not enforce:
        _log("would-deny", tool, action, reason, args)
        return {"allow": True, "reason": "would-deny: " + reason, "kind": "would-deny"}
    _log("deny", tool, action, reason, args)
    return {"allow": False, "reason": reason, "kind": "deny"}


def require(tool, action, args=None):
    r = check(tool, action, args)
    if not r["allow"]:
        raise PermissionError("[" + tool + "/" + action + "] " + r["reason"])
    return r


def _selftest():
    cases = [
        ("read_text", "fs_read", {"path": "README.md"}, True),
        ("read_text", "fs_read", {"path": "self/evolution.md"}, True),
        ("read_text", "fs_read", {"path": "/etc/passwd"}, False),
        ("read_text", "fs_read", {"path": ".secrets/api.txt"}, False),
        ("read_text", "fs_read", {"path": ".ssh/id_rsa"}, False),
        ("read_text", "fs_read", {"path": ".git/config"}, False),
        ("read_text", "fs_read", {"path": ".env"}, False),
        ("read_text", "fs_read", {"path": ".env.local"}, False),
        ("read_text", "http_get", {"path": "README.md"}, False),
        ("nonexistent_tool", "fs_read", {"path": "README.md"}, False),
        ("read_text", "fs_read", {}, False),
        ("fetch_url", "http_get", {"url": "https://example.com/"}, True),
        ("fetch_url", "http_get", {"url": "http://127.0.0.1:8080/"}, False),
        ("fetch_url", "http_get", {"url": "http://10.0.0.1/"}, False),
        ("fetch_url", "http_get", {"url": "file:///etc/passwd"}, False),
        ("tavily_search", "http_get", {"url": "https://api.tavily.com/search"}, True),
        ("tavily_search", "http_get", {"url": "https://evil.com/"}, True),
        # selftest-http-added
        ("ask_gemini", "llm_call", {"url": "https://generativelanguage.googleapis.com", "prompt_chars": 1000}, True),
        ("ask_gemini", "llm_call", {"url": "https://evil.com", "prompt_chars": 1000}, False),
        ("ask_groq", "llm_call", {"url": "https://api.groq.com", "prompt_chars": 10000}, False),
        ("ask_groq", "llm_call", {"url": "https://api.groq.com", "prompt_chars": 3000}, True),
        ("ask_openrouter", "llm_call", {"url": "https://openrouter.ai", "prompt_chars": 5000}, True),
        ("ask_openrouter", "llm_call", {"url": "https://evil.com", "prompt_chars": 5000}, False),
        # selftest-llm-added
    ]
    passed = 0
    for tool, action, args, expect in cases:
        r = check(tool, action, args)
        ok = (r["allow"] == expect)
        if ok:
            passed += 1
        flag = "PASS" if ok else "FAIL"
        print(flag + " " + tool + "/" + action + " " + str(args) + " exp=" + str(expect) + " got=" + str(r["allow"]))
    print("---")
    print("total=" + str(len(cases)) + " passed=" + str(passed))
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    if "--test" in sys.argv:
        sys.exit(_selftest())
    print("usage: python3 security/enforcer.py --test")
    sys.exit(2)
