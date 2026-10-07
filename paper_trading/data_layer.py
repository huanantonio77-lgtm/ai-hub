"""Solana data layer - Jupiter Lite API (free, US-friendly).

Replaces broken pump.fun frontend-api. Real endpoints:
  - price v3:    /price/v3?ids=mint1,mint2
  - quote:       /swap/v1/quote?inputMint=X&outputMint=Y&amount=N
  - recent:      /tokens/v2/recent   (new tokens - S3 source)
  - search:      /tokens/v2/search?query=SYM
"""
from __future__ import annotations
import json, ssl, time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode
import certifi

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://lite-api.jup.ag"
_SSL = ssl.create_default_context(cafile=certifi.where())
_UA = {"User-Agent": "Mozilla/5.0 ai-hub/1.0", "Accept": "application/json"}

SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

def _get(path: str, params: dict | None = None, timeout: int = 10):
    url = BASE + path
    if params:
        url += "?" + urlencode(params)
    req = Request(url, headers=_UA)
    with urlopen(req, timeout=timeout, context=_SSL) as r:
        return json.loads(r.read())

def price(mints: list[str]) -> dict:
    """Price v3. Returns {mint: {usdPrice, ...}}."""
    if not mints: return {}
    return _get("/price/v3", {"ids": ",".join(mints)})

def quote(input_mint: str, output_mint: str, amount_lamports: int,
          slippage_bps: int = 50) -> dict:
    """Swap quote. Returns {outAmount, priceImpactPct, routePlan, ...}."""
    return _get("/swap/v1/quote", {
        "inputMint": input_mint, "outputMint": output_mint,
        "amount": str(amount_lamports),
        "slippageBps": str(slippage_bps),
    })

def recent_tokens(limit: int = 50) -> list:
    """Recent tokens (S3: new-pool detector). Returns list of dicts."""
    try:
        return _get("/tokens/v2/recent")
    except Exception as e:
        print(f"[data_layer] recent_tokens failed: {e!r}")
        return []

def search(query: str) -> list:
    """Search tokens by symbol/name."""
    try:
        r = _get("/tokens/v2/search", {"query": query})
        return r if isinstance(r, list) else []
    except Exception as e:
        print(f"[data_layer] search failed: {e!r}")
        return []

def smoke() -> None:
    print("=== data_layer smoke ===")
    p = price([SOL_MINT, USDC_MINT])
    print(f"price: {len(p)} mints")
    for m, d in list(p.items())[:2]:
        print(f"  {m[:8]}... -> ${d.get('usdPrice')}")

    q = quote(SOL_MINT, USDC_MINT, 1_000_000_000)  # 1 SOL
    print(f"quote 1 SOL -> USDC: out={q.get('outAmount')} "
          f"impact={q.get('priceImpactPct')}")

    rec = recent_tokens()
    print(f"recent tokens: {len(rec)}")
    for t in rec[:5]:
        print(f"  {t.get('symbol','?'):12} {t.get('name','')[:20]:20} "
              f"id={t.get('id','')[:8]}...")
