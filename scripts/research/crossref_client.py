#!/usr/bin/env python3
# scripts/research/crossref_client.py (s180, non-CORE)
# REST client for Crossref. stdlib only.
import argparse, json, os, re, sys, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from scripts.research._common import gateway_call, write_index

BASE = "https://api.crossref.org/works"
DEFAULT_EMAIL = "ai-hub@example.com"
DEFAULT_OUT = "knowledge/research_index.json"

def _mailto(): return os.environ.get("OPENALEX_EMAIL", DEFAULT_EMAIL)

def build_url(query, rows=5):
    params = {"query": query, "rows": str(rows), "mailto": _mailto()}
    return BASE + "?" + urllib.parse.urlencode(params)

def _strip_jats(s):
    if not s: return ""
    return re.sub(r"<[^>]+>", "", s).strip()

def normalize(item):
    t = item.get("title") or [""]
    c = item.get("container-title") or [""]
    y = None
    try: y = item["issued"]["date-parts"][0][0]
    except Exception: pass
    return {
        "id": item.get("DOI") or "",
        "title": t[0] if t else "",
        "year": y,
        "doi": item.get("DOI"),
        "source": c[0] if c else "",
        "cited_by": item.get("is-referenced-by-count") or 0,
        "abstract": _strip_jats(item.get("abstract") or ""),
    }

def search_works(query, rows=5, timeout=15):
    url = build_url(query, rows)
    data = gateway_call("crossref", url, timeout=timeout)
    items = (data.get("message") or {}).get("items") or []
    return [normalize(it) for it in items]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", required=True)
    ap.add_argument("--rows", type=int, default=5)
    ap.add_argument("--out", default=DEFAULT_OUT)
    a = ap.parse_args()
    items = search_works(a.query, a.rows)
    added, total = write_index(items, a.out, a.query)
    print(json.dumps({"found": len(items), "added": added,
                      "total": total}, ensure_ascii=False))

if __name__ == "__main__": main()
