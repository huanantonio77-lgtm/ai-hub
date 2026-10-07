"""F3 momentum agent - orchestrator (s206).

Streams:
  - HL BTC l2Book  (HLBookStream)
  - HL BTC trades  (HLTradesStream)
  - Jupiter recent (pump_detector.detect_new, polling)

Emits MomentumSignal via momentum_signals.detect -> journal.
Memory: records every run in strategy_registry (meme_momentum_jito).
"""
from __future__ import annotations
import asyncio, json, time
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SIGNALS = ROOT / ".runtime" / "f3_signals.jsonl"
POOLS   = ROOT / ".runtime" / "f3_pools.jsonl"
SIGNALS.parent.mkdir(parents=True, exist_ok=True)

from paper_trading.market_data import HLBookStream, HLTradesStream
from paper_trading.momentum_signals import detect, MomentumSignal
from paper_trading.pump_detector import detect_new

class F3Agent:
    def __init__(self, coin: str = "SOL", lookback: int = 60,
                 pct: float = 0.0015, vol_k: float = 3.0):
        self.coin = coin
        self.lookback = lookback
        self.pct = pct
        self.vol_k = vol_k
        self.book = HLBookStream(coin=coin)
        self.trades = HLTradesStream(coin=coin)
        self.signals: deque = deque(maxlen=500)
        self.new_pools: deque = deque(maxlen=500)
        self.stats = {"ticks": 0, "signals": 0, "new_pools": 0}

    def _emit(self, sig: MomentumSignal):
        self.signals.append(sig.to_dict())
        self.stats["signals"] += 1
        with open(SIGNALS, "a") as f:
            f.write(json.dumps(sig.to_dict(), ensure_ascii=False) + "\n")
        print(f"  [SIG] {sig.kind} {sig.coin} "
              f"px={sig.price:.2f} score={sig.score:.3f}")

    async def _detect_loop(self, stop_after: float):
        t0 = time.time()
        while time.time() - t0 < stop_after:
            self.stats["ticks"] += 1
            try:
                sig = detect(self.book, self.trades, coin=self.coin,
                             lookback=self.lookback, pct=self.pct,
                             vol_k=self.vol_k, require_volume=True)
                if sig is not None:
                    self._emit(sig)
            except Exception as e:
                print(f"  [detect ERR] {e!r}")
            await asyncio.sleep(1.0)

    async def _pump_loop(self, stop_after: float, interval: int = 30):
        t0 = time.time()
        while time.time() - t0 < stop_after:
            try:
                fresh = detect_new(limit=50)
                if fresh:
                    with open(POOLS, "a") as fp:
                        for f in fresh:
                            self.new_pools.append(f)
                            fp.write(json.dumps(f, ensure_ascii=False) + "\n")
                    self.stats["new_pools"] += len(fresh)
                    print(f"  [S3] {len(fresh)} new mints "
                          f"(first: {fresh[0].get('symbol')})")
            except Exception as e:
                print(f"  [pump ERR] {e!r}")
            await asyncio.sleep(interval)

    async def run(self, seconds: int = 300):
        print(f"=== F3Agent start: {self.coin} {seconds}s ===")
        tasks = [
            asyncio.create_task(self.book.run()),
            asyncio.create_task(self.trades.run()),
            asyncio.create_task(self._detect_loop(stop_after=seconds)),
            asyncio.create_task(self._pump_loop(stop_after=seconds)),
        ]
        try:
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True),
                                   timeout=seconds + 10)
        except asyncio.TimeoutError:
            for t in tasks:
                t.cancel()
        print(f"=== F3Agent stop === stats={self.stats}")

async def smoke(seconds: int = 60, record: bool = False):
    agent = F3Agent(coin="SOL")
    await agent.run(seconds=seconds)
    print(f"signals: {len(agent.signals)}  new_pools: {len(agent.new_pools)}")
    if agent.signals:
        print("last signal:", agent.signals[-1])
    if record:
        try:
            from paper_trading.memory import record_test_result
            record_test_result(
                strategy="meme_momentum_jito",
                hypothesis_id="H5",
                metrics={
                    "duration_s": seconds,
                    "ticks": agent.stats["ticks"],
                    "signals": agent.stats["signals"],
                    "new_pools": agent.stats["new_pools"],
                },
                verdict="inconclusive",
                note="live smoke run",
            )
            print("recorded to memory")
        except Exception as e:
            print(f"memory record skipped: {e!r}")
