#!/usr/bin/env python3
# live_sniper_full.py - one full live cycle: buy -> hold -> sell.
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

MIN_DEV = float(sys.argv[1]) if len(sys.argv) > 1 else 2.0
AMOUNT = float(sys.argv[2]) if len(sys.argv) > 2 else 0.003
HOLD_S = int(sys.argv[3]) if len(sys.argv) > 3 else 120
TARGET = 0.5
STOP = -0.3
SLIPPAGE = 15

from solders.message import MessageV0
from solders.hash import Hash

def rpc_post(body):
    req = Request(RPC, data=json.dumps(body).encode(), headers={"Content-Type":"application/json"})
    return json.loads(urlopen(req, timeout=20, context=CTX).read())

def fetch_fresh_blockhash():
    r = rpc_post({"jsonrpc":"2.0","id":1,"method":"getLatestBlockhash","params":[{"commitment":"finalized"}]})
    return r["result"]["value"]["blockhash"]

def send_tx(body):
    url = f"https://pumpportal.fun/api/trade-local?api-key={API_KEY}"
    for attempt in range(1, 4):
        print(f"  attempt {attempt}...")
        try:
            fresh_bh = fetch_fresh_blockhash()
        except Exception as e:
            print(f"  blockhash err: {e}"); continue
        req = Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        try:
            raw_tx = urlopen(req, timeout=20, context=CTX).read()
        except Exception as e:
            try: print(f"  trade-local err: {e.read().decode()[:200]}")
            except Exception: print(f"  trade-local err: {e}")
            continue
        try:
            tx = VersionedTransaction.from_bytes(raw_tx)
        except Exception as e:
            print(f"  parse err: {e}"); continue
        msg = tx.message
        new_msg = MessageV0(
            header=msg.header,
            account_keys=msg.account_keys,
            recent_blockhash=Hash.from_string(fresh_bh),
            instructions=msg.instructions,
            address_table_lookups=msg.address_table_lookups,
        )
        signed = VersionedTransaction(new_msg, [kp])
        sig_b64 = base64.b64encode(bytes(signed)).decode()
        rpc_body = {"jsonrpc":"2.0","id":1,"method":"sendTransaction","params":[sig_b64,{"encoding":"base64","skipPreflight":True,"maxRetries":5}]}
        try:
            r2 = rpc_post(rpc_body)
        except Exception as e:
            print(f"  rpc err: {e}"); continue
        if "result" in r2:
            return r2["result"]
        print(f"  rpc err: {json.dumps(r2)[:200]}")
        time.sleep(2)
    return None

def buy(mint):
    body = {"publicKey": str(kp.pubkey()), "action": "buy", "mint": mint, "amount": AMOUNT, "denominatedInSol": "true", "slippage": SLIPPAGE, "priorityFee": 0.0001, "pool": "pump"}
    print(f"  BUY {AMOUNT} SOL...")
    return send_tx(body)

def sell(mint):
    body = {"publicKey": str(kp.pubkey()), "action": "sell", "mint": mint, "amount": "100%", "denominatedInSol": "false", "slippage": SLIPPAGE, "priorityFee": 0.0001, "pool": "pump"}
    print(f"  SELL 100%...")
    return send_tx(body)

def get_sol():
    b={"jsonrpc":"2.0","id":1,"method":"getBalance","params":[str(kp.pubkey())]}
    r=json.loads(urlopen(Request(RPC,data=json.dumps(b).encode(),headers={"Content-Type":"application/json"}),timeout=10,context=CTX).read())
    return r.get("result",{}).get("value",0)/1e9

def log(rec):
    with (ROOT / ".runtime" / "live_trades.jsonl").open("a") as fh:
        fh.write(json.dumps(rec) + chr(10))

async def main():
    print(f"live_sniper_full MIN_DEV={MIN_DEV} AMOUNT={AMOUNT} HOLD={HOLD_S}s")
    print(f"wallet: {kp.pubkey()}")
    print(f"balance: {get_sol():.6f} SOL")
    t0 = time.time()
    async with websockets.connect(WS, ssl=CTX, ping_interval=20, ping_timeout=30) as ws:
        await ws.send(json.dumps({"method": "subscribeNewToken"}))
        print("waiting for mint...")
        while time.time() - t0 < 180:
            task = asyncio.create_task(ws.recv())
            done, pend = await asyncio.wait({task}, timeout=20)
            if task not in done:
                for p in pend: p.cancel()
                continue
            try: msg = task.result()
            except Exception: break
            try: d = json.loads(msg)
            except Exception: continue
            if d.get("txType") != "create": continue
            mint = d.get("mint","")
            dev = float(d.get("solAmount",0) or 0)
            if dev < MIN_DEV: continue
            print(f"[{time.time()-t0:.1f}s] CAND {mint[:12]}... dev={dev:.3f}")
            sig_buy = buy(mint)
            if not sig_buy:
                print("  buy failed, continue"); continue
            print(f"  BUY OK: https://solscan.io/tx/{sig_buy}")
            log({"ts":time.time(),"mint":mint,"action":"buy","amount_sol":AMOUNT,"sig":sig_buy,"wallet":str(kp.pubkey())})
            bal_after_buy = get_sol()
            print(f"  balance after buy: {bal_after_buy:.6f}")
            print(f"  holding {HOLD_S}s...")
            await asyncio.sleep(HOLD_S)
            sig_sell = sell(mint)
            if not sig_sell:
                print("  sell failed, MANUAL SELL NEEDED"); return
            print(f"  SELL OK: https://solscan.io/tx/{sig_sell}")
            log({"ts":time.time(),"mint":mint,"action":"sell","sig":sig_sell,"wallet":str(kp.pubkey())})
            await asyncio.sleep(5)
            bal_after_sell = get_sol()
            print(f"  balance after sell: {bal_after_sell:.6f}")
            delta = bal_after_sell - bal_after_buy
            net = bal_after_sell - (bal_after_buy + AMOUNT)
            print(f"  CYCLE COMPLETE: buy->sell delta={delta:+.6f} SOL")
            return
    print("window ended, no buy")

asyncio.run(main())
