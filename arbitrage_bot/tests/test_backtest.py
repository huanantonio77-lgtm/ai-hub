"""Тесты бэктеста (backtest.py, ТЗ §19).

5 уровней verify (s151-r4):
  V1 POSITIVE   — 1 снапшот с реальным спредом → 1 сделка, PnL>0
  V2 INVARIANT  — 0 снапшотов → пустой результат, PnL=0
  V3 NEG-liq    — спред есть, но объём не влезает в ликвидность → 0 сделок
  V4 NEG-empty  — снапшот с пустыми стаканами → 0 сделок
  V5 EDGE-bound — 2 снапшота: 1-й проходит, 2-й нет → 1 сделка, equity=[x]
"""

import unittest

from arbitrage_bot.app.learning.backtest import (
    BookSnapshot,
    run_backtest,
)
from arbitrage_bot.app.market_data.orderbook import OrderBook
from arbitrage_bot.app.strategy.liquidity import LiquidityConfig
from arbitrage_bot.app.strategy.profitability import ProfitabilityConfig
from arbitrage_bot.app.strategy.scanner import ScannerConfig


SCAN_CFG = ScannerConfig(
    profitability=ProfitabilityConfig(
        min_profit_percent=0.25,
        safety_buffer_percent=0.10,
        max_slippage_percent=0.08,
    ),
    taker_fee_a_percent=0.10,
    taker_fee_b_percent=0.10,
    size=1.0,
)

LIQ_CFG = LiquidityConfig(
    max_orderbook_consumption_percent=50.0,
    max_slippage_percent=1.0,
    min_liquidity_usdt=10.0,
    min_depth_levels=1,
)


def _snap(ts, bid_a, ask_a, bid_b, ask_b, sz=10.0):
    a = OrderBook("BTC/USDT")
    a.apply_snapshot(bids=[(bid_a, sz)], asks=[(ask_a, sz)])
    b = OrderBook("BTC/USDT")
    b.apply_snapshot(bids=[(bid_b, sz)], asks=[(ask_b, sz)])
    return BookSnapshot(ts=ts, symbol="BTC/USDT", books={"A": a, "B": b})


class TestBacktest(unittest.TestCase):

    def test_v1_positive_one_trade(self):
        # A: bid=101 ask=102, B: bid=99 ask=99.5 → buy B sell A
        snaps = [_snap(1, 101.0, 102.0, 99.0, 99.5)]
        r = run_backtest(snaps, SCAN_CFG, LIQ_CFG)
        self.assertEqual(len(r.trades), 1)
        t = r.trades[0]
        self.assertEqual(t.buy_exchange, "B")
        self.assertEqual(t.sell_exchange, "A")
        self.assertAlmostEqual(t.buy_price, 99.5)
        self.assertAlmostEqual(t.sell_price, 101.0)
        self.assertGreater(r.total_pnl_abs, 0.0)
        self.assertEqual(len(r.equity_curve()), 1)

    def test_v2_invariant_empty_snapshots(self):
        r = run_backtest([], SCAN_CFG, LIQ_CFG)
        self.assertEqual(r.snapshots, 0)
        self.assertEqual(len(r.trades), 0)
        self.assertEqual(r.total_pnl_abs, 0.0)
        self.assertEqual(r.equity_curve(), [])

    def test_v3_neg_insufficient_liquidity(self):
        # спред есть, но просим объём больше стакана
        scan_cfg = ScannerConfig(
            profitability=SCAN_CFG.profitability,
            taker_fee_a_percent=0.10,
            taker_fee_b_percent=0.10,
            size=100.0,
        )
        snaps = [_snap(1, 101.0, 102.0, 99.0, 99.5, sz=0.5)]
        r = run_backtest(snaps, scan_cfg, LIQ_CFG)
        self.assertEqual(len(r.trades), 0)
        self.assertGreater(r.passing, 0)  # спред прошёл
        self.assertEqual(r.liquid, 0)     # а ликвидность — нет

    def test_v4_neg_empty_books(self):
        a = OrderBook("BTC/USDT")
        b = OrderBook("BTC/USDT")
        snaps = [BookSnapshot(ts=1, symbol="BTC/USDT", books={"A": a, "B": b})]
        r = run_backtest(snaps, SCAN_CFG, LIQ_CFG)
        self.assertEqual(len(r.trades), 0)
        self.assertEqual(r.passing, 0)

    def test_v5_edge_two_snapshots_one_passes(self):
        snaps = [
            _snap(1, 101.0, 102.0, 99.0, 99.5),         # проходит
            _snap(2, 100.05, 100.10, 100.0, 100.05),     # слишком узкий
        ]
        r = run_backtest(snaps, SCAN_CFG, LIQ_CFG)
        self.assertEqual(r.snapshots, 2)
        self.assertEqual(len(r.trades), 1)
        curve = r.equity_curve()
        self.assertEqual(len(curve), 1)
        self.assertAlmostEqual(curve[0], r.total_pnl_abs, places=9)


if __name__ == "__main__":
    unittest.main()
