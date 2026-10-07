#!/usr/bin/env python3
# scripts/rollback_core.py (s118) -- Safety Layer 14 v1: restore from external backup.
#
# Brother of backup_core.py. Dry by default. Real write requires --confirm.
# Always snapshots current state to archive/pre_rollback/ before write.
#
# Scopes:
#   core      -- 10 CORE files (default)
#   manifest  -- strategy/_features.json only
#   strategy  -- strategy/* except _features.json
#   security  -- security/*.py (keys/ excluded -- machine-dependent)
#   all       -- every file in the backup manifest
#
# Not CORE. Not sensitive.

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKUP_DIR = ROOT / "archive" / "external_backup"
PRE_ROLLBACK_DIR = ROOT / "archive" / "pre_rollback"
HEALER_JOURNAL = ROOT / "self" / "healers" / "rollback.jsonl"
AUTONOMY = ROOT / "self" / "autonomy.jsonl"
MANIFEST_NAME = "_manifest.json"
MAX_AGE_DAYS = 30

CORE_FILES = [
    "orchestrator.py",
    "security/signing.py",
    "self_apply.py",
    "session_verify.py",
    "catchup.py",
    "limits.py",
    "security/enforcer.py",
    "security/audit.py",
    "strategy/00_rules.md",
    "strategy/_features.json",
]

SCOPES = ["core", "manifest", "strategy", "security", "all"]


def _ts():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _log(msg):
    print("[rollback_core] " + str(msg))


def _sha256(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _session():
    try:
        import session_meta as _sm
        return _sm.current()
    except Exception:
        return "unknown"


def _get_backup_dir(date):
    return BACKUP_DIR / date


def _load_manifest(target_dir):
    mf = target_dir / MANIFEST_NAME
    if not mf.exists():
        raise SystemExit("[rollback_core] ERR: no _manifest.json in " + str(target_dir))
    return json.loads(mf.read_text(encoding="utf-8"))


def _filter_files(files, scope):
    if scope == "all":
        return [f["rel"] for f in files]
    if scope == "core":
        cset = set(CORE_FILES)
        return [f["rel"] for f in files if f["rel"] in cset]
    if scope == "manifest":
        return [f["rel"] for f in files if f["rel"] == "strategy/_features.json"]
    if scope == "strategy":
        return [f["rel"] for f in files
                if f["rel"].startswith("strategy/")
                and f["rel"] != "strategy/_features.json"]
    if scope == "security":
        return [f["rel"] for f in files
                if f["rel"].startswith("security/")
                and not f["rel"].startswith("security/keys/")]
    raise SystemExit("unknown scope: " + scope)


def _age_days(target_dir):
    try:
        dt = datetime.strptime(target_dir.name, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
    except Exception:
        return None


def cmd_list(args):
    if not BACKUP_DIR.exists():
        _log("no backup dir: " + str(BACKUP_DIR))
        return 0
    copies = sorted([d for d in BACKUP_DIR.iterdir() if d.is_dir()],
                    key=lambda d: d.name, reverse=True)
    _log("available backups: " + str(len(copies)))
    for d in copies[:10]:
        mf = d / MANIFEST_NAME
        n = "?"
        if mf.exists():
            try:
                m = json.loads(mf.read_text())
                n = len(m.get("files", []))
            except Exception:
                pass
        _log("  " + d.name + "  files=" + str(n))
    return 0


def cmd_list_scopes(args):
    _log("scopes: " + ", ".join(SCOPES))
    _log("core files (10):")
    for r in CORE_FILES:
        _log("  " + r)
    return 0


def _hitl_check(target):
    """Return (allowed, rc, reason). Calls hitl.py --check.
    rc=0 -> ALLOW. rc=10 -> DEFERRED. Other rc -> treat as ERROR (block)."""
    import subprocess as _sp
    try:
        payload = '{"kind":"file_write","target":"' + target + '"}'
        r = _sp.run([sys.executable, str(ROOT / "hitl.py"), "--check", payload],
                    capture_output=True, text=True, timeout=30, cwd=str(ROOT))
        rc = r.returncode
        out = (r.stdout or "").strip().splitlines()
        first = out[0] if out else ""
        if rc == 0:
            return (True, rc, first)
        if rc == 10:
            return (False, rc, first)
        return (False, rc, "hitl rc=" + str(rc) + ": " + first[:120])
    except Exception as e:
        return (False, -1, "hitl call failed: " + str(e)[:120])


def cmd_drill(args):
    """Restore one file to /tmp/s118_drill_<ts>/ and verify sha256. Read-only for project."""
    import tempfile, shutil, subprocess
    date = args.date
    target_dir = _get_backup_dir(date)
    if not target_dir.exists():
        _log("ERR: no backup for " + date)
        return 2
    manifest = _load_manifest(target_dir)
    files = manifest.get("files", [])
    if not files:
        _log("ERR: empty manifest")
        return 2
    # try smallest file for speed
    files_sorted = sorted(files, key=lambda f: f.get("size", 0))
    rec = files_sorted[0]
    rel = rec["rel"]
    src = target_dir / rel
    if not src.exists():
        _log("ERR: file missing in backup: " + rel)
        return 2
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    drill_dir = Path(tempfile.gettempdir()) / ("s118_drill_" + ts)
    drill_dir.mkdir(parents=True, exist_ok=True)
    dst = drill_dir / Path(rel).name
    shutil.copy2(src, dst)
    h_expected = rec.get("sha256")
    h_actual = _sha256(dst)
    ok = (h_expected == h_actual)
    _log("drill: file=" + rel + " to=" + str(drill_dir))
    _log("drill: sha256 expected=" + str(h_expected)[:16] + " actual=" + str(h_actual)[:16]
         + " match=" + str(ok))
    # write marker for staleness detector
    marker = ROOT / "self" / "healers" / ".last_drill"
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(_ts() + " file=" + rel + " ok=" + str(ok), encoding="utf-8")
    except Exception:
        pass
    try:
        with AUTONOMY.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": _ts(), "session": _session(),
                "action": "rollback_drill",
                "note": "file=" + rel + " ok=" + str(ok),
                "effect": 1 if ok else 0,
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # cleanup
    try:
        shutil.rmtree(drill_dir)
    except Exception:
        pass
    return 0 if ok else 1


def cmd_run(args, dry):
    date = args.date
    scope = args.scope
    target_dir = _get_backup_dir(date)
    if not target_dir.exists():
        _log("ERR: no backup for " + date)
        return 2

    age = _age_days(target_dir)
    if age is not None and age > MAX_AGE_DAYS and not args.force:
        _log("ERR: backup older than " + str(MAX_AGE_DAYS) + " days (age="
             + str(round(age, 1)) + "); use --force")
        return 2

    manifest = _load_manifest(target_dir)
    files = manifest.get("files", [])
    rels = _filter_files(files, scope)
    if not rels:
        _log("nothing to restore (scope=" + scope + ")")
        return 2

    _log("date=" + date + " scope=" + scope
         + " mode=" + ("DRY-RUN" if dry else "APPLY"))
    _log("files to restore: " + str(len(rels)))

    bad = []
    for rel in rels:
        src = target_dir / rel
        if not src.exists():
            bad.append(rel + " (missing in backup)")
            continue
        rec = next((f for f in files if f["rel"] == rel), None)
        if rec and _sha256(src) != rec["sha256"]:
            bad.append(rel + " (sha256 mismatch)")
    if bad:
        _log("ERR: backup integrity failed:")
        for b in bad[:10]:
            _log("  " + b)
        return 2
    _log("integrity: OK")

    if any(r == "strategy/_features.json" for r in rels):
        _log("WARN: strategy/_features.json is CORE (feature registry).")
        _log("WARN: restoring it will DROP features added after " + date + ".")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    snap = PRE_ROLLBACK_DIR / (ts + "_rollback_" + date + "_" + scope)
    if not dry:
        snap.mkdir(parents=True, exist_ok=True)
        for rel in rels:
            cur = ROOT / rel
            if cur.exists():
                dst = snap / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(cur, dst)
        _log("pre_rollback snapshot: " + str(snap.relative_to(ROOT)))
    else:
        _log("would snapshot current to: " + str(snap.relative_to(ROOT)))

    changed = []
    hitl_blocked = []
    for rel in rels:
        src = target_dir / rel
        dst = ROOT / rel
        old_h = _sha256(dst) if dst.exists() else None
        new_h = _sha256(src)
        if old_h == new_h:
            changed.append((rel, "unchanged"))
            continue
        changed.append((rel, "changed"))
        if not dry:
            # HITL check before mutation (Safety Layer 13)
            allowed, rc, reason = _hitl_check(rel)
            if not allowed:
                _log("HITL DEFERRED: " + rel + " rc=" + str(rc) + " (" + reason + ")")
                hitl_blocked.append({"rel": rel, "rc": rc, "reason": reason})
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    for rel, st in changed:
        _log("  " + st + ": " + rel)

    if hitl_blocked and not dry:
        _log("SUMMARY: " + str(len(hitl_blocked)) + " file(s) DEFERRED by HITL.")
        for b in hitl_blocked:
            _log("  deferred: " + b["rel"])
        _log("Human approval required. Run:")
        _log("  python3 hitl.py --report")
        _log("  python3 hitl.py --approve <id>")
        _log("Then re-run rollback with --confirm.")
        return 10

    if dry:
        _log("DRY-RUN complete; nothing written. Add --confirm to apply.")
        return 0

    _log("signing CORE...")
    try:
        r = subprocess.run([sys.executable, "scripts/sign_core.py", "--sign"],
                           capture_output=True, text=True, timeout=60)
        tail = ((r.stdout or "") + (r.stderr or ""))[-200:]
        _log("sign rc=" + str(r.returncode) + " " + tail.strip()[-160:])
    except Exception as e:
        _log("sign ERR: " + str(e)[:200])

    _log("verify state...")
    try:
        r = subprocess.run([sys.executable, "session_verify.py", "--in"],
                           capture_output=True, text=True, timeout=60)
        for l in (r.stdout or "").splitlines():
            if l.startswith("mode="):
                _log("verify: " + l)
                break
    except Exception as e:
        _log("verify ERR: " + str(e)[:200])

    try:
        HEALER_JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with HEALER_JOURNAL.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": _ts(), "session": _session(),
                "action": "rollback_core",
                "date": date, "scope": scope,
                "files": len(rels),
                "snapshot": str(snap.relative_to(ROOT)),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass

    try:
        with AUTONOMY.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": _ts(), "session": _session(),
                "action": "rollback_core_applied",
                "note": "date=" + date + " scope=" + scope
                        + " files=" + str(len(rels)),
                "effect": 1,
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass

    _log("done")
    return 0


def main():
    ap = argparse.ArgumentParser(prog="rollback_core.py")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--list-scopes", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--date", metavar="YYYY-MM-DD")
    ap.add_argument("--scope", default="core")
    ap.add_argument("--drill", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if args.list:
        return cmd_list(args)
    if args.list_scopes:
        return cmd_list_scopes(args)
    if args.drill:
        if not args.date:
            ap.error("--drill requires --date YYYY-MM-DD")
        return cmd_drill(args)

    if not args.date:
        ap.error("--date YYYY-MM-DD is required for --dry/--run")

    if args.run:
        if not args.confirm:
            _log("REFUSED: --run without --confirm. Running as dry-run.")
            return cmd_run(args, dry=True)
        return cmd_run(args, dry=False)
    if args.dry:
        return cmd_run(args, dry=True)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
