"""Live-сессия paper-торговли на testnet-данных (stage 8, s167).

Обёртка над LivePaperTrader (stage 7, s165):
  - time-based цикл (duration_sec + interval_sec);
  - safety cap (max_steps) от бесконечного цикла;
  - heartbeat-колбэк для прогресса (каждые N шагов).

Композиция, не наследование: контракт LivePaperTrader не меняется.

Инварианты R1-R5 (s156):
  R1 - ноль LLM-API: только time/dataclasses/typing + локальные модули.
  R2 - ноль ML: чистые правила, никаких моделей.
  R3 - детерминизм: clock И sleep инжектируются; sorted обход адаптеров
       внутри LivePaperTrader; max_steps как жёсткий cap.
  R4 - сеть только через ExchangeAdapter (whitelist внутри adapter'а).
  R5 - решения о сделке только локально (PaperPortfolio).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

from arbitrage_bot.app.exchanges.base import ExchangeAdapter
from arbitrage_bot.app.execution.live_paper import (
    LivePaperConfig,
    LivePaperTrader,
)
from arbitrage_bot.app.execution.paper_trader import (
    PaperResult,
    PaperTrade,
)
from arbitrage_bot.app.strategy.liquidity import LiquidityConfig
from arbitrage_bot.app.strategy.scanner import ScannerConfig


@dataclass
class LiveSessionConfig:
    """Конфиг одной live-сессии (Stage 8, s167)."""

    symbol: str
    initial_capital: float
    duration_sec: float = 60.0
    interval_sec: float = 1.0
    max_steps: int = 10000
    heartbeat_every: int = 10
    scan_cfg: Optional[ScannerConfig] = None
    liq_cfg: Optional[LiquidityConfig] = None

    def __post_init__(self) -> None:
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be > 0")
        if self.duration_sec <= 0:
            raise ValueError("duration_sec must be > 0")
        if self.interval_sec < 0:
            raise ValueError("interval_sec must be >= 0")
        if self.max_steps <= 0:
            raise ValueError("max_steps must be > 0")
        if self.heartbeat_every < 0:
            raise ValueError("heartbeat_every must be >= 0")


@dataclass
class LiveSessionResult:
    """Итог live-сессии."""

    inner: PaperResult
    start_ts: int
    end_ts: int
    steps_done: int
    duration_sec_actual: float
    heartbeats: int


class LiveSession:
    """Обёртка над LivePaperTrader с time-based циклом.

    Один экземпляр = один прогон. run() возвращает LiveSessionResult.
    """

    def __init__(
        self,
        adapters: dict[str, ExchangeAdapter],
        config: LiveSessionConfig,
        clock: Optional[Callable[[], int]] = None,
        sleep: Optional[Callable[[float], None]] = None,
        on_heartbeat: Optional[Callable[[int, Optional[PaperTrade]], 
None]] = None,
    ) -> None:
        inner_cfg = LivePaperConfig(
            symbol=config.symbol,
            initial_capital=config.initial_capital,
            steps=config.max_steps,
            scan_cfg=config.scan_cfg,
            liq_cfg=config.liq_cfg,
        )
        self._trader = LivePaperTrader(
            adapters=adapters,
            config=inner_cfg,
            clock=clock,
        )
        self._config = config
        self._clock: Callable[[], int] = (
            clock if clock is not None else (lambda: 0)
        )
        self._sleep: Callable[[float], None] = (
            sleep if sleep is not None else time.sleep
        )
        self._on_heartbeat = on_heartbeat
        self._heartbeats = 0

    def run(self) -> LiveSessionResult:
        """Цикл: пока (steps < max_steps) и (elapsed < duration_sec)."""
        start_ts = self._clock()
        steps_done = 0
        while steps_done < self._config.max_steps:
            elapsed = self._clock() - start_ts
            if elapsed >= self._config.duration_sec:
                break
            trade = self._trader.step()
            steps_done += 1
            if (
                self._config.heartbeat_every > 0
                and steps_done % self._config.heartbeat_every == 0
            ):
                self._heartbeats += 1
                if self._on_heartbeat is not None:
                    self._on_heartbeat(steps_done, trade)
            if self._config.interval_sec > 0:
                self._sleep(self._config.interval_sec)
        end_ts = self._clock()
        inner = self._trader.finalize()
        return LiveSessionResult(
            inner=inner,
            start_ts=start_ts,
            end_ts=end_ts,
            steps_done=steps_done,
            duration_sec_actual=float(end_ts - start_ts),
            heartbeats=self._heartbeats,
        )
