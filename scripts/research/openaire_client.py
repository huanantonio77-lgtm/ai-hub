#!/usr/bin/env python3
# scripts/research/openaire_client.py (s184, non-CORE)
# OpenAIRE Graph API v1. Required: search, type=publication, page, pageSize.
import argparse, json, os, sys, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
from scripts.research._common import gateway_call, write_index

BASE = "https://api.openaire.eu/graph/v1/researchProducts"
DEFAULT_OUT = "knowledge/research_index.json"


def build_url(query, size=5):
    params = {
        "search": query,
        "type": "publication",
        "page": "1",
        "pageSize": str(size),
        "sortBy": "relevance DESC",
    }
    return BASE + "?" + urllib.parse.urlencode(params)


def _s(v, default=""):
    if v is None: return default
    if isinstance(v, dict): return v.get("$") or v.get("value") or default
    return str(v)


def normalize(item):
    title = _s(item.get("mainTitle"), "").strip()
    year = _s(item.get("publicationDate"), "")
    doi = _s(item.get("doi"), "")
    src = _s(item.get("publisher") or item.get("source"), "") or "OpenAIRE"
    pid = _s(item.get("id"), "") or title[:60]
    return {
        "id": "openaire:" + pid[:100],
        "title": title,
        "year": year[:4] if year else None,
        "doi": doi or None,
        "source": src,
        "cited_by": int(item.get("citationCount") or 0),
        "abstract": _s(item.get("description"), "")[:2000],
    }


def search_works(query, size=5, timeout=25):
    url = build_url(query, size)
    data = gateway_call("openaire", url, timeout=timeout)
    items = (data or {}).get("results") or []
    if isinstance(items, dict):
        items = items.get("result") or [items]
    out = []
    for it in items:
        try:
            out.append(normalize(it))
        except Exception:
            continue
    return out


def main():
    ap = argparse.ArgumentParser(prog="openaire_client")
    ap.add_argument("--query", required=True)
    ap.add_argument("--rows", type=int, default=5)
    ap.add_argument("--out", default=DEFAULT_OUT)
    a = ap.parse_args()
    items = search_works(a.query, a.rows)
    added, total = write_index(items, a.out, a.query)
    print(json.dumps({"found": len(items), "added": added,
                      "total": total}, ensure_ascii=False))


if __name__ == "__main__":
    main()
