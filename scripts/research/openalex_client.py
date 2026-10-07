#!/usr/bin/env python3
# scripts/research/openalex_client.py (s175, non-CORE)
# REST client for OpenAlex. stdlib only (urllib). No external deps.
import argparse
import json
import os
import pathlib
import ssl
import sys
import urllib.parse
import urllib.request

BASE = "https://api.openalex.org/works"
DEFAULT_EMAIL = "ai-hub@example.com"
DEFAULT_OUT = "knowledge/research_index.json"


def _mailto():
    return os.environ.get("OPENALEX_EMAIL", DEFAULT_EMAIL)


def build_url(query, per_page=5):
    params = {
        "search": query,
        "per_page": str(per_page),
        "mailto": _mailto(),
    }
    api_key = os.environ.get("OPENALEX_API_KEY")
    if api_key:
        params["api_key"] = api_key
    return BASE + "?" + urllib.parse.urlencode(params)


def _reconstruct_abstract(inv_idx):
    if not isinstance(inv_idx, dict) or not inv_idx: return ""
    pairs = [(p, w) for w, ps in inv_idx.items() for p in ps]
    pairs.sort(key=lambda x: x[0])
    return " ".join(w for _, w in pairs)


def normalize(work):
    src = (work.get("primary_location") or {}).get("source") or {}
    return {
        "id": work.get("id"),
        "title": work.get("display_name") or "",
        "year": work.get("publication_year"),
        "doi": work.get("doi"),
        "source": src.get("display_name") or "",
        "cited_by": work.get("cited_by_count") or 0,
        "abstract": _reconstruct_abstract(
            work.get("abstract_inverted_index")),
    }







def _track(status, tokens_in=0, tokens_out=0):
    # s177: delegate to limits_gateway (single source of truth).
    try:
        import os as _os
        import sys as _s
        root = _os.path.dirname(_os.path.dirname(
            _os.path.dirname(_os.path.abspath(__file__))))
        if str(root) not in _s.path:
            _s.path.insert(0, str(root))
        import scripts.limits_gateway as _gw
        _gw.track("openalex", status,
                  tokens_in=tokens_in, tokens_out=tokens_out)
    except Exception:
        pass


def _do_search(url, timeout=15):
    # s177: raw HTTP, called by gateway.call (enforcement outside).
    req = urllib.request.Request(url, headers={"User-Agent": "ai-hub/1.0"})
    _ctx = ssl.create_default_context()
    for _cp in ("/etc/ssl/cert.pem", "/usr/local/etc/openssl/cert.pem"):
        if os.path.exists(_cp):
            try:
                _ctx = ssl.create_default_context(cafile=_cp)
                break
            except Exception:
                pass
    with urllib.request.urlopen(req, timeout=timeout, context=_ctx) as r:
        return json.loads(r.read().decode("utf-8"))


def search_works(query, per_page=5, timeout=15):
    url = build_url(query, per_page)
    # s177: gateway.call -> check BEFORE HTTP, track AFTER.
    # Fallback to _do_search if gateway unavailable.
    try:
        import os as _os
        import sys as _s
        root = _os.path.dirname(_os.path.dirname(
            _os.path.dirname(_os.path.abspath(__file__))))
        if str(root) not in _s.path:
            _s.path.insert(0, str(root))
        import scripts.limits_gateway as _gw
        data = _gw.call("openalex", _do_search, url, timeout=timeout)
    except _gw.QuotaExceeded:
        raise
    except Exception:
        # gateway missing or unexpected -> direct call, _track fires below.
        _track("error")
        raise
    _track("ok")
    return [normalize(w) for w in data.get("results", [])]
def write_index(items, path=DEFAULT_OUT, query=""):
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        try:
            existing = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            existing = {"version": 1, "items": []}
    else:
        existing = {"version": 1, "items": []}
    seen = {it.get("id") for it in existing.get("items", [])}
    added = 0
    for it in items:
        if it.get("id") and it["id"] not in seen:
            existing["items"].append(it)
            seen.add(it["id"])
            added += 1
    existing["last_query"] = query
    existing["count"] = len(existing["items"])
    p.write_text(json.dumps(existing, ensure_ascii=False, indent=2),
                 encoding="utf-8")
    return added, existing["count"]


def main():
    ap = argparse.ArgumentParser(prog="openalex_client")
    ap.add_argument("--search", required=True)
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()
    try:
        items = search_works(args.search, per_page=args.top)
    except Exception as e:
        print("openalex_client: error:", e)
        return 1
    for it in items:
        t = (it.get("title") or "")[:100]
        print("  [%s] %s" % (it.get("year") or "????", t))
    if not args.no_write:
        added, total = write_index(items, args.out, args.search)
        print("openalex_client: added=%d total=%d out=%s"
              % (added, total, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
