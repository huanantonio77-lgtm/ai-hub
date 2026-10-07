"""Live paper-trading на реальных данных testnet (stage 7, s165).

Связка: ExchangeAdapter (testnet) -> BookSnapshot -> PaperPortfolio.
Источник данных - реальные (или mock через http_call) стаканы.
Исполнение - виртуальное (PaperPortfolio + VirtualTrade).

Инварианты R1-R5 (s156):
  R1 - ноль LLM-API: только math/dataclasses/typing + локальные модули.
  R2 - ноль ML: чистые правила, никаких моделей.
  R3 - детерминизм: clock инжектируется; порядок обхода адаптеров sorted.
  R4 - сеть только через ExchangeAdapter (whitelist внутри adapter'а).
  R5 - решения о сделке только локально (PaperPortfolio).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from arbitrage_bot.app.exchanges.base import ExchangeAdapter
from arbitrage_bot.app.execution.paper_trader import (
    PaperPortfolio,
    PaperResult,
    PaperTrade,
)
from arbitrage_bot.app.learning.backtest import BookSnapshot
from arbitrage_bot.app.strategy.liquidity import LiquidityConfig
from arbitrage_bot.app.strategy.profitability import ProfitabilityConfig
from arbitrage_bot.app.strategy.scanner import ScannerConfig


def _default_scan_cfg(size: float = 0.01) -> ScannerConfig:
    """Дефолтные пороги scanner'а для live-paper режима."""
    return ScannerConfig(
        profitability=ProfitabilityConfig(
            min_profit_percent=0.10,
            safety_buffer_percent=0.05,
            max_slippage_percent=0.08,
        ),
        taker_fee_a_percent=0.10,
        taker_fee_b_percent=0.10,
        size=size,
    )


def _default_liq_cfg() -> LiquidityConfig:
    """Дефолтные пороги ликвидности (ТЗ §7)."""
    return LiquidityConfig(
        max_orderbook_consumption_percent=15.0,
        max_slippage_percent=0.08,
        min_liquidity_usdt=5000.0,
        min_depth_levels=1,
    )


@dataclass
class LivePaperConfig:
    """Конфиг одного live-paper прогона."""

    symbol: str
    initial_capital: float
    steps: int = 10
    scan_cfg: Optional[ScannerConfig] = None
    liq_cfg: Optional[LiquidityConfig] = None

    def __post_init__(self) -> None:
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be > 0")
        if self.steps <= 0:
            raise ValueError("steps must be > 0")
        if self.scan_cfg is None:
            self.scan_cfg = _default_scan_cfg()
        if self.liq_cfg is None:
            self.liq_cfg = _default_liq_cfg()


class LivePaperTrader:
    """Paper-трейдер на живых (или mock) данных от 2+ ExchangeAdapter.

    Один экземпляр = один прогон. run() возвращает финальный PaperResult.
    """

    def __init__(
        self,
        adapters: dict[str, ExchangeAdapter],
        config: LivePaperConfig,
        clock: Optional[Callable[[], int]] = None,
    ) -> None:
        if len(adapters) < 2:
            raise ValueError(
                "need >= 2 adapters for arbitrage, got " + str(len(adapters))
            )
        self._adapters = dict(adapters)
        self._config = config
        self._clock: Callable[[], int] = (
            clock if clock is not None else (lambda: 0)
        )
        self._portfolio = PaperPortfolio(
            initial_capital=config.initial_capital,
            scan_cfg=config.scan_cfg,
            liq_cfg=config.liq_cfg,
        )
        self._steps_done = 0

    def step(self) -> Optional[PaperTrade]:
        """Один шаг: fetch всех адаптеров -> BookSnapshot -> portfolio.step."""
        books = {
            name: adapter.get_orderbook(self._config.symbol)
            for name, adapter in sorted(self._adapters.items())
        }
        snap = BookSnapshot(
            ts=self._clock(),
            symbol=self._config.symbol,
            books=books,
        )
        self._steps_done += 1
        return self._portfolio.step(snap)

    def finalize(self) -> PaperResult:
        """Финализация (s165-r1, s167-A1): final_capital = capital.

        Публичный метод — используется LiveSession и внешними обёртками,
        которые дёргают step() напрямую.
        """
        self._portfolio.result.final_capital = self._portfolio.capital
        return self._portfolio.result

    def run(self) -> PaperResult:
        """N шагов. Возвращает финальный PaperResult (single-shot)."""
        for _ in range(self._config.steps):
            self.step()
        return self.finalize()
