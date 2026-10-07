#!/usr/bin/env python3
"""research_feeds.py -- structured feeds (Reddit/Habr/GitHub/HN).

s124-stage6.5: 0 LLM-tokens. Structured data (title/score/date/stars) ready.
Complements search_backends.py (semantic search).
"""
import json
import re
import ssl
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SECRETS = ROOT / ".secrets"
_CTX = ssl._create_unverified_context()

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
       "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15")

# s124-fix-reddit-ua: Reddit requires custom UA for JSON API
_UA_REDDIT = "python:ai-nova.research:v1.0 (by /u/salamkhalikov)"

_TIMEOUT = 15


def _proxy_handler():
    """Возвращает urllib handler с прокси или None."""
    p = SECRETS / "proxy.txt"
    try:
        if p.exists():
            v = p.read_text().strip()
            if v:
                return urllib.request.ProxyHandler({
                    "http": v, "https": v,
                })
    except Exception:
        pass
    return None


def _http_get(url, headers=None, timeout=_TIMEOUT):
    """GET с UA + опц. прокси. Возвращает (bytes, status) или (None, err)."""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", _UA)
    req.add_header("Accept", "application/json, text/xml, text/html, */*")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    opener = None
    ph = _proxy_handler()
    if ph:
        opener = urllib.request.build_opener(ph, urllib.request.HTTPSHandler(context=_CTX))
    try:
        if opener:
            with opener.open(req, timeout=timeout) as r:
                return r.read(), r.status
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
            return r.read(), r.status
    except Exception as e:
        return None, type(e).__name__ + ": " + str(e)[:160]


# ========= REDDIT =========
def reddit_feed(sub, sort="top", period="week", limit=15):
    """Reddit JSON: r/<sub>/<sort>.json?t=<period>. Returns list."""
    url = ("https://www.reddit.com/r/" + urllib.parse.quote(sub)
           + "/" + sort + ".json?t=" + period + "&limit=" + str(limit))
    # s124-fix-reddit-ua: use Reddit-specific UA
    body, status = _http_get(url, headers={"User-Agent": _UA_REDDIT})
    if body is None:
        return {"results": [], "error": status}
    try:
        data = json.loads(body.decode("utf-8", errors="replace"))
    except Exception as e:
        return {"results": [], "error": "parse: " + type(e).__name__}
    children = ((data.get("data") or {}).get("children") or [])
    out = []
    for c in children[:limit]:
        d = c.get("data") or {}
        title = (d.get("title") or "").strip()
        permalink = d.get("permalink") or ""
        url_r = "https://www.reddit.com" + permalink if permalink else (d.get("url") or "")
        if not title:
            continue
        out.append({
            "title": title[:220],
            "url": url_r,
            "score": d.get("score", 0),
            "comments": d.get("num_comments", 0),
            "author": d.get("author", ""),
            "created_utc": d.get("created_utc", 0),
            "snippet": (d.get("selftext") or "")[:300],
        })
    return {"results": out, "sub": sub, "sort": sort, "period": period}


# ========= HABR RSS =========
def habr_feed(limit=15, mode="all"):
    """Habr RSS: /ru/rss/all/all/ or /ru/rss/best/daily/."""
    if mode == "best":
        url = "https://habr.com/ru/rss/best/daily/"
    else:
        url = "https://habr.com/ru/rss/all/all/"
    body, status = _http_get(url)
    if body is None:
        return {"results": [], "error": status}
    txt = body.decode("utf-8", errors="replace")
    items = re.findall(r"<item>(.*?)</item>", txt, re.DOTALL)
    out = []
    for it in items[:limit]:
        t = re.search(r"<title>(.*?)</title>", it, re.DOTALL)
        l = re.search(r"<link>(.*?)</link>", it, re.DOTALL)
        d = re.search(r"<pubDate>(.*?)</pubDate>", it, re.DOTALL)
        desc = re.search(r"<description>(.*?)</description>", it, re.DOTALL)
        title = (t.group(1) if t else "").strip()
        # s124-fix-cdata: strip CDATA before tag strip
        title = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", title, flags=re.DOTALL)
        title = re.sub(r"<[^>]+>", "", title).strip()
        link = (l.group(1) if l else "").strip()
        date = (d.group(1) if d else "").strip()
        snip = (desc.group(1) if desc else "").strip()
        snip = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", snip, flags=re.DOTALL)
        snip = re.sub(r"<[^>]+>", "", snip).strip()[:300]
        if not title:
            continue
        out.append({
            "title": title[:220],
            "url": link,
            "date": date,
            "snippet": snip,
        })
    return {"results": out, "mode": mode}


# ========= GITHUB TRENDING =========
def github_trending(days=7, limit=15, language=None):
    """GitHub search API: created:>DATE, sort=stars. Rate: 60/h keyless."""
    import datetime as _dt
    since = (_dt.datetime.utcnow() - _dt.timedelta(days=days)).strftime("%Y-%m-%d")
    q = "created:>" + since
    if language:
        q += "+language:" + language
    url = ("https://api.github.com/search/repositories?q="
           + urllib.parse.quote(q)
           + "&sort=stars&order=desc&per_page=" + str(limit))
    body, status = _http_get(url, headers={"Accept": "application/vnd.github+json"})
    if body is None:
        return {"results": [], "error": status}
    try:
        data = json.loads(body.decode("utf-8", errors="replace"))
    except Exception as e:
        return {"results": [], "error": "parse: " + type(e).__name__}
    items = data.get("items") or []
    out = []
    for it in items[:limit]:
        out.append({
            "title": (it.get("full_name") or "")[:160],
            "url": it.get("html_url") or "",
            "stars": it.get("stargazers_count", 0),
            "language": it.get("language") or "",
            "description": (it.get("description") or "")[:300],
            "created_at": it.get("created_at") or "",
        })
    return {"results": out, "days": days}


# ========= HACKER NEWS =========
def hn_top(limit=15):
    """HN top stories via Firebase. First `limit` items."""
    url_top = "https://hacker-news.firebaseio.com/v0/topstories.json"
    body, status = _http_get(url_top)
    if body is None:
        return {"results": [], "error": status}
    try:
        ids = json.loads(body.decode("utf-8", errors="replace"))
    except Exception as e:
        return {"results": [], "error": "parse top: " + type(e).__name__}
    out = []
    for i in ids[:limit]:
        url = "https://hacker-news.firebaseio.com/v0/item/" + str(i) + ".json"
        b, st = _http_get(url)
        if b is None:
            continue
        try:
            d = json.loads(b.decode("utf-8", errors="replace"))
        except Exception:
            continue
        if not d or not d.get("title"):
            continue
        out.append({
            "title": (d.get("title") or "")[:220],
            "url": d.get("url") or ("https://news.ycombinator.com/item?id=" + str(i)),
            "score": d.get("score", 0),
            "comments": d.get("descendants", 0),
            "hn_id": i,
            "date": d.get("time", 0),
        })
    return {"results": out}


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: research_feeds.py <reddit|habr|github|hn> [args]")
        sys.exit(1)
    mode = sys.argv[1]
    if mode == "reddit":
        sub = sys.argv[2] if len(sys.argv) > 2 else "Entrepreneur"
        d = reddit_feed(sub)
    elif mode == "habr":
        d = habr_feed()
    elif mode == "github":
        d = github_trending()
    elif mode == "hn":
        d = hn_top()
    else:
        print("unknown mode: " + mode)
        sys.exit(2)
    print(json.dumps(d, ensure_ascii=False, indent=2))
