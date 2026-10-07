#!/usr/bin/env python3
# scripts/identity.py (s118) -- Safety Layer 1 v1: identity consistency checker.
#
# Reads strategy/identity.md (source of truth), compares with .secrets/.
# Read-only. Detects: orphan_key, stale_entry, key_changed.
#
# Not CORE. Not sensitive.

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IDENTITY_MD = ROOT / "strategy" / "identity.md"
SECRETS = ROOT / ".secrets"

EXCLUDE = {
    ".secrets/agent_ed25519.key",
    ".secrets/.DS_Store",
    ".secrets/proxy.txt",
    ".secrets/proxies_public.txt",
    ".secrets/proxies_trusted.txt",
}


def _sha16(p):
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    except Exception:
        return "?"


def _parse_identity():
    if not IDENTITY_MD.exists():
        return None, []
    text = IDENTITY_MD.read_text(encoding="utf-8")
    rows = []
    for line in text.splitlines():
        m = re.match(r"^\|\s*`([^`]+)`\s*\|\s*`([0-9a-f?]+)`\s*\|\s*(\d+)\s*\|", line)
        if m:
            rows.append({"file": m.group(1), "sha16": m.group(2),
                         "size": int(m.group(3))})
    return text, rows


def _scan_secrets():
    if not SECRETS.exists():
        return []
    out = []
    for p in sorted(SECRETS.rglob("*")):
        if not p.is_file():
            continue
        if p.name.startswith("."):
            continue
        rel = str(p.resolve().relative_to(ROOT))
        if rel in EXCLUDE:
            continue
        out.append({"file": rel, "sha16": _sha16(p),
                    "size": p.stat().st_size})
    return out


def cmd_show(args):
    text, rows = _parse_identity()
    if text is None:
        print("[identity] ERR: no strategy/identity.md")
        return 2
    man = json.loads((ROOT / "security" / "_core_manifest.json").read_text())
    print("[identity] agent_id: " + man.get("pubkey_fingerprint", "?"))
    print("[identity] created:  " + man.get("created", "?"))
    print("[identity] catalogued keys: " + str(len(rows)))
    return 0


def cmd_verify(args):
    text, rows = _parse_identity()
    if text is None:
        print("[identity] ERR: no identity.md")
        return 2
    catalogued = {r["file"]: r for r in rows}
    actual = {r["file"]: r for r in _scan_secrets()}

    orphans = [f for f in actual if f not in catalogued]
    stales = [f for f in catalogued if f not in actual]
    changed = []
    for f, a in actual.items():
        c = catalogued.get(f)
        if c and c["sha16"] != a["sha16"]:
            changed.append({"file": f, "old": c["sha16"], "new": a["sha16"]})

    n_issues = len(orphans) + len(stales) + len(changed)
    if args.json:
        print(json.dumps({
            "catalogued": len(catalogued),
            "actual": len(actual),
            "orphan_key": orphans,
            "stale_entry": stales,
            "key_changed": changed,
            "issues": n_issues,
        }, ensure_ascii=False, indent=2))
    else:
        print("[identity] catalogued=" + str(len(catalogued))
              + " actual=" + str(len(actual)) + " issues=" + str(n_issues))
        if orphans:
            print("[identity] orphan_key:")
            for f in orphans:
                print("  " + f)
        if stales:
            print("[identity] stale_entry:")
            for f in stales:
                print("  " + f)
        if changed:
            print("[identity] key_changed:")
            for c in changed:
                print("  " + c["file"] + " " + c["old"] + " -> " + c["new"])
        if n_issues == 0:
            print("[identity] OK: identity.md matches .secrets/")
    return 0 if n_issues == 0 else 1


def main():
    ap = argparse.ArgumentParser(prog="identity.py")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if args.show:
        return cmd_show(args)
    if args.verify:
        return cmd_verify(args)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
