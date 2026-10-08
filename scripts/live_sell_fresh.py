#!/usr/bin/env python3
# live_sell_fresh.py - sell with fresh blockhash (fix BlockhashNotFound)
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
from solders.message import MessageV0
from solders.hash import Hash
raw = (ROOT / ".runtime" / "wallet" / "live_keypair.json").read_text().strip()
if raw.startswith("["):
    kp = Keypair.from_bytes(bytes(json.loads(raw)))
else:
    import base58
    kp = Keypair.from_bytes(base58.b58decode(raw))
mint = sys.argv[1]
print(f"wallet: {kp.pubkey()}")
print(f"mint: {mint}")

def rpc_post(body):
    req = Request(RPC, data=json.dumps(body).encode(), headers={"Content-Type":"application/json"})
    return json.loads(urlopen(req, timeout=20, context=CTX).read())

def fetch_fresh_blockhash():
    r = rpc_post({"jsonrpc":"2.0","id":1,"method":"getLatestBlockhash","params":[{"commitment":"finalized"}]})
    return r["result"]["value"]["blockhash"]

def fetch_tx_from_pumpportal():
    body = {"publicKey": str(kp.pubkey()), "action": "sell", "mint": mint, "amount": "100%", "denominatedInSol": "false", "slippage": 15, "priorityFee": 0.0001, "pool": "pump"}
    url = f"https://pumpportal.fun/api/trade-local?api-key={API_KEY}"
    req = Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return urlopen(req, timeout=20, context=CTX).read()

def send_with_retry(sig_b64):
    rpc_body = {"jsonrpc":"2.0","id":1,"method":"sendTransaction","params":[sig_b64, {"encoding":"base64","skipPreflight":True,"maxRetries":5}]}
    return rpc_post(rpc_body)

for attempt in range(1, 6):
    print(f"--- attempt {attempt} ---")
    fresh_bh = fetch_fresh_blockhash()
    print(f"fresh blockhash: {fresh_bh[:8]}...")
    try:
        raw_tx = fetch_tx_from_pumpportal()
    except Exception as e:
        print(f"pumpportal err: {e}")
        continue
    try:
        tx = VersionedTransaction.from_bytes(raw_tx)
    except Exception as e:
        print(f"parse err: {e}"); continue
    msg = tx.message
    new_msg = MessageV0(
        header=msg.header,
        account_keys=msg.account_keys,
        recent_blockhash=Hash.from_string(fresh_bh),
        instructions=msg.instructions,
        address_table_lookups=msg.address_table_lookups,
    )
    new_tx = VersionedTransaction(new_msg, [kp])
    sig_b64 = base64.b64encode(bytes(new_tx)).decode()
    r2 = send_with_retry(sig_b64)
    if "result" in r2:
        sig = r2["result"]
        print(f"SUCCESS SELL: https://solscan.io/tx/{sig}")
        rec = {"ts": time.time(), "mint": mint, "action": "sell", "sig": sig, "wallet": str(kp.pubkey())}
        with (ROOT / ".runtime" / "live_trades.jsonl").open("a") as fh:
            fh.write(json.dumps(rec) + chr(10))
        sys.exit(0)
    print(f"err: {json.dumps(r2)[:200]}")
    time.sleep(2)
print("all attempts failed")
sys.exit(1)
