"""WS diag: subscribeTokenTrade on known live mints + subscribeNewToken."""
import sys, json, ssl, time, asyncio
from pathlib import Path
import certifi, websockets

ROOT = Path(__file__).resolve().parent.parent
SSL_CTX = ssl.create_default_context(cafile=certifi.where())

# Known graduated / live mints
SOL_MINT  = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

async def diag(seconds=60):
    url = "wss://pumpportal.fun/api/data"
    t0 = time.time()
    n_create, n_trade, n_other = 0, 0, 0
    print(f"=== ws_diag {seconds}s ===")
    async with websockets.connect(url, ssl=SSL_CTX, open_timeout=10) as ws:
        # 1. new token
        await ws.send(json.dumps({"method": "subscribeNewToken"}))
        print("  sent subscribeNewToken")
        # 2. trades on known mints
        await ws.send(json.dumps({
            "method": "subscribeTokenTrade",
            "keys": [SOL_MINT, USDC_MINT],
        }))
        print(f"  sent subscribeTokenTrade on SOL + USDC")
        # 3. account trade stream (все трейды всех токенов — не знаем, есть ли)
        try:
            await ws.send(json.dumps({"method": "subscribeAccountTrade",
                                     "keys": []}))
            print("  sent subscribeAccountTrade (empty — checking response)")
        except Exception as e:
            print(f"  subscribeAccountTrade ERR: {e!r}")

        while time.time() - t0 < seconds:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=15)
                try:
                    d = json.loads(msg)
                except Exception:
                    print(f"  [RAW] {msg[:200]}")
                    continue
                # errors / info messages
                if "error" in d or "message" in d:
                    print(f"  [SRV] {json.dumps(d)[:200]}")
                    continue
                tx = d.get("txType")
                if tx == "create":
                    n_create += 1
                    if n_create <= 3:
                        print(f"  [CREATE] {d.get('symbol'):12} mint={str(d.get('mint'))[:8]}..")
                elif tx in ("buy", "sell"):
                    n_trade += 1
                    if n_trade <= 10:
                        print(f"  [TRADE ] {tx:4} mint={str(d.get('mint'))[:8]}.. "
                              f"sol={d.get('solAmount')} mcSol={d.get('marketCapSol')}")
                else:
                    n_other += 1
                    if n_other <= 5:
                        print(f"  [OTHER] keys={list(d.keys())[:6]}")
            except asyncio.TimeoutError:
                print("  (no msg in 15s)")
    print(f"\n=== summary: create={n_create} trade={n_trade} other={n_other} in {time.time()-t0:.1f}s ===")

if __name__ == "__main__":
    sec = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    asyncio.run(diag(sec))
