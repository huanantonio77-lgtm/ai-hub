#!/usr/bin/env python3
# live_sell.py - sell ALL of a given mint on pump.fun
import sys, os, json, ssl, time, pathlib, base64
from urllib.request import Request, urlopen
ROOT = pathlib.Path(__file__).resolve().parent.parent
env = {}
for l in (ROOT / ".env").read_text().splitlines():
    if "=" in l and not l.startswith("#"):
        k, v = l.split("=", 1)
        env[k.strip()] = v.strip()
API_KEY = env["PUMPPORTAL_API_KEY"]
RPC = env.get("HELIUS_RPC") or env.get("CHAINSTACK_RPC") or env.get("QUICKNODE_RPC")
import certifi
CTX = ssl.create_default_context(cafile=certifi.where())
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
raw = (ROOT / ".runtime" / "wallet" / "live_keypair.json").read_text().strip()
if raw.startswith("["):
    kp = Keypair.from_bytes(bytes(json.loads(raw)))
else:
    import base58
    kp = Keypair.from_bytes(base58.b58decode(raw))
print(f"wallet: {kp.pubkey()}")
mint = sys.argv[1]
print(f"mint: {mint}")
body = {
    "publicKey": str(kp.pubkey()),
    "action": "sell",
    "mint": mint,
    "amount": "100%",
    "denominatedInSol": "false",
    "slippage": 15,
    "priorityFee": 0.0001,
    "pool": "pump",
}
url = f"https://pumpportal.fun/api/trade-local?api-key={API_KEY}"
req = Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
try:
    resp = urlopen(req, timeout=20, context=CTX)
    raw_tx = resp.read()
except Exception as e:
    print(f"trade-local failed: {e}")
    try: print(e.read().decode()[:300])
    except Exception: pass
    sys.exit(1)
print(f"raw_tx bytes: {len(raw_tx)}")
tx = VersionedTransaction.from_bytes(raw_tx)
signed = VersionedTransaction(tx.message, [kp])
sig_b64 = base64.b64encode(bytes(signed)).decode()
if os.environ.get("DRY_RUN") == "1":
    print("DRY_RUN - not sending")
    sys.exit(0)
rpc_body = {"jsonrpc":"2.0","id":1,"method":"sendTransaction","params":[sig_b64,{"encoding":"base64","skipPreflight":False,"maxRetries":3}]}
req2 = Request(RPC, data=json.dumps(rpc_body).encode(), headers={"Content-Type": "application/json"})
try:
    r2 = json.loads(urlopen(req2, timeout=20, context=CTX).read())
except Exception as e:
    print(f"send failed: {e}"); sys.exit(1)
if "result" in r2:
    sig = r2["result"]
    print(f"SUCCESS SELL: https://solscan.io/tx/{sig}")
    rec = {"ts": time.time(), "mint": mint, "action": "sell", "sig": sig, "wallet": str(kp.pubkey())}
    with (ROOT / ".runtime" / "live_trades.jsonl").open("a") as fh:
        fh.write(json.dumps(rec) + chr(10))
    print(f"logged")
else:
    print(f"RPC err: {json.dumps(r2)[:300]}")
    sys.exit(1)
