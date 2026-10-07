#!/usr/bin/env python3
# scripts/lesson_apply.py  (s168-A1.1, non-CORE)
# Cross-session memory for lessons.md:
#   --suggest  : top-N relevant lessons for current session (writes suggest file)
#   --mark     : manual application record
#   --stats    : applications summary
#   --auto-close : write close-summary for current session
import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "knowledge" / "lessons_index.json"
APPS = ROOT / "knowledge" / "lesson_applications.jsonl"
NEXT = ROOT / "self" / "curator" / "NEXT_SESSION.md"
PLAN = ROOT / "self" / "curator" / "PLAN.md"
# s174: semantic rerank support
EMB_PATH = ROOT / "knowledge" / "lessons_embeddings.jsonl"
LE_SCRIPT = ROOT / "scripts" / "lesson_embed.py"
STATE = ROOT / "self" / "curator" / "STATE.md"
SUGGEST_DIR = ROOT / "self" / "curator"

STOPWORDS = {
    "этого", "этой", "этот", "будет", "будут", "были", "было", "есть",
    "через", "если", "для", "или", "как", "что", "где", "так", "все",
    "the", "and", "for", "with", "from", "this", "that", "into", "only",
    "сессии", "session", "плюс", "plus", "level", "stage", "stages",
}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read(p, default=""):
    return p.read_text(encoding="utf-8") if p.exists() else default


def _load_index():
    if not INDEX.exists():
        return None
    try:
        return json.loads(INDEX.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_lesson_embed():
    # s174: dynamic import of lesson_embed.py (optional dependency).
    if not LE_SCRIPT.exists():
        return None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("lesson_embed_mod", str(LE_SCRIPT))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def _semantic_rerank(scored, query_text):
    # s175: hybrid rerank v2 - composite key (id,title[:60]) fixes non-unique id
    # for dated entries (18 rows share id='2026-09-25'); 0.3x cosine + tier bonus.
    le = _load_lesson_embed()
    if le is None:
        return scored, False
    try:
        meta, rows = le.load_embeddings()
    except Exception:
        return scored, False
    if not rows:
        return scored, False
    try:
        qv = le.embed(query_text, prefix=le.QUERY_PREFIX)
    except Exception:
        return scored, False
    by_key = {}
    for r in rows:
        k = (r.get("id"), (r.get("title") or "")[:60])
        by_key[k] = r
    out = []
    for s, e in scored:
        k = (e.get("id"), (e.get("title") or "")[:60])
        r = by_key.get(k)
        c = 0.0
        if r and r.get("embedding"):
            try:
                c = le.cosine(qv, r["embedding"])
            except Exception:
                c = 0.0
        tier = 1.0 if e.get("style") == "session" else -0.5
        out.append((s + 0.3 * c * 10.0 + tier, e))
    out.sort(key=lambda x: (-x[0], -(x[1].get("line_start") or 0)))
    return out, True


def _current_session():
    txt = _read(STATE)
    for ln in txt.splitlines():
        if "Следующая сессия:" in ln:
            s = ln.split(":", 1)[1]
            s = s.replace("*", "").replace("_", "").strip().strip(".").strip()
            return s or None
    return None


def _session_keywords():
    # s170-A1: NEXT only — PLAN отравлял keywords (s168-r8).
    txt = _read(NEXT).lower()
    words = set()
    for m in re.finditer(r"[a-zа-яё][a-zа-яё0-9_]{3,}", txt):
        w = m.group(0)
        if w not in STOPWORDS:
            words.add(w)
    return words


def _score(entry, keywords):
    # s172-A3: position-weighting — title x2, tags/related x1 (PLAN s172).
    title   = (entry.get("title", "")).lower()
    tags    = " ".join(entry.get("tags", [])).lower()
    related = " ".join(entry.get("related", [])).lower()
    title_hits   = sum(1 for kw in keywords if kw in title)
    tags_hits    = sum(1 for kw in keywords if kw in tags)
    related_hits = sum(1 for kw in keywords if kw in related)
    hits = title_hits + tags_hits + related_hits
    if hits == 0:
        return 0  # s170-A1: no keyword match -> 0 (бонус не повод)
    s = 2 * title_hits + tags_hits + related_hits  # s172-A3
    if entry.get("style") == "session":
        s += 2
    if entry.get("category") not in ("misc",):
        s += 1
    return s


def cmd_suggest(top, session, semantic=False):
    idx = _load_index()
    if not idx:
        print("lesson_apply: no index (run lesson_index.py --build)")
        return 1
    sess = session or _current_session() or "?"
    kws = _session_keywords()
    # s196-p04b: only real session lessons (sN-rX). Skip dated/auto_log entries
    # that polluted the index (117+19 entries with id != sN-rX, id=YYYY-MM-DD x40).
    _SL_RE = re.compile(r"^s\d+-r\d+$")
    scored = []
    for e in idx.get("entries", []):
        if not _SL_RE.match(str(e.get("id", ""))):
            continue
        s = _score(e, kws)
        if s >= 3:  # s170-A1: порог score>=3 (s168-r8)
            scored.append((s, e))
    scored.sort(key=lambda x: (-x[0], x[1].get("id", "")))
    if semantic:
        query_text = _read(NEXT)[:500]
        scored, ok = _semantic_rerank(scored, query_text)
        if not ok:
            print("lesson_apply: semantic unavailable, fallback to keyword")
    # s196-p04b: dedupe picked by id (paranoia — keep first / best-scored).
    picked = []
    _seen = set()
    for _s, _e in scored:
        _id = str(_e.get("id", ""))
        if _id in _seen:
            continue
        _seen.add(_id)
        picked.append(_e)
        if len(picked) >= top:
            break
    suggest_file = SUGGEST_DIR / ("lesson_suggest_" + sess + ".json")
    try:
        suggest_file.write_text(json.dumps({
            "ts": _now(), "session": sess, "ids": [e["id"] for e in picked],
        }, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    if not picked:
        print("lesson_apply: no relevant lessons for " + sess)
        return 0
    ids = ", ".join(e["id"] for e in picked)
    print("lesson_apply: top=" + str(len(picked)) + " session=" + sess + " ids=[" + ids + "]")
    for s, e in scored[:top]:
        print("  [" + str(s) + "] " + e["id"] + " - " + e["title"][:80])
    return 0


def cmd_mark(lesson_id, evidence, session):
    if not lesson_id:
        print("lesson_apply: --mark needs lesson id")
        return 1
    rec = {
        "ts": _now(),
        "session": session or _current_session() or "?",
        "lesson_id": lesson_id,
        "evidence": evidence or "",
        "source": "manual",
    }
    APPS.parent.mkdir(parents=True, exist_ok=True)
    with APPS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("lesson_apply: marked " + lesson_id)
    return 0


def _read_apps():
    rows = []
    if not APPS.exists():
        return rows
    for ln in APPS.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        try:
            rows.append(json.loads(ln))
        except Exception:
            pass
    return rows


def cmd_stats():
    rows = _read_apps()
    print("lesson_apply: total=" + str(len(rows)))
    if not rows:
        return 0
    print("  by_source :", dict(Counter(r.get("source") for r in rows)))
    print("  by_session:", dict(Counter(r.get("session") for r in rows)))
    ids = Counter(r.get("lesson_id") for r in rows)
    print("  top_ids   :", dict(ids.most_common(5)))
    return 0


def cmd_auto_close(session):
    sess = session or _current_session() or "?"
    suggest_file = SUGGEST_DIR / ("lesson_suggest_" + sess + ".json")
    suggested_ids = []
    if suggest_file.exists():
        try:
            suggested_ids = json.loads(suggest_file.read_text(encoding="utf-8")).get("ids", [])
        except Exception:
            suggested_ids = []
    marked_ids = [
        r.get("lesson_id") for r in _read_apps()
        if r.get("session") == sess
        and not str(r.get("lesson_id", "")).startswith("_")  # s170-A1 / s168-r8
    ]
    rec = {
        "ts": _now(),
        "session": sess,
        "lesson_id": "_session_summary",
        "evidence": "suggested=" + str(len(suggested_ids)) + " marked=" + str(len(marked_ids)),
        "source": "auto_close",
        "suggested_ids": suggested_ids,
        "marked_ids": marked_ids,
    }
    APPS.parent.mkdir(parents=True, exist_ok=True)
    with APPS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("lesson_apply: auto-close session=" + sess
          + " suggested=" + str(len(suggested_ids))
          + " marked=" + str(len(marked_ids)))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="lesson_apply")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--suggest", action="store_true")
    g.add_argument("--mark", metavar="ID")
    g.add_argument("--stats", action="store_true")
    g.add_argument("--auto-close", action="store_true")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--semantic", action="store_true")
    ap.add_argument("--evidence", default="")
    ap.add_argument("--session", default=None)
    args = ap.parse_args(argv)
    if args.suggest:
        return cmd_suggest(top=args.top, session=args.session, semantic=args.semantic)
    if args.mark is not None:
        return cmd_mark(args.mark, args.evidence, session=args.session)
    if args.stats:
        return cmd_stats()
    if args.auto_close:
        return cmd_auto_close(session=args.session)
    return 0


if __name__ == "__main__":
    sys.exit(main())
