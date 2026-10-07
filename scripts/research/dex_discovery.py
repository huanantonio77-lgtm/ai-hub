#!/usr/bin/env python3
"""dex_discovery — автоматический поиск DEX через search_works + LLM 3B.

Использует websearch (webless+ddgs), НЕ deep_dive (s194-r2).
Задача: собрать имена DEX из веб-сниппетов и сравнить с registry.

CLI:
  python3 scripts/research/dex_discovery.py            # dry
  python3 scripts/research/dex_discovery.py --apply    # write JSON+MD
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "research"))

from websearch_client import search_works  # noqa: E402


QUERIES = [
    "complete list of decentralized exchanges 2026",
    "top DEX by volume 2026 perpetuals spot",
    "all DEX protocols list API trading",
    "DEX comparison 2026 Hyperliquid dYdX Jupiter",
    "perpetual DEX list 2026 ranking",
    "AMM DEX list Uniswap PancakeSwap Curve Balancer",
    "Solana DEX list Jupiter Raydium Orca Meteora",
    "Cosmos DEX list Osmosis Astroport",
    "new DEX 2026 launch protocol",
    "DEX aggregator 1inch 0x KyberSwap CoW Swap",
]

# Known names — match against snippets
KNOWN = [
    # already in registry
    "Hyperliquid", "dYdX", "Paradex",
    # from user list
    "Aevo", "ApeX", "Lighter", "Decibel", "Injective", "Vertex", "Synthetix",
    "GMX", "gTrade", "Gains", "Ostium", "Nado", "Extended", "Kinetiq",
    "Drift", "Phoenix", "AFX", "Uniswap", "PancakeSwap", "SushiSwap",
    "Curve", "Balancer", "KyberSwap", "1inch", "0x", "ParaSwap", "Velora",
    "CoW Swap", "Matcha", "Jupiter", "Raydium", "Orca", "Meteora", "Lifinity",
    "Saber", "OpenBook", "Osmosis", "Astroport", "White Whale", "Crescent",
    "Noether", "Archon", "Dexalot", "Sei",
]


def collect() -> list[dict]:
    all_items = []
    seen = set()
    for q in QUERIES:
        try:
            r = search_works(q, max_results=8)
            for it in r:
                url = (it.get("url") or "").strip()
                if url and url not in seen:
                    seen.add(url)
                    all_items.append({
                        "q": q,
                        "title": (it.get("title") or "")[:200],
                        "url": url,
                        "snippet": (it.get("snippet") or "")[:300],
                        "via": it.get("via") or "",
                    })
        except Exception as e:
            print(f"  ERR q={q[:50]}: {type(e).__name__}: {str(e)[:80]}",
                  file=sys.stderr)
        time.sleep(0.5)
    return all_items


def find_known(items: list[dict]) -> dict:
    """Match known names in titles+snippets."""
    hits = {}
    for name in KNOWN:
        pat = re.compile(r"\b" + re.escape(name) + r"\b", re.IGNORECASE)
        cnt = 0
        urls = []
        for it in items:
            text = (it["title"] + " " + it["snippet"])
            if pat.search(text):
                cnt += 1
                if it["url"] not in urls:
                    urls.append(it["url"])
        if cnt > 0:
            hits[name] = {"mentions": cnt, "urls": urls[:5]}
    return hits


def get_registry_names() -> set:
    try:
        sys.path.insert(0, str(ROOT))
        from arbitrage_bot.app.exchanges.registry import REGISTRY
        return {e["name"].lower() for e in REGISTRY}
    except Exception:
        return set()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)

    print(f"queries: {len(QUERIES)}")
    items = collect()
    print(f"unique urls: {len(items)}")

    hits = find_known(items)
    print(f"known names matched: {len(hits)}")

    registry = get_registry_names()
    already = [n for n in hits if n.lower() in registry]
    new_cand = [n for n in hits if n.lower() not in registry]
    print(f"already in registry: {len(already)}")
    print(f"new candidates: {len(new_cand)}")

    result = {
        "ts": int(time.time()),
        "queries": len(QUERIES),
        "unique_urls": len(items),
        "known_matched": len(hits),
        "already_in_registry": already,
        "new_candidates": sorted(new_cand),
        "hits": hits,
        "items": items,
    }

    if not args.apply:
        print("dry-run only. use --apply to write.")
        print("\nnew candidates (top 20):")
        for n in sorted(new_cand)[:20]:
            print(f"  - {n} ({hits[n]['mentions']} mentions)")
        return 0

    out_json = ROOT / "knowledge" / "dex_discovery.json"
    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print("wrote:", out_json)

    md = ROOT / "self" / "curator" / "DEX_DISCOVERY.md"
    lines = [
        "# DEX DISCOVERY",
        "",
        f"Generated: {time.strftime('%Y-%m-%dT%H:%M:%S')}",
        f"Queries: {len(QUERIES)} | Unique URLs: {len(items)}",
        f"Known matched: {len(hits)} | Registry: {len(already)} | New: {len(new_cand)}",
        "",
        "## Already in registry",
        "",
    ]
    for n in sorted(already):
        lines.append(f"- ✅ {n}")
    lines += ["", "## New candidates", ""]
    for n in sorted(new_cand):
        h = hits[n]
        lines.append(f"- ⭐ **{n}** — {h['mentions']} mentions")
    lines += ["", "## URLs (all)", ""]
    for it in items:
        lines.append(f"- [{it['title'][:80]}]({it['url']})")
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote:", md)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
