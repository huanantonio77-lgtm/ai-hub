#!/usr/bin/env python3
"""lesson_embed.py -- semantic embeddings for knowledge/lessons.md (s174).

Build:   python3 scripts/lesson_embed.py --build
Search:  python3 scripts/lesson_embed.py --search "query" --top 5
Stats:   python3 scripts/lesson_embed.py --stats

Requires: ollama serve on 127.0.0.1:11434 + nomic-embed-text model.
Storage:  knowledge/lessons_embeddings.jsonl (1 meta + N entries).
"""
import argparse
import json
import math
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = ROOT / "knowledge" / "lessons_index.json"
LESSONS_PATH = ROOT / "knowledge" / "lessons.md"
EMB_PATH = ROOT / "knowledge" / "lessons_embeddings.jsonl"
OLLAMA_URL = "http://127.0.0.1:11434/api/embeddings"
MODEL = "bge-m3"  # multilingual (100+ langs), 1024 dim, no prefix
DOC_PREFIX = ""  # bge-m3: no prefix needed
QUERY_PREFIX = ""  # bge-m3: no prefix needed
TIMEOUT = 60
MAX_CHARS = 1800  # nomic-embed-text safe limit under ctx=2048


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_index():
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def _extract_body(lines, line_start, line_end):
    # 1-based inclusive -> Python slice
    lo = max(0, int(line_start) - 1)
    hi = min(len(lines), int(line_end))
    return "\n".join(lines[lo:hi]).strip()


def _http_post(url, payload, timeout=TIMEOUT):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        pin = data.get("prompt_eval_count") or 0
        _track("ok", tokens_in=int(pin), tokens_out=0)
        return data
    except urllib.error.HTTPError as e:
        _track("429" if e.code == 429 else "error")
        raise
    except Exception:
        _track("error")
        raise





def _track(status, tokens_in=0, tokens_out=0):
    try:
        import sys as _s
        import os as _os
        root = _os.path.dirname(_os.path.dirname(
            _os.path.abspath(__file__)))
        if str(root) not in _s.path:
            _s.path.insert(0, str(root))
        import limits as _lim
        _lim.record_call("ollama", status,
                         tokens_in=tokens_in, tokens_out=tokens_out)
    except Exception:
        pass


def embed(text, prefix=DOC_PREFIX, timeout=None):
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
    payload = {"model": MODEL, "prompt": prefix + text}
    data = _http_post(OLLAMA_URL, payload, timeout=timeout or TIMEOUT)
    vec = data.get("embedding")
    if not vec:
        raise RuntimeError(f"no embedding in response: {list(data.keys())}")
    return vec


def cosine(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def cmd_build():
    idx = _load_index()
    lines = LESSONS_PATH.read_text(encoding="utf-8").splitlines()
    entries = idx.get("entries", [])
    print(f"  building embeddings for {len(entries)} entries...")
    rows = []
    skipped = []
    for i, e in enumerate(entries, 1):
        body = _extract_body(lines, e["line_start"], e["line_end"])
        try:
            vec = embed(body, prefix=DOC_PREFIX)
        except Exception as ex:
            # s191-p1: cold-start retry with 3x timeout
            try:
                vec = embed(body, prefix=DOC_PREFIX, timeout=TIMEOUT * 3)
            except Exception as ex2:
                skipped.append({"id": e["id"], "error": str(ex2)[:200], "body_len": len(body)})
                print(f"    SKIP {e['id']} ({len(body)} chars): {ex2}")
                continue
        row = {
            "id": e["id"],
            "title": e.get("title", ""),
            "style": e.get("style"),
            "category": e.get("category"),
            "tags": e.get("tags", []),
            "embedding": vec,
        }
        rows.append(row)
        if i % 20 == 0 or i == len(entries):
            print(f"    {i}/{len(entries)}")
    dim = len(rows[0]["embedding"]) if rows else 0
    meta = {
        "version": 1,
        "model": MODEL,
        "dim": dim,
        "count": len(rows),
        "skipped_count": len(skipped),
        "skipped": skipped,
        "source": str(LESSONS_PATH.relative_to(ROOT)),
        "source_bytes": LESSONS_PATH.stat().st_size,
        "built_ts": _now(),
    }
    EMB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EMB_PATH.open("w", encoding="utf-8") as f:
        f.write(json.dumps({"_meta": meta}, ensure_ascii=False) + "\n")
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"  wrote {EMB_PATH} ({EMB_PATH.stat().st_size} bytes)")
    return 0


def load_embeddings():
    if not EMB_PATH.exists():
        return None, []
    rows = []
    meta = None
    with EMB_PATH.open("r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            obj = json.loads(ln)
            if "_meta" in obj:
                meta = obj["_meta"]
            else:
                rows.append(obj)
    return meta, rows


def cmd_search(query, top):
    meta, rows = load_embeddings()
    if not rows:
        print("  no embeddings; run --build first", file=sys.stderr)
        return 1
    m = meta or {}
    print(f"  index: {m.get('count')} entries, model={m.get('model')}, dim={m.get('dim')}")
    qv = embed(query, prefix=QUERY_PREFIX)
    scored = []
    for r in rows:
        c = cosine(qv, r["embedding"])
        scored.append((c, r))
    scored.sort(key=lambda x: -x[0])
    print(f"  query: {query!r}")
    for c, r in scored[:top]:
        title = (r.get("title") or "")[:60]
        print(f"    {c:.4f}  {r['id']:20s}  [{r.get('style','?')}]  {title}")
    return 0


def cmd_stats():
    meta, rows = load_embeddings()
    if not meta:
        print("  no embeddings file")
        return 1
    print(f"  file: {EMB_PATH}")
    print(f"  size: {EMB_PATH.stat().st_size} bytes")
    for k in ("version", "model", "dim", "count", "source", "source_bytes", "built_ts"):
        print(f"  {k}: {meta.get(k)}")
    print(f"  rows loaded: {len(rows)}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="lesson_embed")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--search", type=str, default=None)
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args(argv)
    if args.build:
        return cmd_build()
    if args.search is not None:
        return cmd_search(args.search, args.top)
    if args.stats:
        return cmd_stats()
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
