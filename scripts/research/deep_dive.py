#!/usr/bin/env python3
"""deep_dive.py (s191) — topic-deep-dive into RESEARCH layer.

3 итерации: broad -> specific -> comparative.
Каждая: fetch_from_sources -> enrich_with_unpaywall -> process_one.
Результат: knowledge/deep_dive_<slug>.json + self/curator/DEEP_DIVE_REPORT.md.
"""
import argparse, json, re, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "research"))

import extract as ex

ITER_TEMPLATES = [
    ("broad",       "{topic}"),
    ("specific",    "{topic} architecture pattern"),
    ("comparative", "{topic} comparison survey"),
]


def _slug(s):
    s = re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")
    return s[:40] or "topic"


def run_iteration(name, query, limit, model, verbose=True):
    if verbose:
        print(f"--- iteration [{name}] query={query!r}")
    try:
        items = ex.fetch_from_sources(query, limit=limit)
        items = ex.enrich_with_unpaywall(items)
    except Exception as e:
        print(f"    !! fetch failed: {e!r}")
        return {"name": name, "query": query, "count": 0, "items": [], "error": repr(e)}
    if verbose:
        print(f"    found: {len(items)}")
    out_items = []
    for it in items[:limit]:
        try:
            it2, prop = ex.process_one(it, model=model)
        except Exception as e:
            print(f"    !! process_one failed: {e!r}")
            continue
        tech = (it2.get("extracted_ideas") or [""])[0]
        out_items.append({
            "title": (it.get("title") or "")[:160],
            "doi": it.get("doi") or "",
            "source": it.get("source") or "",
            "year": it.get("year"),
            "technique": tech,
            "suggestion": (prop or {}).get("suggestion", ""),
            "applicable": bool(prop),
            "url": it.get("id") or "",
        })
        if verbose:
            print(f"      + {tech[:70]}")
    return {"name": name, "query": query, "count": len(out_items), "items": out_items}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", required=True)
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--model", default="qwen2.5-coder:3b")
    ap.add_argument("--out", default=None)
    ap.add_argument("--report", default=None)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    slug = _slug(a.topic)
    out_path = Path(a.out) if a.out else ROOT / "knowledge" / f"deep_dive_{slug}.json"
    rep_path = Path(a.report) if a.report else ROOT / "self" / "curator" / "DEEP_DIVE_REPORT.md"

    t0 = time.time()
    iterations = [run_iteration(n, t.format(topic=a.topic), a.limit, a.model)
                  for n, t in ITER_TEMPLATES]

    total_items = sum(r["count"] for r in iterations)
    techniques, seen = [], set()
    for r in iterations:
        for it in r["items"]:
            t = (it.get("technique") or "").strip().lower()
            if t and t not in seen:
                seen.add(t)
                techniques.append(it["technique"])

    doc = {
        "version": 1,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "topic": a.topic, "slug": slug,
        "iterations": iterations,
        "total_items": total_items,
        "unique_techniques": techniques,
        "elapsed_sec": round(time.time() - t0, 1),
    }

    if a.dry:
        print(f"DRY: total_items={total_items} unique_techniques={len(techniques)}")
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote: {out_path}")

    lines = [f"# DEEP DIVE REPORT — {a.topic}", "",
             f"**Generated:** {doc['ts']}",
             f"**Iterations:** {len(iterations)}",
             f"**Total items:** {total_items}",
             f"**Unique techniques:** {len(techniques)}",
             f"**Elapsed:** {doc['elapsed_sec']}s", ""]
    for r in iterations:
        lines.append(f"## {r['name']} — `{r['query']}`")
        extra = f" · error: {r['error']}" if r.get("error") else ""
        lines.append(f"found: {r['count']}{extra}")
        lines.append("")
        for it in r["items"]:
            yr = f" ({it['year']})" if it.get("year") else ""
            lines.append(f"- **{it['technique'] or '(no technique)'}**{yr}")
            lines.append(f"  - {it['title']}")
            if it.get("doi"):
                lines.append(f"  - doi: `{it['doi']}`")
            if it.get("suggestion"):
                lines.append(f"  - why: {it['suggestion'][:200]}")
            lines.append("")
    rep_path.parent.mkdir(parents=True, exist_ok=True)
    rep_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote: {rep_path}")
    print(f"total: {total_items}, unique_techniques: {len(techniques)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
