#!/usr/bin/env python3
"""research.py - поисковый инструмент ai-hub.
Использует Tavily API (.secrets/tavily_api_key.txt).
Команды:
  research.py search <запрос>   - общий поиск
  research.py github <запрос>   - только github.com
  research.py reddit <запрос>   - только reddit.com
  research.py habr <запрос>     - только habr.com
  research.py vc <запрос>       - только vc.ru
  research.py reddit_feed <sub> - Reddit JSON лента (0 LLM)
  research.py habr_feed         - Habr RSS лента (0 LLM)
  research.py github_trending [lang] - GitHub trending
  research.py hn_top            - Hacker News top
"""

import sys, json, urllib.request, ssl
_ctx = ssl._create_unverified_context()
from pathlib import Path

ROOT = Path.home() / "Desktop/ai-hub"
KEY_FILE = ROOT / ".secrets" / "tavily_api_key.txt"

def load_key():
    if not KEY_FILE.exists():
        print("ERROR: нет", KEY_FILE); sys.exit(2)
    return KEY_FILE.read_text().strip()

def search(query, max_results=6, include_domains=None):
    """Единый поиск через search_backends (Rule №1 п.3, Шаг 3).

    env RESEARCH_BACKEND:
      auto (default) -> order из strategy/search_backends.json (ddg -> tavily -> brave)
      tavily         -> только Tavily (старое поведение)
      duckduckgo     -> только DDG
    """
    import os as _os
    backend = _os.environ.get("RESEARCH_BACKEND", "auto")
    try:
        import search_backends
        return search_backends.search(
            query,
            max_results=max_results,
            include_domains=include_domains,
            backend=backend,
        )
    except Exception as e:
        print("ERROR: search_backends: " + type(e).__name__ + ": " + str(e)[:160])
        return {"results": [], "backend": None}

def main():
    # s124-stage6.5: feed modes (0 LLM, structured)
    if len(sys.argv) >= 2 and sys.argv[1] in (
            "reddit_feed", "habr_feed", "github_trending", "hn_top"):
        try:
            import research_feeds as _rf
        except Exception as _e:
            print("ERROR: research_feeds: " + type(_e).__name__)
            sys.exit(2)
        mode = sys.argv[1]
        if mode == "reddit_feed":
            sub = sys.argv[2] if len(sys.argv) > 2 else "Entrepreneur"
            d = _rf.reddit_feed(sub)
        elif mode == "habr_feed":
            d = _rf.habr_feed()
        elif mode == "github_trending":
            lang = sys.argv[2] if len(sys.argv) > 2 else None
            d = _rf.github_trending(language=lang)
        else:
            d = _rf.hn_top()
        print("=== " + mode.upper() + " ===")
        if d.get("error"):
            print("ERROR: " + str(d["error"]))
        for i, r in enumerate(d.get("results") or [], 1):
            print("[" + str(i) + "] " + (r.get("title") or ""))
            print("    " + (r.get("url") or ""))
            extras = []
            for k in ("score", "comments", "stars", "language", "author", "date"):
                if r.get(k) not in (None, "", 0):
                    extras.append(k + "=" + str(r[k]))
            if extras:
                print("    " + "  ".join(extras))
            sn = (r.get("snippet") or r.get("description") or "")[:240]
            if sn:
                print("    " + sn)
            print()
        return

    if len(sys.argv) < 3:
        print("usage: research.py <mode> <query>")
        print("  modes: search, github, reddit, habr, vc")
        sys.exit(1)
    mode = sys.argv[1]
    query = " ".join(sys.argv[2:])
    domains = {
        "github": ["github.com"],
        "reddit": ["reddit.com"],
        "habr": ["habr.com"],
        "vc": ["vc.ru"],
    }.get(mode)
    data = search(query, max_results=6, include_domains=domains)
    results = data.get("results", [])
    print("=== " + mode.upper() + ": " + query + " ===")
    for i, r in enumerate(results, 1):
        print("[" + str(i) + "] " + (r.get("title") or ""))
        print("    " + (r.get("url") or ""))
        snippet = (r.get("content") or r.get("snippet") or "")[:300]
        print("    " + snippet)
        print()

if __name__ == "__main__":
    main()