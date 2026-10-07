#!/usr/bin/env python3
# egress_audit.py (s118) -- Safety Layer 10 v1 healer: Network Egress Controls.
#
# Detector: builds a set of observed HTTP(S) hosts from logs, compares with
# the allow-list derived from:
#   - security/tool_manifest.json (allowed_hosts of every tool)
#   - .secrets/proxies_*.txt (outbound relays)
#   - service allowlist (apple.com, icloud.com, localhost)
#
# Actuator (--run): autonomy_finding for unknown hosts. Cooldown 6h.
#
# Rights: record_finding, add_repair_task.
# Cannot: mutate_core, delete_file, set_cooldown, block_traffic.
#
# Journal: self/healers/egress_audit.jsonl
# Medcard: self/healers/egress_audit.md
# Not CORE. Not sensitive.

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AUTONOMY = ROOT / "self" / "autonomy.jsonl"
HEALER_JOURNAL = ROOT / "self" / "healers" / "egress_audit.jsonl"
AUTOTRIGGER_MARKER = ROOT / "self" / "healers" / ".egress_audit_trigger"
AUTOTRIGGER_COOLDOWN_H = 6
PENDING_FILE = ROOT / 'self' / 'healers' / 'egress_pending.jsonl'
ALLOW_FILE = ROOT / 'strategy' / 'egress_allow.json'
DENY_FILE = ROOT / 'strategy' / 'egress_deny.json'
TLDS = r"(?:com|io|ai|org|net|co|cn|uk|dev|ru|me|app|xyz|info|co\.uk|com\.br)"
HOST_RE = re.compile(
    r"https?://([A-Za-z0-9][A-Za-z0-9\-]*(?:\.[A-Za-z0-9\-]+)*\." + TLDS + r")\b"
)

LOG_DIR = Path("/tmp/ai-hub-logs")
EXTRA_SOURCES = [
    ROOT / ".cache" / "system" / "errors.jsonl",
]

SERVICE_ALLOW = {
    "apple.com", "icloud.com", "localhost", "127.0.0.1",
    "updates.cdn-apple.com", "swscan.apple.com", "swcdn.apple.com",
    "platform.openai.com", "api.openai.com",
    "api.anthropic.com", "api.mistral.ai", "api.cerebras.ai",
    "api.llm7.io", "api.cloudflare.com", "api.cohere.com",
    "api-inference.huggingface.co", "huggingface.co",
    "api.github.com", "github.com", "api.tavily.com",
    "docs.n8n.io", "api.odirouter.com",
}


def _ts():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _session():
    try:
        import session_meta as _sm
        return _sm.current()
    except Exception:
        return "unknown"


def _manifest_hosts():
    p = ROOT / "security" / "tool_manifest.json"
    out = set()
    if not p.exists():
        return out
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        for tname, tdef in (d.get("tools") or {}).items():
            for h in (tdef.get("allowed_hosts") or []):
                out.add(str(h).lower())
    except Exception:
        pass
    return out


def _proxy_hosts():
    out = set()
    for rel in [".secrets/proxies_public.txt", ".secrets/proxies_trusted.txt",
                ".secrets/proxy.txt"]:
        p = ROOT / rel
        if not p.exists():
            continue
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                m = HOST_RE.search(line)
                if m:
                    out.add(m.group(1).lower())
        except Exception:
            pass
    return out


def _observed_hosts():
    observed = {}
    files = []
    if LOG_DIR.exists():
        for p in sorted(LOG_DIR.glob("*.log")):
            files.append(p)
    for p in EXTRA_SOURCES:
        if p.exists():
            files.append(p)
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for m in HOST_RE.finditer(text):
            h = m.group(1).lower()
            observed.setdefault(h, {"count": 0, "files": set()})
            observed[h]["count"] += 1
            observed[h]["files"].add(p.name)
    return observed




def _load_allow_file():
    if not ALLOW_FILE.exists():
        return set()
    try:
        d = json.loads(ALLOW_FILE.read_text('utf-8'))
        return {str(h.get('host','')).lower() for h in (d.get('hosts') or []) if isinstance(h, dict)}
    except Exception:
        return set()


def _load_deny_file():
    if not DENY_FILE.exists():
        return set()
    try:
        d = json.loads(DENY_FILE.read_text('utf-8'))
        return {str(h).lower() for h in (d.get('hosts') or []) if h}
    except Exception:
        return set()


def _pending_open():
    out = {}
    if not PENDING_FILE.exists():
        return out
    try:
        for ln in PENDING_FILE.read_text('utf-8').splitlines():
            ln = ln.strip()
            if not ln: continue
            r = json.loads(ln)
            h = (r.get('host') or '').lower()
            if not h: continue
            if r.get('event') == 'open':
                out[h] = r
            elif r.get('event') == 'resolved':
                out.pop(h, None)
    except Exception:
        pass
    return out


def _append_pending(unknown):
    if not unknown: return 0
    have = set(_pending_open().keys())
    n = 0
    try:
        PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
        with PENDING_FILE.open('a', encoding='utf-8') as f:
            for u in unknown:
                h = u['host'].lower()
                if h in have: continue
                f.write(json.dumps({'ts':_ts(),'event':'open','host':h}) + chr(10))
                n += 1
    except Exception:
        pass
    return n


def _append_resolved(host, why):
    try:
        PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
        with PENDING_FILE.open('a', encoding='utf-8') as f:
            f.write(json.dumps({'ts':_ts(),'event':'resolved','host':host,'reason':why}) + chr(10))
    except Exception:
        pass


def _load_allow_json():
    if not ALLOW_FILE.exists(): return {'hosts': []}
    try:
        d = json.loads(ALLOW_FILE.read_text('utf-8'))
        if not isinstance(d, dict): return {'hosts': []}
        if not isinstance(d.get('hosts'), list): d['hosts'] = []
        return d
    except Exception:
        return {'hosts': []}


def _save_allow_json(d):
    ALLOW_FILE.parent.mkdir(parents=True, exist_ok=True)
    ALLOW_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), 'utf-8')


def _load_deny_json():
    if not DENY_FILE.exists(): return {'hosts': []}
    try:
        d = json.loads(DENY_FILE.read_text('utf-8'))
        if not isinstance(d, dict): return {'hosts': []}
        if not isinstance(d.get('hosts'), list): d['hosts'] = []
        return d
    except Exception:
        return {'hosts': []}


def _save_deny_json(d):
    DENY_FILE.parent.mkdir(parents=True, exist_ok=True)
    DENY_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), 'utf-8')


def cmd_pending():
    p = _pending_open()
    if not p:
        print('egress_audit pending: 0')
        return 0
    print('egress_audit pending: ' + str(len(p)))
    for h in sorted(p):
        print('  ' + h)
    return 0


def cmd_approve(host):
    host = (host or '').lower().strip()
    if not host: return 2
    if host not in _pending_open():
        print('not in pending: ' + host)
        return 2
    d = _load_allow_json()
    have = {str(x.get('host','')).lower() for x in d['hosts'] if isinstance(x, dict)}
    if host not in have:
        d['hosts'].append({'host': host, 'approved_at': _ts()})
        _save_allow_json(d)
    _append_resolved(host, 'approved')
    print('approved: ' + host)
    return 0


def cmd_deny(host):
    host = (host or '').lower().strip()
    if not host: return 2
    if host not in _pending_open():
        print('not in pending: ' + host)
        return 2
    d = _load_deny_json()
    if host not in {str(x).lower() for x in d['hosts']}:
        d['hosts'].append(host)
        _save_deny_json(d)
    _append_resolved(host, 'denied')
    print('denied: ' + host)
    return 0
def scan():
    allow = _manifest_hosts() | _proxy_hosts() | SERVICE_ALLOW | _load_allow_file()
    deny = _load_deny_file()
    observed = _observed_hosts()
    unknown = []
    for h, info in observed.items():
        if h in deny: continue
        if h in allow:
            continue
        # ignore obvious CDN / vendor hosts if wildcard-like suffix matches
        if any(h.endswith("." + a) for a in allow):
            continue
        # ignore truncated substrings: h is a prefix of some allowed host
        if len(h) >= 6 and any(a.startswith(h) for a in allow):
            continue
        unknown.append({
            "host": h, "count": info["count"],
            "files": sorted(info["files"]),
        })
    unknown.sort(key=lambda x: -x["count"])
    return {"allow": sorted(allow), "observed": len(observed), "unknown": unknown}


def _autotrigger(unknown):
    if not unknown:
        return None
    added = _append_pending(unknown)
    if AUTOTRIGGER_MARKER.exists():
        age = time.time() - AUTOTRIGGER_MARKER.stat().st_mtime
        if age < AUTOTRIGGER_COOLDOWN_H * 3600:
            return {"skipped": "cooldown", "age_h": round(age / 3600, 1)}
    try:
        AUTOTRIGGER_MARKER.parent.mkdir(parents=True, exist_ok=True)
        AUTOTRIGGER_MARKER.write_text(_ts(), encoding="utf-8")
    except Exception:
        pass
    try:
        with AUTONOMY.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": _ts(), "session": _session(),
                "action": "egress_audit_unknown_hosts",
                "note": "unknown=" + str(len(unknown))
                        + " top=" + ",".join(u["host"] for u in unknown[:5]),
                "effect": 1,
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return {"unknown": len(unknown)}


def run(actuate=False, quiet=False):
    res = scan()
    unknown = res["unknown"]
    if not quiet:
        print("egress_audit: allow=" + str(len(res["allow"]))
              + " observed=" + str(res["observed"])
              + " unknown=" + str(len(unknown)))
        for u in unknown[:5]:
            print("  " + u["host"] + " count=" + str(u["count"])
                  + " files=" + ",".join(u["files"]))
    try:
        HEALER_JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with HEALER_JOURNAL.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": _ts(), "session": _session(), "healer": "egress_audit",
                "diagnosis": "warn" if unknown else "ok",
                "action": "report",
                "effect": 1 if unknown else 0,
                "outcome": "unknown" if unknown else "ok",
                "note": "unknown=" + str(len(unknown)),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass
    if actuate and unknown:
        _autotrigger(unknown)
    return 0 if not unknown else 1


def main():
    ap = argparse.ArgumentParser(prog="egress_audit.py")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--pending", action="store_true")
    ap.add_argument("--approve", metavar="HOST")
    ap.add_argument("--deny", metavar="HOST")
    args = ap.parse_args()
    if args.pending: return cmd_pending()
    if args.approve: return cmd_approve(args.approve)
    if args.deny: return cmd_deny(args.deny)
    return run(actuate=args.run, quiet=args.quiet)


if __name__ == "__main__":
    sys.exit(main())
