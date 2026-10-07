"""Tests OrcaClient (s195)."""
import json
import unittest

from arbitrage_bot.app.exchanges.base import OrderRequest
from arbitrage_bot.app.exchanges.orca_client import (
    ALLOWED_HOSTS,
    OrcaClient,
)


GOOD_HOST = "https://api.orca.so"


def fake_http_ok(method, url, headers, body):
    if "/pools" in url:
        return 200, json.dumps({
            "data": [
                {
                    "address": "pool1",
                    "tokenA": {"symbol": "SOL"},
                    "tokenB": {"symbol": "USDC"},
                    "price": "100.0",
                    "feeRate": 30,
                    "tvlUsdc": "1000000",
                },
                {
                    "address": "pool2",
                    "tokenA": {"symbol": "SOL"},
                    "tokenB": {"symbol": "USDC"},
                    "price": "101.0",
                    "feeRate": 30,
                    "tvlUsdc": "5000000",
                },
            ],
            "meta": {},
        })
    return 404, "{}"


def fake_http_500(method, url, headers, body):
    return 500, "boom"


class TestOrcaClient(unittest.TestCase):

    def test_positive_get_orderbook(self):
        c = OrcaClient(GOOD_HOST, http_call=fake_http_ok, fee_bps=30)
        book = c.get_orderbook("SOL/USDC")
        self.assertEqual(book.symbol, "SOL/USDC")
        # max-tvl pool = pool2, price=101.0, fee=30bps -> half = 101*15/10000 = 0.1515
        self.assertAlmostEqual(book.best_bid(), 101.0 - 0.1515, places=4)
        self.assertAlmostEqual(book.best_ask(), 101.0 + 0.1515, places=4)
        self.assertTrue(book.is_valid())

    def test_r4_violation_rejected(self):
        with self.assertRaises(ValueError):
            OrcaClient("https://evil.com")

    def test_pool_not_found_returns_empty_book(self):
        c = OrcaClient(GOOD_HOST, http_call=fake_http_ok)
        book = c.get_orderbook("NOPE/XYZ")
        self.assertIsNone(book.best_bid())
        self.assertIsNone(book.best_ask())
        self.assertEqual(book.bids, [])

    def test_http_500_returns_empty_book(self):
        c = OrcaClient(GOOD_HOST, http_call=fake_http_500)
        book = c.get_orderbook("SOL/USDC")
        self.assertIsNone(book.best_bid())
        self.assertIsNone(book.best_ask())
        self.assertEqual(book.bids, [])

    def test_bad_symbol_returns_empty_book(self):
        c = OrcaClient(GOOD_HOST, http_call=fake_http_ok)
        book = c.get_orderbook("NOPE")
        self.assertIsNone(book.best_bid())
        self.assertIsNone(book.best_ask())
        self.assertEqual(book.bids, [])

    def test_place_order_read_only(self):
        c = OrcaClient(GOOD_HOST, http_call=fake_http_ok)
        res = c.place_order(
            OrderRequest(symbol="SOL/USDC", side="buy", price=100.0, size=1.0)
        )
        self.assertFalse(res.accepted)
        self.assertEqual(res.reason, "read_only_phase1")

    def test_cancel_order_returns_false(self):
        c = OrcaClient(GOOD_HOST, http_call=fake_http_ok)
        self.assertFalse(c.cancel_order("x"))


if __name__ == "__main__":
    unittest.main()
