#!/usr/bin/env python3
# scripts/research/pubmed_client.py (s189-p2, non-CORE)
# PubMed E-utilities client. stdlib only. NCBI rate <= 3 req/sec.
import argparse, json, os, sys, time, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from scripts.research._common import gateway_call

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def _norm_doi(raw):
    if not raw: return ""
    s = str(raw).strip().lower()
    for p in ("https://doi.org/", "http://doi.org/", "doi:", "doi "):
        if s.startswith(p): s = s[len(p):]
    return s


def _first(x):
    if isinstance(x, list): return x[0] if x else ""
    return x if x is not None else ""


def _to_item(summary):
    if not isinstance(summary, dict): return None
    pmid = summary.get("uid") or ""
    if not pmid: return None
    title = _first(summary.get("title")) or ""
    year = ""
    for k in ("pubdate", "epubdate", "sortpubdate"):
        v = _first(summary.get(k))
        if v and len(str(v)) >= 4:
            year = str(v)[:4]; break
    doi = ""
    for aid in summary.get("articleids") or []:
        if isinstance(aid, dict) and aid.get("idtype") == "doi":
            doi = _norm_doi(aid.get("value") or ""); break
    url = "https://pubmed.ncbi.nlm.nih.gov/%s/" % pmid
    return {"id": "pubmed:" + pmid, "title": title, "url": url,
            "year": year, "doi": doi, "source": "pubmed",
            "cited_by": 0, "abstract": "", "via": "pubmed"}


def search_works(query, max_results=5, timeout=20):
    q = urllib.parse.urlencode({
        "db": "pubmed", "term": query, "retmode": "json",
        "retmax": str(int(max_results)), "sort": "relevance"})
    try:
        es = gateway_call("pubmed", "%s/esearch.fcgi?%s" % (BASE, q), timeout=timeout)
    except Exception:
        return []
    if not isinstance(es, dict): return []
    ids = (es.get("esearchresult") or {}).get("idlist") or []
    if not ids: return []
    ids_str = ",".join(ids[:max_results])
    q2 = urllib.parse.urlencode({"db": "pubmed", "id": ids_str, "retmode": "json"})
    time.sleep(0.4)
    try:
        sm = gateway_call("pubmed", "%s/esummary.fcgi?%s" % (BASE, q2), timeout=timeout)
    except Exception:
        return []
    if not isinstance(sm, dict): return []
    result = sm.get("result") or {}
    items = []
    for pmid in ids:
        it = _to_item(result.get(pmid))
        if it: items.append(it)
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
