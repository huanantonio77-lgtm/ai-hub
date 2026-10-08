#!/usr/bin/env python3
# scripts/lesson_index.py  (s168-C1.1, non-CORE)
# Build/check/stat a JSON index of knowledge/lessons.md.
# Reads lessons.md (never writes it), writes knowledge/lessons_index.json.
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LESSONS = ROOT / "knowledge" / "lessons.md"
INDEX = ROOT / "knowledge" / "lessons_index.json"

H_SESSION = re.compile(r"^##\s+(s\d+)-r(\d+)\s+[\u2014\-]\s+(.+)$")
H_DATED = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})\b(.*)$")
H_LEGACY = re.compile(r"^##\s+\u0423\u0440\u043e\u043a:\s+(.+)$")

CATEGORY_KEYWORDS = {
    "trading": ["arbitrage", "orderbook", "testnet", "live_session", "livepaper",
                "trading", "stage 8", "stage8", "scanner", "liquidity",
                "adapter", "risk", "backtest", "paper_trader",
                "watcher", "momentum", "sniper", "dv/dt", "dvsol",
                "pump.fun", "pumpfun", "rugcheck", "bonding curve", "bonding-curve",
                "helius", "jupiter", "dexscreener", "birdeye", "pumpportal",
                "solana", "wallet", "solders", "kill flag", "kill_flag",
                "paper_sniper", "sniper_v2", "sniper_filter", "dev-reputation",
                "dev_reputation", "entry", "exit", "partial", "trailing"],
    "curator": ["curator.py", "cmd_close", "cmd_brief", "cmd_resolve",
                "cmd_scale", "--close", "--brief", "--resolve"],
    "family_audit": ["family_audit", "module-without-e2e", "naked-caller",
                     "symmetry-gap", "test-gap"],
    "shell": ["heredoc", "nano", "pbpaste", "grep -e", "zsh", "macos",
              "find ", "wc -l"],
    "self_docs": ["lessons.md", "self_sync", "self.md", "scale.md",
                  "plan.md", "state.md", "journal",
                  "daemon", "launchd", "self_daemon", "agent_daemon",
                  "self_monitor", "watchdog", "plist"],
    "docs": ["tz", "architecture_rules", "arbitrage_tz"],
    "python_syntax": ["f-string", "backslash", "syntaxerror", "re.search",
                     "re.match", "re.compile", "argparse", "if args.",
                     "is not none", "falsy", "truthy", "unittest",
                     "mock.patch", "getattr"],
}

_AUTO_LOG_RE = re.compile(r"\[auto\]|\u0417\u0430\u0434\u0430\u0447\u0430:", re.I)


def _classify(text):
    low = text.lower()
    # s170-B: auto-logs (dated) \u2014 \u043d\u0435 \u0443\u0440\u043e\u043a\u0438.
    first_line = low.split("\n", 1)[0]
    if _AUTO_LOG_RE.search(first_line):
        return "auto_log"
    scores = {}
    for cat, kws in CATEGORY_KEYWORDS.items():
        s = sum(1 for k in kws if k in low)
        if s:
            scores[cat] = s
    if not scores:
        return "misc"
    return max(scores.items(), key=lambda kv: kv[1])[0]

def _tags(text):
    seen = set()
    out = []
    for m in re.finditer(r"`([^`]+)`", text):
        t = m.group(1).strip().lower()
        if 2 <= len(t) <= 80 and t not in seen:
            seen.add(t)
            out.append(t)
    return out[:12]


def _related(text):
    seen = set()
    out = []
    for m in re.finditer(r"\bs(\d+)-r(\d+)\b", text):
        r = "s%s-r%s" % (m.group(1), m.group(2))
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out

def parse():
    text = LESSONS.read_text(encoding="utf-8")
    lines = text.splitlines()
    heads = []
    for i, ln in enumerate(lines):
        m = H_SESSION.match(ln)
        if m:
            heads.append((i, m, "session"))
            continue
        m = H_DATED.match(ln)
        if m:
            heads.append((i, m, "dated"))
            continue
        m = H_LEGACY.match(ln)
        if m:
            heads.append((i, m, "legacy"))
            continue
    entries = []
    n = len(heads)
    for j, (idx, m, style) in enumerate(heads):
        end = heads[j + 1][0] - 1 if j + 1 < n else len(lines) - 1
        body = "\n".join(lines[idx:end + 1])
        if style == "session":
            eid = m.group(1) + "-r" + m.group(2)
            title = m.group(3).strip()
            sess, rev, ts = m.group(1), int(m.group(2)), None
        elif style == "dated":
            eid = m.group(1)
            title = m.group(2).lstrip(" .\u2014-").strip()
            sess, rev, ts = None, None, m.group(1)
        else:
            eid = "legacy-" + str(j + 1).zfill(3)
            title = m.group(1).strip()
            sess, rev, ts = None, None, None
        entries.append({
            "id": eid,
            "title": title[:140],
            "line_start": idx + 1,
            "line_end": end + 1,
            "style": style,
            "session": sess,
            "rev": rev,
            "ts": ts,
            "category": _classify(body),
            "tags": _tags(body),
            "related": [r for r in _related(body) if r != eid],
        })
    return text, entries

def _sha16(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]

def cmd_build():
    text, entries = parse()
    data = {
        "version": 1,
        "built_ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "knowledge/lessons.md",
        "source_bytes": len(text.encode("utf-8")),
        "source_sha256_short": _sha16(text),
        "count": len(entries),
        "entries": entries,
    }
    INDEX.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    print("lesson_index: built count=" + str(len(entries))
          + " bytes=" + str(data["source_bytes"])
          + " sha=" + data["source_sha256_short"])
    return 0

def cmd_check():
    if not INDEX.exists():
        print("lesson_index: MISSING (run --build)")
        return 1
    data = json.loads(INDEX.read_text(encoding="utf-8"))
    text = LESSONS.read_text(encoding="utf-8")
    want = _sha16(text)
    got = data.get("source_sha256_short", "")
    if want == got:
        print("lesson_index: OK count=" + str(data.get("count", 0))
              + " sha=" + got)
        return 0
    print("lesson_index: STALE want=" + want + " got=" + got)
    return 2

def cmd_stat():
    if not INDEX.exists():
        print("lesson_index: MISSING (run --build)")
        return 1
    data = json.loads(INDEX.read_text(encoding="utf-8"))
    from collections import Counter
    by_cat = Counter(e["category"] for e in data["entries"])
    by_style = Counter(e["style"] for e in data["entries"])
    print("lesson_index: stat count=" + str(data["count"]))
    print("  by_style:", dict(by_style))
    print("  by_category:", dict(by_cat))
    return 0

def main(argv=None):
    ap = argparse.ArgumentParser(prog="lesson_index")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--build", action="store_true")
    g.add_argument("--check", action="store_true")
    g.add_argument("--stat", action="store_true")
    args = ap.parse_args(argv)
    if args.build:
        return cmd_build()
    if args.check:
        return cmd_check()
    if args.stat:
        return cmd_stat()
    return 0

if __name__ == "__main__":
    sys.exit(main())
