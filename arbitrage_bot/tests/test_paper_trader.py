"""Тесты paper-портфеля (paper_trader.py, ТЗ §19).

5 уровней verify (s151-r4):
  V1 POSITIVE    — 1 снапшот с прибылью → капитал вырос, equity[1]>equity[0]
  V2 INVARIANT   — 0 снапшотов → equity=[initial], капитал неизменен
  V3 NEG-noopp   — узкий спред → 0 сделок, equity=[initial]
  V4 NEG-nocap   — капитал меньше требуемого → skipped_no_capital>0
  V5 EDGE-compnd — 2 прибыльных снапшота → капитал компаундится
"""

import unittest

from arbitrage_bot.app.execution.paper_trader import PaperPortfolio
from arbitrage_bot.app.learning.backtest import BookSnapshot
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


class TestPaperTrader(unittest.TestCase):

    def test_v1_positive_capital_grows(self):
        p = PaperPortfolio(10_000.0, SCAN_CFG, LIQ_CFG)
        p.run([_snap(1, 101.0, 102.0, 99.0, 99.5)])
        r = p.result
        self.assertEqual(len(r.trades), 1)
        self.assertGreater(r.final_capital, r.initial_capital)
        self.assertGreater(r.equity_curve[-1], r.initial_capital)
        self.assertGreater(r.total_pnl_abs, 0.0)

    def test_v2_invariant_empty_snapshots(self):
        p = PaperPortfolio(10_000.0, SCAN_CFG, LIQ_CFG)
        r = p.run([])
        self.assertEqual(r.final_capital, 10_000.0)
        self.assertEqual(r.equity_curve, [10_000.0])
        self.assertEqual(r.trades, [])
        self.assertEqual(r.max_drawdown(), 0.0)

    def test_v3_neg_narrow_spread_no_trades(self):
        p = PaperPortfolio(10_000.0, SCAN_CFG, LIQ_CFG)
        r = p.run([_snap(1, 100.05, 100.10, 100.0, 100.05)])
        self.assertEqual(len(r.trades), 0)
        self.assertEqual(r.final_capital, 10_000.0)
        self.assertEqual(r.equity_curve, [10_000.0, 10_000.0])

    def test_v4_neg_insufficient_capital(self):
        # требуется ~99.5 * 1 = 99.5 USDT — дадим 50
        p = PaperPortfolio(50.0, SCAN_CFG, LIQ_CFG)
        r = p.run([_snap(1, 101.0, 102.0, 99.0, 99.5)])
        self.assertEqual(len(r.trades), 0)
        self.assertGreater(r.skipped_no_capital, 0)
        self.assertEqual(r.final_capital, 50.0)

    def test_v5_edge_compounding(self):
        p = PaperPortfolio(10_000.0, SCAN_CFG, LIQ_CFG)
        snaps = [
            _snap(1, 101.0, 102.0, 99.0, 99.5),
            _snap(2, 102.0, 103.0, 100.0, 100.5),
        ]
        r = p.run(snaps)
        self.assertEqual(len(r.trades), 2)
        self.assertGreater(r.trades[1].capital_after, r.trades[0].capital_after)
        self.assertEqual(len(r.equity_curve), 3)  # [init, after1, after2]
        self.assertEqual(r.final_capital, r.trades[-1].capital_after)


if __name__ == "__main__":
    unittest.main()
