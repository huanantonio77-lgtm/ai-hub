import asyncio, json, pathlib, time

WATCH_TICK_S = 5
WATCH_WINDOW_S = 60
WATCH_MIN_DV = 1.0
WATCH_MIN_ACCEL = 1.5
WATCH_MAX_AGE_S = 600
WATCH_MIN_SAMPLES = 3
WATCH_FAST_ENTRY_V_SOL = 50.0
WATCH_MAX_CONCURRENT = 3
WATCH_RPC_DELAY_MS = 200
WATCH = {}
V_LOG = pathlib.Path(".runtime/watcher_v_history.jsonl")
_RPC_SEM = None

def _get_sem():
    global _RPC_SEM
    if _RPC_SEM is None:
        _RPC_SEM = asyncio.Semaphore(WATCH_MAX_CONCURRENT)
    return _RPC_SEM

async def throttled_fetch(bc_fetch, mint, loop):
    sem = _get_sem()
    async with sem:
        await asyncio.sleep(WATCH_RPC_DELAY_MS / 1000.0)
        for attempt in range(3):
            try:
                return await loop.run_in_executor(None, bc_fetch, mint)
            except Exception as e:
                err = str(e)
                if "429" in err:
                    await asyncio.sleep(1.0 * (attempt + 1))
                    continue
                return None
    return None

def _log_history(mint, now, v_sol, initial_v):
    rec = {"ts": now, "mint": mint, "v_sol": v_sol, "initial_v": initial_v}
    try:
        with open(V_LOG, "a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass

def register(mint, initial_v_sol, now, meta):
    WATCH[mint] = {"mint": mint, "created_ts": now, "initial_v_sol": initial_v_sol,
                   "history": [(now, initial_v_sol)], "meta": meta}

def update(mint, now, v_sol):
    w = WATCH.get(mint)
    if not w: return None
    w["history"].append((now, v_sol))
    cutoff = now - WATCH_WINDOW_S * 3
    w["history"] = [x for x in w["history"] if x[0] >= cutoff]
    _log_history(mint, now, v_sol, w["initial_v_sol"])
    return w

def signal(mint, now):
    w = WATCH.get(mint)
    if not w: return False, None
    iv = w["initial_v_sol"]
    if iv >= WATCH_FAST_ENTRY_V_SOL:
        return True, {"fast": True, "initial_v": iv, "reason": "already_pumping"}
    hist = w["history"]
    if len(hist) < WATCH_MIN_SAMPLES: return False, None
    t_now, v_now = hist[-1]
    v_now_minus_60 = None
    for t, v in hist:
        if t >= t_now - WATCH_WINDOW_S:
            v_now_minus_60 = v; break
    if v_now_minus_60 is None: return False, None
    v_now_minus_120 = None
    for t, v in hist:
        if t >= t_now - 2 * WATCH_WINDOW_S and t <= t_now - WATCH_WINDOW_S:
            v_now_minus_120 = v; break
    if v_now_minus_120 is None: return False, None
    dv_now = v_now - v_now_minus_60
    dv_prev = v_now_minus_60 - v_now_minus_120
    if dv_now < WATCH_MIN_DV: return False, None
    accel = dv_now / max(dv_prev, 0.5)
    if accel < WATCH_MIN_ACCEL: return False, None
    age = t_now - w["created_ts"]
    return True, {"dv": dv_now, "dv_prev": dv_prev, "accel": accel,
                  "age": age, "v_sol": v_now}

def expire(mint, now):
    w = WATCH.get(mint)
    if not w: return False
    if now - w["created_ts"] > WATCH_MAX_AGE_S:
        del WATCH[mint]; return True
    return False

def stats():
    return {"watching": len(WATCH)}


RPC_POOL = []
def _init_rpc_pool():
    global RPC_POOL
    import os
    pool = []
    h = os.getenv("HELIUS_RPC")
    if h: pool.append(("helius", h))
    pool.append(("ankr", "https://rpc.ankr.com/solana"))
    pool.append(("public", "https://api.mainnet-beta.solana.com"))
    RPC_POOL = pool

def rpc_health():
    return {"providers": len(RPC_POOL), "names": [n for n, _ in RPC_POOL]}
