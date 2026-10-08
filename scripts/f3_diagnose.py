"""F3 diag: SOL relaxed 5min, prints every 30s."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncio, time
from paper_trading.market_data import HLBookStream, HLTradesStream as HLT
from paper_trading.momentum_signals import detect, volume_spike, breakout

async def main(sec=300):
    bk = HLBookStream(coin="SOL"); tr = HLT(coin="SOL")
    ts = [asyncio.create_task(bk.run()), asyncio.create_task(tr.run())]
    t0 = time.time(); tick = 0
    print(f"=== diag SOL {sec}s lk=30 pct=0.0008 vk=1.8 ===")
    while time.time() - t0 < sec:
        tick += 1; await asyncio.sleep(1.0)
        if tick % 30: continue
        v30, v300 = tr.volume(30), tr.volume(300)
        sp = volume_spike(tr, k=1.8)
        bo = breakout(bk, lookback=30, pct=0.0008, need_spike=sp)
        s = detect(bk, tr, coin="SOL", lookback=30, pct=0.0008,
                   vol_k=1.8, require_volume=True)
        mid = bk.snapshots[-1]["mid"] if bk.snapshots else None
        print(f"[{tick:3d}] n={len(bk.snapshots):3d} mid={mid} "
              f"v30={v30['sz']:.1f} v300={v300['sz']:.1f} "
              f"sp={bool(sp)} bo={bool(bo)} sig={bool(s)}")
    print(f"=== diag done: ticks={tick} ===")
    for t in ts: t.cancel()

if __name__ == "__main__":
    asyncio.run(main(300))
