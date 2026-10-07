#!/usr/bin/env python3
# scripts/research/session_lesson_extract.py (s196, non-CORE)
# P0 BACKLOG_LESSON_AUTONOMY: reads EVENTS.jsonl + autonomy.jsonl for current
# session -> proposes 3-5 draft lessons to self/curator/drafts/lessons_session.md.
# CLI: --session sN | --top N | --apply | --dry-run (default)
# Fail-open: never raises. Drafts only; Curator approves manually.
import argparse, json, re, sys
from pathlib import Path

ROOT   = Path(__file__).resolve().parent.parent.parent
EVENTS = ROOT / "self" / "curator" / "EVENTS.jsonl"
AUTO   = ROOT / "self" / "autonomy.jsonl"
STATE  = ROOT / "self" / "curator" / "STATE.md"
DRAFT  = ROOT / "self" / "curator" / "drafts" / "lessons_session.md"

PATTERN_RULES = [
    ("http_404",  r"\b404\b",                              "HTTP 404 \u2014 endpoint not found"),
    ("http_403",  r"\b403\b",                              "HTTP 403 \u2014 access denied (try User-Agent)"),
    ("http_401",  r"\b401\b",                              "HTTP 401 \u2014 unauthorized (need auth)"),
    ("http_429",  r"\b429\b",                              "HTTP 429 \u2014 rate limited (backoff)"),
    ("timeout",   r"\btime(?:d)?\s*out\b|timeout",         "Timeout \u2014 retry or increase limit"),
    ("not_found", r"[Nn]ot\s+[Ff]ound",                    "Resource not found"),
    ("forbidden", r"[Ff]orbidden",                         "Forbidden \u2014 UA or auth fix"),
    ("unauth",    r"[Uu]nauthori[sz]ed",                   "Unauthorized \u2014 auth fix"),
    ("unsupported", r"unsupported|not\s+supported",        "Feature not supported \u2014 switch transport"),
    ("fail",      r"\bfail(?:ed|ure)?\b",                  "Generic failure"),
    ("error",     r"\berror\b",                            "Generic error"),
]
SKIP_KINDS = {"smoke_test", "api_test", "ok", "heartbeat"}


def current_session():
    try:
        txt = STATE.read_text(encoding="utf-8")
    except Exception:
        return "?"
    for ln in txt.splitlines():
        if "\u0421\u043b\u0435\u0434\u0443\u044e\u0449\u0430\u044f \u0441\u0435\u0441\u0441\u0438\u044f:" in ln:
            s = ln.split(":", 1)[1].replace("*", "").replace("_", "").strip().strip(".").strip()
            return s or "?"
    return "?"


def _primary_rule(text):
    """Return first matching (rule_name, human_desc) by priority, or None.
    s196-r1: first-match-wins — prevents over-match (HTTP 404 also matched
    not_found/fail; HTTP 403 matched forbidden). PATTERN_RULES order = priority."""
    for name, pat, desc in PATTERN_RULES:
        if re.search(pat, text or ""):
            return (name, desc)
    return None


def _read_events(session):
    if not EVENTS.exists():
        return []
    out = []
    for ln in EVENTS.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(ln)
        except Exception:
            continue
        if str(r.get("session")) != str(session):
            continue
        if str(r.get("kind")) in SKIP_KINDS:
            continue
        out.append(r)
    return out


def _read_autonomy(session):
    """Tolerant: session may be 's196', '196', 196, or absent."""
    if not AUTO.exists():
        return []
    want = {str(session), str(session).lstrip("s")}
    out = []
    for ln in AUTO.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(ln)
        except Exception:
            continue
        s = r.get("session")
        if s is None:
            continue
        if str(s) not in want and str(s).lstrip("s") not in want:
            continue
        out.append(r)
    return out


def extract(session, top=5):
    """Return list of candidate dicts: {rule, desc, where, count, samples, src}."""
    events = _read_events(session)
    auto   = _read_autonomy(session)
    groups = {}  # (rule, where[:80]) -> {desc, count, samples}

    def _add(text, where, src, detail):
        hit = _primary_rule(text)
        if not hit:
            return
        rule, desc = hit
        key = (rule, (where or "?")[:80])
        g = groups.setdefault(key, {"desc": desc, "count": 0, "samples": [], "src": src})
        g["count"] += 1
        if len(g["samples"]) < 3 and detail:
            g["samples"].append(str(detail)[:140])

    for r in events:
        blob = " ".join([str(r.get("kind", "")), str(r.get("where", "")), str(r.get("detail", ""))])
        _add(blob, r.get("where"), "EVENTS.jsonl", r.get("detail"))
    for r in auto:
        blob = " ".join([str(r.get("action", "")), str(r.get("note", "")), str(r.get("kind", ""))])
        _add(blob, r.get("action") or r.get("where") or "autonomy", "autonomy.jsonl", r.get("note"))

    items = sorted(groups.items(), key=lambda kv: (-kv[1]["count"], kv[0]))
    cands = []
    for i, ((rule, where), g) in enumerate(items[:top], 1):
        cands.append({
            "idx": i,
            "rule": rule,
            "desc": g["desc"],
            "where": where,
            "count": g["count"],
            "samples": g["samples"],
            "src": g["src"],
        })
    return {"session": session, "events_total": len(events),
            "auto_total": len(auto), "candidates": cands}


def render_md(res):
    lines = [
        "# LESSONS DRAFT \u2014 session " + res["session"],
        "",
        "Generated by session_lesson_extract.py (s196, P0 BACKLOG_LESSON_AUTONOMY).",
        "Source: EVENTS.jsonl (events={}) + autonomy.jsonl (actions={}).".format(
            res["events_total"], res["auto_total"]),
        "",
        "\u26a0\ufe0f Status: DRAFT \u2014 \u041a\u0443\u0440\u0430\u0442\u043e\u0440 \u0430\u043f\u0440\u0443\u0432\u0438\u0442 \u0432\u0440\u0443\u0447\u043d\u0443\u044e \u2192 append \u0432 lessons.md + rebuild.",
        "",
        "## Candidates ({})".format(len(res["candidates"])),
        "",
    ]
    for c in res["candidates"]:
        lines.append("## {}-d{} \u2014 {} in {}".format(res["session"], c["idx"], c["desc"], c["where"]))
        lines.append("**\u0424\u0410\u041a\u0422:** {} \u0441\u043e\u0431\u044b\u0442\u0438\u0439, rule=`{}`, where=`{}`.".format(
            c["count"], c["rule"], c["where"]))
        if c["samples"]:
            for s in c["samples"]:
                lines.append("  - `{}`".format(s.replace("`", "'")))
        lines.append("**\u041f\u0420\u0410\u0412\u0418\u041b\u041e:** [\u041a\u0443\u0440\u0430\u0442\u043e\u0440 \u0434\u043e\u043f\u0438\u0448\u0435\u0442 \u043f\u043e \u043a\u043e\u043d\u0442\u0435\u043a\u0441\u0442\u0443]")
        lines.append("**\u0418\u0441\u0442\u043e\u0447\u043d\u0438\u043a:** {}".format(c["src"]))
        lines.append("**\u0421\u0442\u0430\u0442\u0443\u0441:** draft")
        lines.append("")
    if not res["candidates"]:
        lines.append("_No candidates. No negative patterns in events/autonomy for this session._")
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="session_lesson_extract")
    ap.add_argument("--session", default=None)
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    session = args.session or current_session()
    res = extract(session, top=args.top)
    md = render_md(res)

    print("extract: session={} events={} auto={} candidates={}".format(
        session, res["events_total"], res["auto_total"], len(res["candidates"])))
    for c in res["candidates"]:
        print("  [{}] {} x{} @ {}".format(c["rule"], c["desc"], c["count"], c["where"]))

    if args.apply and not args.dry_run:
        DRAFT.parent.mkdir(parents=True, exist_ok=True)
        DRAFT.write_text(md, encoding="utf-8")
        print("wrote:", DRAFT)
    else:
        print("--- DRY-RUN (use --apply to write) ---")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
