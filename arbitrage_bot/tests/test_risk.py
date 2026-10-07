"""Тесты риск-лимитов и EMERGENCY_STOP (ТЗ §11).

5 уровней verify (s151-r4):
  V1 POSITIVE    — RiskGuard разрешает валидную сделку
  V2 INVARIANT   — on_close обновляет daily_pnl и consecutive_losses
  V3 NEG-notion  — notional > max_trade_notional → deny
  V4 NEG-losses  — 5 убытков подряд → max_consecutive_losses → deny
  V5 EDGE-bound  — EmergencyStop: trigger/reset + drain_actions
"""

import unittest

from arbitrage_bot.app.risk.emergency_stop import (
    EmergencyStop,
    TRIGGER_REASONS,
)
from arbitrage_bot.app.risk.limits import RiskGuard, RiskLimits


class TestRiskLimits(unittest.TestCase):

    def test_v1_positive_valid_trade(self):
        g = RiskGuard(RiskLimits())
        d = g.check_new_trade(50.0)
        self.assertTrue(d.allow)
        self.assertEqual(d.reason, "")

    def test_v2_invariant_state_updates(self):
        g = RiskGuard(RiskLimits())
        g.on_open()
        self.assertEqual(g.state.open_operations, 1)
        g.on_close(pnl_usdt=-5.0)
        self.assertEqual(g.state.open_operations, 0)
        self.assertAlmostEqual(g.state.daily_pnl_usdt, -5.0)
        self.assertEqual(g.state.consecutive_losses, 1)
        # прибыль сбрасывает серию
        g.on_close(pnl_usdt=+2.0)
        self.assertEqual(g.state.consecutive_losses, 0)
        self.assertAlmostEqual(g.state.daily_pnl_usdt, -3.0)

    def test_v3_neg_notional_too_high(self):
        g = RiskGuard(RiskLimits(max_trade_notional_usdt=100.0))
        d = g.check_new_trade(101.0)
        self.assertFalse(d.allow)
        self.assertEqual(d.reason, "trade_notional_too_high")

    def test_v4_neg_consecutive_losses(self):
        g = RiskGuard(RiskLimits(max_consecutive_losses=5))
        for _ in range(5):
            g.on_open()
            g.on_close(pnl_usdt=-1.0)
        d = g.check_new_trade(50.0)
        self.assertFalse(d.allow)
        self.assertEqual(d.reason, "max_consecutive_losses")

    def test_v5_edge_emergency_stop(self):
        es = EmergencyStop()
        self.assertTrue(es.can_trade())
        es.trigger("daily_loss_exceeded")
        self.assertFalse(es.can_trade())
        self.assertEqual(es.reason, "daily_loss_exceeded")
        actions = es.drain_actions()
        self.assertIn("block_new_trades", actions)
        self.assertIn("cancel_open_orders", actions)
        self.assertIn("close_unhedged", actions)
        self.assertEqual(es.pending_actions, [])
        es.reset()
        self.assertTrue(es.can_trade())
        # невалидная причина
        with self.assertRaises(ValueError):
            es.trigger("nonsense")
        # все причины из TRIGGER_REASONS валидны
        for r in TRIGGER_REASONS:
            es2 = EmergencyStop()
            es2.trigger(r)
            self.assertTrue(es2.tripped)


if __name__ == "__main__":
    unittest.main()
