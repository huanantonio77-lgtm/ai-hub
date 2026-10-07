"""Tests GmxClient (s195).

Oracle scale check: SOL 10^(30-9)=1e21, ETH 10^(30-18)=1e12, BTC 10^(30-8)=1e22.
"""
import json
import unittest

from arbitrage_bot.app.exchanges.base import OrderRequest
from arbitrage_bot.app.exchanges.gmx_client import (
    ALLOWED_HOSTS,
    GmxClient,
)


GOOD_HOST = "https://arbitrum-api.gmxinfra.io"


def fake_http_ok(method, url, headers, body):
    if "/prices/tickers" in url:
        # SOL: 10^(30-9) = 1e21. raw = 121.0 * 1e21 = "121000000000000000000000"
        # BTC: 10^(30-8) = 1e22. raw = 85610.0 * 1e22 = "856100000000000000000000000"
        return 200, json.dumps([
            {
                "tokenAddress": "0xsol",
                "tokenSymbol": "SOL",
                "minPrice": "121000000000000000000000",
                "maxPrice": "121000000000000000000000",
                "updatedAt": 1,
                "timestamp": 1,
            },
            {
                "tokenAddress": "0xbtc",
                "tokenSymbol": "BTC",
                "minPrice": "856100000000000000000000000",
                "maxPrice": "856100000000000000000000000",
                "updatedAt": 1,
                "timestamp": 1,
            },
        ])
    return 404, "{}"


def fake_http_500(method, url, headers, body):
    return 500, "boom"


class TestGmxClient(unittest.TestCase):

    def test_positive_get_orderbook(self):
        c = GmxClient(GOOD_HOST, http_call=fake_http_ok, fee_bps=20)
        book = c.get_orderbook("SOL/USD")
        self.assertEqual(book.symbol, "SOL/USD")
        # mid = 121.0, half = 121 * 10 / 10000 = 0.121
        self.assertAlmostEqual(book.best_bid(), 121.0 - 0.121, places=4)
        self.assertAlmostEqual(book.best_ask(), 121.0 + 0.121, places=4)
        self.assertTrue(book.is_valid())

    def test_btc_oracle_scale(self):
        """BTC имеет decimals=8 → 10^(30-8)=1e22."""
        c = GmxClient(GOOD_HOST, http_call=fake_http_ok)
        book = c.get_orderbook("BTC/USD")
        self.assertAlmostEqual(book.mid(), 85610.0, places=2)

    def test_r4_violation_rejected(self):
        with self.assertRaises(ValueError):
            GmxClient("https://evil.com")

    def test_ticker_not_found_returns_empty_book(self):
        c = GmxClient(GOOD_HOST, http_call=fake_http_ok)
        book = c.get_orderbook("NOPE/USD")
        self.assertIsNone(book.best_bid())
        self.assertIsNone(book.best_ask())
        self.assertEqual(book.bids, [])

    def test_http_500_returns_empty_book(self):
        c = GmxClient(GOOD_HOST, http_call=fake_http_500)
        book = c.get_orderbook("SOL/USD")
        self.assertIsNone(book.best_bid())
        self.assertEqual(book.bids, [])

    def test_bad_symbol_returns_empty_book(self):
        c = GmxClient(GOOD_HOST, http_call=fake_http_ok)
        book = c.get_orderbook("NOPE")
        self.assertIsNone(book.best_bid())
        self.assertEqual(book.bids, [])

    def test_place_order_read_only(self):
        c = GmxClient(GOOD_HOST, http_call=fake_http_ok)
        res = c.place_order(
            OrderRequest(symbol="SOL/USD", side="buy", price=100.0, size=1.0)
        )
        self.assertFalse(res.accepted)
        self.assertEqual(res.reason, "read_only_phase1")

    def test_cancel_order_returns_false(self):
        c = GmxClient(GOOD_HOST, http_call=fake_http_ok)
        self.assertFalse(c.cancel_order("x"))


if __name__ == "__main__":
    unittest.main()
