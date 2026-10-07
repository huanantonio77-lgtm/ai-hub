"""Отчёты по виртуальным арбитражным сделкам (stage 1).

Вход: список VirtualTrade (из execution/state_machine.py).
Выход: list[dict] / CSV-строки / JSON-строки.

Не открывает файлы сам — возвращает содержимое; запись на диск делает
consumer (например, e2e-скрипт или CLI). I/O здесь ноль.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Iterable


CSV_COLUMNS = [
    "symbol",
    "state",
    "target_size",
    "buy_filled",
    "sell_filled",
    "matched_size",
    "unmatched_buy",
    "unmatched_sell",
    "vwap_buy",
    "vwap_sell",
    "pnl_abs",
    "needs_hedge",
    "abort_reason",
]


def trade_to_dict(t) -> dict:
    """Одна сделка → плоский dict."""
    return {
        "symbol": t.symbol,
        "state": t.state,
        "target_size": t.target_size,
        "buy_filled": t.buy_filled(),
        "sell_filled": t.sell_filled(),
        "matched_size": t.matched_size(),
        "unmatched_buy": t.unmatched_buy(),
        "unmatched_sell": t.unmatched_sell(),
        "vwap_buy": t.vwap("buy"),
        "vwap_sell": t.vwap("sell"),
        "pnl_abs": t.realized_pnl_abs(),
        "needs_hedge": t.needs_hedge(),
        "abort_reason": t.abort_reason,
    }


def trades_to_dicts(trades: Iterable) -> list[dict]:
    return [trade_to_dict(t) for t in trades]


def summary(trades: Iterable) -> dict:
    """Агрегат по всем сделкам."""
    rows = trades_to_dicts(trades)
    if not rows:
        return {
            "count": 0, "closed": 0, "aborted": 0,
            "total_pnl_abs": 0.0, "avg_pnl_abs": 0.0,
        }
    total_pnl = sum(r["pnl_abs"] for r in rows)
    return {
        "count": len(rows),
        "closed": sum(1 for r in rows if r["state"] == "CLOSED"),
        "aborted": sum(1 for r in rows if r["state"] == "ABORTED"),
        "total_pnl_abs": total_pnl,
        "avg_pnl_abs": total_pnl / len(rows),
    }


def to_csv(trades: Iterable) -> str:
    """CSV-строка (с заголовком) для всех сделок."""
    rows = trades_to_dicts(trades)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS)
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def to_json(trades: Iterable, indent: int = 2) -> str:
    """JSON-строка: {"summary": ..., "trades": [...]}."""
    return json.dumps(
        {"summary": summary(trades), "trades": trades_to_dicts(trades)},
        indent=indent,
        ensure_ascii=False,
    )
