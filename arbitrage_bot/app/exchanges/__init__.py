"""Биржевые адаптеры (ТЗ §14).

Stage 4: базовый контракт (base.py) + NoopExchange.
Stage 5: ExchangeA / ExchangeB как подклассы NoopExchange (R4: без I/O).
"""

from arbitrage_bot.app.exchanges.base import (
    ExchangeAdapter,
    NoopExchange,
    OrderRequest,
    OrderResult,
)
from arbitrage_bot.app.exchanges.exchange_a import ExchangeA
from arbitrage_bot.app.exchanges.exchange_b import ExchangeB

__all__ = [
    "ExchangeAdapter",
    "NoopExchange",
    "OrderRequest",
    "OrderResult",
    "ExchangeA",
    "ExchangeB",
]
