"""Симулятор биржевого стакана (order book) для arbitrage_bot.

Stage 1: без биржевого I/O. Стакан наполняется снапшотами/дельтами извне
(в тестах — фикстурами; в stage 2+ — из websocket_manager).

Контракт по ТЗ §6: best_bid = цена продажи на бирже A,
best_ask = цена покупки на бирже B.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class BookLevel:
    """Один уровень стакана: цена + объём."""
    price: float
    size: float


class OrderBook:
    """Симулятор стакана одной пары на одной бирже.

    Контракт:
      - bids хранятся по убыванию цены (лучший bid = bids[0]);
      - asks хранятся по возрастанию цены (лучший ask = asks[0]);
      - best_bid < best_ask (нет пересечения).

    Инварианты валидны после каждого apply_snapshot / apply_delta.
    """

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.bids: list[BookLevel] = []
        self.asks: list[BookLevel] = []

    # --- геттеры ---

    def best_bid(self) -> Optional[float]:
        return self.bids[0].price if self.bids else None

    def best_ask(self) -> Optional[float]:
        return self.asks[0].price if self.asks else None

    def spread(self) -> Optional[float]:
        bb, ba = self.best_bid(), self.best_ask()
        if bb is None or ba is None:
            return None
        return ba - bb

    def mid(self) -> Optional[float]:
        bb, ba = self.best_bid(), self.best_ask()
        if bb is None or ba is None:
            return None
        return (bb + ba) / 2.0

    # --- мутаторы ---

    def apply_snapshot(self, bids, asks) -> None:
        """Перезаписывает стакан целиком (не мержит).

        Уровни с size<=0 отбрасываются. Порядок приводится к инварианту.
        """
        self.bids = sorted(
            (BookLevel(float(p), float(s)) for p, s in bids if float(s) > 0),
            key=lambda l: l.price, reverse=True,
        )
        self.asks = sorted(
            (BookLevel(float(p), float(s)) for p, s in asks if float(s) > 0),
            key=lambda l: l.price,
        )

    def apply_delta(self, side: str, price: float, size: float) -> None:
        """Применяет одну дельту.

        side in {'bid','ask'}; size=0 → удалить уровень;
        несуществующий уровень + size>0 → добавить.
        """
        if side not in ("bid", "ask"):
            raise ValueError(f"side must be 'bid' or 'ask', got {side!r}")
        book = self.bids if side == "bid" else self.asks
        price = float(price)
        size = float(size)
        for i, lvl in enumerate(book):
            if lvl.price == price:
                if size == 0:
                    book.pop(i)
                else:
                    lvl.size = size
                break
        else:
            if size > 0:
                book.append(BookLevel(price, size))
        book.sort(key=lambda l: l.price, reverse=(side == "bid"))

    # --- интроспекция ---

    def depth(self, n: int = 5) -> dict:
        return {
            "bids": [(l.price, l.size) for l in self.bids[:n]],
            "asks": [(l.price, l.size) for l in self.asks[:n]],
        }

    def is_valid(self) -> bool:
        """Проверка инвариантов: сортировка + нет пересечения."""
        if any(self.bids[i].price < self.bids[i + 1].price
               for i in range(len(self.bids) - 1)):
            return False
        if any(self.asks[i].price > self.asks[i + 1].price
               for i in range(len(self.asks) - 1)):
            return False
        bb, ba = self.best_bid(), self.best_ask()
        if bb is not None and ba is not None and bb >= ba:
            return False
        return True
