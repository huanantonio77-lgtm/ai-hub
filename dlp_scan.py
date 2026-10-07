#!/usr/bin/env python3
# dlp_scan.py (s118) -- Safety Layer 9 v1: Data Leak Prevention scanner.
#
# Scans text/files for secrets, API keys, PEM blocks, emails.
# Read-only by default. --redact rewrites with [REDACTED:type] + .bak-dlp-* backup.
#
# Not CORE. Not sensitive. Safe to run against any text file.
#
# Patterns tuned to avoid false positives on docs:
#   - require long random-looking tails (>=20 chars for sk-, >=30 for AIza)
#   - generic KEY=value only if value >=16 chars
#   - emails are opt-in via --emails

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent

PATTERNS = [
    ("openai_legacy",  re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("openai_project", re.compile(r"\bsk-proj-[A-Za-z0-9_\-]{40,}\b")),
    ("anthropic",      re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{40,}\b")),
    ("google_api",     re.compile(r"\bAIza[A-Za-z0-9_\-]{30,}\b")),
    ("groq",           re.compile(r"\bgsk_[A-Za-z0-9]{40,}\b")),
    ("tavily",         re.compile(r"\btvly-[A-Za-z0-9]{20,}\b")),
    ("pem_private",    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----")),
    ("generic_secret", re.compile(
        r"(?i)\b(?:api[_-]?key|apikey|token|password|secret|passwd)\s*[:=]\s*"
        r"['\"]?([A-Za-z0-9_\-/+=]{16,})['\"]?")),
    ("secrets_path",   re.compile(r"\.secrets/[A-Za-z0-9_\-./]+")),
]

EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "archive", ".cache", ".browser", ".trash",
}


def _ts():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _scan_text(text, emails=False):
    hits = []
    for name, pat in PATTERNS:
        for m in pat.finditer(text):
            snippet = m.group(0)
            if len(snippet) > 80:
                snippet = snippet[:40] + "..." + snippet[-20:]
            hits.append({"kind": name, "match": snippet,
                         "start": m.start(), "end": m.end()})
    if emails:
        for m in EMAIL_PATTERN.finditer(text):
            hits.append({"kind": "email", "match": m.group(0),
                         "start": m.start(), "end": m.end()})
    return hits


def _redact_text(text, hits):
    if not hits:
        return text, 0
    # apply from end so positions stay valid
    hits = sorted(hits, key=lambda h: h["start"], reverse=True)
    out = text
    n = 0
    for h in hits:
        tag = "[REDACTED:" + h["kind"] + "]"
        out = out[:h["start"]] + tag + out[h["end"]:]
        n += 1
    return out, n


def _iter_files(root, emails=False):
    root = Path(root)
    if root.is_file():
        yield root
        return
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() not in (".log", ".txt", ".jsonl", ".json", ".md"):
            continue
        yield p


def cmd_scan(args):
    files = []
    if args.scan_file:
        files = [Path(args.scan_file)]
    elif args.scan_dir:
        files = list(_iter_files(args.scan_dir, emails=args.emails))
    elif args.scan_logs:
        log_dir = Path("/tmp/ai-hub-logs")
        if log_dir.exists():
            files = list(_iter_files(log_dir, emails=args.emails))
    else:
        files = [Path("self/autonomy.jsonl")]
        if Path("self/healers").exists():
            files += list(Path("self/healers").rglob("*.jsonl"))

    total_hits = 0
    per_kind = {}
    findings = []
    for f in files:
        if not f.exists():
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            findings.append({"file": str(f), "error": str(e)[:200]})
            continue
        hits = _scan_text(text, emails=args.emails)
        if not hits:
            continue
        total_hits += len(hits)
        for h in hits:
            per_kind[h["kind"]] = per_kind.get(h["kind"], 0) + 1
        findings.append({
            "file": str(f),
            "hits": [{"kind": h["kind"], "match": h["match"]} for h in hits[:20]],
            "count": len(hits),
        })

    if args.json:
        print(json.dumps({
            "ts": _ts(), "files": len(files),
            "total_hits": total_hits, "per_kind": per_kind,
            "findings": findings,
        }, ensure_ascii=False, indent=2))
    else:
        print("[dlp_scan] files=" + str(len(files)) + " hits=" + str(total_hits))
        if per_kind:
            print("[dlp_scan] per_kind: " + json.dumps(per_kind))
        for fnd in findings:
            if "error" in fnd:
                print("  ERR: " + fnd["file"] + " " + fnd["error"])
                continue
            print("  " + fnd["file"] + " count=" + str(fnd["count"]))
            for h in fnd["hits"][:5]:
                print("     " + h["kind"] + ": " + h["match"])
    return 0 if total_hits == 0 else 1


def cmd_redact(args):
    f = Path(args.redact)
    if not f.exists():
        print("[dlp_scan] ERR: no file " + str(f))
        return 2
    text = f.read_text(encoding="utf-8", errors="replace")
    hits = _scan_text(text, emails=args.emails)
    if not hits:
        print("[dlp_scan] no hits in " + str(f))
        return 0
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f.with_name(f.name + ".bak-dlp-" + ts)
    bak.write_text(text, encoding="utf-8")
    new_text, n = _redact_text(text, hits)
    if args.dry:
        print("[dlp_scan] DRY: would redact " + str(n) + " in " + str(f))
        print("[dlp_scan]   backup target: " + bak.name)
        return 0
    f.write_text(new_text, encoding="utf-8")
    print("[dlp_scan] redacted " + str(n) + " in " + str(f))
    print("[dlp_scan] backup: " + bak.name)
    return 0


def main():
    ap = argparse.ArgumentParser(prog="dlp_scan.py")
    ap.add_argument("--scan-file")
    ap.add_argument("--scan-dir")
    ap.add_argument("--scan-logs", action="store_true")
    ap.add_argument("--redact")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--emails", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.redact:
        return cmd_redact(args)
    return cmd_scan(args)


if __name__ == "__main__":
    sys.exit(main())
