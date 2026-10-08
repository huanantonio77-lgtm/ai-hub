#!/usr/bin/env python3
# live_sniper_full.py - one full live cycle: buy -> hold -> sell.
import asyncio, json, ssl, sys, time, pathlib, base64
from urllib.request import Request, urlopen
import certifi, websockets
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from trade_stream import TradeStream
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
WAIT_S = 30
FILTER_NP_MIN = 0.3
FILTER_UB_MIN = 3
FILTER_BUY_SOL = 0.5
TICK_S = 5
INITIAL_V_SOL = 30.0
AMOUNT = float(sys.argv[2]) if len(sys.argv) > 2 else 0.003
HOLD_S = int(sys.argv[3]) if len(sys.argv) > 3 else 120
TARGET = 0.5
STOP = -0.3
SLIPPAGE = 8

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
        if "result" not in r2:
            print(f"  rpc err: {json.dumps(r2)[:200]}")
            time.sleep(2)
            continue
        sig = r2["result"]
        # Confirm: wait until finalized and check err
        print(f"  submitted: {sig[:20]}... checking...")
        for _ in range(20):
            time.sleep(3)
            try:
                cr = rpc_post({"jsonrpc":"2.0","id":1,"method":"getTransaction","params":[sig, {"encoding":"jsonParsed","commitment":"confirmed","maxSupportedTransactionVersion":0}]})
            except Exception:
                continue
            if "result" in cr and cr["result"]:
                meta = cr["result"].get("meta", {})
                err = meta.get("err")
                if err is not None:
                    print(f"  ON-CHAIN FAIL: {json.dumps(err)[:120]}")
                    break
                return sig
        else:
            print("  confirm timeout, treating as failed")
            continue
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

CANDIDATES = {}
POSITIONS = {}
_ts = None

async def _on_new_async(d):
    if d.get('txType') != 'create':
        return
    mint = d.get('mint', '')
    dev = float(d.get('solAmount', 0) or 0)
    if dev < MIN_DEV:
        return
    if mint in CANDIDATES or mint in POSITIONS:
        return
    CANDIDATES[mint] = {'seen_at': time.time(), 'dev': dev, 'v_sol': INITIAL_V_SOL + dev}
    print(f'[cand] {mint[:12]} dev={dev:.3f}')
    try:
        await _ts.subscribe_token(mint)
    except Exception as e:
        print(f'  sub err: {e}')

async def execute_cycle(mint, v_sol_entry):
    print(f'  [ENTER] {mint[:16]} v_sol={v_sol_entry:.2f}')
    sig_buy = await asyncio.to_thread(buy, mint)
    if not sig_buy:
        print('  buy failed, skip')
        return
    print(f'  BUY OK: https://solscan.io/tx/{sig_buy}')
    log({'ts': time.time(), 'mint': mint, 'action': 'buy', 'amount_sol': AMOUNT, 'sig': sig_buy, 'wallet': str(kp.pubkey())})
    bal_after_buy = await asyncio.to_thread(get_sol)
    print(f'  balance after buy: {bal_after_buy:.6f}')
    print(f'  holding {HOLD_S}s...')
    await asyncio.sleep(HOLD_S)
    sig_sell = await asyncio.to_thread(sell, mint)
    if not sig_sell:
        print('  sell failed, MANUAL SELL NEEDED')
        return
    print(f'  SELL OK: https://solscan.io/tx/{sig_sell}')
    log({'ts': time.time(), 'mint': mint, 'action': 'sell', 'sig': sig_sell, 'wallet': str(kp.pubkey())})
    await asyncio.sleep(5)
    bal_after_sell = await asyncio.to_thread(get_sol)
    print(f'  balance after sell: {bal_after_sell:.6f}')
    delta = bal_after_sell - bal_after_buy
    print(f'  CYCLE COMPLETE: delta={delta:+.6f} SOL')

async def main():
    global _ts
    duration = int(sys.argv[4]) if len(sys.argv) > 4 else 1800
    print(f'live_sniper_filtered MIN_DEV={MIN_DEV} AMOUNT={AMOUNT} HOLD={HOLD_S} WAIT={WAIT_S} np>={FILTER_NP_MIN} ub>={FILTER_UB_MIN} buy>={FILTER_BUY_SOL} SLIP={SLIPPAGE}')
    print(f'wallet: {kp.pubkey()}')
    print(f'balance: {get_sol():.6f} SOL')
    t0 = time.time()
    _ts = TradeStream(API_KEY, on_new_token=_on_new_async)
    await _ts.start()
    try:
        while time.time() - t0 < duration:
            await asyncio.sleep(TICK_S)
            now = time.time()
            for mint, c in list(CANDIDATES.items()):
                if mint in POSITIONS:
                    CANDIDATES.pop(mint, None)
                    continue
                if now - c['seen_at'] < WAIT_S:
                    continue
                s = _ts.stats_for(mint)
                if s is None:
                    if now - c['seen_at'] > WAIT_S * 2:
                        aged = now - c['seen_at']
                        print(f'  [skip] {mint[:12]} no stats aged={aged:.0f}s')
                        CANDIDATES.pop(mint, None)
                        try:
                            await _ts.unsubscribe_token(mint)
                        except Exception:
                            pass
                    continue
                npv = s['net_pressure']
                ubv = s['unique_buyers']
                bv = s['buy_sol']
                if npv >= FILTER_NP_MIN and ubv >= FILTER_UB_MIN and bv >= FILTER_BUY_SOL:
                    print(f'  [PASS] {mint[:12]} np={npv:+.2f} ub={ubv} buy={bv:.3f}')
                    CANDIDATES.pop(mint, None)
                    POSITIONS[mint] = {'entry_time': now, 'entry_v_sol': c['v_sol']}
                    await execute_cycle(mint, c['v_sol'])
                    POSITIONS.pop(mint, None)
                elif now - c['seen_at'] > WAIT_S * 2:
                    aged = now - c['seen_at']
                    print(f'  [skip] {mint[:12]} aged={aged:.0f}s np={npv:+.2f} ub={ubv}')
                    CANDIDATES.pop(mint, None)
                    try:
                        await _ts.unsubscribe_token(mint)
                    except Exception:
                        pass
    finally:
        await _ts.stop()

asyncio.run(main())
