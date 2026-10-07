"""Тесты расчёта чистой прибыли (profitability.py, ТЗ §6).

5 уровней verify (s151-r4):
  V1 POSITIVE   — известная возможность, точное значение net_abs
  V2 INVARIANT  — нулевые комиссии/слип/safety → net == gross_abs
  V3 NEG-low    — net_pct < min_profit → passes=False
  V4 NEG-inv    — sell_price <= buy_price → net<0, passes=False
  V5 EDGE-bound — net_pct == min_profit_percent → passes=True (граница)
"""

import unittest

from arbitrage_bot.app.strategy.profitability import (
    ProfitabilityConfig,
    evaluate,
    gross_percent,
)


CFG = ProfitabilityConfig(
    min_profit_percent=0.25,
    safety_buffer_percent=0.10,
    max_slippage_percent=0.08,
)


class TestProfitabilityPositive(unittest.TestCase):
    """V1 POSITIVE — известная возможность с точным net_abs."""

    def test_known_opportunity(self):
        # Из smoke A5-a-1: buy=100, sell=100.5, size=1, fees=0.10/0.10
        opp = evaluate(
            symbol="BTC/USDT",
            buy_exchange="A",
            sell_exchange="B",
            buy_price=100.0,
            sell_price=100.5,
            size=1.0,
            taker_fee_buy_percent=0.10,
            taker_fee_sell_percent=0.10,
            cfg=CFG,
        )
        self.assertAlmostEqual(opp.gross_percent, 0.5000, places=4)
        self.assertAlmostEqual(opp.net_abs, 0.0391, places=4)
        self.assertAlmostEqual(opp.net_percent, 0.0391, places=4)
        self.assertFalse(opp.passes)


class TestProfitabilityInvariant(unittest.TestCase):
    """V2 INVARIANT — при нулевых издержках net == gross_abs."""

    def test_zero_costs(self):
        cfg0 = ProfitabilityConfig(
            min_profit_percent=0.0,
            safety_buffer_percent=0.0,
            max_slippage_percent=0.0,
        )
        opp = evaluate(
            symbol="ETH/USDT",
            buy_exchange="A",
            sell_exchange="B",
            buy_price=100.0,
            sell_price=102.0,
            size=2.0,
            taker_fee_buy_percent=0.0,
            taker_fee_sell_percent=0.0,
            cfg=cfg0,
        )
        # V_buy=200, V_sell=204, издержки=0 → net_abs=4, net_pct=2.0%
        self.assertAlmostEqual(opp.net_abs, 4.0, places=6)
        self.assertAlmostEqual(opp.net_percent, 2.0, places=6)
        self.assertAlmostEqual(opp.gross_percent, 2.0, places=6)
        self.assertTrue(opp.passes)


class TestProfitabilityNegLow(unittest.TestCase):
    """V3 NEG-low — чистая прибыль ниже порога → passes=False."""

    def test_below_min(self):
        opp = evaluate(
            symbol="SOL/USDT",
            buy_exchange="A",
            sell_exchange="B",
            buy_price=100.0,
            sell_price=100.2,  # gross=0.2% < min_profit+safety+costs
            size=1.0,
            taker_fee_buy_percent=0.10,
            taker_fee_sell_percent=0.10,
            cfg=CFG,
        )
        self.assertLess(opp.net_percent, CFG.min_profit_percent)
        self.assertFalse(opp.passes)


class TestProfitabilityNegInverted(unittest.TestCase):
    """V4 NEG-inv — sell <= buy → net<0, passes=False."""

    def test_inverted(self):
        opp = evaluate(
            symbol="XRP/USDT",
            buy_exchange="A",
            sell_exchange="B",
            buy_price=100.0,
            sell_price=99.5,  # продаём дешевле, чем купили
            size=1.0,
            taker_fee_buy_percent=0.10,
            taker_fee_sell_percent=0.10,
            cfg=CFG,
        )
        self.assertLess(opp.net_abs, 0)
        self.assertFalse(opp.passes)


class TestProfitabilityEdgeBoundary(unittest.TestCase):
    """V5 EDGE — граница: net_pct ровно == min_profit_percent.

    Подбираем sell_price так, чтобы net_pct с точностью ~1e-9 совпал
    с min_profit_percent (0.25). Условие passes — нестрогое (>=).
    """

    def test_boundary(self):
        cfg = ProfitabilityConfig(
            min_profit_percent=0.25,
            safety_buffer_percent=0.0,
            max_slippage_percent=0.0,
        )
        # С нулевыми издержками: net_pct == gross_pct == 0.25
        # → sell_price = buy_price * 1.0025
        buy = 100.0
        sell = buy * 1.0025  # 100.25
        opp = evaluate(
            symbol="BTC/USDT",
            buy_exchange="A",
            sell_exchange="B",
            buy_price=buy,
            sell_price=sell,
            size=1.0,
            taker_fee_buy_percent=0.0,
            taker_fee_sell_percent=0.0,
            cfg=cfg,
        )
        self.assertAlmostEqual(opp.net_percent, 0.25, places=6)
        self.assertTrue(opp.passes)


if __name__ == "__main__":
    unittest.main()
