"""Тесты TestnetAdapter (stage 6, s163).

R3: mock http_call — никакой реальной сети.
R4: NEG-1 проверяет, что чужой хост отсекается.
"""

from __future__ import annotations

import json
import unittest

from arbitrage_bot.app.exchanges.base import OrderRequest
from arbitrage_bot.app.exchanges.testnet_adapter import (
    ALLOWED_HOSTS,
    TestnetAdapter,
)


GOOD_HOST = "https://testnet.binance.vision"


def fake_http_ok(method, url, headers, body):
    """POSITIVE: валидный JSON для /depth, /order (POST/DELETE)."""
    if "/depth" in url:
        return 200, json.dumps({
            "bids": [["100.0", "1.5"], ["99.5", "2.0"]],
            "asks": [["100.5", "1.0"], ["101.0", "3.0"]],
        })
    if "/order" in url and method == "POST":
        return 200, json.dumps({
            "orderId": "TX-42",
            "executedQty": "1.5",
            "price": "100.0",
        })
    if "/order" in url and method == "DELETE":
        return 200, "{}"
    return 404, "{}"


def fake_http_500(method, url, headers, body):
    return 500, '{"error":"boom"}'


class TestTestnetAdapter(unittest.TestCase):

    def test_positive_get_orderbook(self):
        """POSITIVE: GET depth -> заполненный валидный book."""
        a = TestnetAdapter(GOOD_HOST, http_call=fake_http_ok)
        book = a.get_orderbook("BTCUSDT")
        self.assertEqual(book.symbol, "BTCUSDT")
        self.assertEqual(book.best_bid(), 100.0)
        self.assertEqual(book.best_ask(), 100.5)
        self.assertTrue(book.is_valid())

    def test_non_quiet_http_500(self):
        """NON-QUIET: HTTP 500 на GET -> пустой book без исключений."""
        a = TestnetAdapter(GOOD_HOST, http_call=fake_http_500)
        book = a.get_orderbook("BTCUSDT")
        self.assertIsNone(book.best_bid())
        self.assertIsNone(book.best_ask())
        self.assertTrue(book.is_valid())

    def test_neg1_r4_violation(self):
        """NEG-1: чужой хост -> ValueError (R4)."""
        with self.assertRaises(ValueError):
            TestnetAdapter("https://evil.example.com")

    def test_neg2_r4_whitelist_shape(self):
        """NEG-2: whitelist непустой, содержит testnet-хосты."""
        self.assertGreaterEqual(len(ALLOWED_HOSTS), 1)
        self.assertIn("testnet.binance.vision", ALLOWED_HOSTS)
        for h in ALLOWED_HOSTS:
            self.assertTrue("testnet" in h or "test" in h)

    def test_write_path_place_order(self):
        """WRITE-PATH: POST order -> accepted=True, order_id заполнен."""
        a = TestnetAdapter(GOOD_HOST, http_call=fake_http_ok)
        req = OrderRequest(symbol="BTCUSDT", side="buy", price=100.0, size=1.5)
        res = a.place_order(req)
        self.assertTrue(res.accepted)
        self.assertEqual(res.order_id, "TX-42")
        self.assertEqual(res.filled_size, 1.5)

    def test_write_path_cancel_order(self):
        """WRITE-PATH: DELETE order -> True при 200, False иначе."""
        a = TestnetAdapter(GOOD_HOST, http_call=fake_http_ok)
        self.assertTrue(a.cancel_order("TX-42"))
        b = TestnetAdapter(GOOD_HOST, http_call=fake_http_500)
        self.assertFalse(b.cancel_order("TX-42"))


if __name__ == "__main__":
    unittest.main()
