"""agent.py v3 - $100 paper trader with correlation tracking. Read-only."""
import sys, time, json, signal, importlib, statistics as st
from collections import deque
from pathlib import Path

R = Path("/Users/salamkhalikov/Desktop/ai-hub")
sys.path.insert(0, str(R))
from arbitrage_bot.app.exchanges.registry import all_exchanges
import limits as lim
import logger as L

DEXS = {"hyperliquid": "SOL", "dydx": "SOL-USD",
        "gmx": "SOL/USD", "injective": "SOL"}
FEE = {"hyperliquid": 0.035, "dydx": 0.050, "gmx": 0.050, "injective": 0.020}
BUF = 60
CORR_EVERY = 5
Z_THRESH = 2.0

RT = R / ".runtime"
J = RT / "paper_journal.jsonl"
S = RT / "paper_state.json"
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
            "best": 0.0, "429s": 0, "skips": 0, "signals": 0, "corrs": {}, "rejects": 0, "near": 0}

def save(s):
    t = S.with_suffix(".tmp"); t.write_text(json.dumps(s, indent=2)); t.replace(S)

def corr(a, b):
    if len(a) < 3 or len(a) != len(b): return None
    ma, mb = st.mean(a), st.mean(b)
    num = sum((a[i]-ma)*(b[i]-mb) for i in range(len(a)))
    da = sum((x-ma)**2 for x in a)**0.5
    db = sum((x-mb)**2 for x in b)**0.5
    return num/(da*db) if da*db else None

def main():
    signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop)
    C = clients()
    print(f"start corr-agent:{list(C)}", flush=True)
    s = load()
    for k, v in {"near": 0, "rejects": 0, "corrs": {}}.items():
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
                    c = corr(ra, rb)
                    if c is not None: cm[f"{a[:4]}x{b[:4]}"] = round(c, 3)
            s["corrs"] = cm
            L.corrs(cm=cm, ticks=s["ticks"])
            if all(len(mids[n]) >= 10 for n in C):
                names2 = sorted(C.keys())
                for i in range(len(names2)):
                    for j in range(i+1, len(names2)):
                        a, b = names2[i], names2[j]
                        ma = list(mids[a]); mb = list(mids[b])
                        n_last = min(len(ma), len(mb), 20)
                        if n_last < 5: continue
                        spread_hist = [ma[k]-mb[k] for k in range(-n_last, 0)]
                        mu = st.mean(spread_hist); sd = st.pstdev(spread_hist) or 1e-9
                        cur = ma[-1] - mb[-1]
                        z = (cur - mu) / sd
                        if 0.7 * Z_THRESH < abs(z) < Z_THRESH:
                            s["near"] += 1
                            L.near(a=a, b=b, z=round(z, 2))
                        if abs(z) > Z_THRESH:
                            s["signals"] += 1
                            gross_bps = abs(cur) / ((ma[-1]+mb[-1])/2) * 10000
                            net_bps = gross_bps - (FEE[a] + FEE[b])
                            if net_bps <= 5:
                                s["rejects"] += 1
                                L.reject(a=a, b=b, z=round(z, 2), net_bps=round(net_bps, 2), reason="fees")
                            if net_bps > 5:
                                s["trades"] += 1
                                s["cap"] *= (1.0 + net_bps / 10000.0)
                                if net_bps > s["best"]: s["best"] = net_bps
                                rec = {"ts": time.time(), "strategy": "corr_pairs",
                                       "a": a, "b": b, "z": round(z, 2),
                                       "gross_bps": round(gross_bps, 2),
                                       "net_bps": round(net_bps, 2),
                                       "cap": round(s["cap"], 4)}
                                L.trade(**rec)
                                print(f"T {a}->{b} z={z:+.2f} net={net_bps:+.2f}bps ${s['cap']:.4f}", flush=True)
        save(s)
        time.sleep(max(0.5, 3.0 - (time.time() - t0)))
    save(s); print("stopped", flush=True)

if __name__ == "__main__":
    main()
