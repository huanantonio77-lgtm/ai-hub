"""Paper-trading виртуальный портфель (ТЗ §19, stage 3).

Stage 3: без биржевого I/O. Принимает список BookSnapshot (готовые
стаканы), на каждом шаге ищет возможность по scanner, проверяет
ликвидность, исполняет через VirtualTrade и обновляет капитал.

Детерминизм (R3): обход снапшотов в порядке списка; при нескольких
возможностях берётся первая (scan_exchanges возвращает в детерминир.
порядке). Без ML/LLM (R1/R2). Всё локально (R4/R5).

Покрывает §19 Paper-сценарий:
  - капитал (initial → final);
  - equity curve (кумулятивный PnL);
  - max drawdown;
  - пропуск сделки при недостатке капитала;
  - частичное исполнение через VirtualTrade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from arbitrage_bot.app.execution.state_machine import VirtualTrade
from arbitrage_bot.app.learning.backtest import BookSnapshot
from arbitrage_bot.app.strategy.liquidity import LiquidityConfig, check_liquidity
from arbitrage_bot.app.strategy.scanner import ScannerConfig, scan_exchanges


@dataclass
class PaperTrade:
    """Одна исполненная сделка в paper-режиме + состояние капитала."""
    ts: int
    buy_exchange: str
    sell_exchange: str
    buy_price: float
    sell_price: float
    size: float
    net_percent: float
    realized_pnl_abs: float
    capital_after: float


@dataclass
class PaperResult:
    """Результат paper-прогона по списку снапшотов."""
    initial_capital: float
    final_capital: float = 0.0
    total_pnl_abs: float = 0.0
    skipped_no_capital: int = 0
    skipped_no_liq: int = 0
    trades: list[PaperTrade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)

    def max_drawdown(self) -> float:
        """Максимальная просадка от пика к впадине (в абсолютных USDT)."""
        peak = self.initial_capital
        max_dd = 0.0
        for eq in self.equity_curve:
            peak = max(peak, eq)
            dd = peak - eq
            max_dd = max(max_dd, dd)
        return max_dd


class PaperPortfolio:
    """Виртуальный портфель: капитал + последовательный прогон."""

    def __init__(
        self,
        initial_capital: float,
        scan_cfg: ScannerConfig,
        liq_cfg: LiquidityConfig,
    ):
        if initial_capital <= 0:
            raise ValueError("initial_capital must be > 0")
        self.initial_capital = float(initial_capital)
        self.capital = float(initial_capital)
        self.scan_cfg = scan_cfg
        self.liq_cfg = liq_cfg
        self.result = PaperResult(initial_capital=self.initial_capital)
        self.result.equity_curve.append(self.initial_capital)

    def _required_capital(self, opp) -> float:
        """Сколько USDT нужно на покупку ноги (V_buy)."""
        return opp.buy_price * opp.size

    def step(self, snap: BookSnapshot) -> Optional[PaperTrade]:
        """Обрабатывает один снапшот. Возвращает исполненную сделку или None."""
        opps = scan_exchanges(
            snap.symbol, snap.books, self.scan_cfg, only_passing=True
        )
        for opp in opps:
            if self.capital < self._required_capital(opp):
                self.result.skipped_no_capital += 1
                continue

            book_buy = snap.books[opp.buy_exchange]
            book_sell = snap.books[opp.sell_exchange]
            liq_buy = check_liquidity(book_buy, "buy", opp.size, self.liq_cfg)
            liq_sell = check_liquidity(book_sell, "sell", opp.size, self.liq_cfg)
            if not (liq_buy.ok and liq_sell.ok):
                self.result.skipped_no_liq += 1
                continue

            t = VirtualTrade(snap.symbol, target_size=opp.size)
            t.on_fill("buy", opp.buy_exchange, opp.buy_price, opp.size, ts=snap.ts)
            t.on_fill("sell", opp.sell_exchange, opp.sell_price, opp.size, ts=snap.ts + 1)
            t.close()
            pnl = t.realized_pnl_abs()

            self.capital += pnl
            self.result.total_pnl_abs += pnl
            self.result.equity_curve.append(self.capital)

            trade = PaperTrade(
                ts=snap.ts,
                buy_exchange=opp.buy_exchange,
                sell_exchange=opp.sell_exchange,
                buy_price=opp.buy_price,
                sell_price=opp.sell_price,
                size=opp.size,
                net_percent=opp.net_percent,
                realized_pnl_abs=pnl,
                capital_after=self.capital,
            )
            self.result.trades.append(trade)
            return trade

        # на этом снапшоте ничего не исполнено — фиксируем flat
        self.result.equity_curve.append(self.capital)
        return None

    def run(self, snapshots: list[BookSnapshot]) -> PaperResult:
        for snap in snapshots:
            self.step(snap)
        self.result.final_capital = self.capital
        return self.result
