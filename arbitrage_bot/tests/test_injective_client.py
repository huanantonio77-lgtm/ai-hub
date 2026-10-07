"""Тесты InjectiveClient (s200).

Симметрия с test_dydx_client.py. Покрывают:
positive, http 500, R4 whitelist, read-only place/cancel,
symbol passthrough через market_id (Injective REST LCD).
"""
import json
import unittest

from arbitrage_bot.app.exchanges.base import OrderRequest
from arbitrage_bot.app.exchanges.injective_client import (
    ALLOWED_HOSTS,
    InjectiveClient,
)
from arbitrage_bot.app.exchanges.injective_markets import MARKETS


GOOD_HOST = "https://sentry.lcd.injective.network"


def _ok_body():
    return json.dumps({
        "buys_price_level": [
            {"p": "100000000", "q": "1.5"},
            {"p": "99500000", "q": "2.0"},
        ],
        "sells_price_level": [
            {"p": "100500000", "q": "1.0"},
            {"p": "101000000", "q": "3.0"},
        ],
    })


def fake_http_ok(method, url, headers, body):
    if "orderbook" in url:
        return 200, _ok_body()
    return 404, "{}"


def fake_http_500(method, url, headers, body):
    return 500, '{"error":"boom"}'


class TestInjectiveClient(unittest.TestCase):

    def test_positive_get_orderbook(self):
        c = InjectiveClient(GOOD_HOST, http_call=fake_http_ok)
        book = c.get_orderbook("BTC")
        self.assertEqual(book.best_bid(), 100.0)
        self.assertEqual(book.best_ask(), 100.5)
        self.assertTrue(book.is_valid())

    def test_non_quiet_http_500(self):
        c = InjectiveClient(GOOD_HOST, http_call=fake_http_500)
        book = c.get_orderbook("BTC")
        self.assertIsNone(book.best_bid())
        self.assertIsNone(book.best_ask())
        self.assertTrue(book.is_valid())

    def test_neg1_r4_whitelist_shape(self):
        self.assertGreaterEqual(len(ALLOWED_HOSTS), 1)
        self.assertIn("sentry.lcd.injective.network", ALLOWED_HOSTS)

    def test_read_only_place_order(self):
        c = InjectiveClient(GOOD_HOST, http_call=fake_http_ok)
        req = OrderRequest(symbol="BTC", side="buy", price=100.0, size=1.0)
        res = c.place_order(req)
        self.assertFalse(res.accepted)
        self.assertEqual(res.reason, "read_only_phase1")

    def test_read_only_cancel_order(self):
        c = InjectiveClient(GOOD_HOST, http_call=fake_http_ok)
        self.assertFalse(c.cancel_order("XXX"))

    def test_symbol_passthrough_market_id(self):
        seen = {}
        def capture(method, url, headers, body):
            seen["url"] = url
            return 200, _ok_body()
        c = InjectiveClient(GOOD_HOST, http_call=capture)
        c.get_orderbook("ETH")
        self.assertIn(MARKETS["ETH"]["market_id"], seen["url"])

    def test_unknown_symbol_returns_empty(self):
        c = InjectiveClient(GOOD_HOST, http_call=fake_http_ok)
        book = c.get_orderbook("DOGE")
        self.assertIsNone(book.best_bid())
        self.assertIsNone(book.best_ask())


if __name__ == "__main__":
    unittest.main()
