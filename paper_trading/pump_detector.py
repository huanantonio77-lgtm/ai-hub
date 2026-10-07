"""S3: new Solana tokens via Jupiter recent (pump.fun frontend is dead).

Replaces broken pump.fun frontend-api (HTTP 530 global). Uses
data_layer.recent_tokens (Jupiter lite-api, US-friendly).
Persists seen mints in .runtime/pump_seen.json.
"""
from __future__ import annotations
import json, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEEN = ROOT / ".runtime" / "pump_seen.json"
SEEN.parent.mkdir(parents=True, exist_ok=True)

def _load_seen() -> set:
    if not SEEN.exists():
        return set()
    try:
        return set(json.loads(SEEN.read_text()).get("mints", []))
    except Exception:
        return set()

def _save_seen(mints: set) -> None:
    SEEN.write_text(json.dumps({
        "updated": int(time.time()),
        "mints": sorted(mints)[-5000:],
    }))

def detect_new(limit: int = 50) -> list:
    """Return list of new mints since last call. Updates seen file."""
    from paper_trading.data_layer import recent_tokens
    try:
        items = recent_tokens(limit=limit)
    except Exception as e:
        print(f"[pump_detector] fetch failed: {e!r}")
        return []
    seen = _load_seen()
    fresh = []
    for c in items or []:
        mint = c.get("id") or c.get("address") or c.get("mint")
        if not mint or mint in seen:
            continue
        fresh.append({
            "mint": mint,
            "symbol": c.get("symbol"),
            "name": c.get("name"),
            "decimals": c.get("decimals"),
            "usd_market_cap": c.get("mcap") or c.get("usd_market_cap"),
            "ts": int(time.time() * 1000),
        })
        seen.add(mint)
    if fresh:
        _save_seen(seen)
    return fresh

def smoke(n_rounds: int = 2, sleep_s: int = 5) -> None:
    print(f"pump_detector smoke: {n_rounds} rounds, {sleep_s}s apart")
    total = 0
    for i in range(n_rounds):
        fresh = detect_new(limit=50)
        print(f"  round {i+1}: {len(fresh)} new mints")
        for f in fresh[:3]:
            print(f"    {f['symbol']:12} {f.get('name','')[:20]:20} "
                  f"mint={f['mint'][:8]}...")
        total += len(fresh)
        if i < n_rounds - 1:
            time.sleep(sleep_s)
    print(f"smoke: total {total} new mints across {n_rounds} rounds")
