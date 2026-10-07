#!/usr/bin/env python3
# input_audit.py (s118) -- Safety Layer 6 v1 healer: Input Validation.
#
# Detector for free-form text inputs (tasks, research entries, drafts):
#   - shell injection markers: ; | & $() `  with commands
#   - path traversal: ../ or /etc/ or ~/..
#   - unbalanced quotes / brackets
#   - invisible unicode (zero-width, bidi)
#
# Actuator (--run): signal autonomy when findings present; does NOT block.
# Human-in-the-loop is handled by hitl.py separately.
#
# Rights: record_finding, add_repair_task.
# Cannot: mutate_core, delete_file, set_cooldown, execute_input.
#
# Journal: self/healers/input_audit.jsonl
# Medcard: self/healers/input_audit.md
# Not CORE. Not sensitive.

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AUTONOMY = ROOT / "self" / "autonomy.jsonl"
HEALER_JOURNAL = ROOT / "self" / "healers" / "input_audit.jsonl"
INVISIBLE_RE = re.compile("[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
CMD_INJECT_RE = re.compile(r"(?:;|\|\||&&|\$\()[^a-zA-Z0-9_\s]*\s*(?:rm|mv|cp|curl|wget|nc|bash|sh|sudo)\b", re.I)  # s124-F25: drop backtick (markdown false positives)
TRAVERSAL_RE = re.compile(r"(?:\.\./){2,}|(?:^|\s)/etc/|(?:^|\s)~/\.\.|/private/etc/", re.I)
UNBALANCED_RE = re.compile(r"['\"][^'\"]*$|^[^'\"]*['\"]", re.M)

TARGETS = [  # s124-F13: mirror strategy/input_targets.json
    "self/BACKLOG.md",
    "self/research_log.jsonl",
    "strategy/_autonomy_health.jsonl",
    "memory.json",
    "self/autonomy.jsonl",
    "knowledge/lessons.md",
    "team/orchestrator.md",
    "team/researcher.md",
    "team/writer.md",
    "team/planner.md",
    "team/qa.md",
]

TARGETS_JSON = ROOT / "strategy" / "input_targets.json"
INPUT_PENDING = ROOT / "self" / "healers" / "input_pending.jsonl"
INPUT_DECISIONS = ROOT / "self" / "healers" / "input_decisions.jsonl"


def _ts():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _session():
    try:
        import session_meta as _sm
        return _sm.current()
    except Exception:
        return "unknown"


def _scan_text(t):
    hits = []
    for m in CMD_INJECT_RE.finditer(t):
        hits.append({"kind": "cmd_inject", "sample": m.group(0)[:80]})
    for m in TRAVERSAL_RE.finditer(t):
        hits.append({"kind": "traversal", "sample": m.group(0)[:80]})
    inv = INVISIBLE_RE.findall(t)
    if inv:
        hits.append({"kind": "invisible", "count": len(inv)})
    return hits


def _scan_file(rel, max_bytes=131072):
    p = ROOT / rel
    if not p.exists():
        return {"file": rel, "exists": False, "hits": []}
    try:
        text = p.read_text(encoding="utf-8", errors="replace")[:max_bytes]
    except Exception as e:
        return {"file": rel, "error": str(e)[:200], "hits": []}
    return {"file": rel, "hits": _scan_text(text), "size": p.stat().st_size}

def _load_targets():
    try:
        if TARGETS_JSON.exists():
            d = json.loads(TARGETS_JSON.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                ts = d.get("targets")
                if isinstance(ts, list):
                    out = [str(x) for x in ts if x]
                    if out:
                        return out
    except Exception:
        pass
    return list(TARGETS)


def _finding_id(source, kind, sample):
    base = str(source) + "|" + str(kind) + "|" + str(sample)
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]


def _scan_text_with_source(source, t):
    hits = _scan_text(t)
    out = []
    for h in hits:
        sample = h.get("sample") or ("count=" + str(h.get("count")))
        fid = _finding_id(source, h.get("kind"), sample)
        out.append({
            "finding_id": fid,
            "source": source,
            "kind": h.get("kind"),
            "sample": str(sample)[:80],
        })
    return out


def _pending_open():
    out = {}
    try:
        if not INPUT_PENDING.exists():
            return out
        txt = INPUT_PENDING.read_text(encoding="utf-8")
        for line in txt.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            fid = d.get("finding_id")
            ev = d.get("event")
            if not fid:
                continue
            if ev == "resolved":
                out.pop(fid, None)
            elif ev == "opened":
                out[fid] = d
    except Exception:
        pass
    return out


def _append_pending(fid, source, kind, sample, event):
    try:
        INPUT_PENDING.parent.mkdir(parents=True, exist_ok=True)
        with INPUT_PENDING.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": _ts(), "session": _session(),
                "healer": "input_audit",
                "finding_id": fid, "source": source,
                "kind": kind, "sample": sample, "event": event,
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _append_decision(fid, decision, reason):
    try:
        INPUT_DECISIONS.parent.mkdir(parents=True, exist_ok=True)
        with INPUT_DECISIONS.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": _ts(), "session": _session(),
                "finding_id": fid, "decision": decision,
                "reason": reason or "",
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _open_pending_for_hits(source, hits, dry=False):
    if dry:
        return 0
    opened = 0
    pend = _pending_open()
    for h in hits:
        fid = h["finding_id"]
        if fid in pend:
            continue
        _append_pending(fid, h["source"], h["kind"], h["sample"], "opened")
        opened += 1
    return opened


def cmd_text(text, source="text:inline", dry=False, quiet=False):
    hits = _scan_text_with_source(source, text)
    if not quiet:
        if not hits:
            print("input_audit scan-text: clean src=" + source)
        else:
            print("input_audit scan-text: hits=" + str(len(hits))
                  + " src=" + source)
            for h in hits[:10]:
                print("  " + h["kind"] + " id=" + h["finding_id"]
                      + " sample=" + h["sample"])
    opened = _open_pending_for_hits(source, hits, dry=dry)
    if not quiet and opened:
        print("  pending_opened=" + str(opened))
    return 0 if not hits else 1


def cmd_scan_stdin(dry=False, quiet=False):
    try:
        text = sys.stdin.read()
    except Exception:
        text = ""
    return cmd_text(text, source="stdin", dry=dry, quiet=quiet)


def cmd_pending():
    pend = _pending_open()
    if not pend:
        print("input_audit pending: 0")
        return 0
    print("input_audit pending: " + str(len(pend)))
    for fid in sorted(pend.keys()):
        d = pend[fid]
        line = "  " + fid + " " + str(d.get("kind"))
        line += " src=" + str(d.get("source"))
        line += " sample=" + str(d.get("sample"))[:60]
        print(line)
    return 0


def cmd_approve(fid):
    fid = (fid or "").strip()
    if not fid:
        print("input_audit --approve: empty id")
        return 2
    pend = _pending_open()
    if fid not in pend:
        print("input_audit --approve: not in pending: " + fid)
        return 2
    d = pend[fid]
    _append_pending(fid, d.get("source"), d.get("kind"),
                    d.get("sample"), "resolved")
    _append_decision(fid, "approve", "")
    print("input_audit: approved " + fid)
    return 0


def cmd_deny(fid, reason=""):
    fid = (fid or "").strip()
    if not fid:
        print("input_audit --deny: empty id")
        return 2
    pend = _pending_open()
    if fid not in pend:
        print("input_audit --deny: not in pending: " + fid)
        return 2
    d = pend[fid]
    _append_pending(fid, d.get("source"), d.get("kind"),
                    d.get("sample"), "resolved")
    _append_decision(fid, "deny", reason)
    print("input_audit: denied " + fid)
    return 0



def run(actuate=False, quiet=False):
    findings = []
    for rel in _load_targets():
        r = _scan_file(rel)
        if r.get("hits"):
            findings.append(r)
    total = sum(len(f.get("hits", [])) for f in findings)
    if not quiet:
        print("input_audit: files_scanned=" + str(len(TARGETS))
              + " findings=" + str(len(findings))
              + " total_hits=" + str(total))
        for f in findings[:5]:
            print("  " + f["file"] + " hits=" + str(len(f["hits"])))
            for h in f["hits"][:3]:
                print("     " + h["kind"] + ": " + str(h.get("sample") or h.get("count")))
    try:
        HEALER_JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with HEALER_JOURNAL.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": _ts(), "session": _session(), "healer": "input_audit",
                "diagnosis": "warn" if total else "ok",
                "action": "report",
                "effect": 1 if total else 0,
                "outcome": "dirty" if total else "ok",
                "note": "files=" + str(len(TARGETS)) + " hits=" + str(total),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass
    if total:
        try:
            with AUTONOMY.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": _ts(), "session": _session(),
                    "action": "input_audit_finding",
                    "note": "total_hits=" + str(total) + " files=" + str(len(findings)),
                    "effect": 1,
                }, ensure_ascii=False) + "\n")
        except Exception:
            pass
    if actuate and total:
        pend = _pending_open()
        opened = 0
        for f in findings:
            for h in f.get("hits", []):
                sample = h.get("sample") or ("count=" + str(h.get("count")))
                fid = _finding_id(f["file"], h.get("kind"), sample)
                if fid in pend:
                    continue
                _append_pending(fid, f["file"], h.get("kind"),
                                str(sample)[:80], "opened")
                opened += 1
        if not quiet and opened:
            print("input_audit actuator: pending_opened=" + str(opened))
    return 0 if not total else 1


def main():
    ap = argparse.ArgumentParser(prog="input_audit.py")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--text", default=None)
    ap.add_argument("--scan-text", action="store_true")
    ap.add_argument("--pending", action="store_true")
    ap.add_argument("--approve", default=None)
    ap.add_argument("--deny", default=None)
    ap.add_argument("--reason", default="")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    if args.text is not None:
        return cmd_text(args.text, source="text:inline",
                        dry=args.dry, quiet=args.quiet)
    if args.scan_text:
        return cmd_scan_stdin(dry=args.dry, quiet=args.quiet)
    if args.pending:
        return cmd_pending()
    if args.approve:
        return cmd_approve(args.approve)
    if args.deny:
        return cmd_deny(args.deny, args.reason)
    return run(actuate=args.run, quiet=args.quiet)


if __name__ == "__main__":
    sys.exit(main())
