"""sniper_v2.py (s209) - real-time in-memory sniper pipeline.

Flow: PumpPortal WS -> queue -> worker (RugCheck + bonding_curve + risk filter)
      -> if pass: virtual entry at current on-curve price (in-memory)
      -> tracker: exit on target +50% / stop -30% / time 120s
"""
from __future__ import annotations
from collections import Counter
import asyncio, json, ssl, sys, time
from pathlib import Path
from urllib.request import Request, urlopen
import certifi, websockets

# s210: env loader + multi-RPC pool (fix 429)
import os
from pathlib import Path as _P
_env = _P(__file__).resolve().parent.parent / ".env"
if _env.exists():
    for _l in _env.read_text().splitlines():
        if "=" in _l and not _l.startswith("#"):
            _k, _v = _l.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

RPC_POOL = []
for _k in ("CHAINSTACK_RPC", "HELIUS_RPC", "QUICKNODE_RPC"):
    _v = os.environ.get(_k)
    if _v:
        RPC_POOL.append((_k.lower().replace("_rpc", ""), _v))
RPC_POOL.append(("public", "https://api.mainnet-beta.solana.com"))

os.environ["HELIUS_RPC"] = RPC_POOL[0][1] if RPC_POOL else ""
print(f"[s210] RPC pool: {[n for n,_ in RPC_POOL]}")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bonding_curve import fetch as bc_fetch

ROOT = Path(__file__).resolve().parent.parent
SSL_CTX = ssl.create_default_context(cafile=certifi.where())
PUMP_WS = "wss://pumpportal.fun/api/data"
JOURNAL = ROOT / ".runtime" / "sniper_v2_trades.jsonl"
JOURNAL.parent.mkdir(parents=True, exist_ok=True)

SIZE_SOL = 0.05
import watcher as wwatch

TARGET = 0.5
STOP = -0.3
HOLD_S = 2400
MOMENTUM_GATE_SOL = 31.5
MOMENTUM_WAIT_S = 8
TICK_S = 3
PARTIAL_1_PCT = 0.50
PARTIAL_1_LEVEL = 0.50
PARTIAL_2_PCT = 0.30
PARTIAL_2_LEVEL = 1.00
TRAIL_PCT = 0.15
TRAIL_ACTIVATE = 0.30
UA = {"User-Agent": "Mozilla/5.0 ai-hub/1.0", "Accept": "application/json"}

MINT_Q = asyncio.Queue(maxsize=200)
OPEN = {}
STATS = {"seen": 0, "passed": 0, "rejected": 0, "entries": 0, "exits": 0, "pnl_sol": 0.0}
REJECT_REASONS = Counter()
RC_SEM = None  # asyncio.Semaphore, init in main
BENIGN_RISKS = {"Single holder ownership", "High holder concentration", "Low liquidity", "Low amount of LP providers"}


def _http_json(url: str, timeout: int = 15):
    req = Request(url, headers=UA)
    with urlopen(req, timeout=timeout, context=SSL_CTX) as r:
        return json.loads(r.read())


def rugcheck(mint: str):
    try:
        return _http_json(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report")
    except Exception:
        return None


async def rugcheck_async(mint: str):
    loop = asyncio.get_running_loop()
    async with RC_SEM:
        return await loop.run_in_executor(None, rugcheck, mint)


def risk_ok(rc: dict) -> tuple[bool, str]:
    if not rc:
        return False, "no_rc"
    if rc.get("mintAuthority"):
        return False, "mint_authority"
    if rc.get("freezeAuthority"):
        return False, "freeze_authority"
    tm = rc.get("tokenMeta") or {}
    if tm.get("mutable"):
        return False, "mutable_meta"
    risks = rc.get("risks") or []
    bad = [r.get("name") for r in risks if r.get("name") not in BENIGN_RISKS]
    if bad:
        return False, "risks:" + ",".join(str(x) for x in bad[:2])
    return True, "ok"


async def ws_consumer(seconds: int):
    t0 = time.time()
    async with websockets.connect(PUMP_WS, ssl=SSL_CTX, open_timeout=10) as ws:
        await ws.send(json.dumps({"method": "subscribeNewToken"}))
        while time.time() - t0 < seconds:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=15)
                d = json.loads(msg)
                if d.get("txType") != "create":
                    continue
                STATS["seen"] += 1
                try:
                    MINT_Q.put_nowait(d)
                except asyncio.QueueFull:
                    pass
            except asyncio.TimeoutError:
                continue
            except Exception:
                continue


async def worker(wid: int, seconds: int):
    loop = asyncio.get_running_loop()
    t0 = time.time()
    while time.time() - t0 < seconds:
        try:
            d = await asyncio.wait_for(MINT_Q.get(), timeout=5)
        except asyncio.TimeoutError:
            continue
        mint = d.get("mint")
        if not mint or mint in OPEN:
            continue
        try:
            await asyncio.sleep(2)
            rc = None; bc = None
            for attempt in range(4):
                rc = await rugcheck_async(mint)
                bc = await loop.run_in_executor(None, bc_fetch, mint)
                if rc and bc and not bc.get("error"):
                    break
                await asyncio.sleep(2)
            ok, why = risk_ok(rc)
            if not ok:
                STATS["rejected"] += 1
                REJECT_REASONS[why] += 1
                continue
            if not bc or bc.get("error"):
                STATS["rejected"] += 1
                REJECT_REASONS["bc_" + str((bc or {}).get("error","none"))] += 1
                continue
            price = bc.get("price_sol_per_token") or 0.0
            if price <= 0:
                STATS["rejected"] += 1
                REJECT_REASONS["px_zero"] += 1
                continue
            v_sol = bc.get("v_sol_reserves", 0) / 1e9
            now = int(time.time())
            meta = {"score_norm": (rc or {}).get("score_normalised"),
                    "risks": len((rc or {}).get("risks") or []),
                    "dev": d.get("traderPublicKey"),
                    "entry_px_seed": price}
            wwatch.register(mint, v_sol, now, meta)
            STATS["registered"] = STATS.get("registered", 0) + 1
            print(f"[w{wid}] WATCH {mint[:8]} v_sol={v_sol:.2f} score={meta['score_norm']}")
        except Exception as e:
            STATS["rejected"] += 1
            print(f"[w{wid}] ERR {mint[:8]}: {type(e).__name__} {e}")


async def _probe(mint, pos, now, loop):
    try:
        bc = await loop.run_in_executor(None, bc_fetch, mint)
    except Exception:
        return None
    if not bc or bc.get("error"):
        return None
    px = bc.get("price_sol_per_token") or 0.0
    if px <= 0:
        return None
    chg = (px - pos["entry_px"]) / pos["entry_px"]
    age = now - pos["entry_ts"]
    pos["peak_chg"] = max(pos.get("peak_chg", 0.0), chg)
    peak = pos["peak_chg"]
    size_rem = pos.get("size_remaining", 1.0)
    reason = None
    exit_pct = 0.0
    if chg >= PARTIAL_1_LEVEL and not pos.get("partial_1_done"):
        reason = "partial_1"; exit_pct = PARTIAL_1_PCT; pos["partial_1_done"] = True
    elif chg >= PARTIAL_2_LEVEL and pos.get("partial_1_done") and not pos.get("partial_2_done"):
        reason = "partial_2"; exit_pct = PARTIAL_2_PCT; pos["partial_2_done"] = True
    elif peak >= TRAIL_ACTIVATE and (peak - chg) >= TRAIL_PCT:
        reason = "trail"; exit_pct = size_rem
    elif chg <= STOP:
        reason = "stop"; exit_pct = size_rem
    elif age >= HOLD_S:
        reason = "time"; exit_pct = size_rem
    return (mint, pos, px, chg, age, reason, exit_pct)


def _write_exit(mint, pos, px, chg, age, reason, exit_pct, now):
    size_rem = pos.get("size_remaining", 1.0)
    size_orig = pos.get("size_original", 1.0)
    actual_exit = min(exit_pct, size_rem) if exit_pct > 0 else size_rem
    pnl = SIZE_SOL * actual_exit * chg
    rec = {
        "mint": mint, "entry_ts": pos["entry_ts"], "exit_ts": now,
        "entry_px": pos["entry_px"], "exit_px": px,
        "chg": chg, "age_s": age, "reason": reason,
        "pnl_sol": pnl, "size_sol": SIZE_SOL,
        "exit_pct": actual_exit, "size_remaining_before": size_rem,
        "score_norm": pos.get("score_norm"), "risks": pos.get("risks"),
    }
    with open(JOURNAL, "a") as f:
        f.write(json.dumps(rec) + "\n")
    STATS["exits"] = STATS.get("exits", 0) + 1
    print(f"[t] EXIT {mint[:8]} {reason} chg={chg*100:+.1f}% age={age}s pnl={pnl:+.4f} x{actual_exit:.2f}")

    # partial: reduce size, keep in OPEN if remainder > 0
    new_rem = size_rem - actual_exit
    if new_rem <= 0.01:
        if mint in OPEN:
            del OPEN[mint]
    else:
        pos["size_remaining"] = new_rem
        pos["realized_pnl"] = pos.get("realized_pnl", 0.0) + pnl


async def watcher_loop(seconds: int):
    loop = asyncio.get_running_loop()
    t0 = time.time()
    while time.time() - t0 < seconds:
        await asyncio.sleep(wwatch.WATCH_TICK_S)
        now = int(time.time())
        for mint in list(wwatch.WATCH.keys()):
            if wwatch.expire(mint, now):
                STATS["expired"] = STATS.get("expired", 0) + 1
                continue
            if mint in OPEN:
                del wwatch.WATCH[mint]
                continue
            try:
                bc = await loop.run_in_executor(None, bc_fetch, mint)
            except Exception:
                continue
            if not bc or bc.get("error"):
                continue
            v_sol = bc.get("v_sol_reserves", 0) / 1e9
            if v_sol < 29.0:
                del wwatch.WATCH[mint]
                STATS["dropped_rug"] = STATS.get("dropped_rug", 0) + 1
                continue
            wwatch.update(mint, now, v_sol)
            sig_ok, info = wwatch.signal(mint, now)
            if not sig_ok:
                continue
            price = bc.get("price_sol_per_token") or 0.0
            if price <= 0:
                continue
            meta = wwatch.WATCH[mint]["meta"]
            OPEN[mint] = {
                "mint": mint, "entry_ts": now, "entry_px": price,
                "score_norm": meta.get("score_norm"),
                "risks": meta.get("risks", 0),
                "dev": meta.get("dev"),
                "v_sol": v_sol,
                "signal_info": info,
                "size_original": 1.0,
                "size_remaining": 1.0,
                "peak_chg": 0.0,
                "partial_1_done": False,
                "partial_2_done": False,
                "realized_pnl": 0.0,
            }
            STATS["entries"] += 1
            STATS["passed"] += 1
            STATS["watch_signals"] = STATS.get("watch_signals", 0) + 1
            _dv = info.get('dv', info.get('initial_v', 0.0))
            _rt = info.get('ratio', info.get('accel', 0.0))
            _ag = info.get('age', 0)
            print(f"[watch] ENTRY {mint[:8]} px={price:.3e} dv={_dv:.2f} ratio={_rt:.1f} age={_ag}s")
            del wwatch.WATCH[mint]


async def tracker(seconds: int):
    loop = asyncio.get_running_loop()
    t0 = time.time()
    while time.time() - t0 < seconds:
        await asyncio.sleep(TICK_S)
        now = int(time.time())
        items = list(OPEN.items())
        if not items:
            continue
        results = await asyncio.gather(*[_probe(m, p, now, loop) for m, p in items])
        for r in results:
            if not r:
                continue
            mint, pos, px, chg, age, reason, exit_pct = r
            if reason:
                _write_exit(mint, pos, px, chg, age, reason, exit_pct, now)


async def main(seconds: int):
    global RC_SEM
    RC_SEM = asyncio.Semaphore(1)
    t0 = time.time()
    tasks = [
        asyncio.create_task(ws_consumer(seconds)),
        asyncio.create_task(worker(1, seconds)),
        asyncio.create_task(worker(2, seconds)),
        asyncio.create_task(watcher_loop(seconds)),
        asyncio.create_task(tracker(seconds + 30)),
    ]
    await asyncio.wait(tasks, timeout=seconds + 60)
    for t in tasks:
        t.cancel()
    # force-close any remaining OPEN
    loop = asyncio.get_running_loop()
    now = int(time.time())
    for mint in list(OPEN.keys()):
        pos = OPEN[mint]
        try:
            bc = await loop.run_in_executor(None, bc_fetch, mint)
            px = (bc or {}).get("price_sol_per_token") or pos["entry_px"]
        except Exception:
            px = pos["entry_px"]
        chg = (px - pos["entry_px"]) / pos["entry_px"]
        age = now - pos["entry_ts"]
        _write_exit(mint, pos, px, chg, age, "force", 1.0, now)
    print("=== STATS ===")
    print(json.dumps(STATS, indent=2))
    print("rejects:", dict(REJECT_REASONS.most_common(10)))
    print("open:", len(OPEN))


if __name__ == "__main__":
    dur = int(sys.argv[1]) if len(sys.argv) > 1 else 180
    print(f"=== sniper_v2 {dur}s ===")
    try:
        asyncio.run(main(dur))
    except KeyboardInterrupt:
        print("stopped")
