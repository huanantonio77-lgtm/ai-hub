#!/usr/bin/env python3
# scripts/research/events.py (s196, non-CORE) — session event sink (append-only JSONL).
# P0 BACKLOG_LESSON_AUTONOMY: closes the hole "agent tried REST -> 404 -> lesson".
# API: emit_event(kind, where, detail="", session=None) -> appends to EVENTS.jsonl.
# CLI: --emit KIND --where W [--detail D] [--session sN] | --tail N | --count
# Never raises (fail-open) — safe from probe/healthcheck/daemon paths.
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
EVENTS = ROOT / "self" / "curator" / "EVENTS.jsonl"
STATE  = ROOT / "self" / "curator" / "STATE.md"


def _now():
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def current_session():
    """STATE.md -> next session tag (sN). Tolerant, matches lesson_apply pattern."""
    try:
        txt = STATE.read_text(encoding="utf-8")
    except Exception:
        return "?"
    for ln in txt.splitlines():
        if "\u0421\u043b\u0435\u0434\u0443\u044e\u0449\u0430\u044f \u0441\u0435\u0441\u0441\u0438\u044f:" in ln:
            s = ln.split(":", 1)[1]
            s = s.replace("*", "").replace("_", "").strip().strip(".").strip()
            if s:
                return s
    return "?"


def emit_event(kind, where, detail="", session=None):
    """Append one event. Never raises. Returns True on write, False on failure."""
    try:
        sess = session or current_session()
        rec = {
            "ts": _now(),
            "session": str(sess)[:32],
            "kind": str(kind)[:64],
            "where": str(where)[:120],
            "detail": str(detail)[:500],
        }
        EVENTS.parent.mkdir(parents=True, exist_ok=True)
        with EVENTS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def tail(n=20):
    if not EVENTS.exists():
        print("events: no EVENTS.jsonl")
        return 0
    lines = EVENTS.read_text(encoding="utf-8").splitlines()
    for ln in lines[-n:]:
        print(ln)
    return 0


def count():
    if not EVENTS.exists():
        print("events: count=0")
        return 0
    n = sum(1 for _ in EVENTS.open(encoding="utf-8"))
    print(f"events: count={n}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="events")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--emit", metavar="KIND")
    g.add_argument("--tail", type=int, metavar="N")
    g.add_argument("--count", action="store_true")
    ap.add_argument("--where", default="")
    ap.add_argument("--detail", default="")
    ap.add_argument("--session", default=None)
    args = ap.parse_args(argv)

    if args.emit:
        ok = emit_event(args.emit, args.where, args.detail, args.session)
        print(f"events: emit kind={args.emit} where={args.where} ok={ok}")
        return 0 if ok else 1
    if args.tail is not None:
        return tail(args.tail)
    if args.count:
        return count()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
