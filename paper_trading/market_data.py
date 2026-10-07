"""Hyperliquid WebSocket market data - l2Book + trades (async).

Reuses OrderBook from arbitrage_bot as container. websockets 15.
"""
from __future__ import annotations
import asyncio
import json
import ssl
import certifi
from collections import deque
from typing import Optional
import websockets
from arbitrage_bot.app.market_data.orderbook import OrderBook

WS_URL = "wss://api.hyperliquid.xyz/ws"
_SSL_CTX = ssl.create_default_context(cafile=certifi.where())

def _parse_levels(levels):
    """HL: [{'px','sz'}, ...] or [[px, sz], ...] -> [(px, sz)]."""
    out = []
    for lv in levels or []:
        if isinstance(lv, dict):
            out.append((float(lv["px"]), float(lv["sz"])))
        else:
            out.append((float(lv[0]), float(lv[1])))
    return out

class HLBookStream:
    """HL l2Book -> OrderBook + deque of snapshot dicts."""
    def __init__(self, coin: str = "BTC", maxlen: int = 200):
        self.coin = coin
        self.book = OrderBook(coin)
        self.snapshots: deque = deque(maxlen=maxlen)

    async def _subscribe(self, ws):
        msg = {"method": "subscribe",
               "subscription": {"type": "l2Book", "coin": self.coin}}
        await ws.send(json.dumps(msg))

    async def run(self, on_snapshot=None, stop_after: Optional[int] = None,
                  max_reconnects: int = 3) -> int:
        """Consume l2Book. Returns count of snapshots. stop_after=N -> exit."""
        got = 0
        rc = 0
        while rc < max_reconnects:
            try:
                async with websockets.connect(WS_URL, ping_interval=20, ssl=_SSL_CTX) as ws:
                    await self._subscribe(ws)
                    rc = 0
                    async for raw in ws:
                        msg = json.loads(raw)
                        if msg.get("channel") != "l2Book":
                            continue
                        data = msg.get("data") or {}
                        levels = data.get("levels") or [[], []]
                        if len(levels) < 2:
                            continue
                        bids = _parse_levels(levels[0])
                        asks = _parse_levels(levels[1])
                        self.book.apply_snapshot(bids, asks)
                        snap = {"coin": self.coin,
                                "ts": data.get("time"),
                                "best_bid": self.book.best_bid(),
                                "best_ask": self.book.best_ask(),
                                "mid": self.book.mid(),
                                "imb5": _imbalance(self.book, 5)}
                        self.snapshots.append(snap)
                        got += 1
                        if on_snapshot is not None:
                            on_snapshot(snap)
                        if stop_after is not None and got >= stop_after:
                            return got
            except Exception as e:
                rc += 1
                print(f"[HLBookStream] reconnect {rc}/{max_reconnects}: {e!r}")
                await asyncio.sleep(1.5 * rc)
        return got

def _imbalance(book, n: int = 5) -> Optional[float]:
    d = book.depth(n)
    bv = sum(s for _, s in d["bids"])
    av = sum(s for _, s in d["asks"])
    if bv + av <= 0:
        return None
    return (bv - av) / (bv + av)

async def smoke(coin: str = "BTC", seconds: int = 20) -> None:
    s = HLBookStream(coin=coin)
    task = asyncio.create_task(s.run())
    try:
        await asyncio.wait_for(task, timeout=seconds)
    except asyncio.TimeoutError:
        task.cancel()
    print(f"smoke {coin}: got {len(s.snapshots)} snapshots")
    if s.snapshots:
        print("last:", s.snapshots[-1])

class HLTradesStream:
    """HL trades -> deque of {ts, px, sz, side}."""
    def __init__(self, coin: str = "BTC", maxlen: int = 2000):
        self.coin = coin
        self.trades: deque = deque(maxlen=maxlen)

    def _ingest(self, items):
        for t in items or []:
            try:
                self.trades.append({
                    "ts": int(t.get("time") or 0),
                    "px": float(t.get("px") or 0),
                    "sz": float(t.get("sz") or 0),
                    "side": t.get("side"),
                })
            except Exception:
                continue

    def volume(self, seconds: int = 60) -> dict:
        if not self.trades:
            return {"n": 0, "sz": 0.0, "notional": 0.0,
                    "buy": 0.0, "sell": 0.0, "window_s": seconds}
        now = self.trades[-1]["ts"]
        cutoff = now - seconds * 1000
        n = 0; sz = 0.0; notional = 0.0; buy = 0.0; sell = 0.0
        for t in reversed(self.trades):
            if t["ts"] < cutoff:
                break
            n += 1
            sz += t["sz"]
            notional += t["px"] * t["sz"]
            if t["side"] == "B":
                buy += t["sz"]
            else:
                sell += t["sz"]
        return {"n": n, "sz": sz, "notional": notional,
                "buy": buy, "sell": sell, "window_s": seconds,
                "last_ts": now}

    async def _subscribe(self, ws):
        await ws.send(json.dumps({
            "method": "subscribe",
            "subscription": {"type": "trades", "coin": self.coin},
        }))

    async def run(self, on_trades=None, stop_after=None, max_reconnects=3):
        got = 0
        rc = 0
        while rc < max_reconnects:
            try:
                async with websockets.connect(WS_URL, ping_interval=20,
                                              ssl=_SSL_CTX) as ws:
                    await self._subscribe(ws)
                    rc = 0
                    async for raw in ws:
                        msg = json.loads(raw)
                        if msg.get("channel") != "trades":
                            continue
                        data = msg.get("data") or []
                        if not isinstance(data, list):
                            continue
                        self._ingest(data)
                        got += len(data)
                        if on_trades is not None:
                            on_trades(data)
                        if stop_after is not None and got >= stop_after:
                            return got
            except Exception as e:
                rc += 1
                print(f"[HLTradesStream] rc {rc}/{max_reconnects}: {e!r}")
                await asyncio.sleep(1.5 * rc)
        return got

async def smoke_trades(coin: str = "BTC", seconds: int = 15) -> None:
    s = HLTradesStream(coin=coin)
    task = asyncio.create_task(s.run())
    try:
        await asyncio.wait_for(task, timeout=seconds)
    except asyncio.TimeoutError:
        task.cancel()
    print(f"smoke_trades {coin}: got {len(s.trades)} trades")
    print("volume(60s):", s.volume(60))
