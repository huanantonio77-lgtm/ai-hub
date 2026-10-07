"""Тесты HyperliquidClient (s192).

Покрывают: positive, http 500, R4 violation, R4 whitelist shape,
read-only place_order/cancel_order, symbol passthrough.
"""
import json
import unittest

from arbitrage_bot.app.exchanges.base import OrderRequest
from arbitrage_bot.app.exchanges.hyperliquid_client import (
    ALLOWED_HOSTS,
    HyperliquidClient,
)


GOOD_HOST = "https://api.hyperliquid.xyz"


def fake_http_ok(method, url, headers, body):
    if url.endswith("/info"):
        payload = json.loads(body.decode("utf-8"))
        assert payload.get("type") == "l2Book"
        assert "coin" in payload
        return 200, json.dumps({
            "coin": payload["coin"],
            "time": 1700000000000,
            "levels": [
                [{"px": "100.0", "sz": "1.5", "n": 3},
                 {"px": "99.5", "sz": "2.0", "n": 5}],
                [{"px": "100.5", "sz": "1.0", "n": 4},
                 {"px": "101.0", "sz": "3.0", "n": 6}],
            ],
        })
    return 404, "{}"


def fake_http_500(method, url, headers, body):
    return 500, '{"error":"boom"}'


class TestHyperliquidClient(unittest.TestCase):

    def test_positive_get_orderbook(self):
        c = HyperliquidClient(GOOD_HOST, http_call=fake_http_ok)
        book = c.get_orderbook("BTC")
        self.assertEqual(book.symbol, "BTC")
        self.assertEqual(book.best_bid(), 100.0)
        self.assertEqual(book.best_ask(), 100.5)
        self.assertTrue(book.is_valid())

    def test_non_quiet_http_500(self):
        c = HyperliquidClient(GOOD_HOST, http_call=fake_http_500)
        book = c.get_orderbook("BTC")
        self.assertIsNone(book.best_bid())
        self.assertIsNone(book.best_ask())
        self.assertTrue(book.is_valid())

    def test_neg1_r4_violation(self):
        with self.assertRaises(ValueError):
            HyperliquidClient("https://evil.example.com")

    def test_neg2_r4_whitelist_shape(self):
        self.assertGreaterEqual(len(ALLOWED_HOSTS), 1)
        self.assertIn("api.hyperliquid.xyz", ALLOWED_HOSTS)

    def test_read_only_place_order(self):
        c = HyperliquidClient(GOOD_HOST, http_call=fake_http_ok)
        req = OrderRequest(symbol="BTC", side="buy", price=100.0, size=1.0)
        res = c.place_order(req)
        self.assertFalse(res.accepted)
        self.assertEqual(res.reason, "read_only_phase1")

    def test_read_only_cancel_order(self):
        c = HyperliquidClient(GOOD_HOST, http_call=fake_http_ok)
        self.assertFalse(c.cancel_order("XXX"))

    def test_symbol_passthrough(self):
        seen = {}
        def capture(method, url, headers, body):
            seen["payload"] = json.loads(body.decode("utf-8"))
            return 200, json.dumps({"coin": "ETH", "levels": [[], []]})
        c = HyperliquidClient(GOOD_HOST, http_call=capture)
        c.get_orderbook("ETH")
        self.assertEqual(seen["payload"]["coin"], "ETH")


if __name__ == "__main__":
    unittest.main()
