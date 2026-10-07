"""Симулятор виртуальных арбитражных сделок (state machine).

Stage 1: без биржевого I/O. Каждая сделка = 2 ноги (buy + sell) на двух
биржах. on_fill(...) накапливает частичные исполнения, состояние меняется
детерминированно. При несовпадении объёмов ног — сигнал hedge.

Состояния:
    IDLE → OPENING → OPEN → CLOSED
    (любое) → ABORTED (с причиной)

Контракт по ТЗ §6: частичное исполнение + ошибки контролируются явно.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


STATES = ("IDLE", "OPENING", "OPEN", "CLOSED", "ABORTED")


@dataclass
class Fill:
    side: str        # 'buy' | 'sell'
    exchange: str
    price: float
    size: float
    ts: int = 0


@dataclass
class VirtualTrade:
    """Одна виртуальная арбитражная сделка (buy leg + sell leg)."""

    symbol: str
    target_size: float
    min_profit_percent: float = 0.0
    state: str = "IDLE"
    fills: list[Fill] = field(default_factory=list)
    abort_reason: Optional[str] = None
    _events: list[dict] = field(default_factory=list)

    def _log(self, event: str, **kw) -> None:
        self._events.append({"event": event, "state": self.state, **kw})

    # --- геттеры ---

    def buy_filled(self) -> float:
        return sum(f.size for f in self.fills if f.side == "buy")

    def sell_filled(self) -> float:
        return sum(f.size for f in self.fills if f.side == "sell")

    def matched_size(self) -> float:
        return min(self.buy_filled(), self.sell_filled())

    def unmatched_buy(self) -> float:
        return max(0.0, self.buy_filled() - self.sell_filled())

    def unmatched_sell(self) -> float:
        return max(0.0, self.sell_filled() - self.buy_filled())

    def vwap(self, side: str) -> Optional[float]:
        legs = [f for f in self.fills if f.side == side]
        total = sum(f.size for f in legs)
        if total == 0:
            return None
        return sum(f.price * f.size for f in legs) / total

    def realized_pnl_abs(self) -> float:
        """PnL только по matched части (min из buy/sell)."""
        m = self.matched_size()
        if m == 0:
            return 0.0
        vb = self.vwap("buy")
        vs = self.vwap("sell")
        return (vs - vb) * m

    def is_fully_matched(self) -> bool:
        return self.buy_filled() == self.sell_filled() == self.target_size

    def needs_hedge(self) -> bool:
        return self.state in ("OPENING", "OPEN") and (
            self.unmatched_buy() > 0 or self.unmatched_sell() > 0
        )

    # --- переходы ---

    def on_fill(self, side: str, exchange: str, price: float, size: float, ts: int = 0) -> None:
        if self.state in ("CLOSED", "ABORTED"):
            raise RuntimeError(f"trade already {self.state}")
        if side not in ("buy", "sell"):
            raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")
        if size <= 0:
            raise ValueError("size must be > 0")
        if price <= 0:
            raise ValueError("price must be > 0")

        self.fills.append(Fill(side, exchange, float(price), float(size), ts))
        self._log("fill", side=side, size=float(size), price=float(price))

        bf, sf = self.buy_filled(), self.sell_filled()
        if bf > 0 and sf > 0:
            self.state = "OPEN"
        elif bf > 0 or sf > 0:
            self.state = "OPENING"

    def abort(self, reason: str) -> None:
        self.state = "ABORTED"
        self.abort_reason = reason
        self._log("abort", reason=reason)

    def close(self) -> None:
        if self.state != "OPEN":
            raise RuntimeError(f"cannot close from {self.state}")
        self.state = "CLOSED"
        self._log("close")
