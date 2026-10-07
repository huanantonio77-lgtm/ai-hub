"""Tests ParadexClient (s194)."""
import json
import unittest

from arbitrage_bot.app.exchanges.base import OrderRequest
from arbitrage_bot.app.exchanges.paradex_client import (
    ALLOWED_HOSTS,
    ParadexClient,
)


GOOD_HOST = "https://api.prod.paradex.trade"


def fake_http_ok(method, url, headers, body):
    if "/orderbook/" in url:
        return 200, json.dumps({
            "market": "BTC-USD-PERP",
            "seq_no": 1,
            "bids": [["100.0", "1.5"], ["99.5", "2.0"]],
            "asks": [["100.5", "1.0"], ["101.0", "3.0"]],
        })
    return 404, "{}"


def fake_http_500(method, url, headers, body):
    return 500, '{"error":"boom"}'


class TestParadexClient(unittest.TestCase):

    def test_positive_get_orderbook(self):
        c = ParadexClient(GOOD_HOST, http_call=fake_http_ok)
        book = c.get_orderbook("BTC-USD-PERP")
        self.assertEqual(book.symbol, "BTC-USD-PERP")
        self.assertEqual(book.best_bid(), 100.0)
        self.assertEqual(book.best_ask(), 100.5)
        self.assertTrue(book.is_valid())

    def test_non_quiet_http_500(self):
        c = ParadexClient(GOOD_HOST, http_call=fake_http_500)
        book = c.get_orderbook("BTC-USD-PERP")
        self.assertIsNone(book.best_bid())
        self.assertIsNone(book.best_ask())
        self.assertTrue(book.is_valid())

    def test_neg1_r4_violation(self):
        with self.assertRaises(ValueError):
            ParadexClient("https://evil.example.com")

    def test_neg2_r4_whitelist_shape(self):
        self.assertIn("api.prod.paradex.trade", ALLOWED_HOSTS)

    def test_read_only_place_order(self):
        c = ParadexClient(GOOD_HOST, http_call=fake_http_ok)
        req = OrderRequest(symbol="BTC-USD-PERP", side="buy", price=100.0, size=1.0)
        res = c.place_order(req)
        self.assertFalse(res.accepted)
        self.assertEqual(res.reason, "read_only_phase1")

    def test_read_only_cancel_order(self):
        c = ParadexClient(GOOD_HOST, http_call=fake_http_ok)
        self.assertFalse(c.cancel_order("XXX"))

    def test_symbol_passthrough(self):
        seen = {}
        def capture(method, url, headers, body):
            seen["url"] = url
            return 200, json.dumps({"bids": [], "asks": []})
        c = ParadexClient(GOOD_HOST, http_call=capture)
        c.get_orderbook("ETH-USD-PERP")
        self.assertIn("ETH-USD-PERP", seen["url"])


if __name__ == "__main__":
    unittest.main()
