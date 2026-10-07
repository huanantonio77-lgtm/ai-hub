"""Сканер межбиржевого арбитража (ТЗ §6, stage 2).

Stage 2: без биржевого I/O — работает с готовыми OrderBook.
Детерминизм (R3): порядок обхода фиксирован, никакой случайности.
Без ML/LLM (R1/R2). Всё локально (R4/R5).

Контракт по ТЗ §6:
  - sell_price = best_bid биржи-продавца;
  - buy_price  = best_ask биржи-покупателя;
  - gross_pct  = (sell - buy) / buy;
  - net_pct    — считает profitability.evaluate по §6.

scanner НЕ ходит вглубь стакана — это задача liquidity.py (C2).
"""

from __future__ import annotations

from dataclasses import dataclass

from arbitrage_bot.app.market_data.orderbook import OrderBook
from arbitrage_bot.app.strategy.profitability import (
    ArbitrageOpportunity,
    ProfitabilityConfig,
    evaluate,
)


@dataclass
class ScannerConfig:
    """Пороги scanner'а — надстройка над ProfitabilityConfig.

    taker_fee_a/b — комиссии тейкера на биржах A и B в процентах (0.1 = 0.1%).
    size — объём сделки в базовой валюте (BTC).
    """
    profitability: ProfitabilityConfig
    taker_fee_a_percent: float
    taker_fee_b_percent: float
    size: float


def scan_pair(
    symbol: str,
    book_a: OrderBook,
    book_b: OrderBook,
    cfg: ScannerConfig,
    exchange_a: str = "A",
    exchange_b: str = "B",
) -> list[ArbitrageOpportunity]:
    """Ищет арбитраж по двум стаканам одной пары (ТЗ §6).

    Проверяет оба направления детерминированно:
      1) купить на B по best_ask(B), продать на A по best_bid(A);
      2) купить на A по best_ask(A), продать на B по best_bid(B).

    Возвращает список возможностей, включая непрошедшие (passes=False) —
    фильтрация по `passes` — задача вызывающего кода.
    """
    out: list[ArbitrageOpportunity] = []

    # Направление 1: buy B, sell A
    buy_p = book_b.best_ask()
    sell_p = book_a.best_bid()
    if buy_p is not None and sell_p is not None and sell_p > buy_p:
        out.append(evaluate(
            symbol=symbol,
            buy_exchange=exchange_b,
            sell_exchange=exchange_a,
            buy_price=buy_p,
            sell_price=sell_p,
            size=cfg.size,
            taker_fee_buy_percent=cfg.taker_fee_b_percent,
            taker_fee_sell_percent=cfg.taker_fee_a_percent,
            cfg=cfg.profitability,
        ))

    # Направление 2: buy A, sell B
    buy_p = book_a.best_ask()
    sell_p = book_b.best_bid()
    if buy_p is not None and sell_p is not None and sell_p > buy_p:
        out.append(evaluate(
            symbol=symbol,
            buy_exchange=exchange_a,
            sell_exchange=exchange_b,
            buy_price=buy_p,
            sell_price=sell_p,
            size=cfg.size,
            taker_fee_buy_percent=cfg.taker_fee_a_percent,
            taker_fee_sell_percent=cfg.taker_fee_b_percent,
            cfg=cfg.profitability,
        ))

    return out


def scan_exchanges(
    symbol: str,
    books: dict[str, OrderBook],
    cfg: ScannerConfig,
    only_passing: bool = True,
) -> list[ArbitrageOpportunity]:
    """Ищет арбитраж по всем парам бирж (ТЗ §6).

    books: {exchange_name: OrderBook} — все стаканы одной пары.
    Порядок обхода — по отсортированным именам (детерминизм R3).
    """
    names = sorted(books.keys())
    out: list[ArbitrageOpportunity] = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            for opp in scan_pair(symbol, books[a], books[b], cfg, a, b):
                if only_passing and not opp.passes:
                    continue
                out.append(opp)
    return out
