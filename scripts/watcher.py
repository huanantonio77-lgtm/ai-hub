
WATCH_TICK_S = 5
WATCH_WINDOW_S = 60
WATCH_MIN_DV = 2.0
WATCH_MIN_RATIO = 3.0
WATCH_MAX_AGE_S = 600
WATCH_MIN_SAMPLES = 3
WATCH = {}

def register(mint, initial_v_sol, now, meta):
    WATCH[mint] = {"mint": mint, "created_ts": now, "initial_v_sol": initial_v_sol,
                   "history": [(now, initial_v_sol)], "meta": meta}

def update(mint, now, v_sol):
    w = WATCH.get(mint)
    if not w: return None
    w["history"].append((now, v_sol))
    cutoff = now - WATCH_WINDOW_S * 2
    w["history"] = [x for x in w["history"] if x[0] >= cutoff]
    return w

def signal(mint, now):
    w = WATCH.get(mint)
    if not w: return False, None
    hist = w["history"]
    if len(hist) < WATCH_MIN_SAMPLES: return False, None
    t_now, v_now = hist[-1]
    past = None
    for t, v in hist:
        if t >= t_now - WATCH_WINDOW_S:
            past = (t, v); break
    if not past: return False, None
    dt = t_now - past[0]
    if dt < WATCH_WINDOW_S * 0.5: return False, None
    dv = v_now - past[1]
    if dv < WATCH_MIN_DV: return False, None
    age = t_now - w["created_ts"]
    if age <= 0: return False, None
    baseline = max((v_now - w["initial_v_sol"]) / age, 0.01)
    ratio = (dv / dt) / baseline
    if ratio < WATCH_MIN_RATIO: return False, None
    return True, {"dv": dv, "dvdt": dv/dt, "baseline": baseline,
                  "ratio": ratio, "age": age, "v_sol": v_now}

def expire(mint, now):
    w = WATCH.get(mint)
    if not w: return False
    if now - w["created_ts"] > WATCH_MAX_AGE_S:
        del WATCH[mint]; return True
    return False

def stats():
    return {"watching": len(WATCH)}
