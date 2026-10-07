# scripts/research/websearch_client.py (s188, non-CORE)
# Keyless web-search client: webless (primary) + ddgs (fallback).
import argparse
import json
import os
import sys
import time
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from scripts.research._common import _http_log, write_index

DEFAULT_OUT = "knowledge/research_index.json"


def _host(url):
    try:
        return urlparse(url).netloc or ""
    except Exception:
        return ""


def _normalize(title, url, snippet, via):
    return {
        "id": url or "",
        "title": (title or "").strip(),
        "url": url or "",
        "year": None,
        "doi": None,
        "source": _host(url) or via,
        "cited_by": 0,
        "abstract": (snippet or "").strip(),
        "via": via,
    }


def _search_webless(query, max_results=5):
    from webless import search_sync
    t0 = time.time()
    audit_url = "webless://search?q=" + query
    try:
        r = search_sync(query, limit=max_results)
        ok = bool(getattr(r, "ok", False))
        succeeded = list(getattr(r, "succeeded", []) or [])
        failed = list((getattr(r, "failed", {}) or {}).keys())
        _http_log("webless", audit_url,
                  "ok" if ok else "empty",
                  ms=(time.time() - t0) * 1000.0,
                  err=None if ok else ("succeeded=%s failed=%s" % (succeeded, failed))[:120])
        out = []
        for h in list(getattr(r, "hits", []) or [])[:max_results]:
            out.append(_normalize(
                getattr(h, "title", ""),
                getattr(h, "url", ""),
                getattr(h, "snippet", ""),
                "webless",
            ))
        return out
    except Exception as e:
        _http_log("webless", audit_url, "error", ms=(time.time() - t0) * 1000.0, err=str(e)[:120])
        return []


def _search_ddgs(query, max_results=5):
    from ddgs import DDGS
    t0 = time.time()
    audit_url = "ddgs://search?q=" + query
    try:
        with DDGS() as d:
            raw = list(d.text(query, max_results=max_results))
        _http_log("ddgs", audit_url, "ok", ms=(time.time() - t0) * 1000.0)
        out = []
        for h in raw[:max_results]:
            url = h.get("href") or h.get("url") or ""
            out.append(_normalize(
                h.get("title", ""),
                url,
                h.get("body") or h.get("snippet") or "",
                "ddgs",
            ))
        return out
    except Exception as e:
        _http_log("ddgs", audit_url, "error", ms=(time.time() - t0) * 1000.0, err=str(e)[:120])
        return []


def search_works(query, max_results=5):
    items = _search_webless(query, max_results=max_results)
    if not items:
        items = _search_ddgs(query, max_results=max_results)
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", required=True)
    ap.add_argument("--max-results", type=int, default=5)
    ap.add_argument("--out", default=DEFAULT_OUT)
    a = ap.parse_args()
    items = search_works(a.query, a.max_results)
    added, total = write_index(items, a.out, a.query)
    print(json.dumps({"found": len(items), "added": added,
                      "total": total}, ensure_ascii=False))


if __name__ == "__main__":
    main()
