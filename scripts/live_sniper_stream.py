#!/usr/bin/env python3
# live_sniper_stream.py - listen for fresh pump.fun create + buy immediately.
import asyncio, json, ssl, sys, time, pathlib, base64
from urllib.request import Request, urlopen
import certifi, websockets
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
ROOT = pathlib.Path(__file__).resolve().parent.parent
env = {}
for l in (ROOT / ".env").read_text().splitlines():
    if "=" in l and not l.startswith("#"):
        k, v = l.split("=", 1)
        env[k.strip()] = v.strip()
API_KEY = env["PUMPPORTAL_API_KEY"]
RPC = env.get("HELIUS_RPC") or env.get("CHAINSTACK_RPC") or env.get("QUICKNODE_RPC")
CTX = ssl.create_default_context(cafile=certifi.where())
WS = "wss://pumpportal.fun/api/data"
raw = (ROOT / ".runtime" / "wallet" / "live_keypair.json").read_text().strip()
if raw.startswith("["):
    kp = Keypair.from_bytes(bytes(json.loads(raw)))
else:
    import base58
    kp = Keypair.from_bytes(base58.b58decode(raw))
MIN_DEV = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0
AMOUNT = float(sys.argv[2]) if len(sys.argv) > 2 else 0.003
DUR = int(sys.argv[3]) if len(sys.argv) > 3 else 120
DRY = os.environ.get("DRY_RUN") == "1" if False else False
import os as _os
DRY = _os.environ.get("DRY_RUN") == "1"

def do_buy(mint):
    body = {"publicKey": str(kp.pubkey()), "action": "buy", "mint": mint, "amount": AMOUNT, "denominatedInSol": "true", "slippage": 15, "priorityFee": 0.0001, "pool": "pump"}
    url = f"https://pumpportal.fun/api/trade-local?api-key={API_KEY}"
    req = Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        raw_tx = urlopen(req, timeout=20, context=CTX).read()
    except Exception as e:
        print(f"  trade-local failed: {e}")
        try: print(e.read().decode()[:300])
        except Exception: pass
        return None
    try:
        tx = VersionedTransaction.from_bytes(raw_tx)
    except Exception as e:
        print(f"  parse fail: {e}")
        return None
    signed = VersionedTransaction(tx.message, [kp])
    sig_b64 = base64.b64encode(bytes(signed)).decode()
    if DRY:
        print(f"  DRY_RUN - not sending, sig_b64_len={len(sig_b64)}")
        return "DRY"
    rpc_body = {"jsonrpc":"2.0","id":1,"method":"sendTransaction","params":[sig_b64,{"encoding":"base64","skipPreflight":False,"maxRetries":3}]}
    req2 = Request(RPC, data=json.dumps(rpc_body).encode(), headers={"Content-Type": "application/json"})
    try:
        r2 = json.loads(urlopen(req2, timeout=20, context=CTX).read())
    except Exception as e:
        print(f"  send failed: {e}")
        return None
    if "result" in r2:
        sig = r2["result"]
        print(f"  SUCCESS: https://solscan.io/tx/{sig}")
        rec = {"ts": time.time(), "mint": mint, "action": "buy", "amount_sol": AMOUNT, "sig": sig, "wallet": str(kp.pubkey())}
        with (ROOT / ".runtime" / "live_trades.jsonl").open("a") as fh:
            fh.write(json.dumps(rec) + chr(10))
        return sig
    print(f"  RPC err: {json.dumps(r2)[:300]}")
    return None

async def main():
    print(f"live_sniper_stream MIN_DEV={MIN_DEV} AMOUNT={AMOUNT} DUR={DUR}s DRY={DRY}")
    print(f"wallet: {kp.pubkey()}")
    t0 = time.time()
    async with websockets.connect(WS, ssl=CTX, ping_interval=20) as ws:
        await ws.send(json.dumps({"method": "subscribeNewToken"}))
        print("subscribed, waiting for fresh mint...")
        while time.time() - t0 < DUR:
            task = asyncio.create_task(ws.recv())
            done, pending = await asyncio.wait({task}, timeout=15)
            if task not in done:
                for p in pending:
                    p.cancel()
                continue
            try:
                msg = task.result()
            except Exception:
                break
            try: d = json.loads(msg)
            except Exception: continue
            if d.get("txType") != "create": continue
            mint = d.get("mint","")
            dev = float(d.get("solAmount",0) or 0)
            if dev >= MIN_DEV:
                print(f"")
                print(f"[{time.time()-t0:.1f}s] CAND {mint[:12]}... dev={dev:.3f}")
                print(f"  firing {AMOUNT} SOL...")
                sig = do_buy(mint)
                if sig:
                    print(f"  LIVE sig={sig}")
                    return
                else:
                    print(f"  failed, continuing...")
    print("window ended, no buy")

asyncio.run(main())
