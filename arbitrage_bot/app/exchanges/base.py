"""Абстракция биржевого адаптера (ТЗ §14, stage 4).

Stage 4: testnet-интерфейс БЕЗ реального I/O (R4).
Адаптер — это контракт: get_orderbook / place_order / cancel_order.
Реальные реализации (testnet-драйвер) подключаются только при gate:
Автономность >= 97% (сейчас 96% — поэтому NoopExchange).

Инварианты (s156-r0):
  R1 — ноль LLM-API.
  R2 — ноль ML в runtime.
  R3 — детерминизм (один вход → один выход).
  R4 — сеть только к биржам за данными (в stage 4 — I/O вообще нет).
  R5 — решения о сделках только локально.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from arbitrage_bot.app.market_data.orderbook import OrderBook


SIDES = ("buy", "sell")


@dataclass
class OrderRequest:
    """Заявка на исполнение (без биржевого контекста — чистые данные)."""
    symbol: str
    side: str
    price: float
    size: float
    client_id: str = ""

    def __post_init__(self):
        if self.side not in SIDES:
            raise ValueError(f"side must be in {SIDES}, got {self.side!r}")
        if self.price <= 0:
            raise ValueError("price must be > 0")
        if self.size <= 0:
            raise ValueError("size must be > 0")


@dataclass
class OrderResult:
    """Ответ на заявку: принята/отклонена + детали исполнения."""
    accepted: bool
    order_id: str = ""
    reason: str = ""
    filled_size: float = 0.0
    avg_price: float = 0.0


class ExchangeAdapter(ABC):
    """Контракт биржевого адаптера.

    Реализации:
      - NoopExchange — заглушка для stage 4 (R4: без I/O).
      - будущие ExchangeA/B — testnet/live при gate (>=97%).
    """

    name: str = "adapter"

    @abstractmethod
    def get_orderbook(self, symbol: str) -> OrderBook:
        """Возвращает стакан по символу. Без I/O в stage 4."""
        raise NotImplementedError

    @abstractmethod
    def place_order(self, req: OrderRequest) -> OrderResult:
        """Размещает ордер. В Noop — rejects."""
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Отменяет ордер. True если отменён."""
        raise NotImplementedError


class NoopExchange(ExchangeAdapter):
    """R4-совместимая заглушка: ноль I/O, ноль сети.

    get_orderbook → пустой OrderBook.
    place_order   → OrderResult(accepted=False, reason='noop').
    cancel_order  → False (нечего отменять).
    """

    name = "noop"

    def get_orderbook(self, symbol: str) -> OrderBook:
        return OrderBook(symbol)

    def place_order(self, req: OrderRequest) -> OrderResult:
        return OrderResult(
            accepted=False,
            order_id="",
            reason="noop",
            filled_size=0.0,
            avg_price=0.0,
        )

    def cancel_order(self, order_id: str) -> bool:
        return False
