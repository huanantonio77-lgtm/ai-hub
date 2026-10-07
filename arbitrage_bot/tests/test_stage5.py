"""Тесты stage 5 адаптеров ExchangeA/ExchangeB (ТЗ §14).

5 уровней verify (s151-r4):
  V1 POSITIVE   — ExchangeA/B удовлетворяют ExchangeAdapter + name
  V2 INVARIANT  — независимые стаканы у разных инстансов
  V3 NEG-place  — place_order → reject (noop), как Noop
  V4 NEG-empty  — get_orderbook пустой
  V5 EDGE-export — импорт из __init__ работает; A != B по name
"""

import unittest

from arbitrage_bot.app.exchanges import (
    ExchangeA,
    ExchangeB,
    ExchangeAdapter,
    NoopExchange,
    OrderRequest,
)


class TestStage5Adapters(unittest.TestCase):

    def test_v1_positive_contract(self):
        a = ExchangeA()
        b = ExchangeB()
        self.assertIsInstance(a, ExchangeAdapter)
        self.assertIsInstance(b, ExchangeAdapter)
        self.assertIsInstance(a, NoopExchange)
        self.assertIsInstance(b, NoopExchange)
        self.assertEqual(a.name, "exchange_a")
        self.assertEqual(b.name, "exchange_b")

    def test_v2_invariant_isolated_books(self):
        a = ExchangeA()
        book1 = a.get_orderbook("BTC/USDT")
        book2 = a.get_orderbook("BTC/USDT")
        self.assertIsNot(book1, book2)
        book1.apply_snapshot(bids=[(100.0, 1.0)], asks=[(101.0, 1.0)])
        self.assertEqual(len(book1.bids), 1)
        self.assertEqual(len(book2.bids), 0)

    def test_v3_neg_place_rejected(self):
        a = ExchangeA()
        req = OrderRequest(symbol="BTC/USDT", side="buy", price=99.5, size=1.0)
        res = a.place_order(req)
        self.assertFalse(res.accepted)
        self.assertEqual(res.reason, "noop")

    def test_v4_neg_empty_book(self):
        b = ExchangeB()
        book = b.get_orderbook("ETH/USDT")
        self.assertIsNone(book.best_bid())
        self.assertIsNone(book.best_ask())

    def test_v5_edge_names_differ(self):
        a = ExchangeA()
        b = ExchangeB()
        self.assertNotEqual(a.name, b.name)
        # оба отменяют невалидно
        self.assertFalse(a.cancel_order("x"))
        self.assertFalse(b.cancel_order("y"))


if __name__ == "__main__":
    unittest.main()
