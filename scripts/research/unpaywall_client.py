#!/usr/bin/env python3
# scripts/research/unpaywall_client.py (s184, non-CORE)
# Unpaywall: lookup by DOI. Requires valid email in query.
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
from scripts.research._common import gateway_call, write_index

BASE = "https://api.unpaywall.org/v2"
DEFAULT_EMAIL = "ai-hub@example.com"
DEFAULT_OUT = "knowledge/research_index.json"


def _email():
    return os.environ.get("UNPAYWALL_EMAIL",
                          os.environ.get("OPENALEX_EMAIL", DEFAULT_EMAIL))


def build_url(doi):
    return "%s/%s?email=%s" % (BASE, doi.strip(), _email())


def normalize(doi, data):
    best = data.get("best_oa_location") or {}
    return {
        "id": "unpaywall:" + (data.get("doi") or doi),
        "title": (data.get("title") or "").strip(),
        "year": data.get("year"),
        "doi": data.get("doi") or doi,
        "source": (data.get("journal_name") or "Unpaywall"),
        "cited_by": int(data.get("num_citations") or 0),
        "abstract": "",
        "oa_status": data.get("oa_status") or "closed",
        "oa_url": best.get("url") or "",
    }


def lookup_doi(doi, timeout=15):
    url = build_url(doi)
    data = gateway_call("unpaywall", url, timeout=timeout)
    if not data or not data.get("doi"):
        return None
    return normalize(doi, data)


def main():
    ap = argparse.ArgumentParser(prog="unpaywall_client")
    ap.add_argument("--doi", required=True,
                    help="one DOI or comma-separated DOIs")
    ap.add_argument("--out", default=DEFAULT_OUT)
    a = ap.parse_args()
    items = []
    for d in [x.strip() for x in a.doi.split(",") if x.strip()]:
        try:
            it = lookup_doi(d)
            if it:
                items.append(it)
        except Exception as e:
            print("unpaywall: %s -> %s" % (d, e))
    added, total = write_index(items, a.out, a.doi)
    print(json.dumps({"found": len(items), "added": added,
                      "total": total}, ensure_ascii=False))


if __name__ == "__main__":
    main()
