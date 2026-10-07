#!/usr/bin/env python3
# scripts/research/arxiv_client.py (s184, non-CORE)
# REST client for arXiv (Atom XML). stdlib only.
import argparse, json, os, sys, urllib.parse
import xml.etree.ElementTree as ET
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
from scripts.research._common import gateway_call_text, write_index

BASE = "http://export.arxiv.org/api/query"
DEFAULT_OUT = "knowledge/research_index.json"
NS = {"a": "http://www.w3.org/2005/Atom"}


def build_url(query, max_results=5):
    params = {"search_query": "all:" + query,
              "max_results": str(max_results)}
    return BASE + "?" + urllib.parse.urlencode(params)


def _t(e, tag):
    el = e.find("a:" + tag, NS)
    return (el.text or "").strip() if el is not None and el.text else ""


def normalize(entry):
    doi = ""
    for lnk in entry.findall("a:link", NS):
        if lnk.get("title") == "doi":
            doi = lnk.get("href") or ""
    return {
        "id": _t(entry, "id"),
        "title": " ".join(_t(entry, "title").split()),
        "year": (_t(entry, "published") or "")[:4] or None,
        "doi": doi,
        "source": "arXiv",
        "cited_by": 0,
        "abstract": " ".join(_t(entry, "summary").split()),
    }


def search_works(query, max_results=5, timeout=15):
    url = build_url(query, max_results)
    xml_text = gateway_call_text("arxiv", url, timeout=timeout)
    root = ET.fromstring(xml_text)
    return [normalize(e) for e in root.findall("a:entry", NS)]


def main():
    ap = argparse.ArgumentParser(prog="arxiv_client")
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
