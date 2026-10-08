#!/usr/bin/env python3
"""market_flow.py - real-time pump.fun new-token counter.

Usage: python3 scripts/market_flow.py [DURATION_SEC]

Counts new tokens, dev_buy distribution, per-minute rate.
Appends each create to .runtime/market_flow.jsonl
"""
import asyncio, json, ssl, sys, time, pathlib, statistics
from collections import defaultdict
import certifi, websockets

WS = "wss://pumpportal.fun/api/data"
CTX = ssl.create_default_context(cafile=certifi.where())
DUR = int(sys.argv[1]) if len(sys.argv) > 1 else 300
OUT = pathlib.Path(".runtime/market_flow.jsonl")
OUT.parent.mkdir(parents=True, exist_ok=True)


async def main():
    n = 0
    buys = []
    by_min = defaultdict(int)
    sol_by_min = defaultdict(float)
    t0 = time.time()
    nxt = t0 + 60
    print(f"[flow] start dur={DUR}s out={OUT}")
    async with websockets.connect(WS, ssl=CTX, ping_interval=20) as ws:
        await ws.send(json.dumps({"method": "subscribeNewToken"}))
        while time.time() - t0 < DUR:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=5)
            except asyncio.TimeoutError:
                msg = None
            if msg:
                try:
                    d = json.loads(msg)
                except Exception:
                    d = None
                if d and d.get("txType") == "create":
                    n += 1
                    db = float(d.get("solAmount", 0) or 0)
                    buys.append(db)
                    m = int((time.time() - t0) // 60)
                    by_min[m] += 1
                    sol_by_min[m] += db
                    rec = {
                        "ts": time.time(), "mint": d.get("mint", ""),
                        "name": d.get("name", ""), "symbol": d.get("symbol", ""),
                        "uri": d.get("uri", ""), "dev_buy": db,
                        "initialBuy": d.get("initialBuy", 0),
                        "mcapSol": d.get("marketCapSol", 0),
                        "vSol": d.get("vSolInBondingCurve", 0),
                    }
                    with OUT.open("a") as fh:
                        fh.write(json.dumps(rec) + "\n")
            if time.time() >= nxt:
                m = int((time.time() - t0) // 60) - 1
                print(f"  [min {m}] tokens={by_min[m]} dev_sol={sol_by_min[m]:.2f}")
                nxt += 60
    dt = time.time() - t0
    print()
    print(f"=== SUMMARY {dt:.0f}s ===")
    print(f"  tokens: {n}  rate: {n / dt * 60:.1f}/min")
    if buys:
        print(f"  dev_buy: min={min(buys):.3f} med={statistics.median(buys):.3f} max={max(buys):.3f}")
        for t in (1, 2, 5, 10, 50):
            c = sum(1 for x in buys if x >= t)
            print(f"  dev>={t:>3}: {c:4d} ({c / n * 100:5.1f}%)")
    print(f"  journal: {OUT}")


asyncio.run(main())
