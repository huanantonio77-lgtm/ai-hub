#!/usr/bin/env python3
# secrets_audit.py (s118) -- Safety Layer 4 v1 healer: Secure Secrets Management.
#
# Detector: checks file permissions under .secrets/.
# Expected: 600 (owner read/write) for all key material.
# Actuator (--run): chmod 600 for 644/640/etc. Non-public exceptions skipped.
#
# Rights: record_finding, add_repair_task, chmod_secret.
# Cannot: mutate_core, delete_file, set_cooldown, touch_secrets_content, touch_secrets_dir.
#
# Journal: self/healers/secrets_audit.jsonl
# Medcard: self/healers/secrets_audit.md
# Not CORE. Not sensitive.

import argparse
import json
import os
import stat
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SECRETS = ROOT / ".secrets"
AUTONOMY = ROOT / "self" / "autonomy.jsonl"
HEALER_JOURNAL = ROOT / "self" / "healers" / "secrets_audit.jsonl"
AUTOTRIGGER_MARKER = ROOT / "self" / "healers" / ".secrets_audit_trigger"
AUTOTRIGGER_COOLDOWN_H = 1
EXPECTED_MODE = 0o600

# Non-key files: skip (transport / placeholders / OS meta)
EXCLUDE = {
    ".secrets/.DS_Store",
    ".secrets/proxy.txt",
    ".secrets/proxies_public.txt",
    ".secrets/proxies_trusted.txt",
    ".secrets/providers/nvidia.txt",
}

# s121: Safety Layer 4 v2 -- Rotation-pending.
ROTATION_POLICY = ROOT / "strategy" / "secrets_policy.json"
ROTATION_PENDING = ROOT / "self" / "healers" / "secrets_pending.jsonl"
ROTATION_DISMISS_LOG = ROOT / "self" / "healers" / "secrets_dismissed.jsonl"
ROTATION_DAYS_DEFAULT = 90
ROTATION_DISMISS_DAYS_DEFAULT = 30
ROTATION_EXCLUDE = {
    ".secrets/agent_ed25519.key",
}


def _ts():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _session():
    try:
        import session_meta as _sm
        return _sm.current()
    except Exception:
        return "unknown"


def _iter_secrets():
    if not SECRETS.exists():
        return
    for p in sorted(SECRETS.rglob("*")):
        if not p.is_file():
            continue
        rel = str(p.relative_to(ROOT))
        if rel in EXCLUDE:
            continue
        if p.name.startswith("."):
            continue
        yield p, rel


def scan():
    bad = []
    for p, rel in _iter_secrets():
        try:
            m = stat.S_IMODE(p.stat().st_mode)
        except Exception:
            continue
        if m != EXPECTED_MODE:
            bad.append({"file": rel, "mode": oct(m), "want": oct(EXPECTED_MODE)})
    return bad


def _autotrigger(bad):
    if not bad:
        return None
    if AUTOTRIGGER_MARKER.exists():
        age = time.time() - AUTOTRIGGER_MARKER.stat().st_mtime
        if age < AUTOTRIGGER_COOLDOWN_H * 3600:
            return {"skipped": "cooldown", "age_h": round(age / 3600, 1)}
    fixed = 0
    failed = []
    for b in bad:
        p = ROOT / b["file"]
        try:
            os.chmod(p, EXPECTED_MODE)
            m = stat.S_IMODE(p.stat().st_mode)
            if m == EXPECTED_MODE:
                fixed += 1
            else:
                failed.append(b["file"])
        except Exception:
            failed.append(b["file"])
    try:
        AUTOTRIGGER_MARKER.parent.mkdir(parents=True, exist_ok=True)
        AUTOTRIGGER_MARKER.write_text(_ts(), encoding="utf-8")
    except Exception:
        pass
    try:
        with HEALER_JOURNAL.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": _ts(), "session": _session(), "healer": "secrets_audit",
                "diagnosis": "crit", "action": "chmod_600",
                "effect": 1 if fixed else 0,
                "outcome": "fixed" if fixed else "failed",
                "note": "fixed=" + str(fixed) + " failed=" + str(len(failed)),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return {"fixed": fixed, "failed": failed}


def run(actuate=False, quiet=False):
    bad = scan()
    if not quiet:
        print("secrets_audit: total_bad=" + str(len(bad)))
        for b in bad[:8]:
            print("  " + b["file"] + " mode=" + b["mode"] + " want=" + b["want"])
    try:
        HEALER_JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with HEALER_JOURNAL.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": _ts(), "session": _session(), "healer": "secrets_audit",
                "diagnosis": "crit" if bad else "ok",
                "action": "report",
                "effect": 2 if bad else 0,
                "outcome": "bad" if bad else "ok",
                "note": "bad=" + str(len(bad)),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass
    if bad:
        try:
            with AUTONOMY.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": _ts(), "session": _session(),
                    "action": "secrets_audit_finding",
                    "note": "bad_perms=" + str(len(bad)),
                    "effect": 2,
                }, ensure_ascii=False) + "\n")
        except Exception:
            pass
    if actuate and bad:
        res = _autotrigger(bad)
        if res and not quiet:
            print("secrets_audit actuator: " + str(res))
    return 0 if not bad else 1

def _load_rotation_policy():
    days = ROTATION_DAYS_DEFAULT
    dis = ROTATION_DISMISS_DAYS_DEFAULT
    try:
        if ROTATION_POLICY.exists():
            d = json.loads(ROTATION_POLICY.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                v = d.get("rotation_days")
                if isinstance(v, int) and v > 0:
                    days = v
                v = d.get("dismiss_days")
                if isinstance(v, int) and v > 0:
                    dis = v
    except Exception:
        pass
    return days, dis


def _dismissals():
    out = {}
    try:
        if not ROTATION_DISMISS_LOG.exists():
            return out
        txt = ROTATION_DISMISS_LOG.read_text(encoding="utf-8")
        for line in txt.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            name = d.get("name")
            ts = d.get("ts")
            if not name or not ts:
                continue
            try:
                t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                continue
            prev = out.get(name)
            if prev is None or t > prev:
                out[name] = t
    except Exception:
        pass
    return out


def _rotation_scan():
    days, dis = _load_rotation_policy()
    dismissed = _dismissals()
    now = time.time()
    out = []
    for p, rel in _iter_secrets():
        if rel in ROTATION_EXCLUDE:
            continue
        try:
            age_days = int((now - p.stat().st_mtime) // 86400)
        except Exception:
            continue
        if age_days < days:
            continue
        t = dismissed.get(rel)
        if t is not None:
            d_age = (now - t.timestamp()) // 86400
            if d_age < dis:
                continue
        out.append({"file": rel, "age_days": age_days})
    return out


def _pending_open():
    out = {}
    try:
        if not ROTATION_PENDING.exists():
            return out
        txt = ROTATION_PENDING.read_text(encoding="utf-8")
        for line in txt.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            name = d.get("name")
            ev = d.get("event")
            if not name:
                continue
            if ev == "resolved":
                out.pop(name, None)
            elif ev == "opened":
                out[name] = d
    except Exception:
        pass
    return out


def _append_pending(name, age_days, event):
    try:
        ROTATION_PENDING.parent.mkdir(parents=True, exist_ok=True)
        with ROTATION_PENDING.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": _ts(),
                "session": _session(),
                "healer": "secrets_audit",
                "name": name,
                "age_days": age_days,
                "event": event,
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _write_action_journal(action, name, effect, note):
    try:
        HEALER_JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with HEALER_JOURNAL.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": _ts(), "session": _session(),
                "healer": "secrets_audit",
                "diagnosis": "rotation", "action": action,
                "name": name, "effect": effect,
                "outcome": "applied", "note": note,
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


def cmd_rotation_report():
    days, dis = _load_rotation_policy()
    stale = _rotation_scan()
    line = "secrets_audit rotation: policy_days=" + str(days)
    line += " dismiss_days=" + str(dis)
    print(line)
    if not stale:
        print("  (no secrets older than policy)")
    for s in stale:
        print("  " + s["file"] + " age_days=" + str(s["age_days"]))
    return 0


def cmd_rotation_pending():
    pend = _pending_open()
    if not pend:
        print("secrets_audit rotation-pending: 0")
        return 0
    print("secrets_audit rotation-pending: " + str(len(pend)))
    for name in sorted(pend.keys()):
        info = pend[name]
        print("  " + name + " age_days=" + str(info.get("age_days", "?")))
    return 0


def cmd_rotation_dismiss(name, reason=""):
    name = (name or "").strip()
    if not name:
        print("secrets_audit --rotation-dismiss: empty name")
        return 2
    if not name.startswith(".secrets/"):
        name = ".secrets/" + name
    try:
        ROTATION_DISMISS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with ROTATION_DISMISS_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": _ts(), "session": _session(),
                "name": name, "reason": reason or "no reason",
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass
    _append_pending(name, None, "resolved")
    _write_action_journal("rotation_dismiss", name, 2,
                          "reason=" + (reason or "none"))
    print("secrets_audit: dismissed " + name)
    return 0


def cmd_rotation_run(quiet=False):
    stale = _rotation_scan()
    pend = _pending_open()
    opened = 0
    for s in stale:
        name = s["file"]
        if name in pend:
            continue
        _append_pending(name, s["age_days"], "opened")
        opened += 1
    stale_names = {s["file"] for s in stale}
    resolved = 0
    for name in list(pend.keys()):
        if name not in stale_names:
            _append_pending(name, None, "resolved")
            resolved += 1
    if not quiet:
        line = "secrets_audit rotation-run: stale=" + str(len(stale))
        line += " opened=" + str(opened)
        line += " resolved=" + str(resolved)
        print(line)
    if opened:
        note = "opened=" + str(opened)
        _write_action_journal("rotation_open", "multiple", 2, note)
        try:
            with AUTONOMY.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": _ts(), "session": _session(),
                    "action": "secrets_rotation_pending",
                    "note": "stale=" + str(len(stale)) + " opened=" + str(opened),
                    "effect": 2,
                }, ensure_ascii=False) + "\n")
        except Exception:
            pass
    return 0



def main():
    ap = argparse.ArgumentParser(prog="secrets_audit.py")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--rotation-report", action="store_true")
    ap.add_argument("--rotation-pending", action="store_true")
    ap.add_argument("--rotation-run", action="store_true")
    ap.add_argument("--rotation-dismiss", default=None)
    ap.add_argument("--reason", default="")
    args = ap.parse_args()
    if args.rotation_report:
        return cmd_rotation_report()
    if args.rotation_pending:
        return cmd_rotation_pending()
    if args.rotation_run:
        return cmd_rotation_run(quiet=args.quiet)
    if args.rotation_dismiss:
        return cmd_rotation_dismiss(args.rotation_dismiss, args.reason)
    return run(actuate=args.run, quiet=args.quiet)


if __name__ == "__main__":
    sys.exit(main())
