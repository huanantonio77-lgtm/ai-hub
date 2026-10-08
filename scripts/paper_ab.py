"""paper_ab: A/B comparison. A=baseline, B=flow-based. Read-only research."""
import asyncio, json, time, pathlib, sys, statistics
from dataclasses import dataclass
from typing import Optional
sys.path.insert(0, "scripts")
from trade_stream import TradeStream

A_MIN_DEV=2.0; A_WAIT=30; A_NP=0.3; A_UB=3; A_BUY=0.5; A_HOLD=120
B_MIN_DEV=1.0; B_WAIT=30; B_MULT=3.0; B_HOLD=180
SIZE=0.01; TICK=5; DURATION=600; INITIAL_V=30.0

@dataclass
class Cand:
    mint:str; dev_buy:float; seen_at:float; v_create:float

@dataclass
class Pos:
    mint:str; entry_time:float; entry_v:float; size:float
    strat:str; peak_chg:float=0.0
async def main():
    env={}
    for l in pathlib.Path(".env").read_text().splitlines():
        if "=" in l and not l.startswith("#"):
            k,v=l.split("=",1); env[k.strip()]=v.strip()
    cA,cB={},{}
    pA,pB={},{}
    clA,clB=[],[]
    ts=None
    async def on_new(data):
        mint=data.get("mint")
        if not mint: return
        try: dev=float(data.get("solAmount",0))
        except Exception: dev=0.0
        v=INITIAL_V+dev
        if dev>=A_MIN_DEV and mint not in cA: cA[mint]=Cand(mint,dev,time.time(),v)
        if dev>=B_MIN_DEV and mint not in cB: cB[mint]=Cand(mint,dev,time.time(),v)
        if (mint in cA or mint in cB) and mint not in ts.tracked_mints():
            await ts.subscribe_token(mint)
    ts=TradeStream(env["PUMPPORTAL_API_KEY"],on_new_token=on_new)
    await ts.start()
    print(f"A:dev>={A_MIN_DEV} B:dev>={B_MIN_DEV} dur={DURATION}s size={SIZE}")
    start=time.time()
    while time.time()-start<DURATION:
        await asyncio.sleep(TICK)
        now=time.time()
        for mint,c in list(cA.items()):
            if mint in pA or now-c.seen_at<A_WAIT: continue
            s=ts.stats_for(mint)
            if s is None: continue
            if s["net_pressure"]>=A_NP and s["unique_buyers"]>=A_UB and s["buy_sol"]>=A_BUY:
                cur=c.v_create+(s["buy_sol"]-s["sell_sol"])
                pA[mint]=Pos(mint,now,cur,SIZE,"A")
                print(f"[A.ENTER] {mint[:14]} np={s['net_pressure']:+.2f} ub={s['unique_buyers']}")
                cA.pop(mint,None)
        for mint,c in list(cB.items()):
            if mint in pB or now-c.seen_at<B_WAIT: continue
            s=ts.stats_for(mint)
            if s is None: continue
            ex=s["buy_sol"]-s["sell_sol"]
            if ex>=SIZE*B_MULT:
                cur=c.v_create+ex
                pB[mint]=Pos(mint,now,cur,SIZE,"B")
                print(f"[B.ENTER] {mint[:14]} ex={ex:.3f} np={s['net_pressure']:+.2f}")
                cB.pop(mint,None)
        for mint,p in list(pA.items()):
            s=ts.stats_for(mint)
            if s is None: continue
            cur=p.entry_v+(s["buy_sol"]-s["sell_sol"])
            chg=(cur/p.entry_v)**2-1.0
            if chg>p.peak_chg: p.peak_chg=chg
            age=now-p.entry_time; reason=None
            if chg>=0.5: reason="partial_1"
            elif chg<=-0.30: reason="stop"
            elif age>=A_HOLD: reason="timeout"
            if reason:
                pnl=chg*p.size
                clA.append({"mint":mint,"chg":chg,"pnl":pnl,"reason":reason,"hold":age})
                print(f"[A.EXIT/{reason}] {mint[:14]} chg={chg:+.1%} pnl={pnl:+.5f}")
                pA.pop(mint); cA.pop(mint,None)
                await ts.unsubscribe_token(mint)
        for mint,p in list(pB.items()):
            s=ts.stats_for(mint)
            if s is None: continue
            cur=p.entry_v+(s["buy_sol"]-s["sell_sol"])
            chg=(cur/p.entry_v)**2-1.0
            if chg>p.peak_chg: p.peak_chg=chg
            age=now-p.entry_time; np_now=s["net_pressure"]; reason=None
            if np_now<-0.2 and age>=60: reason="flow_reversal"
            elif chg<=-0.30: reason="stop"
            elif age>=B_HOLD: reason="max_hold"
            if reason:
                pnl=chg*p.size
                clB.append({"mint":mint,"chg":chg,"pnl":pnl,"reason":reason,"hold":age})
                print(f"[B.EXIT/{reason}] {mint[:14]} chg={chg:+.1%} np={np_now:+.2f} pnl={pnl:+.5f}")
                pB.pop(mint); cB.pop(mint,None)
                await ts.unsubscribe_token(mint)
    await ts.stop()
    print()
    for nm,cl,op in [("A",clA,pA),("B",clB,pB)]:
        pnl=sum(c["pnl"] for c in cl)
        wins=[c for c in cl if c["pnl"]>0]
        ah=statistics.mean(c["hold"] for c in cl) if cl else 0
        ac=statistics.mean(c["chg"] for c in cl) if cl else 0
        print(f"=== {nm} ({DURATION}s) ===")
        print(f"  closed:{len(cl)} open:{len(op)} pnl:{pnl:+.5f}")
        print(f"  winrate:{len(wins)}/{len(cl)} avg_chg:{ac:+.1%} avg_hold:{ah:.0f}s")
    print(f"stream cost: {ts.cost_sol():.8f}")

asyncio.run(main())
