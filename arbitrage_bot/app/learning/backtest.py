"""Backtest-обвязка для stage 3 (ТЗ §19).

Stage 3: без биржевого I/O — работает по списку готовых снапшотов
(BookSnapshot), которые формируются вызывающим кодом (fixtures, replay).

Детерминизм (R3): обход снапшотов в порядке списка.
Без ML/LLM (R1/R2). Всё локально (R4/R5).

Покрывает §19 Backtest:
  - исторический стакан (передаётся снаружи как BookSnapshot);
  - реальные комиссии (из ScannerConfig);
  - проскальзывание (profitability + liquidity);
  - частичное исполнение (через VirtualTrade);
  - ограничения по объёму (liquidity).

Задержка/недоступность биржи — моделируются отсутствием снапшота
или пустым стаканом в конкретный ts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from arbitrage_bot.app.execution.state_machine import VirtualTrade
from arbitrage_bot.app.market_data.orderbook import OrderBook
from arbitrage_bot.app.strategy.liquidity import LiquidityConfig, check_liquidity
from arbitrage_bot.app.strategy.scanner import ScannerConfig, scan_exchanges


@dataclass
class BookSnapshot:
    """Один снапшот рынка: момент времени + стаканы по биржам."""
    ts: int
    symbol: str
    books: dict[str, OrderBook]


@dataclass
class BacktestTrade:
    """Одна прошедшая сделка в бэктесте (opportunity + виртуальная нога)."""
    ts: int
    buy_exchange: str
    sell_exchange: str
    buy_price: float
    sell_price: float
    size: float
    net_percent: float
    realized_pnl_abs: float


@dataclass
class BacktestResult:
    """Результат прогона бэктеста по списку снапшотов."""
    snapshots: int
    scanned: int
    passing: int
    liquid: int
    trades: list[BacktestTrade] = field(default_factory=list)
    total_pnl_abs: float = 0.0

    def equity_curve(self) -> list[float]:
        """Кумулятивный PnL по сделкам в порядке исполнения."""
        out: list[float] = []
        acc = 0.0
        for t in self.trades:
            acc += t.realized_pnl_abs
            out.append(acc)
        return out


def _play_trade(
    snap: BookSnapshot,
    buy_ex: str,
    sell_ex: str,
    buy_price: float,
    sell_price: float,
    size: float,
    net_percent: float,
) -> BacktestTrade:
    """Прогоняет одну возможность через VirtualTrade, возвращает запись."""
    t = VirtualTrade(snap.symbol, target_size=size)
    t.on_fill("buy", buy_ex, buy_price, size, ts=snap.ts)
    t.on_fill("sell", sell_ex, sell_price, size, ts=snap.ts + 1)
    t.close()
    return BacktestTrade(
        ts=snap.ts,
        buy_exchange=buy_ex,
        sell_exchange=sell_ex,
        buy_price=buy_price,
        sell_price=sell_price,
        size=size,
        net_percent=net_percent,
        realized_pnl_abs=t.realized_pnl_abs(),
    )


def run_backtest(
    snapshots: list[BookSnapshot],
    scan_cfg: ScannerConfig,
    liq_cfg: LiquidityConfig,
) -> BacktestResult:
    """Прогон scanner + liquidity по списку снапшотов (ТЗ §19).

    Для каждого снапшота:
      1. scan_exchanges — все прошедшие возможности по всем парам бирж;
      2. check_liquidity на buy-ноге и sell-ноге;
      3. VirtualTrade проигрывает сделку, копит realized_pnl_abs.

    Возвращает BacktestResult с агрегатами и списком сделок.
    """
    res = BacktestResult(snapshots=len(snapshots), scanned=0, passing=0, liquid=0)

    for snap in snapshots:
        opps = scan_exchanges(snap.symbol, snap.books, scan_cfg, only_passing=True)
        res.scanned += 1
        res.passing += len(opps)
        for opp in opps:
            book_buy = snap.books[opp.buy_exchange]
            book_sell = snap.books[opp.sell_exchange]
            liq_buy = check_liquidity(book_buy, "buy", opp.size, liq_cfg)
            liq_sell = check_liquidity(book_sell, "sell", opp.size, liq_cfg)
            if not (liq_buy.ok and liq_sell.ok):
                continue
            res.liquid += 1
            trade = _play_trade(
                snap,
                buy_ex=opp.buy_exchange,
                sell_ex=opp.sell_exchange,
                buy_price=opp.buy_price,
                sell_price=opp.sell_price,
                size=opp.size,
                net_percent=opp.net_percent,
            )
            res.trades.append(trade)
            res.total_pnl_abs += trade.realized_pnl_abs

    return res
