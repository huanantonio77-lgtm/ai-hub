"""agent.py v4 (s205-F1.5) - corr_pairs with REALIZED PnL.
Exit: |z|<EXIT_Z (mean), |z|>SL_Z (sl), age>TIMEOUT_T (timeout).
Cap can go DOWN (realized_pnl_bps may be < 0).
"""
import sys, os, time, json, signal, importlib, statistics as st
from collections import deque
from pathlib import Path

R = Path("/Users/salamkhalikov/Desktop/ai-hub")
sys.path.insert(0, str(R))
from arbitrage_bot.app.exchanges.registry import all_exchanges
import limits as lim
import logger as L

DEXS = {"hyperliquid": "SOL", "dydx": "SOL-USD",
        "gmx": "SOL/USD", "injective": "SOL"}
FEE = {"hyperliquid": 1.5, "dydx": 1.0, "gmx": 5.0, "injective": 1.0}

GAS_BPS = 0.1
SLIP_BPS = 0.5
EXIT_Z = 0.5
SL_Z = 3.5
TIMEOUT_T = 600

BUF = 60
CORR_EVERY = 5
Z_THRESH = 2.0

RT = R / ".runtime"
S = RT / "paper_state_v43.json"
RUN = [True]

def stop(*_): RUN[0] = False

def clients():
    o = {}
    for e in all_exchanges():
        n = e["name"]
        if n not in DEXS: continue
        m, _, c = e["class"].partition(":")
        try: o[n] = getattr(importlib.import_module(m), c)()
        except Exception as x: print(f"[skip]{n}:{x}", flush=True)
    return o

def load():
    if S.exists():
        try: return json.loads(S.read_text())
        except: pass
    return {"cap": 100.0, "trades": 0, "ticks": 0, "started": time.time(),
            "best": 0.0, "429s": 0, "skips": 0, "signals": 0, "corrs": {},
            "rejects": 0, "near": 0,
            "open_positions": [], "closed": 0, "realized_pnl_bps": 0.0,
            "wins": 0, "losses": 0, "worst": 0.0}

def save(s):
    try:
        RT.mkdir(parents=True, exist_ok=True)
        t = S.with_suffix(".tmp")
        t.write_text(json.dumps(s, indent=2))
        os.replace(t, S)
    except Exception as e:
        try:
            with open(RT / "save_errors.log", "a") as f:
                f.write(f"{time.time()} {e}\n")
        except: pass

def corr(a, b):
    if len(a) < 3 or len(a) != len(b): return None
    ma, mb = st.mean(a), st.mean(b)
    num = sum((a[i]-ma)*(b[i]-mb) for i in range(len(a)))
    da = sum((x-ma)**2 for x in a)**0.5
    db = sum((x-mb)**2 for x in b)**0.5
    return num/(da*db) if da*db else None

# --- cointegration functions (s205-F1.5) ---
try:
    from statsmodels.tsa.stattools import coint as _coint, adfuller as _adf
    from statsmodels.regression.linear_model import OLS as _OLS
    import numpy as _np
    _HAS_SM = True
except Exception:
    _HAS_SM = False

def hedge_ratio(pa, pb):
    """OLS: log(pa) = alpha + beta*log(pb). Returns beta or None."""
    if not _HAS_SM or len(pa) < 10 or len(pb) < 10: return None
    try:
        la = _np.log(_np.array(pa, dtype=float))
        lb = _np.log(_np.array(pb, dtype=float))
        X = _np.column_stack([_np.ones(len(lb)), lb])
        if _np.linalg.matrix_rank(X) < 2:
            return 1.0
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = _OLS(la, X).fit()
        return float(res.params[1])
    except Exception:
        return None

def coint_pvalue(pa, pb):
    """Engle-Granger cointegration p-value. Returns p or 1.0."""
    if not _HAS_SM or len(pa) < 20 or len(pb) < 20: return 1.0
    try:
        _, p, _ = _coint(_np.array(pa, dtype=float),
                          _np.array(pb, dtype=float))
        return float(p)
    except Exception:
        return 1.0

def close_position(pos, s, mid_a, mid_b, reason, tick):
    """Realized PnL with all costs. Logs to journal or losses."""
    ea, eb = pos["entry_mid_a"], pos["entry_mid_b"]
    sa = mid_a - ea
    sb = mid_b - eb
    direction = 1 if pos["entry_z"] < 0 else -1
    raw_bps = direction * (sa - sb) / ((ea + eb) / 2) * 10000
    costs = (FEE[pos["a"]] + FEE[pos["b"]]) * 2 + GAS_BPS * 2 + SLIP_BPS * 2
    realized = raw_bps - costs
    s["closed"] += 1
    s["cap"] *= (1.0 + realized / 10000.0)
    s["realized_pnl_bps"] += realized
    if realized > 0:
        s["wins"] += 1
        if realized > s["best"]: s["best"] = realized
    else:
        s["losses"] += 1
        if realized < s["worst"]: s["worst"] = realized
    rec = {"ts": time.time(), "strategy": "corr_pairs",
           "a": pos["a"], "b": pos["b"],
           "entry_z": pos["entry_z"], "exit_z": pos.get("last_z"),
           "entry_mid_a": round(ea, 4), "entry_mid_b": round(eb, 4),
           "exit_mid_a": round(mid_a, 4), "exit_mid_b": round(mid_b, 4),
           "raw_bps": round(raw_bps, 2), "costs_bps": round(costs, 2),
           "realized_bps": round(realized, 2), "reason": reason,
           "age_ticks": tick - pos["entry_tick"],
           "cap": round(s["cap"], 4)}
    L.trade(**rec) if realized > 0 else L.loss(**rec)
    print(f"C {pos['a']}->{pos['b']} {reason} z={pos.get('last_z'):+.2f} "
          f"realized={realized:+.2f}bps ${s['cap']:.4f}", flush=True)

def main():
    signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop)
    C = clients()
    print(f"start corr-agent v4:{list(C)}", flush=True)
    s = load()
    for k, v in {"near": 0, "rejects": 0, "corrs": {},
                 "open_positions": [], "closed": 0, "realized_pnl_bps": 0.0,
                 "wins": 0, "losses": 0, "worst": 0.0}.items():
        s.setdefault(k, v)
    mids = {n: deque(maxlen=BUF) for n in C}
    rets = {n: deque(maxlen=BUF-1) for n in C}
    prev = {}

    while RUN[0]:
        t0 = time.time(); s["ticks"] += 1
        for n, c in C.items():
            ok, _ = lim.is_available(n)
            if not ok: s["skips"] += 1; continue
            try:
                ob = c.get_orderbook(DEXS[n])
                if ob and ob.is_valid():
                    m = (ob.best_bid() + ob.best_ask()) / 2
                    if n in prev and prev[n] > 0:
                        rets[n].append((m - prev[n]) / prev[n])
                    mids[n].append(m); prev[n] = m
            except Exception as e:
                if "429" in str(e):
                    try: lim.record_call(n, "429")
                    except: pass
                    s["429s"] += 1

        if s["ticks"] % CORR_EVERY == 0 and all(len(rets[n]) >= 5 for n in C):
            cm = {}
            names = sorted(C.keys())
            for i in range(len(names)):
                for j in range(i+1, len(names)):
                    a, b = names[i], names[j]
                    ra = list(rets[a])[-10:]; rb = list(rets[b])[-10:]
                    cc = corr(ra, rb)
                    if cc is not None: cm[f"{a[:4]}x{b[:4]}"] = round(cc, 3)
            s["corrs"] = cm
            L.corrs(cm=cm, ticks=s["ticks"])

            if all(len(mids[n]) >= 30 for n in C):
                for i in range(len(names)):
                    for j in range(i+1, len(names)):
                        a, b = names[i], names[j]
                        ma = list(mids[a])[-30:]; mb = list(mids[b])[-30:]
                        cval = cm.get(f"{a[:4]}x{b[:4]}", 0)
                        pval = coint_pvalue(ma, mb)
                        if pval > 0.10: continue
                        beta = hedge_ratio(ma, mb)
                        if beta is None: continue
                        sp = [ma[k] - beta*mb[k] for k in range(-20, 0)]
                        mu = st.mean(sp); sd = st.pstdev(sp) or 1e-9
                        z = (ma[-1] - beta*mb[-1] - mu) / sd
                        if 0.7 * Z_THRESH < abs(z) < Z_THRESH:
                            s["near"] += 1; L.near(a=a, b=b, z=round(z, 2))

                        if abs(z) > Z_THRESH:
                            s["signals"] += 1
                            already = any((p["a"]==a and p["b"]==b) or
                                          (p["a"]==b and p["b"]==a)
                                          for p in s["open_positions"])
                            if already: continue
                            spread_now = ma[-1] - beta*mb[-1]
                            mid_avg = (ma[-1] + mb[-1]) / 2
                            gross_bps = abs(spread_now) / mid_avg * 10000
                            costs = (FEE[a]+FEE[b])*2 + GAS_BPS*2 + SLIP_BPS*2
                            net_bps = gross_bps - costs
                            if net_bps <= 5:
                                s["rejects"] += 1
                                L.reject(a=a, b=b, z=round(z, 2),
                                         net_bps=round(net_bps, 2),
                                         reason="costs")
                                continue
                            s["open_positions"].append({
                                "a": a, "b": b, "beta": round(beta, 4),
                                "entry_mid_a": ma[-1], "entry_mid_b": mb[-1],
                                "entry_z": round(z, 2), "entry_tick": s["ticks"],
                                "pvalue": round(pval, 4), "corr": round(cval, 3),
                                "last_z": round(z, 2)})
                            print(f"O {a}->{b} z={z:+.2f} beta={beta:.3f} "
                                  f"p={pval:.3f} cost={costs:.1f}bps", flush=True)

        still_open = []
        for pos in s["open_positions"]:
            a, b = pos["a"], pos["b"]
            if len(mids[a]) < 30 or len(mids[b]) < 30:
                still_open.append(pos); continue
            ma = list(mids[a])[-30:]; mb = list(mids[b])[-30:]
            beta = hedge_ratio(ma, mb) or pos["beta"]
            sp = [ma[k] - beta*mb[k] for k in range(-20, 0)]
            mu = st.mean(sp); sd = st.pstdev(sp) or 1e-9
            z = (ma[-1] - beta*mb[-1] - mu) / sd
            pos["last_z"] = round(z, 2)
            age = s["ticks"] - pos["entry_tick"]
            reason = None
            if abs(z) < EXIT_Z: reason = "mean"
            elif abs(z) > SL_Z: reason = "sl"
            elif age > TIMEOUT_T: reason = "timeout"
            if reason:
                close_position(pos, s, ma[-1], mb[-1], reason, s["ticks"])
            else:
                still_open.append(pos)
        s["open_positions"] = still_open

        save(s)
        time.sleep(max(0.5, 3.0 - (time.time() - t0)))
    save(s); print("stopped", flush=True)

if __name__ == "__main__":
    main()
