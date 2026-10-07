"""Тесты CurveClient (s201).

Симметрия с test_injective_client.py + AMM synthetic book.
Покрывают: positive DAI/USDC, positive ETH/stETH, http 500,
R4 whitelist, read-only place/cancel, unknown symbol,
+ AMM-инвариант (bid == ask == spot).
"""
import json
import unittest

from arbitrage_bot.app.exchanges.base import OrderRequest
from arbitrage_bot.app.exchanges.curve_client import (
    ALLOWED_HOSTS,
    CurveClient,
)
from arbitrage_bot.app.exchanges.curve_markets import (
    MARKETS,
    POOL_3POOL,
    POOL_STETH,
)


GOOD_HOST = "https://api.curve.finance/v1/getPools/ethereum/main"


def _ok_body():
    """Реалистичный снапшот: 3pool (3 монеты) + stETH (2 монеты)."""
    return json.dumps({
        "success": True,
        "data": {"poolData": [
            {
                "address": POOL_3POOL,
                "amplificationCoefficient": "2000",
                "coins": [
                    {"symbol": "DAI",  "decimals": "18",
                     "poolBalance": "2000000000000000000000000"},   # 2M DAI
                    {"symbol": "USDC", "decimals": "6",
                     "poolBalance": "1000000000000"},               # 1M USDC
                    {"symbol": "USDT", "decimals": "6",
                     "poolBalance": "3000000000000"},               # 3M USDT
                ],
            },
            {
                "address": POOL_STETH,
                "amplificationCoefficient": "100",
                "coins": [
                    {"symbol": "ETH",   "decimals": "18",
                     "poolBalance": "10000000000000000000000"},     # 10000 ETH
                    {"symbol": "stETH", "decimals": "18",
                     "poolBalance": "11000000000000000000000"},     # 11000 stETH
                ],
            },
        ]},
    })


def fake_http_ok(method, url, headers, body):
    return 200, _ok_body()


def fake_http_500(method, url, headers, body):
    return 500, '{"error":"boom"}'


class TestCurveClient(unittest.TestCase):

    def test_positive_dai_usdc(self):
        c = CurveClient(GOOD_HOST, http_call=fake_http_ok)
        b = c.get_orderbook("DAI/USDC")
        # spot = 1M USDC / 2M DAI = 0.5; mid ~= spot, tick surrounds
        # StableSwap A=2000: mid near 1.0 (not constant-product 0.5)
        self.assertGreater(b.mid(), 0.90)
        self.assertLess(b.mid(), 1.10)
        self.assertGreater(b.spread(), 0)
        self.assertTrue(b.is_valid())

    def test_positive_eth_steth(self):
        c = CurveClient(GOOD_HOST, http_call=fake_http_ok)
        b = c.get_orderbook("ETH/STETH")
        # spot = 11000 stETH / 10000 ETH = 1.1
        # StableSwap A=100, imbalance 10000/11000 -> mid in [0.95, 1.20]
        self.assertGreater(b.mid(), 0.95)
        self.assertLess(b.mid(), 1.20)
        self.assertTrue(b.is_valid())

    def test_amm_bid_below_ask(self):
        # AMM synthetic with micro-tick: bid < ask (s195-r0 + tick s201)
        c = CurveClient(GOOD_HOST, http_call=fake_http_ok)
        b = c.get_orderbook("DAI/USDC")
        self.assertLess(b.best_bid(), b.best_ask())

    def test_http_500_empty(self):
        c = CurveClient(GOOD_HOST, http_call=fake_http_500)
        b = c.get_orderbook("DAI/USDC")
        self.assertIsNone(b.best_bid())
        self.assertIsNone(b.best_ask())
        self.assertTrue(b.is_valid())

    def test_r4_whitelist_shape(self):
        self.assertGreaterEqual(len(ALLOWED_HOSTS), 1)
        self.assertIn("api.curve.finance", ALLOWED_HOSTS)

    def test_read_only_place_and_cancel(self):
        c = CurveClient(GOOD_HOST, http_call=fake_http_ok)
        req = OrderRequest(symbol="DAI/USDC", side="buy", price=0.5, size=1.0)
        r = c.place_order(req)
        self.assertFalse(r.accepted)
        self.assertEqual(r.reason, "read_only_phase1")
        self.assertFalse(c.cancel_order("XXX"))

    def test_unknown_symbol_returns_empty(self):
        c = CurveClient(GOOD_HOST, http_call=fake_http_ok)
        b = c.get_orderbook("DOGE")
        self.assertIsNone(b.best_bid())
        self.assertIsNone(b.best_ask())

    def test_url_passthrough(self):
        seen = {}
        def cap(method, url, headers, body):
            seen["url"] = url
            return 200, _ok_body()
        c = CurveClient(GOOD_HOST, http_call=cap)
        c.get_orderbook("DAI/USDC")
        self.assertEqual(seen["url"], GOOD_HOST)


if __name__ == "__main__":
    unittest.main()
