# frozen_auto_patch.py - s127-T3: frozen auto-patch (basket E).
# Owner-only mechanism. Allows agent to auto-apply whitelisted frozen actions
# with full protocol: backup -> apply -> sign_core --sign -> journal -> escalate.
#
# Whitelist: strategy/_frozen_auto_whitelist.json
# MVP kind: "sign_only" (protocol test, no content change).
# Future kinds: "json_field_set", "file_append" — when a real case appears.
#
# CLI:
#   python3 frozen_auto_patch.py --init-whitelist
#   python3 frozen_auto_patch.py --list
#   python3 frozen_auto_patch.py --selftest
#   python3 frozen_auto_patch.py --apply-rule <id> [--action <text>] [--dry-run]

from __future__ import annotations
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WHITELIST_PATH = ROOT / "strategy" / "_frozen_auto_whitelist.json"
JOURNAL_PATH = ROOT / "self" / "curator" / "JOURNAL.jsonl"
ESCALATIONS_PATH = ROOT / "self" / "curator" / "ESCALATIONS.jsonl"
APPLY_LOG_PATH = ROOT / "strategy" / "_apply_log.jsonl"
BACKUP_DIR = ROOT / "archive" / "backups"
SESSION = "s128"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_whitelist():
    if not WHITELIST_PATH.exists():
        return {"version": 1, "rules": []}
    try:
        return json.loads(WHITELIST_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "rules": []}


def matches(action, whitelist=None):
    """Return rule dict if action matches a whitelist entry, else None."""
    if whitelist is None:
        whitelist = load_whitelist()
    a = (action or "").lower()
    if not a:
        return None
    for rule in (whitelist.get("rules") or []):
        need = (rule.get("match") or {}).get("action_contains") or []
        if not need:
            continue
        if all((str(n).lower() in a) for n in need):
            return rule
    return None


def _backup(target):
    if not target or not target.exists():
        return None
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    bp = BACKUP_DIR / (target.name + ".bak-fap-" + SESSION + "-" + ts)
    bp.write_bytes(target.read_bytes())
    return bp


def _sign():
    try:
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "sign_core.py"), "--sign"],
            capture_output=True, text=True, timeout=30,
        )
        return r.returncode == 0
    except Exception:
        return False


def _append_jsonl(path, rec):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def apply_rule(rule, action, dry=False):
    """Execute one whitelisted rule. Returns result dict."""
    rid = str(rule.get("id") or "?")
    kind = str((rule.get("apply") or {}).get("kind") or "sign_only")
    target_rel = (rule.get("match") or {}).get("target")
    target = (ROOT / target_rel) if target_rel else None

    result = {
        "ok": True, "rule_id": rid, "kind": kind,
        "target": target_rel, "action": (action or "")[:120], "dry": dry,
    }

    if kind not in ("sign_only", "json_field_set"):
        return {"ok": False, "reason": "unsupported kind: " + kind, "rule_id": rid}

    if dry:
        result["note"] = "dry-run: no changes written"
        return result

    backup_path = _backup(target) if target else None
    if backup_path:
        result["backup"] = str(backup_path.relative_to(ROOT))

    # Apply kind
    if kind == "sign_only":
        pass
    elif kind == "json_field_set":
        try:
            d = json.loads(target.read_text(encoding="utf-8"))
            field = (rule.get("apply") or {}).get("field")
            value = (rule.get("apply") or {}).get("value")
            if not field:
                return {"ok": False, "reason": "no field", "rule_id": rid}
            d[field] = value
            target.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            return {"ok": False, "reason": "json_field_set: " + type(e).__name__ + ": " + str(e)[:120], "rule_id": rid}

    # Sign
    if not _sign():
        if backup_path and target:
            try:
                target.write_bytes(backup_path.read_bytes())
                result["rolled_back"] = True
            except Exception as e:
                result["rollback_err"] = type(e).__name__ + ": " + str(e)[:100]
        return {"ok": False, "reason": "sign failed", "rule_id": rid, "result": result}

    # Journal
    _append_jsonl(JOURNAL_PATH, {
        "ts": _now(), "session": SESSION, "action": "auto_patch_frozen",
        "rule_id": rid, "kind": kind, "target": target_rel,
        "backup": result.get("backup"), "sign_ok": True,
    })

    # Escalation
    _append_jsonl(ESCALATIONS_PATH, {
        "ts": _now(), "session": SESSION, "kind": "auto_patch_frozen",
        "rule_id": rid, "target": target_rel,
        "action": (action or "")[:200],
        "owner_action": "review if not expected",
    })

    # Apply log (existing pattern in project)
    _append_jsonl(APPLY_LOG_PATH, {
        "ts": _now(), "bucket": "E", "rule_id": rid,
        "target": target_rel, "sign_ok": True,
    })

    return result


def cmd_init_whitelist():
    if WHITELIST_PATH.exists():
        print("exists: " + str(WHITELIST_PATH.relative_to(ROOT)))
        return 0
    WHITELIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    WHITELIST_PATH.write_text(
        json.dumps({"version": 1, "rules": []}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("created: " + str(WHITELIST_PATH.relative_to(ROOT)))
    return 0


def cmd_list():
    w = load_whitelist()
    rules = w.get("rules") or []
    print("frozen_auto_patch whitelist: " + str(len(rules)) + " rule(s)")
    for r in rules:
        print("  " + str(r.get("id"))
              + "  kind=" + str((r.get("apply") or {}).get("kind"))
              + "  target=" + str((r.get("match") or {}).get("target")))
    return 0


def cmd_selftest():
    # 1) matches: both substrings required
    w = {"version": 1, "rules": [
        {"id": "t1", "match": {"action_contains": ["foo", "bar"]}, "apply": {"kind": "sign_only"}},
    ]}
    assert matches("do foo and bar thing", w) is not None
    assert matches("only foo", w) is None
    assert matches("", w) is None
    # 2) dry apply
    r = apply_rule(w["rules"][0], "do foo and bar thing", dry=True)
    assert r["ok"] is True, r
    assert r["rule_id"] == "t1", r
    assert r["dry"] is True, r
    # 3) unsupported kind
    bad = {"id": "bad", "match": {"action_contains": ["x"]}, "apply": {"kind": "danger"}}
    r2 = apply_rule(bad, "x", dry=True)
    assert r2["ok"] is False, r2
    print("frozen_auto_patch selftest: ok")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--init-whitelist", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--apply-rule", default="")
    ap.add_argument("--action", default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return cmd_selftest()
    if args.init_whitelist:
        return cmd_init_whitelist()
    if args.list:
        return cmd_list()
    if args.apply_rule:
        w = load_whitelist()
        rule = None
        for r in (w.get("rules") or []):
            if str(r.get("id")) == args.apply_rule:
                rule = r
                break
        if not rule:
            print("rule not found: " + args.apply_rule)
            return 1
        out = apply_rule(rule, args.action or "manual test", dry=args.dry_run)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out.get("ok") else 1

    print("frozen_auto_patch.py - --init-whitelist | --list | --selftest | --apply-rule <id> [--dry-run]")
    return 0


if __name__ == "__main__":
    sys.exit(main())