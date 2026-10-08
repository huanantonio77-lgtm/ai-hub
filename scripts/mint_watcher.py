"""Mint watcher: PumpPortal WS stream of new token creations."""
import sys, json, ssl, time, asyncio
from pathlib import Path
import certifi, websockets

ROOT = Path(__file__).resolve().parent.parent
SSL_CTX = ssl.create_default_context(cafile=certifi.where())
JOURNAL = ROOT / ".runtime" / "mint_watch.jsonl"
JOURNAL.parent.mkdir(parents=True, exist_ok=True)

async def watch(seconds=60):
    url = "wss://pumpportal.fun/api/data"
    n = 0; t0 = time.time()
    print(f"=== mint_watcher {seconds}s ===")
    async with websockets.connect(url, ssl=SSL_CTX, open_timeout=10) as ws:
        await ws.send(json.dumps({"method": "subscribeNewToken"}))
        while time.time() - t0 < seconds:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=15)
                d = json.loads(msg)
                if d.get("txType") != "create": continue
                rec = {
                    "ts": int(time.time()),
                    "mint": d.get("mint"),
                    "symbol": d.get("symbol"),
                    "name": d.get("name"),
                    "dev": d.get("traderPublicKey"),
                    "mcSol": d.get("marketCapSol"),
                    "uri": d.get("uri"),
                }
                with open(JOURNAL, "a") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n += 1
                if n % 5 == 0:
                    print(f"  [{n:3d}] {str(rec['symbol'])[:15]:15} "
                          f"mcSol={rec['mcSol']:.1f} dev={str(rec['dev'])[:8]}..")
            except asyncio.TimeoutError:
                pass
    print(f"=== done: {n} mints in {time.time()-t0:.1f}s ===")

if __name__ == "__main__":
    sec = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    asyncio.run(watch(sec))
