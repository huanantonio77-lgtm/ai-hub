#!/usr/bin/env python3
# scripts/research/semanticscholar_client.py (s189-p2, non-CORE)
# SemanticScholar Graph API. stdlib only. Keyless tier → 429 (graceful []).
import argparse, json, os, sys, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from scripts.research._common import gateway_call

BASE = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = "title,year,externalIds,abstract,citationCount"


def _norm_doi(raw):
    if not raw: return ""
    s = str(raw).strip().lower()
    for p in ("https://doi.org/", "http://doi.org/", "doi:", "doi "):
        if s.startswith(p): s = s[len(p):]
    return s


def _to_item(rec):
    if not isinstance(rec, dict): return None
    pid = rec.get("paperId") or ""
    ext = rec.get("externalIds") or {}
    doi = _norm_doi(ext.get("DOI") or "")
    url = ("https://www.semanticscholar.org/paper/" + pid) if pid else ""
    return {"id": "s2:" + pid if pid else "", "title": rec.get("title") or "",
            "url": url, "year": str(rec.get("year") or ""), "doi": doi,
            "source": "semanticscholar",
            "cited_by": int(rec.get("citationCount") or 0),
            "abstract": (rec.get("abstract") or "")[:600],
            "via": "semanticscholar"}


def search_works(query, max_results=5, timeout=20):
    params = {"query": query, "limit": str(min(int(max_results), 20)),
              "fields": FIELDS}
    api_key = os.environ.get("S2_API_KEY")
    if api_key:
        params["apiKey"] = api_key
    url = BASE + "?" + urllib.parse.urlencode(params)
    try:
        d = gateway_call("semanticscholar", url, timeout=timeout)
    except Exception:
        return []
    if not isinstance(d, dict): return []
    items = []
    for rec in (d.get("data") or []):
        it = _to_item(rec)
        if it and it.get("title"): items.append(it)
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    items = search_works(a.query, max_results=a.limit)
    if a.json: print(json.dumps(items, ensure_ascii=False, indent=2))
    else:
        print("got %d items" % len(items))
        for it in items: print(" ", it.get("year"), "|", (it.get("title") or "")[:80])


if __name__ == "__main__":
    main()
