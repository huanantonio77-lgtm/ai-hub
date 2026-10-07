"""Тесты dataclass-ов покрытия TEST-GAP (s203).

Закрывают 6 findings из family_audit:
  FeesConfig, ArbitrageOpportunity (strategy/profitability.py)
  BacktestTrade (learning/backtest.py)
  LiquidityCheck (strategy/liquidity.py)
  PaperResult (execution/paper_trader.py)
  RiskState (risk/limits.py)

Стиль: unittest.TestCase, зеркало test_curve_client.py.
Часть 1: FeesConfig + ArbitrageOpportunity.
"""
import unittest

from arbitrage_bot.app.strategy.profitability import (
    ArbitrageOpportunity,
    FeesConfig,
)


class TestFeesConfig(unittest.TestCase):
    """FeesConfig: 4 float-поля (taker_a, maker_a, taker_b, maker_b)."""

    def test_v1_constructor_stores_values(self):
        f = FeesConfig(taker_a=0.10, maker_a=0.05, taker_b=0.10, maker_b=0.05)
        self.assertEqual(f.taker_a, 0.10)
        self.assertEqual(f.maker_a, 0.05)
        self.assertEqual(f.taker_b, 0.10)
        self.assertEqual(f.maker_b, 0.05)

    def test_v2_zero_fees_allowed(self):
        f = FeesConfig(taker_a=0.0, maker_a=0.0, taker_b=0.0, maker_b=0.0)
        self.assertEqual(f.taker_a, 0.0)
        self.assertEqual(f.maker_b, 0.0)


class TestArbitrageOpportunity(unittest.TestCase):
    """ArbitrageOpportunity: 10 полей, включая passes: bool."""

    def _make(self, passes=True, net_percent=0.5):
        return ArbitrageOpportunity(
            symbol="BTC/USDT",
            buy_exchange="binance",
            sell_exchange="kraken",
            buy_price=50000.0,
            sell_price=50300.0,
            size=0.1,
            gross_percent=0.6,
            net_percent=net_percent,
            net_abs=25.0,
            passes=passes,
        )

    def test_v1_positive_passes_true(self):
        opp = self._make(passes=True)
        self.assertTrue(opp.passes)
        self.assertEqual(opp.symbol, "BTC/USDT")
        self.assertGreater(opp.net_percent, 0)

    def test_v2_negative_passes_false(self):
        opp = self._make(passes=False, net_percent=-0.1)
        self.assertFalse(opp.passes)
        self.assertLess(opp.net_percent, 0)

    def test_v3_equality_by_value(self):
        a = self._make()
        b = self._make()
        self.assertEqual(a, b)


# --- Chunk B (s203): BacktestTrade + LiquidityCheck ---
from arbitrage_bot.app.learning.backtest import BacktestTrade
from arbitrage_bot.app.strategy.liquidity import LiquidityCheck


class TestBacktestTrade(unittest.TestCase):
    """BacktestTrade: 8 полей (ts, exchanges, prices, size, net, pnl)."""

    def test_v1_positive_basic(self):
        t = BacktestTrade(
            ts=1700000000,
            buy_exchange="binance", sell_exchange="kraken",
            buy_price=50000.0, sell_price=50300.0,
            size=0.1, net_percent=0.5, realized_pnl_abs=25.0,
        )
        self.assertEqual(t.buy_exchange, "binance")
        self.assertGreater(t.realized_pnl_abs, 0)
        self.assertGreater(t.net_percent, 0)

    def test_v2_negative_loss(self):
        t = BacktestTrade(
            ts=0, buy_exchange="a", sell_exchange="b",
            buy_price=1.0, sell_price=0.9, size=1.0,
            net_percent=-5.0, realized_pnl_abs=-0.5,
        )
        self.assertLess(t.realized_pnl_abs, 0)
        self.assertLess(t.net_percent, 0)


class TestLiquidityCheck(unittest.TestCase):
    """LiquidityCheck: 10 полей (side, sizes, prices, slippage, ok, reason)."""

    def test_v1_positive_ok(self):
        c = LiquidityCheck(
            side="buy", requested_size=1.0, filled_size=1.0,
            avg_price=100.5, best_price=100.0,
            slippage_percent=0.5, consumption_percent=10.0,
            liquidity_usdt=1000.0, ok=True, reason="",
        )
        self.assertTrue(c.ok)
        self.assertEqual(c.filled_size, c.requested_size)
        self.assertEqual(c.reason, "")

    def test_v2_negative_insufficient(self):
        c = LiquidityCheck(
            side="buy", requested_size=100.0, filled_size=10.0,
            avg_price=0.0, best_price=0.0,
            slippage_percent=0.0, consumption_percent=0.0,
            liquidity_usdt=100.0, ok=False, reason="insufficient",
        )
        self.assertFalse(c.ok)
        self.assertLess(c.filled_size, c.requested_size)
        self.assertEqual(c.reason, "insufficient")

    def test_v3_edge_exact_fill(self):
        c = LiquidityCheck(
            side="sell", requested_size=5.0, filled_size=5.0,
            avg_price=99.9, best_price=100.0,
            slippage_percent=0.1, consumption_percent=50.0,
            liquidity_usdt=500.0, ok=True, reason="",
        )
        self.assertTrue(c.ok)
        self.assertEqual(c.side, "sell")


# --- Chunk C (s203): PaperResult ---
from arbitrage_bot.app.execution.paper_trader import PaperResult


class TestPaperResult(unittest.TestCase):
    """PaperResult: 7 полей + метод max_drawdown().

    Проверяем:
    - defaults необязательных полей (default_factory для list)
    - max_drawdown() инвариант: monotonic up -> 0, decline -> >0
    """

    def test_v1_defaults(self):
        r = PaperResult(initial_capital=1000.0)
        self.assertEqual(r.initial_capital, 1000.0)
        self.assertEqual(r.final_capital, 0.0)
        self.assertEqual(r.total_pnl_abs, 0.0)
        self.assertEqual(r.skipped_no_capital, 0)
        self.assertEqual(r.skipped_no_liq, 0)
        self.assertEqual(r.trades, [])
        self.assertEqual(r.equity_curve, [])

    def test_v2_max_drawdown_empty_curve(self):
        r = PaperResult(initial_capital=1000.0)
        self.assertEqual(r.max_drawdown(), 0.0)

    def test_v3_max_drawdown_monotonic_up(self):
        r = PaperResult(initial_capital=1000.0)
        r.equity_curve = [1000.0, 1050.0, 1100.0, 1200.0]
        self.assertEqual(r.max_drawdown(), 0.0)

    def test_v4_max_drawdown_positive_on_decline(self):
        r = PaperResult(initial_capital=1000.0)
        r.equity_curve = [1000.0, 1200.0, 900.0, 1100.0]
        dd = r.max_drawdown()
        self.assertGreater(dd, 0)

    def test_v5_max_drawdown_flat_curve(self):
        r = PaperResult(initial_capital=1000.0)
        r.equity_curve = [1000.0, 1000.0, 1000.0]
        self.assertEqual(r.max_drawdown(), 0.0)


# --- Chunk D (s203): BacktestResult, Fill, PaperTrade, RiskDecision, RiskState ---
from arbitrage_bot.app.execution.paper_trader import PaperTrade
from arbitrage_bot.app.execution.state_machine import Fill
from arbitrage_bot.app.learning.backtest import BacktestResult
from arbitrage_bot.app.risk.limits import RiskDecision, RiskState


class TestBacktestResult(unittest.TestCase):
    """BacktestResult: 6 полей + метод equity_curve()."""

    def test_v1_defaults_and_factory(self):
        r = BacktestResult(snapshots=3, scanned=10, passing=2, liquid=1)
        self.assertEqual(r.snapshots, 3)
        self.assertEqual(r.scanned, 10)
        self.assertEqual(r.passing, 2)
        self.assertEqual(r.liquid, 1)
        self.assertEqual(r.trades, [])
        self.assertEqual(r.total_pnl_abs, 0.0)

    def test_v2_equity_curve_empty(self):
        r = BacktestResult(snapshots=0, scanned=0, passing=0, liquid=0)
        self.assertEqual(r.equity_curve(), [])


class TestFill(unittest.TestCase):
    """Fill: 5 полей, ts default 0."""

    def test_v1_positive(self):
        f = Fill(side="buy", exchange="binance", price=50000.0, size=0.1)
        self.assertEqual(f.side, "buy")
        self.assertEqual(f.exchange, "binance")
        self.assertEqual(f.ts, 0)

    def test_v2_explicit_ts(self):
        f = Fill(side="sell", exchange="kraken", price=50001.0, size=0.2, ts=1700000000)
        self.assertEqual(f.ts, 1700000000)


class TestPaperTrade(unittest.TestCase):
    """PaperTrade: 9 полей без дефолтов."""

    def test_v1_positive(self):
        t = PaperTrade(
            ts=1700000000,
            buy_exchange="binance", sell_exchange="kraken",
            buy_price=50000.0, sell_price=50300.0,
            size=0.1, net_percent=0.5,
            realized_pnl_abs=25.0, capital_after=1025.0,
        )
        self.assertEqual(t.capital_after, 1025.0)
        self.assertGreater(t.realized_pnl_abs, 0)

    def test_v2_negative_loss(self):
        t = PaperTrade(
            ts=0, buy_exchange="a", sell_exchange="b",
            buy_price=1.0, sell_price=0.9, size=1.0,
            net_percent=-5.0, realized_pnl_abs=-0.5, capital_after=999.5,
        )
        self.assertLess(t.realized_pnl_abs, 0)


class TestRiskDecision(unittest.TestCase):
    """RiskDecision: allow(bool), reason(str) default ''."""

    def test_v1_positive_allow(self):
        d = RiskDecision(allow=True)
        self.assertTrue(d.allow)
        self.assertEqual(d.reason, "")

    def test_v2_negative_deny_with_reason(self):
        d = RiskDecision(allow=False, reason="daily_loss_limit")
        self.assertFalse(d.allow)
        self.assertEqual(d.reason, "daily_loss_limit")


class TestRiskState(unittest.TestCase):
    """RiskState: 3 поля со всеми default=0."""

    def test_v1_defaults_zero(self):
        s = RiskState()
        self.assertEqual(s.daily_pnl_usdt, 0.0)
        self.assertEqual(s.consecutive_losses, 0)
        self.assertEqual(s.open_operations, 0)

    def test_v2_custom_values(self):
        s = RiskState(daily_pnl_usdt=-50.0, consecutive_losses=3, open_operations=2)
        self.assertEqual(s.daily_pnl_usdt, -50.0)
        self.assertEqual(s.consecutive_losses, 3)
        self.assertEqual(s.open_operations, 2)
