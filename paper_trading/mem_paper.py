"""MEM paper: S4 + virtual executor. Jupiter recent+price. +20%/60s signal, $5 trade, hold 120s, target +30%, stop -15%, fees 250bps RT."""
import sys, time, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from paper_trading.data_layer import recent_tokens, price

SCAN_S, WINDOW_S, PUMP_PCT = 30, 30, 0.08
SIZE_USD, HOLD_S, TGT_PCT, STP_PCT = 5.0, 60, 0.25, -0.20
FEE_RT_BPS, RUN_S = 250, 300
MAX_PCT = 0.50
PHIST = ROOT / ".runtime" / "f3_pricehist.jsonl"
JOURNAL = ROOT / ".runtime" / "f3_trades.jsonl"

class MemPaper:
    def __init__(self):
        self.hist, self.pos = {}, {}
        self.st = {"sig":0,"ent":0,"exi":0,"W":0,"L":0,"pnl":0.0}

    def _delta(self, m, now):
        h = [x for x in self.hist.get(m, []) if x[0] >= now - WINDOW_S - 10]
        if len(h) < 2 or h[0][1] <= 0: return None
        return h[-1][1] / h[0][1] - 1.0, h[0][1], h[-1][1]

    def scan(self, rec):
        now = int(time.time())
        mints = [t["id"] for t in rec if t.get("id")][:50]
        watch = list(set(mints) | set(self.pos.keys()))
        p = price(watch)
        for m in mints:
            px = p.get(m, {}).get("usdPrice")
            if px and px > 0:
                self.hist.setdefault(m, []).append((now, float(px)))
                self.hist[m] = [x for x in self.hist[m] if x[0] >= now - WINDOW_S*3]
        sym = {t["id"]: t.get("symbol","?") for t in rec}
        for m in mints:
            if m in self.pos: continue
            d = self._delta(m, now)
            if d and PUMP_PCT <= d[0] <= MAX_PCT:
                self._open(m, sym.get(m,"?"), d[2], now, d[0])
        for m in list(self.pos):
            self._exit(m, p.get(m, {}).get("usdPrice"), now)
        try:
            with open(PHIST, "a") as fh:
                for m in mints:
                    px = p.get(m, {}).get("usdPrice")
                    if px: fh.write(json.dumps({"ts":now,"m":m,"px":float(px)})+"\n")
        except Exception: pass

    def _open(self, m, s, px, now, delta):
        self.pos[m] = {"mint":m,"symbol":s,"entry_ts":now,"entry_px":px,
                       "size_usd":SIZE_USD,"sig_delta":delta}
        self.st["sig"] += 1; self.st["ent"] += 1
        print(f"  [ENTRY] {s:12} ${px:.8f} sig +{delta*100:.1f}%")

    def _exit(self, m, px, now):
        po = self.pos[m]; age = now - po["entry_ts"]
        if px is None:
            if age >= HOLD_S * 2:
                px = po["entry_px"]  # stale close, no pnl
            else:
                return
        chg = px / po["entry_px"] - 1.0
        reason = ("target" if chg >= TGT_PCT else "stop" if chg <= STP_PCT
                  else "time" if age >= HOLD_S else None)
        if reason is None: return
        pnl = po["size_usd"] * (chg - FEE_RT_BPS / 10000.0)
        self.st["exi"] += 1; self.st["W" if pnl > 0 else "L"] += 1
        self.st["pnl"] += pnl
        with open(JOURNAL, "a") as f:
            f.write(json.dumps({**po,"exit_ts":now,"exit_px":px,"chg":chg,
                                "pnl":pnl,"reason":reason,"age_s":age}) + "\n")
        s = po["symbol"]
        print(f"  [EXIT ] {s:12} {reason:6} chg={chg*100:+.1f}% pnl=${pnl:+.4f}")
        del self.pos[m]

def main():
    mp = MemPaper()
    t0 = time.time()
    print(f"=== mem_paper {RUN_S}s win={WINDOW_S}s pump>={PUMP_PCT*100:.0f}% ===")
    while time.time() - t0 < RUN_S:
        try: mp.scan(recent_tokens(50))
        except Exception as e: print(f"  [scan ERR] {e!r}")
        print(f"[t={int(time.time()-t0):3d}s] hist={len(mp.hist)} pos={len(mp.pos)} "
              f"sig={mp.st['sig']} tr={mp.st['exi']} W/L={mp.st['W']}/{mp.st['L']} "
              f"pnl=${mp.st['pnl']:+.4f}")
        time.sleep(SCAN_S)
    print(f"=== done: {mp.st} ===")
    try:
        from paper_trading.memory import record_test_result
        record_test_result("H5", "mem_momentum_jito", mp.st, "s207")
        print("recorded to memory")
    except Exception as e:
        print(f"memory record skipped: {e!r}")

if __name__ == "__main__":
    main()
