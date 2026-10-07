"""Testnet-заглушка биржи A (ТЗ §14, stage 5).

Stage 5: R4-совместимый адаптер без I/O. Полностью наследует контракт
NoopExchange; отличается только `name`. Реальный testnet-драйвер —
только при gate Автономность >= 97% (сейчас 96, gate закрыт).
"""

from __future__ import annotations

from arbitrage_bot.app.exchanges.base import NoopExchange


class ExchangeA(NoopExchange):
    """Адаптер биржи A в режиме заглушки (R4: без I/O)."""
    name = "exchange_a"
