"""TradeStream: PumpPortal WS subscribeNewToken + subscribeTokenTrade with rolling 60s stats.

One connection only (PumpPortal bans parallel WS).
Cost: 0.01 SOL per 10000 paid events (NewToken free).
"""
import asyncio, json, ssl, time, certifi
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable
import websockets

WINDOW_S = 60


@dataclass
class MintStats:
    buys: deque = field(default_factory=deque)
    sells: deque = field(default_factory=deque)


class TradeStream:
    def __init__(
        self,
        api_key: str,
        on_new_token: Optional[Callable[[dict], Awaitable[None]]] = None,
    ):
        self.api_key = api_key
        self.on_new_token = on_new_token
        self._stats: dict[str, MintStats] = {}
        self._subscribed: set[str] = set()
        self._ws = None
        self._task: Optional[asyncio.Task] = None
        self._events_count = 0
        self._running = False

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self):
        url = f"wss://pumpportal.fun/api/data?api-key={self.api_key}"
        ctx = ssl.create_default_context(cafile=certifi.where())
        while self._running:
            try:
                async with websockets.connect(url, ssl=ctx, ping_interval=20) as ws:
                    self._ws = ws
                    await ws.send(json.dumps({"method": "subscribeNewToken"}))
                    if self._subscribed:
                        await ws.send(json.dumps({
                            "method": "subscribeTokenTrade",
                            "keys": list(self._subscribed),
                        }))
                    async for msg in ws:
                        if not self._running:
                            break
                        try:
                            data = json.loads(msg)
                        except Exception:
                            continue
                        await self._handle(data)
            except Exception as e:
                if self._running:
                    print(f"[trade_stream] ws error: {e}")
                    await asyncio.sleep(5)

    async def _handle(self, data: dict):
        mint = data.get("mint")
        if not mint:
            return
        self._events_count += 1
        tx = data.get("txType")
        if tx == "create":
            if self.on_new_token:
                try:
                    await self.on_new_token(data)
                except Exception as e:
                    print(f"[trade_stream] on_new_token error: {e}")
        elif tx in ("buy", "sell"):
            st = self._stats.setdefault(mint, MintStats())
            now = time.time()
            try:
                sol = float(data.get("solAmount", 0))
            except Exception:
                sol = 0.0
            trader = data.get("traderPublicKey", "")
            if tx == "buy":
                st.buys.append((now, sol, trader))
            else:
                st.sells.append((now, sol, trader))

    async def subscribe_token(self, mint: str):
        if mint in self._subscribed or self._ws is None:
            return
        try:
            await self._ws.send(json.dumps({
                "method": "subscribeTokenTrade",
                "keys": [mint],
            }))
            self._subscribed.add(mint)
            self._stats.setdefault(mint, MintStats())
        except Exception as e:
            print(f"[trade_stream] subscribe_token error: {e}")

    async def unsubscribe_token(self, mint: str):
        if mint not in self._subscribed or self._ws is None:
            return
        try:
            await self._ws.send(json.dumps({
                "method": "unsubscribeTokenTrade",
                "keys": [mint],
            }))
            self._subscribed.discard(mint)
        except Exception:
            pass

    def stats_for(self, mint: str, window_s: int = WINDOW_S) -> Optional[dict]:
        st = self._stats.get(mint)
        if st is None:
            return None
        cutoff = time.time() - window_s
        while st.buys and st.buys[0][0] < cutoff:
            st.buys.popleft()
        while st.sells and st.sells[0][0] < cutoff:
            st.sells.popleft()
        buy_sol = sum(e[1] for e in st.buys)
        sell_sol = sum(e[1] for e in st.sells)
        total = buy_sol + sell_sol
        net = (buy_sol - sell_sol) / total if total > 0 else 0.0
        return {
            "buy_count": len(st.buys),
            "sell_count": len(st.sells),
            "buy_sol": buy_sol,
            "sell_sol": sell_sol,
            "unique_buyers": len({e[2] for e in st.buys if e[2]}),
            "unique_sellers": len({e[2] for e in st.sells if e[2]}),
            "net_pressure": net,
            "total_events": len(st.buys) + len(st.sells),
        }

    def cost_sol(self) -> float:
        return self._events_count * 0.01 / 10000.0

    def tracked_mints(self) -> list[str]:
        return list(self._subscribed)
