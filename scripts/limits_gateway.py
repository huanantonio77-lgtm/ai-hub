#!/usr/bin/env python3
# s177: Gateway-based quota enforcement.
# Apply SELF_PROPOSALS (Gateway-based quota):
#  - single entry point for API calls;
#  - check BEFORE call (enforcement);
#  - track AFTER call (usage);
#  - rolling window: rpm / rpd / rpw / rpm_month.
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIMITS_FILE = ROOT / "provider_limits.json"
USAGE_FILE = ROOT / ".cache" / "limits_usage.json"
PROPOSALS_FILE = ROOT / "self" / "curator" / "SELF_PROPOSALS.jsonl"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import limits as _limits


class QuotaExceeded(RuntimeError):
    def __init__(self, provider, reason, remaining=0):
        super().__init__("quota exceeded: " + provider + " (" + reason + ")")
        self.provider = provider
        self.reason = reason
        self.remaining = remaining


def _load_limits():
    try:
        return json.loads(LIMITS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_usage():
    # schema: {provider: {"events": [...], "last_429": float}}
    try:
        return json.loads(USAGE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _count_events(events, since_ts, statuses=("ok", "429", "error")):
    n = 0
    for e in events:
        if not isinstance(e, dict):
            continue
        if e.get("ts", 0) >= since_ts and e.get("status") in statuses:
            n += 1
    return n


def check(provider):
    # returns (allowed: bool, reason: str, remaining: int)
    # "unknown" limit => do NOT block, only count.
    now = time.time()
    lims = _load_limits()
    usage = _load_usage()
    cfg = lims.get(provider) or {}
    evs = (usage.get(provider) or {}).get("events", []) or []
    windows = (
        ("rpm",      60,        now - 60),
        ("rpd",      86400,     now - 86400),
        ("rpw",      604800,    now - 604800),
        ("rpm_month", 2592000,  now - 2592000),
    )
    for key, _span, since in windows:
        lim = cfg.get(key, "unknown")
        if lim == "unknown" or lim is None:
            continue
        try:
            lim_i = int(lim)
        except Exception:
            continue
        used = _count_events(evs, since)
        if used >= lim_i:
            return (False, key + ": " + str(used) + "/" + str(lim_i), 0)
    return (True, "ok", -1)


def track(provider, status, tokens_in=0, tokens_out=0):
    # passthrough to limits.record_call (single source of truth).
    try:
        _limits.record_call(provider, status,
                            tokens_in=int(tokens_in or 0),
                            tokens_out=int(tokens_out or 0))
    except Exception:
        pass


def call(provider, fn, *args, **kwargs):
    # enforce -> invoke -> track. raises QuotaExceeded BEFORE HTTP.
    allowed, reason, remaining = check(provider)
    if not allowed:
        track(provider, "429")
        raise QuotaExceeded(provider, reason, remaining)
    tin = kwargs.pop("_tokens_in", 0)
    tout = kwargs.pop("_tokens_out", 0)
    try:
        result = fn(*args, **kwargs)
        track(provider, "ok", tin, tout)
        return result
    except Exception:
        track(provider, "error")
        raise


def apply_proposal(idx, note="applied: limits_gateway (s177)"):
    # mark SELF_PROPOSALS.jsonl[idx] pending -> applied (in-place, atomic).
    try:
        lines = PROPOSALS_FILE.read_text(encoding="utf-8").splitlines()
    except Exception:
        return (False, "no proposals file")
    if idx < 0 or idx >= len(lines):
        return (False, "idx out of range: 0.." + str(len(lines) - 1))
    try:
        rec = json.loads(lines[idx])
    except Exception:
        return (False, "bad json at idx=" + str(idx))
    if rec.get("status") != "pending":
        return (False, "not pending: " + str(rec.get("status")))
    rec["status"] = "applied"
    rec["applied_ts"] = int(time.time())
    rec["applied_note"] = note
    lines[idx] = json.dumps(rec, ensure_ascii=False)
    tmp = PROPOSALS_FILE.with_suffix(".jsonl.tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(PROPOSALS_FILE)
    return (True, "applied idx=" + str(idx))


def set_status(idx, status, note=""):
    STATUS_MAP = {
        "apply": "applied",
        "reject": "rejected",
        "defer": "defer",
    }
    status = STATUS_MAP.get(status, status)
    # pending -> applied | rejected | deferred (atomic).
    try:
        lines = PROPOSALS_FILE.read_text(encoding="utf-8").splitlines()
    except Exception:
        return (False, "no proposals file")
    if idx < 0 or idx >= len(lines):
        return (False, "idx out of range: 0.." + str(len(lines) - 1))
    try:
        rec = json.loads(lines[idx])
    except Exception:
        return (False, "bad json at idx=" + str(idx))
    prev = rec.get("status")
    if prev == "applied" and status != "applied":
        return (False, "cannot change applied")
    rec["status"] = status
    rec["status_ts"] = int(time.time())
    rec["status_note"] = note
    lines[idx] = json.dumps(rec, ensure_ascii=False)
    tmp = PROPOSALS_FILE.with_suffix(".jsonl.tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(PROPOSALS_FILE)
    return (True, "idx=" + str(idx) + " " + str(prev) + " -> " + status)


def _main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: limits_gateway.py check PROVIDER")
        print("       limits_gateway.py apply IDX")
        print("       limits_gateway.py reject IDX [note]")
        return 0
    cmd = argv[0]
    if cmd == "check":
        if len(argv) < 2:
            print("usage: check PROVIDER"); return 2
        ok, reason, remaining = check(argv[1])
        print("provider=" + argv[1] + " allowed=" + str(ok)
              + " reason=" + reason + " remaining=" + str(remaining))
        return 0 if ok else 1
    if cmd == "apply":
        if len(argv) < 2:
            print("usage: apply IDX"); return 2
        ok, msg = set_status(int(argv[1]), "applied",
                             note="limits_gateway.py (s177)")
        print(msg); return 0 if ok else 1
    if cmd == "reject":
        if len(argv) < 2:
            print("usage: reject IDX [note]"); return 2
        note = " ".join(argv[2:]) or "rejected (s177)"
        ok, msg = set_status(int(argv[1]), "rejected", note=note)
        print(msg); return 0 if ok else 1
    print("unknown cmd: " + cmd); return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
