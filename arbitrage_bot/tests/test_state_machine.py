"""Тесты state_machine.py — виртуальные арбитражные сделки.

5 уровней verify (s151-r4):
  V1 POSITIVE     — полная сделка buy 1.0 / sell 1.0, pnl по vwap
  V2 PARTIAL-FILL — buy 1.0 / sell 0.7 → unmatched_buy=0.3, needs_hedge=True
  V3 UNMATCHED    — sell 1.0 / buy 0.7 → unmatched_sell=0.3
  V4 ABORT        — abort из OPENING → ABORTED, abort_reason заполнен
  V5 NEG-invalid  — fill после CLOSED/ABORTED → RuntimeError; size<=0 → ValueError
"""

import unittest

from arbitrage_bot.app.execution.state_machine import VirtualTrade


class TestStateMachinePositive(unittest.TestCase):
    """V1 POSITIVE — полная сделка, pnl по vwap."""

    def test_full_trade(self):
        t = VirtualTrade("BTC/USDT", target_size=1.0)
        t.on_fill("buy", "A", 100.0, 0.4)
        t.on_fill("buy", "A", 100.1, 0.6)
        t.on_fill("sell", "B", 100.5, 0.7)
        t.on_fill("sell", "B", 100.6, 0.3)
        self.assertEqual(t.state, "OPEN")
        self.assertTrue(t.is_fully_matched())
        self.assertAlmostEqual(t.vwap("buy"), 100.06, places=6)
        self.assertAlmostEqual(t.vwap("sell"), 100.53, places=6)
        self.assertAlmostEqual(t.realized_pnl_abs(), 0.47, places=6)
        t.close()
        self.assertEqual(t.state, "CLOSED")


class TestStateMachinePartialFill(unittest.TestCase):
    """V2 PARTIAL-FILL — buy опережает sell → unmatched_buy > 0."""

    def test_partial_buy_ahead(self):
        t = VirtualTrade("BTC/USDT", target_size=1.0)
        t.on_fill("buy", "A", 100.0, 1.0)
        t.on_fill("sell", "B", 100.5, 0.7)
        self.assertEqual(t.state, "OPEN")
        self.assertAlmostEqual(t.buy_filled(), 1.0)
        self.assertAlmostEqual(t.sell_filled(), 0.7)
        self.assertAlmostEqual(t.matched_size(), 0.7)
        self.assertAlmostEqual(t.unmatched_buy(), 0.3)
        self.assertAlmostEqual(t.unmatched_sell(), 0.0)
        self.assertTrue(t.needs_hedge())


class TestStateMachineUnmatchedSell(unittest.TestCase):
    """V3 UNMATCHED — sell опережает buy → unmatched_sell > 0."""

    def test_sell_ahead(self):
        t = VirtualTrade("ETH/USDT", target_size=1.0)
        t.on_fill("sell", "B", 100.5, 1.0)
        t.on_fill("buy", "A", 100.0, 0.7)
        self.assertAlmostEqual(t.unmatched_sell(), 0.3)
        self.assertAlmostEqual(t.unmatched_buy(), 0.0)
        self.assertTrue(t.needs_hedge())


class TestStateMachineAbort(unittest.TestCase):
    """V4 ABORT — abort из OPENING переводит в ABORTED."""

    def test_abort(self):
        t = VirtualTrade("SOL/USDT", target_size=1.0)
        t.on_fill("buy", "A", 100.0, 0.5)
        self.assertEqual(t.state, "OPENING")
        t.abort("sell_leg_timeout")
        self.assertEqual(t.state, "ABORTED")
        self.assertEqual(t.abort_reason, "sell_leg_timeout")


class TestStateMachineNegInvalid(unittest.TestCase):
    """V5 NEG-invalid — fill после CLOSED/ABORTED; size<=0; price<=0."""

    def test_fill_after_close_raises(self):
        t = VirtualTrade("XRP/USDT", target_size=0.5)
        t.on_fill("buy", "A", 100.0, 0.5)
        t.on_fill("sell", "B", 100.5, 0.5)
        t.close()
        with self.assertRaises(RuntimeError):
            t.on_fill("buy", "A", 100.0, 0.1)

    def test_fill_after_abort_raises(self):
        t = VirtualTrade("XRP/USDT", target_size=0.5)
        t.abort("manual")
        with self.assertRaises(RuntimeError):
            t.on_fill("buy", "A", 100.0, 0.1)

    def test_bad_size_and_price(self):
        t = VirtualTrade("XRP/USDT", target_size=0.5)
        with self.assertRaises(ValueError):
            t.on_fill("buy", "A", 100.0, 0.0)
        with self.assertRaises(ValueError):
            t.on_fill("buy", "A", 0.0, 0.5)
        with self.assertRaises(ValueError):
            t.on_fill("hold", "A", 100.0, 0.5)


if __name__ == "__main__":
    unittest.main()
