"""Тесты scanner'а арбитража (scanner.py, ТЗ §6).

5 уровней verify (s151-r4):
  V1 POSITIVE   — реальный спред, passes=True, точные buy/sell
  V2 INVARIANT  — нулевые комиссии/слип/safety → net == gross
  V3 NEG-low    — маленький спред → passes=False
  V4 NEG-empty  — пустые стаканы → []
  V5 EDGE-bound — net_pct == min_profit_percent → passes=True
"""

import unittest

from arbitrage_bot.app.market_data.orderbook import OrderBook
from arbitrage_bot.app.strategy.profitability import ProfitabilityConfig
from arbitrage_bot.app.strategy.scanner import (
    ScannerConfig,
    scan_exchanges,
    scan_pair,
)


def _make_book(symbol: str, bid: float, ask: float, size: float = 10.0) -> OrderBook:
    book = OrderBook(symbol)
    book.apply_snapshot(bids=[(bid, size)], asks=[(ask, size)])
    return book


CFG_PASS = ScannerConfig(
    profitability=ProfitabilityConfig(
        min_profit_percent=0.25,
        safety_buffer_percent=0.10,
        max_slippage_percent=0.08,
    ),
    taker_fee_a_percent=0.1,
    taker_fee_b_percent=0.1,
    size=1.0,
)

CFG_ZERO = ScannerConfig(
    profitability=ProfitabilityConfig(
        min_profit_percent=0.0,
        safety_buffer_percent=0.0,
        max_slippage_percent=0.0,
    ),
    taker_fee_a_percent=0.0,
    taker_fee_b_percent=0.0,
    size=1.0,
)


class TestScanner(unittest.TestCase):

    def test_v1_positive_real_spread(self):
        a = _make_book("BTC/USDT", bid=101.0, ask=102.0)
        b = _make_book("BTC/USDT", bid=99.0, ask=99.5)
        opps = scan_pair("BTC/USDT", a, b, CFG_PASS, "A", "B")
        passing = [o for o in opps if o.passes]
        self.assertEqual(len(passing), 1)
        o = passing[0]
        self.assertEqual(o.buy_exchange, "B")
        self.assertEqual(o.sell_exchange, "A")
        self.assertAlmostEqual(o.buy_price, 99.5)
        self.assertAlmostEqual(o.sell_price, 101.0)
        self.assertGreater(o.net_percent, 0.25)

    def test_v2_invariant_zero_costs(self):
        a = _make_book("BTC/USDT", bid=101.0, ask=102.0)
        b = _make_book("BTC/USDT", bid=100.0, ask=100.5)
        opps = scan_pair("BTC/USDT", a, b, CFG_ZERO, "A", "B")
        b2a = [o for o in opps if o.buy_exchange == "B" and o.sell_exchange == "A"]
        self.assertEqual(len(b2a), 1)
        o = b2a[0]
        self.assertAlmostEqual(o.net_percent, o.gross_percent, places=9)
        self.assertAlmostEqual(o.net_abs, 101.0 - 100.5, places=9)

    def test_v3_neg_low_spread(self):
        a = _make_book("BTC/USDT", bid=100.01, ask=100.02)
        b = _make_book("BTC/USDT", bid=100.00, ask=100.005)
        opps = scan_pair("BTC/USDT", a, b, CFG_PASS, "A", "B")
        for o in opps:
            self.assertFalse(o.passes)

    def test_v4_neg_empty_books(self):
        a = OrderBook("BTC/USDT")
        b = OrderBook("BTC/USDT")
        opps = scan_pair("BTC/USDT", a, b, CFG_PASS, "A", "B")
        self.assertEqual(opps, [])

    def test_v5_edge_boundary(self):
        cfg = ScannerConfig(
            profitability=ProfitabilityConfig(
                min_profit_percent=0.25,
                safety_buffer_percent=0.0,
                max_slippage_percent=0.0,
            ),
            taker_fee_a_percent=0.0,
            taker_fee_b_percent=0.0,
            size=1.0,
        )
        a = _make_book("BTC/USDT", bid=100.25, ask=200.0)
        b = _make_book("BTC/USDT", bid=50.0, ask=100.0)
        opps = scan_pair("BTC/USDT", a, b, cfg, "A", "B")
        b2a = [o for o in opps if o.buy_exchange == "B" and o.sell_exchange == "A"]
        self.assertEqual(len(b2a), 1)
        o = b2a[0]
        self.assertAlmostEqual(o.net_percent, 0.25, places=6)
        self.assertTrue(o.passes)


if __name__ == "__main__":
    unittest.main()
