"""Риск-лимиты по ТЗ §11 (stage 4).

R4-совместимо: чистая арифметика на числах, ноль I/O.
Детерминизм (R3): один вход → один выход.

Значения из §11 (config/default.json может переопределять):
    max_trade_notional_usdt = 100
    max_daily_loss_usdt     = 20
    max_open_operations     = 1
    max_position_time_seconds = 10
    max_api_errors_per_minute = 5
    max_price_age_ms        = 300
    max_clock_difference_ms = 500
    max_consecutive_losses  = 5
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RiskLimits:
    """Обязательные ограничения §11."""
    max_trade_notional_usdt: float = 100.0
    max_daily_loss_usdt: float = 20.0
    max_open_operations: int = 1
    max_position_time_seconds: int = 10
    max_api_errors_per_minute: int = 5
    max_price_age_ms: int = 300
    max_clock_difference_ms: int = 500
    max_consecutive_losses: int = 5


@dataclass
class RiskState:
    """Изменяемое состояние риск-контроля (сбрасывается раз в день)."""
    daily_pnl_usdt: float = 0.0
    consecutive_losses: int = 0
    open_operations: int = 0


@dataclass
class RiskDecision:
    allow: bool
    reason: str = ""


class RiskGuard:
    """Проверяет каждую новую операцию против лимитов §11."""

    def __init__(self, limits: RiskLimits, state: Optional[RiskState] = None):
        self.limits = limits
        self.state = state or RiskState()

    def check_new_trade(self, notional_usdt: float) -> RiskDecision:
        """Проверить возможность открытия новой сделки.

        notional_usdt — V_buy = buy_price * size.
        """
        if notional_usdt <= 0:
            return RiskDecision(False, "notional_must_be_positive")
        if notional_usdt > self.limits.max_trade_notional_usdt:
            return RiskDecision(False, "trade_notional_too_high")
        if self.state.open_operations >= self.limits.max_open_operations:
            return RiskDecision(False, "max_open_operations_reached")
        if self.state.daily_pnl_usdt <= -self.limits.max_daily_loss_usdt:
            return RiskDecision(False, "daily_loss_limit_hit")
        if self.state.consecutive_losses >= self.limits.max_consecutive_losses:
            return RiskDecision(False, "max_consecutive_losses")
        return RiskDecision(True, "")

    def on_open(self) -> None:
        self.state.open_operations += 1

    def on_close(self, pnl_usdt: float) -> None:
        """Закрытие сделки: обновляем дневной PnL и серию убытков."""
        self.state.open_operations = max(0, self.state.open_operations - 1)
        self.state.daily_pnl_usdt += pnl_usdt
        if pnl_usdt < 0:
            self.state.consecutive_losses += 1
        else:
            self.state.consecutive_losses = 0

    def reset_daily(self) -> None:
        self.state.daily_pnl_usdt = 0.0
        self.state.consecutive_losses = 0
