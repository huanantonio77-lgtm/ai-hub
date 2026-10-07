#!/usr/bin/env python3
# backup_core.py (s117) -- Safety Layer 12c: external backup of CORE + keys.
#
# Copies:
#   - CORE_FILES (10) from security.signing
#   - security/keys/ (Ed25519 keypair)
#   - strategy/_closed.json
#   - strategy/safety_layers.md, strategy/healers.json
#   - self/BACKLOG.md, HANDOFF/current.md, self/current.md
#
# Where:
#   default -> archive/external_backup/YYYY-MM-DD/
#   --target icloud -> also into iCloud Drive folder
#
# Default dry-run. Real write only with --apply.
# Keeps last 7 local copies.
#
# CLI:
#   python3 scripts/backup_core.py --list
#   python3 scripts/backup_core.py                 # dry-run
#   python3 scripts/backup_core.py --run --apply   # write
#   python3 scripts/backup_core.py --verify
#   python3 scripts/backup_core.py --verify --date YYYY-MM-DD

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # s117-fix: чтобы видеть security/, orchestrator и т.д.
BACKUP_DIR = ROOT / "archive" / "external_backup"
ICLOUD_DIR = (Path.home() / "Library" / "Mobile Documents"
              / "com~apple~CloudDocs" / "ai-hub-backup")
KEEP = 7


def _ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log(msg):
    print("[" + _ts() + "] " + msg, flush=True)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _collect_targets():
    out = []
    try:
        from security.signing import CORE_FILES
        for rel in CORE_FILES:
            p = ROOT / rel
            if p.exists() and p.is_file():
                out.append((p, rel))
    except Exception as e:
        _log("WARN: cannot read CORE_FILES: " + str(e))
    keys_dir = ROOT / "security" / "keys"
    if keys_dir.exists():
        for p in sorted(keys_dir.rglob("*")):
            if p.is_file():
                out.append((p, str(p.relative_to(ROOT))))
    extras = [
        "strategy/_closed.json",
        "strategy/safety_layers.md",
        "strategy/healers.json",
        "self/BACKLOG.md",
        "HANDOFF/current.md",
        "self/current.md",
    ]
    for rel in extras:
        p = ROOT / rel
        if p.exists() and p.is_file():
            out.append((p, rel))
    return out


def cmd_list(args):
    if not BACKUP_DIR.exists():
        _log("no backup dir: " + str(BACKUP_DIR))
        return 0
    copies = sorted([d for d in BACKUP_DIR.iterdir() if d.is_dir()],
                    key=lambda d: d.name, reverse=True)
    _log("backup dir: " + str(BACKUP_DIR))
    _log("copies: " + str(len(copies)))
    for d in copies[:10]:
        n = sum(1 for _ in d.rglob("*") if _.is_file())
        size = sum(_.stat().st_size for _ in d.rglob("*") if _.is_file())
        _log("  " + d.name + "  files=" + str(n) + "  size=" + str(size) + "b")
    return 0


def _do_copy(targets, target_dir, apply_):
    manifest = {"ts": _ts(), "root": str(ROOT), "files": []}
    for src, rel in targets:
        h = _sha256(src)
        manifest["files"].append({
            "rel": rel, "sha256": h, "size": src.stat().st_size
        })
        if apply_:
            dst = target_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    return manifest


def _cleanup_old(apply_):
    if not BACKUP_DIR.exists():
        return []
    copies = sorted(
        [d for d in BACKUP_DIR.iterdir()
         if d.is_dir() and d.name[:4].isdigit()],
        key=lambda d: d.name, reverse=True)
    to_del = copies[KEEP:]
    out = []
    for d in to_del:
        out.append(d.name)
        if apply_:
            try:
                shutil.rmtree(d)
            except Exception as e:
                out[-1] = d.name + " (fail: " + str(e) + ")"
    return out


def cmd_run(args):
    mode = "APPLY" if args.apply else "DRY-RUN"
    _log("backup_core " + mode)
    targets = _collect_targets()
    _log("targets: " + str(len(targets)))
    if not targets:
        _log("ERR: empty targets")
        return 2
    date_key = datetime.now().strftime("%Y-%m-%d")
    target_dir = BACKUP_DIR / date_key
    if target_dir.exists() and not args.force:
        _log("today already backed up: " + str(target_dir))
        return 0
    manifest = _do_copy(targets, target_dir, args.apply)
    if args.apply:
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        _log("wrote: " + str(target_dir))
        if args.target == "icloud":
            if ICLOUD_DIR.parent.exists():
                ic_dir = ICLOUD_DIR / date_key
                ic_dir.mkdir(parents=True, exist_ok=True)
                for src, rel in targets:
                    dst = ic_dir / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                (ic_dir / "_manifest.json").write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
                _log("wrote icloud: " + str(ic_dir))
            else:
                _log("WARN: iCloud unavailable")
        deleted = _cleanup_old(args.apply)
        if deleted:
            _log("cleanup removed: " + ", ".join(deleted))
    else:
        _log("would write: " + str(target_dir))
        for src, rel in targets[:5]:
            _log("  " + rel)
        if len(targets) > 5:
            _log("  ... +" + str(len(targets) - 5) + " more")
    _log("done")
    return 0


def cmd_verify(args):
    if args.date:
        target_dir = BACKUP_DIR / args.date
    else:
        if not BACKUP_DIR.exists():
            _log("no backup dir")
            return 2
        copies = sorted(
            [d for d in BACKUP_DIR.iterdir()
             if d.is_dir() and d.name[:4].isdigit()],
            key=lambda d: d.name, reverse=True)
        if not copies:
            _log("no copies")
            return 2
        target_dir = copies[0]
    if not target_dir.exists():
        _log("ERR: no copy " + str(target_dir))
        return 2
    mf = target_dir / "_manifest.json"
    if not mf.exists():
        _log("ERR: no _manifest.json in " + str(target_dir))
        return 2
    manifest = json.loads(mf.read_text(encoding="utf-8"))
    n = 0
    ok = 0
    miss = []
    mismatch = []
    for rec in manifest.get("files", []):
        n += 1
        src = ROOT / rec["rel"]
        if not src.exists():
            miss.append(rec["rel"])
            continue
        if _sha256(src) == rec["sha256"]:
            ok += 1
        else:
            mismatch.append(rec["rel"])
    _log("verify " + str(target_dir))
    _log("  files=" + str(n) + " ok=" + str(ok)
         + " miss=" + str(len(miss)) + " mismatch=" + str(len(mismatch)))
    if miss:
        _log("  missing: " + ", ".join(miss[:5]))
    if mismatch:
        _log("  mismatch: " + ", ".join(mismatch[:5]))
    return 0 if (not miss and not mismatch) else 1


def main():
    ap = argparse.ArgumentParser(prog="backup_core.py")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--date", metavar="YYYY-MM-DD")
    ap.add_argument("--target", choices=["local", "icloud"], default="local")
    args = ap.parse_args()

    if args.list:
        return cmd_list(args)
    if args.verify:
        return cmd_verify(args)
    if args.run or args.apply:
        return cmd_run(args)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
