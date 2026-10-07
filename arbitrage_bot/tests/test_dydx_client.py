"""Тесты DydxClient (s194).

Симметрия с test_hyperliquid_client.py. Покрывают:
positive, http 500, R4 violation, R4 whitelist, read-only place/cancel,
symbol passthrough (формат BTC-USD).
"""
import json
import unittest

from arbitrage_bot.app.exchanges.base import OrderRequest
from arbitrage_bot.app.exchanges.dydx_client import (
    ALLOWED_HOSTS,
    DydxClient,
)


GOOD_HOST = "https://indexer.dydx.trade"


def fake_http_ok(method, url, headers, body):
    if "orderbooks" in url:
        return 200, json.dumps({
            "bids": [
                {"price": "100.0", "size": "1.5"},
                {"price": "99.5", "size": "2.0"},
            ],
            "asks": [
                {"price": "100.5", "size": "1.0"},
                {"price": "101.0", "size": "3.0"},
            ],
        })
    return 404, "{}"


def fake_http_500(method, url, headers, body):
    return 500, '{"error":"boom"}'


class TestDydxClient(unittest.TestCase):

    def test_positive_get_orderbook(self):
        c = DydxClient(GOOD_HOST, http_call=fake_http_ok)
        book = c.get_orderbook("BTC-USD")
        self.assertEqual(book.symbol, "BTC-USD")
        self.assertEqual(book.best_bid(), 100.0)
        self.assertEqual(book.best_ask(), 100.5)
        self.assertTrue(book.is_valid())

    def test_non_quiet_http_500(self):
        c = DydxClient(GOOD_HOST, http_call=fake_http_500)
        book = c.get_orderbook("BTC-USD")
        self.assertIsNone(book.best_bid())
        self.assertIsNone(book.best_ask())
        self.assertTrue(book.is_valid())

    def test_neg1_r4_violation(self):
        with self.assertRaises(ValueError):
            DydxClient("https://evil.example.com")

    def test_neg2_r4_whitelist_shape(self):
        self.assertGreaterEqual(len(ALLOWED_HOSTS), 1)
        self.assertIn("indexer.dydx.trade", ALLOWED_HOSTS)

    def test_read_only_place_order(self):
        c = DydxClient(GOOD_HOST, http_call=fake_http_ok)
        req = OrderRequest(symbol="BTC-USD", side="buy", price=100.0, size=1.0)
        res = c.place_order(req)
        self.assertFalse(res.accepted)
        self.assertEqual(res.reason, "read_only_phase1")

    def test_read_only_cancel_order(self):
        c = DydxClient(GOOD_HOST, http_call=fake_http_ok)
        self.assertFalse(c.cancel_order("XXX"))

    def test_symbol_passthrough(self):
        seen = {}
        def capture(method, url, headers, body):
            seen["url"] = url
            return 200, json.dumps({"bids": [], "asks": []})
        c = DydxClient(GOOD_HOST, http_call=capture)
        c.get_orderbook("ETH-USD")
        self.assertIn("ETH-USD", seen["url"])


if __name__ == "__main__":
    unittest.main()
