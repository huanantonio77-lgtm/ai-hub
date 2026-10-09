import sys, asyncio, json, pathlib, ssl, certifi, time
sys.path.insert(0, "scripts")
from own_stream import SolanaStream
ROOT = pathlib.Path.cwd()
env = {}
for l in (ROOT / ".env").read_text().splitlines():
    if "=" in l and not l.startswith("#"):
        k, v = l.split("=", 1); env[k.strip()] = v.strip()
WAIT_S = 15
TICK_S = 5
NP_MIN = 0.3
UB_MIN = 3
BUY_MIN = 0.5
FORWARD_S = 120
MAX_ENTRY_V = 38.0
DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 1800
JOURNAL = ROOT / ".runtime" / "shadow_A_signals.jsonl"
CANDIDATES = {}
PASSED = []
async def main():
    ts = SolanaStream(env["PUMPPORTAL_API_KEY"])
    await ts.start()
    async def on_new(d):
        if d.get("txType") != "create":
            return
        mint = d.get("mint", "")
        dev = float(d.get("solAmount", 0) or 0)
        if dev < 2.0 or not mint or mint in CANDIDATES:
            return
        CANDIDATES[mint] = {"seen_at": time.time(), "v0": 30.0 + dev}
        print("[cand]", mint[:12], "dev=", round(dev,3))
        await ts.subscribe_token(mint)
    ts.on_new_token = on_new
    print("=== SHADOW MONITOR (own_stream + A-filter, no orders) ===")
    print("WAIT=" + str(WAIT_S) + " np>=" + str(NP_MIN) + " ub>=" + str(UB_MIN) + " buy>=" + str(BUY_MIN))
    t0 = time.time()
    while time.time() - t0 < DURATION:
        await asyncio.sleep(TICK_S)
        now = time.time()
        for mint, c in list(CANDIDATES.items()):
            age = now - c["seen_at"]
            if age < WAIT_S:
                continue
            s = ts.stats_for(mint)
            if s is None:
                if age > WAIT_S * 2:
                    CANDIDATES.pop(mint, None)
                continue
            if s["net_pressure"] >= NP_MIN and s["unique_buyers"] >= UB_MIN and s["buy_sol"] >= BUY_MIN and s["v_sol_now"] <= MAX_ENTRY_V:
                entry_v = s["v_sol_now"]
                rec = {"ts": now, "mint": mint, "action": "PASS", "age": round(age,1), "np": round(s["net_pressure"],3), "ub": s["unique_buyers"], "buy_sol": round(s["buy_sol"],3), "entry_v": round(entry_v,3)}
                with JOURNAL.open("a") as fh:
                    fh.write(json.dumps(rec) + chr(10))
                PASSED.append({"mint": mint, "pass_ts": now, "entry_v": entry_v, "logged": False})
                print("[PASS]", mint[:12], "np=" + str(round(s["net_pressure"],2)), "ub=" + str(s["unique_buyers"]), "buy=" + str(round(s["buy_sol"],3)), "v_sol=" + str(round(entry_v,2)))
                CANDIDATES.pop(mint, None)
            elif age > WAIT_S * 2:
                CANDIDATES.pop(mint, None)
        for p in list(PASSED):
            if p["logged"]:
                continue
            if now - p["pass_ts"] < FORWARD_S:
                continue
            s = ts.stats_for(p["mint"])
            if s is None:
                continue
            exit_v = s["v_sol_now"]
            chg = (exit_v / p["entry_v"]) ** 2 - 1.0
            p["logged"] = True
            rec = {"ts": now, "mint": p["mint"], "action": "FORWARD", "entry_v": round(p["entry_v"],3), "exit_v": round(exit_v,3), "chg": round(chg,4), "dt": FORWARD_S}
            with JOURNAL.open("a") as fh:
                fh.write(json.dumps(rec) + chr(10))
            print("[FORWARD]", p["mint"][:12], "entry_v=" + str(round(p["entry_v"],2)), "exit_v=" + str(round(exit_v,2)), "chg=" + str(round(chg*100,2)) + "pct")
    await ts.stop()
    print("=== SUMMARY ===")
    print("candidates_pending:", len(CANDIDATES))
    print("passes:", len(PASSED))
    completed = [p for p in PASSED if p["logged"]]
    print("forward_complete:", len(completed))
asyncio.run(main())
