"""Тесты проверки ликвидности (liquidity.py, ТЗ §7).

5 уровней verify (s151-r4):
  V1 POSITIVE   — малый объём в одном уровне → ok=True, slippage=0
  V2 INVARIANT  — полный обход одного уровня → avg == best
  V3 NEG-slip   — большой объём, кросс уровней → slippage > max → ok=False
  V4 NEG-depth  — объём больше стакана → filled < size → ok=False
  V5 EDGE-bound — consumption == max_orderbook_consumption_percent → ok=True
"""

import unittest

from arbitrage_bot.app.market_data.orderbook import OrderBook
from arbitrage_bot.app.strategy.liquidity import (
    LiquidityConfig,
    check_liquidity,
)


def _book_with_asks(levels: list[tuple[float, float]]) -> OrderBook:
    book = OrderBook("BTC/USDT")
    book.apply_snapshot(bids=[(1.0, 1.0)], asks=levels)
    return book


def _book_with_bids(levels: list[tuple[float, float]]) -> OrderBook:
    book = OrderBook("BTC/USDT")
    book.apply_snapshot(bids=levels, asks=[(999999.0, 1.0)])
    return book


CFG = LiquidityConfig(
    max_orderbook_consumption_percent=15.0,
    max_slippage_percent=0.08,
    min_liquidity_usdt=100.0,
    min_depth_levels=1,
)


class TestLiquidity(unittest.TestCase):

    def test_v1_positive_small_size_top_level(self):
        # один уровень 100.0 * 10, берём 1.0 — slippage=0, ok
        book = _book_with_asks([(100.0, 10.0)])
        cfg = LiquidityConfig(
            max_orderbook_consumption_percent=50.0,
            max_slippage_percent=1.0,
            min_liquidity_usdt=10.0,
            min_depth_levels=1,
        )
        r = check_liquidity(book, "buy", 1.0, cfg)
        self.assertTrue(r.ok)
        self.assertAlmostEqual(r.avg_price, 100.0, places=9)
        self.assertAlmostEqual(r.best_price, 100.0, places=9)
        self.assertAlmostEqual(r.slippage_percent, 0.0, places=9)
        self.assertAlmostEqual(r.consumption_percent, 10.0, places=9)  # 1/10
        self.assertAlmostEqual(r.liquidity_usdt, 100.0, places=9)

    def test_v2_invariant_full_top_level(self):
        # два уровня, берём ровно верхний — avg == best, slippage=0
        book = _book_with_asks([(100.0, 5.0), (200.0, 5.0)])
        cfg = LiquidityConfig(
            max_orderbook_consumption_percent=100.0,
            max_slippage_percent=1.0,
            min_liquidity_usdt=10.0,
            min_depth_levels=1,
        )
        r = check_liquidity(book, "buy", 5.0, cfg)
        self.assertTrue(r.ok)
        self.assertAlmostEqual(r.avg_price, 100.0, places=9)
        self.assertAlmostEqual(r.slippage_percent, 0.0, places=9)

    def test_v3_neg_slippage_too_high(self):
        # большой объём кросс 100 → 200: avg≈150, slippage≈50% > 0.08
        book = _book_with_asks([(100.0, 1.0), (200.0, 100.0)])
        r = check_liquidity(book, "buy", 10.0, CFG)
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, "slippage_too_high")
        self.assertGreater(r.slippage_percent, CFG.max_slippage_percent)

    def test_v4_neg_insufficient_size(self):
        # просим 100, в стакане только 2
        book = _book_with_asks([(100.0, 1.0), (101.0, 1.0)])
        r = check_liquidity(book, "buy", 100.0, CFG)
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, "insufficient_size")
        self.assertLess(r.filled_size, 100.0)

    def test_v5_edge_consumption_exact_boundary(self):
        # ровно max_orderbook_consumption_percent → ok
        book = _book_with_asks([(100.0, 10.0)])
        cfg = LiquidityConfig(
            max_orderbook_consumption_percent=10.0,   # 1/10 = 10% — ровно граница
            max_slippage_percent=1.0,
            min_liquidity_usdt=10.0,
            min_depth_levels=1,
        )
        r = check_liquidity(book, "buy", 1.0, cfg)
        self.assertTrue(r.ok, f"reason={r.reason}")
        self.assertAlmostEqual(r.consumption_percent, 10.0, places=9)

    def test_sell_side_walks_bids(self):
        # sell: обход bids сверху вниз
        book = _book_with_bids([(101.0, 5.0), (100.0, 5.0)])
        cfg = LiquidityConfig(
            max_orderbook_consumption_percent=100.0,
            max_slippage_percent=1.0,
            min_liquidity_usdt=10.0,
            min_depth_levels=1,
        )
        r = check_liquidity(book, "sell", 5.0, cfg)
        self.assertTrue(r.ok)
        self.assertAlmostEqual(r.avg_price, 101.0, places=9)


if __name__ == "__main__":
    unittest.main()
