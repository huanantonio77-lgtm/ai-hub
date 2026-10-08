#!/usr/bin/env python3
# close_all_ata.py - close ALL Token-2022 ATAs, recover rent.
import json, ssl, time, pathlib, base64
from urllib.request import Request, urlopen
import certifi
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.instruction import Instruction, AccountMeta
from solders.message import MessageV0
from solders.transaction import VersionedTransaction
from solders.hash import Hash
ROOT = pathlib.Path(__file__).resolve().parent.parent
env = {}
for l in (ROOT / ".env").read_text().splitlines():
    if "=" in l and not l.startswith("#"):
        k, v = l.split("=", 1)
        env[k.strip()] = v.strip()
RPC = env.get("HELIUS_RPC") or env.get("CHAINSTACK_RPC") or env.get("QUICKNODE_RPC")
CTX = ssl.create_default_context(cafile=certifi.where())
raw = (ROOT / ".runtime" / "wallet" / "live_keypair.json").read_text().strip()
if raw.startswith("["):
    kp = Keypair.from_bytes(bytes(json.loads(raw)))
else:
    import base58
    kp = Keypair.from_bytes(base58.b58decode(raw))
TOKEN_2022 = Pubkey.from_string("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")

def rpc_post(b):
    return json.loads(urlopen(Request(RPC, data=json.dumps(b).encode(), headers={"Content-Type":"application/json"}), timeout=20, context=CTX).read())

r = rpc_post({"jsonrpc":"2.0","id":1,"method":"getTokenAccountsByOwner","params":[str(kp.pubkey()), {"programId":str(TOKEN_2022)}, {"encoding":"jsonParsed"}]})
atas = [(a["pubkey"], a["account"]["data"]["parsed"]["info"]["mint"]) for a in r.get("result",{}).get("value",[])]
print(f"ATAs to close: {len(atas)}")
for ata, mint in atas:
    print(f"  {ata[:12]}... mint={mint[:16]}...")
if not atas:
    print("nothing to close"); raise SystemExit(0)

pk_ata = Pubkey.from_string(atas[0][0])
ins = Instruction(
    program_id=TOKEN_2022,
    accounts=[
        AccountMeta(pubkey=pk_ata, is_signer=False, is_writable=True),
        AccountMeta(pubkey=kp.pubkey(), is_signer=False, is_writable=True),
        AccountMeta(pubkey=kp.pubkey(), is_signer=True, is_writable=False),
    ],
    data=bytes([9]),
)
bh = rpc_post({"jsonrpc":"2.0","id":1,"method":"getLatestBlockhash","params":[{"commitment":"finalized"}]})["result"]["value"]["blockhash"]
msg = MessageV0.try_compile(payer=kp.pubkey(), instructions=[ins], address_lookup_table_accounts=[], recent_blockhash=Hash.from_string(bh))
tx = VersionedTransaction(msg, [kp])
sig_b64 = base64.b64encode(bytes(tx)).decode()
r2 = rpc_post({"jsonrpc":"2.0","id":1,"method":"sendTransaction","params":[sig_b64, {"encoding":"base64","skipPreflight":True,"maxRetries":5}]})
print(f"result: {json.dumps(r2)[:200]}")
if "result" in r2:
    sig = r2["result"]
    print(f"SUBMITTED {sig[:44]}...")
    for _ in range(15):
        time.sleep(3)
        cr = rpc_post({"jsonrpc":"2.0","id":1,"method":"getTransaction","params":[sig, {"encoding":"jsonParsed","commitment":"confirmed","maxSupportedTransactionVersion":0}]})
        if "result" in cr and cr["result"]:
            err = cr["result"].get("meta",{}).get("err")
            print(f"  on-chain err: {err}")
            if err is None:
                print("  CLOSED OK")
            break
    else:
        print("  confirm timeout")
print("first ATA test done - if OK, loop the rest:")
