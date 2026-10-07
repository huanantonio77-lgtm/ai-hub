"""Тесты live_paper.py (stage 7, s165).

5 уровней verify (s151-r4):
  V1 POSITIVE    - прибыльный спред -> >=1 сделка, PnL > 0
  V2 NON-QUIET   - нет спреда -> 0 сделок, run() завершается
  V3 NEG-1       - <2 адаптеров -> ValueError
  V4 NEG-2       - TestnetAdapter на evil.com -> ValueError (R4)
  V5 WRITE-PATH  - steps=3 -> 3 вызова get_orderbook на каждом адаптере
"""

from __future__ import annotations

import unittest

from arbitrage_bot.app.exchanges.base import (
    ExchangeAdapter,
    OrderRequest,
    OrderResult,
)
from arbitrage_bot.app.exchanges.testnet_adapter import TestnetAdapter
from arbitrage_bot.app.execution.live_paper import (
    LivePaperConfig,
    LivePaperTrader,
)
from arbitrage_bot.app.market_data.orderbook import OrderBook
from arbitrage_bot.app.strategy.liquidity import LiquidityConfig
from arbitrage_bot.app.strategy.profitability import ProfitabilityConfig
from arbitrage_bot.app.strategy.scanner import ScannerConfig


def _make_book(symbol, bids, asks):
    book = OrderBook(symbol)
    book.apply_snapshot(bids, asks)
    return book


class FakeAdapter(ExchangeAdapter):
    """Минимальный адаптер: возвращает заранее заданный стакан."""

    def __init__(self, name, book):
        self.name = name
        self._book = book
        self.get_orderbook_calls = 0

    def get_orderbook(self, symbol):
        self.get_orderbook_calls += 1
        return self._book

    def place_order(self, req):
        return OrderResult(accepted=False, reason="fake: no real orders")

    def cancel_order(self, order_id):
        return False


def _profitable_books():
    a = _make_book("BTCUSDT", bids=[(99.5, 1000.0)], asks=[(100.0, 1000.0)])
    b = _make_book("BTCUSDT", bids=[(101.0, 1000.0)], asks=[(101.5, 1000.0)])
    return a, b


def _flat_books():
    a = _make_book("BTCUSDT", bids=[(99.5, 1000.0)], asks=[(100.0, 1000.0)])
    b = _make_book("BTCUSDT", bids=[(99.5, 1000.0)], asks=[(100.0, 1000.0)])
    return a, b


def _test_scan_cfg(size=100.0):
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


def _test_liq_cfg():
    return LiquidityConfig(
        max_orderbook_consumption_percent=15.0,
        max_slippage_percent=0.08,
        min_liquidity_usdt=100.0,
        min_depth_levels=1,
    )


class TestLivePaper(unittest.TestCase):

    def test_v1_positive_profitable_spread(self):
        a, b = _profitable_books()
        adapters = {"A": FakeAdapter("A", a), "B": FakeAdapter("B", b)}
        cfg = LivePaperConfig(
            symbol="BTCUSDT",
            initial_capital=100000.0,
            steps=1,
            scan_cfg=_test_scan_cfg(),
            liq_cfg=_test_liq_cfg(),
        )
        trader = LivePaperTrader(adapters, cfg)
        result = trader.run()
        self.assertGreaterEqual(len(result.trades), 1)
        self.assertGreater(result.total_pnl_abs, 0.0)

    def test_v2_non_quiet_no_spread(self):
        a, b = _flat_books()
        adapters = {"A": FakeAdapter("A", a), "B": FakeAdapter("B", b)}
        cfg = LivePaperConfig(
            symbol="BTCUSDT",
            initial_capital=100000.0,
            steps=2,
            scan_cfg=_test_scan_cfg(),
            liq_cfg=_test_liq_cfg(),
        )
        trader = LivePaperTrader(adapters, cfg)
        result = trader.run()
        self.assertEqual(len(result.trades), 0)
        self.assertGreaterEqual(len(result.equity_curve), 1)
        self.assertEqual(result.total_pnl_abs, 0.0)

    def test_v3_neg_one_adapter_raises(self):
        a, _ = _profitable_books()
        adapters = {"A": FakeAdapter("A", a)}
        cfg = LivePaperConfig(
            symbol="BTCUSDT", initial_capital=10000.0, steps=1
        )
        with self.assertRaises(ValueError):
            LivePaperTrader(adapters, cfg)

    def test_v4_neg_r4_whitelist_violation(self):
        # TestnetAdapter падает на недопустимом хосте ещё до live_paper.
        with self.assertRaises(ValueError):
            TestnetAdapter("https://evil.com")

    def test_v6_write_path_final_capital_matches_pnl(self):
        """s165-r1: run() должен финализировать final_capital.

        Проверка: final == initial + total_pnl_abs; final > initial при прибыли.
        """
        a, b = _profitable_books()
        adapters = {"A": FakeAdapter("A", a), "B": FakeAdapter("B", b)}
        cfg = LivePaperConfig(
            symbol="BTCUSDT",
            initial_capital=100000.0,
            steps=3,
            scan_cfg=_test_scan_cfg(),
            liq_cfg=_test_liq_cfg(),
        )
        trader = LivePaperTrader(adapters, cfg)
        result = trader.run()
        self.assertEqual(
            result.final_capital,
            result.initial_capital + result.total_pnl_abs,
        )
        self.assertGreater(result.final_capital, result.initial_capital)

    def test_v5_write_path_steps_call_adapter(self):
        a, b = _profitable_books()
        fa = FakeAdapter("A", a)
        fb = FakeAdapter("B", b)
        adapters = {"A": fa, "B": fb}
        cfg = LivePaperConfig(
            symbol="BTCUSDT",
            initial_capital=100000.0,
            steps=3,
            scan_cfg=_test_scan_cfg(),
            liq_cfg=_test_liq_cfg(),
        )
        trader = LivePaperTrader(adapters, cfg)
        result = trader.run()
        self.assertEqual(fa.get_orderbook_calls, 3)
        self.assertEqual(fb.get_orderbook_calls, 3)
        self.assertGreaterEqual(len(result.equity_curve), 1)


if __name__ == "__main__":
    unittest.main()
