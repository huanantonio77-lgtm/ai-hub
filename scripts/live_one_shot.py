#!/usr/bin/env python3
# live_one_shot.py v2 - rewritten with raw-bytes parsing.
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
if not RPC:
    print("no RPC in .env"); sys.exit(1)
import certifi
CTX = ssl.create_default_context(cafile=certifi.where())
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
kp_path = ROOT / ".runtime" / "wallet" / "live_keypair.json"
raw = kp_path.read_text().strip()
if raw.startswith("["):
    kp = Keypair.from_bytes(bytes(json.loads(raw)))
else:
    import base58
    kp = Keypair.from_bytes(base58.b58decode(raw))
print(f"wallet: {kp.pubkey()}")
mint = sys.argv[1]
amount = float(sys.argv[2]) if len(sys.argv) > 2 else 0.003
print(f"mint: {mint}")
print(f"mint_len: {len(mint)}")
if len(mint) not in (43, 44):
    print(f"BAD MINT LEN: {len(mint)}")
    sys.exit(2)
body = {
    "publicKey": str(kp.pubkey()),
    "action": "buy",
    "mint": mint,
    "amount": amount,
    "denominatedInSol": "true",
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
print(f"raw_tx head: {raw_tx[:8].hex()}")
try:
    tx = VersionedTransaction.from_bytes(raw_tx)
    print("parsed: VersionedTransaction")
except Exception as e1:
    try:
        from solders.transaction import Transaction
        tx = Transaction.from_bytes(raw_tx)
        print("parsed: legacy Transaction")
    except Exception as e2:
        print(f"parse fail: v={e1} | l={e2}")
        sys.exit(1)
print(f"msg sigs: {len(tx.signatures)}")
signed = VersionedTransaction(tx.message, [kp])
print(f"signed sig: {str(signed.signatures[0])[:44]}...")
sig_b64 = base64.b64encode(bytes(signed)).decode()
print(f"signed tx b64 len: {len(sig_b64)}")
if os.environ.get("DRY_RUN") == "1":
    print("DRY_RUN=1 - NOT sending")
    sys.exit(0)
rpc_body = {"jsonrpc": "2.0", "id": 1, "method": "sendTransaction", "params": [sig_b64, {"encoding": "base64", "skipPreflight": False, "maxRetries": 3}]}
req2 = Request(RPC, data=json.dumps(rpc_body).encode(), headers={"Content-Type": "application/json"})
try:
    r2 = json.loads(urlopen(req2, timeout=20, context=CTX).read())
except Exception as e:
    print(f"send failed: {e}"); sys.exit(1)
print(f"RPC resp: {json.dumps(r2)[:200]}")
if "result" in r2:
    sig = r2["result"]
    print(f"SUCCESS: https://solscan.io/tx/{sig}")
    rec = {"ts": time.time(), "mint": mint, "action": "buy", "amount_sol": amount, "sig": sig, "wallet": str(kp.pubkey())}
    log = ROOT / ".runtime" / "live_trades.jsonl"
    with log.open("a") as fh:
        fh.write(json.dumps(rec) + chr(10))
    print(f"logged: {log}")
else:
    print(f"RPC error: {json.dumps(r2)[:300]}")
    sys.exit(1)
