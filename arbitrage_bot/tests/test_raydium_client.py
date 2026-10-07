"""Tests RaydiumClient (s195)."""
import json
import unittest

from arbitrage_bot.app.exchanges.base import OrderRequest
from arbitrage_bot.app.exchanges.raydium_client import (
    ALLOWED_HOSTS,
    RaydiumClient,
)


GOOD_HOST = "https://api-v3.raydium.io"


def fake_http_ok(method, url, headers, body):
    if "/pools/info/list" in url:
        return 200, json.dumps({
            "id": "abc",
            "success": True,
            "data": {
                "count": 2,
                "data": [
                    {
                        "type": "Standard",
                        "id": "pool-small",
                        "mintA": {"symbol": "WSOL", "address": "So111"},
                        "mintB": {"symbol": "USDC", "address": "EPjF"},
                        "price": "100.0",
                        "feeRate": 0.0025,
                        "tvl": "1000000",
                        "day": {"volume": "100"},
                    },
                    {
                        "type": "Standard",
                        "id": "pool-big",
                        "mintA": {"symbol": "WSOL", "address": "So111"},
                        "mintB": {"symbol": "USDC", "address": "EPjF"},
                        "price": "101.0",
                        "feeRate": 0.0025,
                        "tvl": "5000000",
                        "day": {"volume": "500"},
                    },
                ],
                "hasNextPage": False,
            },
        })
    return 404, "{}"


def fake_http_500(method, url, headers, body):
    return 500, "boom"


class TestRaydiumClient(unittest.TestCase):

    def test_positive_get_orderbook(self):
        c = RaydiumClient(GOOD_HOST, http_call=fake_http_ok, fee_bps=25)
        book = c.get_orderbook("SOL/USDC")
        self.assertEqual(book.symbol, "SOL/USDC")
        # max-tvl pool = pool-big, price=101.0, fee=25bps -> half = 101*12.5/10000 = 0.12625
        self.assertAlmostEqual(book.best_bid(), 101.0 - 0.12625, places=4)
        self.assertAlmostEqual(book.best_ask(), 101.0 + 0.12625, places=4)
        self.assertTrue(book.is_valid())

    def test_sol_alias_wsol(self):
        """SOL должен матчиться с WSOL из API."""
        c = RaydiumClient(GOOD_HOST, http_call=fake_http_ok)
        book = c.get_orderbook("SOL/USDC")
        self.assertIsNotNone(book.best_bid())

    def test_r4_violation_rejected(self):
        with self.assertRaises(ValueError):
            RaydiumClient("https://evil.com")

    def test_pool_not_found_returns_empty_book(self):
        c = RaydiumClient(GOOD_HOST, http_call=fake_http_ok)
        book = c.get_orderbook("NOPE/XYZ")
        self.assertIsNone(book.best_bid())
        self.assertIsNone(book.best_ask())
        self.assertEqual(book.bids, [])

    def test_http_500_returns_empty_book(self):
        c = RaydiumClient(GOOD_HOST, http_call=fake_http_500)
        book = c.get_orderbook("SOL/USDC")
        self.assertIsNone(book.best_bid())
        self.assertIsNone(book.best_ask())
        self.assertEqual(book.bids, [])

    def test_bad_symbol_returns_empty_book(self):
        c = RaydiumClient(GOOD_HOST, http_call=fake_http_ok)
        book = c.get_orderbook("NOPE")
        self.assertIsNone(book.best_bid())
        self.assertIsNone(book.best_ask())
        self.assertEqual(book.bids, [])

    def test_place_order_read_only(self):
        c = RaydiumClient(GOOD_HOST, http_call=fake_http_ok)
        res = c.place_order(
            OrderRequest(symbol="SOL/USDC", side="buy", price=100.0, size=1.0)
        )
        self.assertFalse(res.accepted)
        self.assertEqual(res.reason, "read_only_phase1")

    def test_cancel_order_returns_false(self):
        c = RaydiumClient(GOOD_HOST, http_call=fake_http_ok)
        self.assertFalse(c.cancel_order("x"))


if __name__ == "__main__":
    unittest.main()
