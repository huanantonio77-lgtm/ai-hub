"""Тесты симулятора стакана (orderbook.py).

5 уровней verify (s151-r4):
  V1 POSITIVE    — best_bid/best_ask/spread на фиксированном стакане
  V2 INVARIANT   — после apply_delta bids по убыв., asks по возр.
  V3 NEG-1 empty — пустой стакан → None, без краша
  V4 NEG-2 zero  — size=0 удаляет уровень, следующий становится лучшим
  V5 EDGE snap   — apply_snapshot перезаписывает (не мержит)
"""

import unittest

from arbitrage_bot.app.market_data.orderbook import BookLevel, OrderBook


class TestOrderBookPositive(unittest.TestCase):
    """V1 POSITIVE — базовые геттеры на фиксированном стакане."""

    def test_best_and_spread(self):
        ob = OrderBook("BTC/USDT")
        ob.apply_snapshot(
            bids=[(100.0, 1.0), (99.5, 2.0)],
            asks=[(100.5, 1.5), (101.0, 2.5)],
        )
        self.assertEqual(ob.best_bid(), 100.0)
        self.assertEqual(ob.best_ask(), 100.5)
        self.assertAlmostEqual(ob.spread(), 0.5)
        self.assertAlmostEqual(ob.mid(), 100.25)
        self.assertTrue(ob.is_valid())


class TestOrderBookInvariant(unittest.TestCase):
    """V2 INVARIANT — сортировка сохраняется после delta."""

    def test_sort_after_delta(self):
        ob = OrderBook("ETH/USDT")
        ob.apply_snapshot(
            bids=[(100.0, 1.0), (99.0, 1.0)],
            asks=[(101.0, 1.0), (102.0, 1.0)],
        )
        ob.apply_delta("bid", 99.5, 2.0)
        ob.apply_delta("ask", 100.8, 1.0)
        self.assertEqual([l.price for l in ob.bids], [100.0, 99.5, 99.0])
        self.assertEqual([l.price for l in ob.asks], [100.8, 101.0, 102.0])
        self.assertTrue(ob.is_valid())


class TestOrderBookNegEmpty(unittest.TestCase):
    """V3 NEG-1 — пустой стакан: геттеры возвращают None, не падают."""

    def test_empty(self):
        ob = OrderBook("SOL/USDT")
        self.assertIsNone(ob.best_bid())
        self.assertIsNone(ob.best_ask())
        self.assertIsNone(ob.spread())
        self.assertIsNone(ob.mid())
        self.assertTrue(ob.is_valid())


class TestOrderBookNegZeroSize(unittest.TestCase):
    """V4 NEG-2 — size=0 удаляет уровень; следующий становится лучшим."""

    def test_zero_removes_and_promotes(self):
        ob = OrderBook("XRP/USDT")
        ob.apply_snapshot(
            bids=[(100.0, 1.0), (99.5, 1.0)],
            asks=[(100.5, 1.0), (101.0, 1.0)],
        )
        ob.apply_delta("bid", 100.0, 0)  # убрать лучший bid
        self.assertEqual(ob.best_bid(), 99.5)
        ob.apply_delta("ask", 100.5, 0)  # убрать лучший ask
        self.assertEqual(ob.best_ask(), 101.0)
        self.assertTrue(ob.is_valid())


class TestOrderBookEdgeSnapshotOverwrite(unittest.TestCase):
    """V5 EDGE — apply_snapshot перезаписывает, а не мержит."""

    def test_snapshot_overwrites(self):
        ob = OrderBook("BTC/USDT")
        ob.apply_snapshot(bids=[(100.0, 1.0)], asks=[(101.0, 1.0)])
        ob.apply_snapshot(bids=[(200.0, 3.0)], asks=[(201.0, 3.0)])
        self.assertEqual(len(ob.bids), 1)
        self.assertEqual(len(ob.asks), 1)
        self.assertEqual(ob.best_bid(), 200.0)
        self.assertEqual(ob.best_ask(), 201.0)


if __name__ == "__main__":
    unittest.main()
