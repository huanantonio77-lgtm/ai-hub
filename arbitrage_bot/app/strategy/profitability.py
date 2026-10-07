"""Расчёт чистой прибыли арбитражной возможности (ТЗ §6).

Формула:
    net_abs = V_sell - V_buy - F_buy - F_sell - S_buy - S_sell - safety_buffer
    net_percent = net_abs / V_buy * 100
    passes = net_percent >= min_profit_percent

Обозначения:
    V_buy   = buy_price * size              (фактическая стоимость покупки)
    V_sell  = sell_price * size             (ожидаемая стоимость продажи)
    F_*     = V_* * taker_fee_percent / 100 (комиссии тейкера на ноге)
    S_*     = V_* * max_slippage_percent / 100 (проскальзывание)
    safety_buffer = V_buy * safety_buffer_percent / 100 (резерв риска)

Все проценты — в тех же единицах, что в config/default.json
(0.25 = 0.25%, не 0.0025). I/O здесь нет.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FeesConfig:
    """Комиссии бирж в процентах от объёма сделки."""
    taker_a: float
    maker_a: float
    taker_b: float
    maker_b: float


@dataclass
class ProfitabilityConfig:
    """Пороги из ТЗ §6."""
    min_profit_percent: float
    safety_buffer_percent: float
    max_slippage_percent: float


@dataclass
class ArbitrageOpportunity:
    symbol: str
    buy_exchange: str
    sell_exchange: str
    buy_price: float
    sell_price: float
    size: float
    gross_percent: float
    net_percent: float
    net_abs: float
    passes: bool


def gross_percent(buy_price: float, sell_price: float) -> float:
    """Валовая разница по ТЗ §6: (sell - buy) / buy."""
    if buy_price <= 0:
        raise ValueError("buy_price must be > 0")
    return (sell_price - buy_price) / buy_price


def evaluate(
    symbol: str,
    buy_exchange: str,
    sell_exchange: str,
    buy_price: float,
    sell_price: float,
    size: float,
    taker_fee_buy_percent: float,
    taker_fee_sell_percent: float,
    cfg: ProfitabilityConfig,
) -> ArbitrageOpportunity:
    """Оценивает одну возможность покупки на buy_exchange и продажи
    на sell_exchange.

    Все проценты — в единицах config (0.25 = 0.25%).
    """
    if buy_price <= 0:
        raise ValueError("buy_price must be > 0")
    if sell_price <= 0:
        raise ValueError("sell_price must be > 0")
    if size <= 0:
        raise ValueError("size must be > 0")

    v_buy = buy_price * size
    v_sell = sell_price * size
    f_buy = v_buy * taker_fee_buy_percent / 100.0
    f_sell = v_sell * taker_fee_sell_percent / 100.0
    s_buy = v_buy * cfg.max_slippage_percent / 100.0
    s_sell = v_sell * cfg.max_slippage_percent / 100.0
    safety = v_buy * cfg.safety_buffer_percent / 100.0

    net_abs = v_sell - v_buy - f_buy - f_sell - s_buy - s_sell - safety
    net_pct = net_abs / v_buy * 100.0
    gross_pct = gross_percent(buy_price, sell_price) * 100.0

    return ArbitrageOpportunity(
        symbol=symbol,
        buy_exchange=buy_exchange,
        sell_exchange=sell_exchange,
        buy_price=buy_price,
        sell_price=sell_price,
        size=size,
        gross_percent=gross_pct,
        net_percent=net_pct,
        net_abs=net_abs,
        passes=net_pct >= cfg.min_profit_percent,
    )
