"""Тесты контракта биржевого адаптера (exchanges/base.py, ТЗ §14).

5 уровней verify (s151-r4):
  V1 POSITIVE   — NoopExchange удовлетворяет контракту (instances of ABC)
  V2 INVARIANT  — get_orderbook возвращает изолированные OrderBook
  V3 NEG-empty  — Noop стакан пустой (best_bid/ask = None)
  V4 NEG-place  — place_order отклоняется (accepted=False, reason='noop')
  V5 EDGE-bound — cancel_order(unknown) → False; OrderRequest валидация
"""

import unittest

from arbitrage_bot.app.exchanges.base import (
    ExchangeAdapter,
    NoopExchange,
    OrderRequest,
    OrderResult,
)


class TestExchangeAdapter(unittest.TestCase):

    def test_v1_positive_contract(self):
        ex = NoopExchange()
        self.assertIsInstance(ex, ExchangeAdapter)
        self.assertEqual(ex.name, "noop")
        for meth in ("get_orderbook", "place_order", "cancel_order"):
            self.assertTrue(callable(getattr(ex, meth)))

    def test_v2_invariant_isolated_books(self):
        ex = NoopExchange()
        a = ex.get_orderbook("BTC/USDT")
        b = ex.get_orderbook("BTC/USDT")
        self.assertIsNot(a, b)
        a.apply_snapshot(bids=[(100.0, 1.0)], asks=[(101.0, 1.0)])
        self.assertEqual(len(a.bids), 1)
        self.assertEqual(len(b.bids), 0)  # b не изменился

    def test_v3_neg_empty_book(self):
        ex = NoopExchange()
        book = ex.get_orderbook("BTC/USDT")
        self.assertIsNone(book.best_bid())
        self.assertIsNone(book.best_ask())
        self.assertEqual(len(book.bids), 0)
        self.assertEqual(len(book.asks), 0)

    def test_v4_neg_place_rejected(self):
        ex = NoopExchange()
        req = OrderRequest(symbol="BTC/USDT", side="buy", price=100.0, size=1.0)
        res = ex.place_order(req)
        self.assertIsInstance(res, OrderResult)
        self.assertFalse(res.accepted)
        self.assertEqual(res.reason, "noop")
        self.assertEqual(res.filled_size, 0.0)

    def test_v5_edge_validation_and_cancel(self):
        # side невалидный
        with self.assertRaises(ValueError):
            OrderRequest(symbol="BTC/USDT", side="hold", price=100.0, size=1.0)
        # price<=0
        with self.assertRaises(ValueError):
            OrderRequest(symbol="BTC/USDT", side="buy", price=0.0, size=1.0)
        # size<=0
        with self.assertRaises(ValueError):
            OrderRequest(symbol="BTC/USDT", side="sell", price=100.0, size=0.0)
        # cancel неизвестного ордера
        ex = NoopExchange()
        self.assertFalse(ex.cancel_order("nonexistent"))


if __name__ == "__main__":
    unittest.main()
