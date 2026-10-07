"""Проверка ликвидности арбитражной возможности (ТЗ §7, stage 2).

Stage 2: без биржевого I/O — работает с готовыми OrderBook.
Детерминизм (R3): обход уровней сверху вниз, без случайности.
Без ML/LLM (R1/R2). Всё локально (R4/R5).

Контракт по ТЗ §7:
  - нельзя считать по best_ask — нужно пройти по уровням;
  - средневзвешенная цена исполнения для заданного объёма;
  - отказ, если заполнено меньше заявленного объёма;
  - отказ, если потребление стакана > max_orderbook_consumption_percent;
  - отказ, если проскальзывание > max_slippage_percent;
  - отказ, если доступная ликвидность (USDT) < min_liquidity_usdt.
"""

from __future__ import annotations

from dataclasses import dataclass

from arbitrage_bot.app.market_data.orderbook import BookLevel, OrderBook


@dataclass
class LiquidityConfig:
    """Пороги из ТЗ §7."""
    max_orderbook_consumption_percent: float  # 15 = 15%
    max_slippage_percent: float               # 0.08 = 0.08%
    min_liquidity_usdt: float                 # 5000 USDT
    min_depth_levels: int = 1                 # минимальная глубина (число уровней)


@dataclass
class LiquidityCheck:
    """Результат проверки ликвидности одной стороны сделки."""
    side: str                    # 'buy' (eat asks) | 'sell' (eat bids)
    requested_size: float
    filled_size: float
    avg_price: float             # средневзвешенная цена исполнения
    best_price: float            # лучшая цена (верх стакана)
    slippage_percent: float      # (avg - best)/best*100 для buy, (best-avg)/best*100 для sell
    consumption_percent: float   # заполнено / доступно
    liquidity_usdt: float        # filled_size * avg_price
    ok: bool
    reason: str                  # '' если ok, иначе код причины


def _levels_for(book: OrderBook, side: str) -> list[BookLevel]:
    if side == "buy":
        return list(book.asks)
    if side == "sell":
        return list(book.bids)
    raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")


def _total_available(levels: list[BookLevel]) -> float:
    return sum(l.size for l in levels)


def _walk(levels: list[BookLevel], size: float) -> tuple[float, float]:
    """Проходит по уровням, набирает `size`. Возвращает (filled, notional)."""
    filled = 0.0
    notional = 0.0
    for lvl in levels:
        take = min(lvl.size, size - filled)
        filled += take
        notional += take * lvl.price
        if filled >= size:
            break
    return filled, notional


def check_liquidity(
    book: OrderBook,
    side: str,
    size: float,
    cfg: LiquidityConfig,
) -> LiquidityCheck:
    """Проверяет, что заданный объём `size` исполнится в пределах порогов §7."""
    if size <= 0:
        raise ValueError("size must be > 0")
    levels = _levels_for(book, side)
    if len(levels) < cfg.min_depth_levels:
        return LiquidityCheck(
            side=side, requested_size=size, filled_size=0.0,
            avg_price=0.0, best_price=0.0, slippage_percent=0.0,
            consumption_percent=0.0, liquidity_usdt=0.0,
            ok=False, reason="insufficient_depth",
        )

    best_price = levels[0].price
    available = _total_available(levels)
    filled, notional = _walk(levels, size)
    avg_price = notional / filled if filled > 0 else 0.0

    if filled < size - 1e-12:
        return LiquidityCheck(
            side=side, requested_size=size, filled_size=filled,
            avg_price=avg_price, best_price=best_price,
            slippage_percent=0.0,
            consumption_percent=(filled / available * 100.0) if available > 0 else 0.0,
            liquidity_usdt=filled * avg_price,
            ok=False, reason="insufficient_size",
        )

    if side == "buy":
        slippage_percent = (avg_price - best_price) / best_price * 100.0
    else:
        slippage_percent = (best_price - avg_price) / best_price * 100.0

    consumption_percent = (filled / available * 100.0) if available > 0 else 100.0
    liquidity_usdt = filled * avg_price

    if consumption_percent > cfg.max_orderbook_consumption_percent:
        return LiquidityCheck(
            side=side, requested_size=size, filled_size=filled,
            avg_price=avg_price, best_price=best_price,
            slippage_percent=slippage_percent,
            consumption_percent=consumption_percent,
            liquidity_usdt=liquidity_usdt,
            ok=False, reason="consumption_too_high",
        )
    if slippage_percent > cfg.max_slippage_percent:
        return LiquidityCheck(
            side=side, requested_size=size, filled_size=filled,
            avg_price=avg_price, best_price=best_price,
            slippage_percent=slippage_percent,
            consumption_percent=consumption_percent,
            liquidity_usdt=liquidity_usdt,
            ok=False, reason="slippage_too_high",
        )
    if liquidity_usdt < cfg.min_liquidity_usdt:
        return LiquidityCheck(
            side=side, requested_size=size, filled_size=filled,
            avg_price=avg_price, best_price=best_price,
            slippage_percent=slippage_percent,
            consumption_percent=consumption_percent,
            liquidity_usdt=liquidity_usdt,
            ok=False, reason="liquidity_too_low",
        )

    return LiquidityCheck(
        side=side, requested_size=size, filled_size=filled,
        avg_price=avg_price, best_price=best_price,
        slippage_percent=slippage_percent,
        consumption_percent=consumption_percent,
        liquidity_usdt=liquidity_usdt,
        ok=True, reason="",
    )
