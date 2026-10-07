#!/usr/bin/env python3
# audit_watch.py (s118) -- Safety Layer 11 v1 healer: Tamper-Evident Logging.
#
# Two checks:
#   1. Chain-verify hash-chained logs (strategy/_apply_log.jsonl)
#      via security/audit.verify_chain.
#   2. Prefix-fingerprint append-only logs (errors.jsonl, autonomy.jsonl,
#      research_log.jsonl, _security_log.jsonl, self/healers/*.jsonl).
#      sha256(first min(64KB, size) bytes). If prefix changes -> tamper.
#
# Snapshot in .cache/system/log_fingerprints.json.
# Commands: --snapshot (baseline), --report, --run (report + autonomy on fail).
#
# Rights: record_finding, add_repair_task.
# Cannot: mutate_core, delete_file, set_cooldown, touch_secrets_dir.
#
# Journal: self/healers/audit_watch.jsonl
# Medcard: self/healers/audit_watch.md
# Not CORE. Not sensitive.

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AUTONOMY = ROOT / "self" / "autonomy.jsonl"
HEALER_JOURNAL = ROOT / "self" / "healers" / "audit_watch.jsonl"
SNAPSHOT = ROOT / ".cache" / "system" / "log_fingerprints.json"
PREFIX_BYTES = 64 * 1024

CHAINED = [
    "strategy/_apply_log.jsonl",
]

FINGERPRINTED = [
    ".cache/system/errors.jsonl",
    "self/autonomy.jsonl",
    "self/research_log.jsonl",
    "strategy/_security_log.jsonl",
]


def _ts():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _session():
    try:
        import session_meta as _sm
        return _sm.current()
    except Exception:
        return "unknown"


def _healer_journals():
    d = ROOT / "self" / "healers"
    if not d.exists():
        return []
    return [str(p.relative_to(ROOT)) for p in sorted(d.glob("*.jsonl"))]


def _fingerprint(rel, fixed_bytes=None):
    """Returns fingerprint. If fixed_bytes given, sha is computed from data[:fixed_bytes],
    so appends (which grow the file) do not shift the fingerprint."""
    p = ROOT / rel
    if not p.exists():
        return {"exists": False, "sha16": None, "size": 0}
    try:
        size = p.stat().st_size
        read_n = PREFIX_BYTES
        if isinstance(fixed_bytes, int) and fixed_bytes > 0:
            read_n = min(PREFIX_BYTES, fixed_bytes)
        with p.open("rb") as f:
            head = f.read(read_n)
        h = hashlib.sha256(head).hexdigest()[:16]
        return {"exists": True, "sha16": h, "size": size}
    except Exception as e:
        return {"exists": True, "error": str(e)[:120], "sha16": None, "size": 0}


def _snapshot():
    d = {"ts": _ts(), "chained": {}, "fingerprints": {}}
    try:
        from security.audit import verify_chain
        for rel in CHAINED:
            p = ROOT / rel
            if not p.exists():
                continue
            r = verify_chain(str(p))
            d["chained"][rel] = r
    except Exception as e:
        d["chained_error"] = str(e)[:200]
    targets = FINGERPRINTED + _healer_journals()
    for rel in targets:
        d["fingerprints"][rel] = _fingerprint(rel)
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    return d


def _load_snapshot():
    if not SNAPSHOT.exists():
        return None
    try:
        return json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    except Exception:
        return None


def _check():
    snap = _load_snapshot()
    if snap is None:
        return {"status": "no_snapshot", "chained_bad": [], "fp_bad": []}
    chained_bad = []
    for rel, prev in (snap.get("chained") or {}).items():
        p = ROOT / rel
        if not p.exists():
            chained_bad.append({"file": rel, "reason": "missing"})
            continue
        try:
            from security.audit import verify_chain
            r = verify_chain(str(p))
            if not r.get("valid"):
                chained_bad.append({"file": rel, "reason": r.get("reason"),
                                    "broken_at": r.get("broken_at")})
        except Exception as e:
            chained_bad.append({"file": rel, "reason": str(e)[:120]})
    fp_bad = []
    for rel, prev in (snap.get("fingerprints") or {}).items():
        # Compare prefix of fixed length = size at snapshot time (or less if snapshot was tiny).
        # This way an append-only grow does NOT change the fingerprint.
        prev_size = prev.get("size") or 0
        cur = _fingerprint(rel, fixed_bytes=prev_size)
        if not prev.get("exists") and not cur.get("exists"):
            continue
        if prev.get("exists") and not cur.get("exists"):
            fp_bad.append({"file": rel, "reason": "vanished"})
            continue
        if prev.get("exists") and cur.get("exists"):
            # size shrink -> реально проблема (усечение).
            if prev_size and cur.get("size", 0) < prev_size:
                fp_bad.append({
                    "file": rel, "reason": "shrunk",
                    "old_size": prev_size, "new_size": cur.get("size"),
                })
                continue
            if prev.get("sha16") != cur.get("sha16"):
                fp_bad.append({
                    "file": rel,
                    "reason": "prefix_changed",
                    "old": prev.get("sha16"),
                    "new": cur.get("sha16"),
                })
    status = "ok" if not (chained_bad or fp_bad) else "tampered"
    return {"status": status, "chained_bad": chained_bad, "fp_bad": fp_bad}


def run(actuate=False, quiet=False, snapshot=False):
    if snapshot:
        d = _snapshot()
        if not quiet:
            print("audit_watch: snapshot saved (chained="
                  + str(len(d.get("chained", {}))) + " fp="
                  + str(len(d.get("fingerprints", {}))) + ")")
        return 0
    res = _check()
    if not quiet:
        print("audit_watch: status=" + res["status"]
              + " chained_bad=" + str(len(res["chained_bad"]))
              + " fp_bad=" + str(len(res["fp_bad"])))
        for b in res["chained_bad"][:3]:
            print("  [CHAIN] " + b["file"] + ": " + str(b.get("reason")))
        for b in res["fp_bad"][:3]:
            print("  [FP] " + b["file"] + ": " + str(b.get("reason")))
    try:
        HEALER_JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with HEALER_JOURNAL.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": _ts(), "session": _session(), "healer": "audit_watch",
                "diagnosis": res["status"],
                "action": "report",
                "effect": 2 if res["status"] == "tampered" else 0,
                "outcome": res["status"],
                "note": "chained_bad=" + str(len(res["chained_bad"]))
                        + " fp_bad=" + str(len(res["fp_bad"])),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass
    if actuate and res["status"] == "tampered":
        try:
            with AUTONOMY.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": _ts(), "session": _session(),
                    "action": "audit_watch_tamper",
                    "note": "chained_bad=" + str(len(res["chained_bad"]))
                            + " fp_bad=" + str(len(res["fp_bad"])),
                    "effect": 2,
                }, ensure_ascii=False) + "\n")
        except Exception:
            pass
    return 0 if res["status"] in ("ok", "no_snapshot") else 1


def main():
    ap = argparse.ArgumentParser(prog="audit_watch.py")
    ap.add_argument("--snapshot", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    if args.snapshot:
        return run(snapshot=True, quiet=args.quiet)
    return run(actuate=args.run, quiet=args.quiet)


if __name__ == "__main__":
    sys.exit(main())
