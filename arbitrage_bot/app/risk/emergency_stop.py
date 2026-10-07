"""EMERGENCY_STOP по ТЗ §11 (stage 4).

Кнопка/команда аварийной остановки. В stage 4 — только локальное
состояние + список действий; реальная отмена ордеров и закрытие
позиций — через ExchangeAdapter (NoopExchange в stage 4).

R4-совместимо: чистое состояние, ноль I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field


TRIGGER_REASONS = (
    "price_stale",
    "websocket_lost",
    "orderbook_corrupted",
    "balance_mismatch",
    "exchange_down",
    "daily_loss_exceeded",
    "api_errors_exceeded",
    "exchange_limits_changed",
    "unhedged_timeout",
    "manual",
)


@dataclass
class EmergencyStop:
    """Аварийный стоп-переключатель.

    Пока tripped=True — новые сделки запрещены; cancel/close — pending
    до вызова `drain_actions()`.
    """
    tripped: bool = False
    reason: str = ""
    pending_actions: list[str] = field(default_factory=list)

    def trigger(self, reason: str) -> None:
        if reason not in TRIGGER_REASONS:
            raise ValueError(f"unknown trigger reason: {reason!r}")
        self.tripped = True
        self.reason = reason
        self.pending_actions = [
            "block_new_trades",
            "cancel_open_orders",
            "list_unhedged_positions",
            "close_unhedged",
        ]

    def can_trade(self) -> bool:
        return not self.tripped

    def reset(self) -> None:
        self.tripped = False
        self.reason = ""
        self.pending_actions = []

    def drain_actions(self) -> list[str]:
        """Забирает список действий и очищает его (для consumer'а)."""
        out = list(self.pending_actions)
        self.pending_actions = []
        return out
