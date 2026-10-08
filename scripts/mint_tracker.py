"""Mint tracker: PumpPortal new-token + trade stream for 3 mints, 120s."""
import sys, json, ssl, time, asyncio
from pathlib import Path
from collections import defaultdict
import certifi, websockets

ROOT = Path(__file__).resolve().parent.parent
SSL_CTX = ssl.create_default_context(cafile=certifi.where())
JOURNAL = ROOT / ".runtime" / "mint_trades.jsonl"
JOURNAL.parent.mkdir(parents=True, exist_ok=True)

async def watch(seconds=120, n_watch=3):
    url = "wss://pumpportal.fun/api/data"
    watched, trades, meta = [], defaultdict(list), {}
    t0 = time.time()
    print(f"=== mint_tracker {seconds}s, watching first {n_watch} mints ===")
    async with websockets.connect(url, ssl=SSL_CTX, open_timeout=10) as ws:
        await ws.send(json.dumps({"method": "subscribeNewToken"}))
        while time.time() - t0 < seconds:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=15)
                d = json.loads(msg)
                tx_type = d.get("txType")
                mint = d.get("mint")
                if tx_type == "create" and len(watched) < n_watch:
                    watched.append(mint)
                    meta[mint] = {"symbol": d.get("symbol"), "created_ts": int(time.time())}
                    await ws.send(json.dumps({
                        "method": "subscribeTokenTrade",
                        "keys": [mint],
                    }))
                    print(f"  [WATCH] {d.get('symbol'):12} {mint[:8]}..")
                elif mint in watched and tx_type in ("buy", "sell"):
                    rec = {
                        "ts": int(time.time()),
                        "mint": mint,
                        "side": tx_type,
                        "sol": d.get("solAmount"),
                        "tokens": d.get("tokenAmount"),
                        "mcSol": d.get("marketCapSol"),
                        "trader": d.get("traderPublicKey"),
                    }
                    trades[mint].append(rec)
                    with open(JOURNAL, "a") as f:
                        f.write(json.dumps(rec) + "\n")
                    print(f"    [{tx_type:4}] {meta[mint]['symbol']:12} "
                          f"sol={d.get('solAmount'):.3f} "
                          f"mcSol={d.get('marketCapSol'):.1f}")
            except asyncio.TimeoutError:
                pass
    print(f"\n=== summary ===")
    for m in watched:
        ts = trades[m]
        if not ts:
            print(f"  {meta[m]['symbol']:12} 0 trades (DEAD)")
            continue
        mc0, mc1 = ts[0]["mcSol"], ts[-1]["mcSol"]
        buys = sum(1 for t in ts if t["side"] == "buy")
        sells = sum(1 for t in ts if t["side"] == "sell")
        chg = (mc1 / mc0 - 1) * 100 if mc0 else 0
        print(f"  {meta[m]['symbol']:12} {len(ts):3d} trades  "
              f"buy/sell={buys}/{sells}  mcSol {mc0:.1f}->{mc1:.1f} ({chg:+.1f}%)")

if __name__ == "__main__":
    sec = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    asyncio.run(watch(sec, n_watch=3))
