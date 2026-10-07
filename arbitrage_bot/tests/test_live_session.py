"""Тесты live_session.py (stage 8, s167).

5 уровней verify (s151-r4):
  V1 POSITIVE    - duration=3, interval=1 -> steps_done=3, PnL > 0
  V2 NON-QUIET   - нет спреда -> 0 сделок, final == initial
  V3 NEG-1       - <2 адаптеров -> ValueError (контракт Stage 7)
  V4 NEG-2 (R4)  - TestnetAdapter на evil.com -> ValueError
  V5 WRITE-PATH  - fake clock+sleep: start/end/steps согласованы
  V6 WRITE-PATH  - final_capital == capital; duration_sec_actual == duration
  V7 POSITIVE    - heartbeat вызван ровно floor(steps/heartbeat_every) раз
  V8 NEG-1       - clock стоит -> runaway останавливается по max_steps
"""

from __future__ import annotations

import unittest

from arbitrage_bot.app.exchanges.base import (
    ExchangeAdapter,
    OrderRequest,
    OrderResult,
)
from arbitrage_bot.app.exchanges.testnet_adapter import TestnetAdapter
from arbitrage_bot.app.execution.live_session import (
    LiveSession,
    LiveSessionConfig,
    LiveSessionResult,
)
from arbitrage_bot.app.market_data.orderbook import OrderBook
from arbitrage_bot.app.strategy.liquidity import LiquidityConfig
from arbitrage_bot.app.strategy.profitability import ProfitabilityConfig
from arbitrage_bot.app.strategy.scanner import ScannerConfig


def _make_book(symbol, bids, asks):
    book = OrderBook(symbol)
    book.apply_snapshot(bids, asks)
    return book


class FakeAdapter(ExchangeAdapter):
    """Минимальный адаптер: возвращает заранее заданный стакан."""

    def __init__(self, name, book):
        self.name = name
        self._book = book
        self.get_orderbook_calls = 0

    def get_orderbook(self, symbol):
        self.get_orderbook_calls += 1
        return self._book

    def place_order(self, req):
        return OrderResult(accepted=False, reason="fake: no real orders")

    def cancel_order(self, order_id):
        return False


class FakeClock:
    """Управляемые часы: int, растут только через advance()."""

    def __init__(self, start=1000):
        self._t = start

    def __call__(self):
        return self._t

    def advance(self, dt):
        self._t += int(dt)


def _fake_sleep(clock):
    def _sleep(sec):
        clock.advance(sec)
    return _sleep


def _profitable_books():
    a = _make_book("BTCUSDT", bids=[(99.5, 1000.0)], asks=[(100.0, 1000.0)])
    b = _make_book("BTCUSDT", bids=[(101.0, 1000.0)], asks=[(101.5, 1000.0)])
    return a, b


def _flat_books():
    a = _make_book("BTCUSDT", bids=[(99.5, 1000.0)], asks=[(100.0, 1000.0)])
    b = _make_book("BTCUSDT", bids=[(99.5, 1000.0)], asks=[(100.0, 1000.0)])
    return a, b


def _test_scan_cfg(size=100.0):
    return ScannerConfig(
        profitability=ProfitabilityConfig(
            min_profit_percent=0.10,
            safety_buffer_percent=0.05,
            max_slippage_percent=0.08,
        ),
        taker_fee_a_percent=0.10,
        taker_fee_b_percent=0.10,
        size=size,
    )


def _test_liq_cfg():
    return LiquidityConfig(
        max_orderbook_consumption_percent=15.0,
        max_slippage_percent=0.08,
        min_liquidity_usdt=100.0,
        min_depth_levels=1,
    )


class TestLiveSession(unittest.TestCase):

    def _profitable_adapters(self):
        a, b = _profitable_books()
        return {"A": FakeAdapter("A", a), "B": FakeAdapter("B", b)}

    def _flat_adapters(self):
        a, b = _flat_books()
        return {"A": FakeAdapter("A", a), "B": FakeAdapter("B", b)}

    def _cfg(self, duration=3.0, interval=1.0, max_steps=100,
             heartbeat_every=10):
        return LiveSessionConfig(
            symbol="BTCUSDT",
            initial_capital=100000.0,
            duration_sec=duration,
            interval_sec=interval,
            max_steps=max_steps,
            heartbeat_every=heartbeat_every,
            scan_cfg=_test_scan_cfg(),
            liq_cfg=_test_liq_cfg(),
        )

    # --- V1 POSITIVE ---
    def test_v1_positive_profitable_session(self):
        clock = FakeClock(1000)
        session = LiveSession(
            adapters=self._profitable_adapters(),
            config=self._cfg(duration=3.0, interval=1.0),
            clock=clock,
            sleep=_fake_sleep(clock),
        )
        r = session.run()
        self.assertEqual(r.steps_done, 3)
        self.assertGreater(r.inner.final_capital, r.inner.initial_capital)
        self.assertGreaterEqual(len(r.inner.trades), 1)
        self.assertEqual(r.duration_sec_actual, 3.0)

    # --- V2 NON-QUIET ---
    def test_v2_non_quiet_no_spread(self):
        clock = FakeClock(1000)
        session = LiveSession(
            adapters=self._flat_adapters(),
            config=self._cfg(duration=3.0, interval=1.0),
            clock=clock,
            sleep=_fake_sleep(clock),
        )
        r = session.run()
        self.assertEqual(r.steps_done, 3)
        self.assertEqual(r.inner.final_capital, r.inner.initial_capital)
        self.assertEqual(len(r.inner.trades), 0)

    # --- V3 NEG-1: 1 adapter ---
    def test_v3_neg_one_adapter_raises(self):
        a, _ = _profitable_books()
        with self.assertRaises(ValueError):
            LiveSession(
                adapters={"A": FakeAdapter("A", a)},
                config=self._cfg(),
                clock=FakeClock(1000),
                sleep=lambda s: None,
            )

    # --- V4 NEG-2 (R4): evil host in TestnetAdapter ---
    def test_v4_neg_r4_whitelist_violation(self):
        with self.assertRaises(ValueError):
            TestnetAdapter("https://evil.com", http_call=lambda *a, **k: (200, "{}"))

    # --- V5 WRITE-PATH (R3): clock+sleep согласованы ---
    def test_v5_write_path_clock_sleep_consistent(self):
        clock = FakeClock(5000)
        sleep_calls = []
        def _recording_sleep(sec):
            sleep_calls.append(sec)
            clock.advance(sec)
        session = LiveSession(
            adapters=self._profitable_adapters(),
            config=self._cfg(duration=3.0, interval=1.0),
            clock=clock,
            sleep=_recording_sleep,
        )
        r = session.run()
        self.assertEqual(r.start_ts, 5000)
        self.assertEqual(r.end_ts, 5003)
        self.assertEqual(r.duration_sec_actual, 3.0)
        # sleep ровно после каждого шага
        self.assertEqual(len(sleep_calls), r.steps_done)

    # --- V6 WRITE-PATH: final_capital == capital ---
    def test_v6_write_path_final_capital_matches_pnl(self):
        clock = FakeClock(0)
        session = LiveSession(
            adapters=self._profitable_adapters(),
            config=self._cfg(duration=3.0, interval=1.0),
            clock=clock,
            sleep=_fake_sleep(clock),
        )
        r = session.run()
        self.assertEqual(
            r.inner.final_capital,
            r.inner.initial_capital + r.inner.total_pnl_abs,
        )

    # --- V7 POSITIVE: heartbeat каждые 1 шаг ---
    def test_v7_positive_heartbeat(self):
        clock = FakeClock(0)
        heartbeats = []
        def _on_hb(step, trade):
            heartbeats.append(step)
        session = LiveSession(
            adapters=self._profitable_adapters(),
            config=self._cfg(duration=3.0, interval=1.0, heartbeat_every=1),
            clock=clock,
            sleep=_fake_sleep(clock),
            on_heartbeat=_on_hb,
        )
        r = session.run()
        self.assertEqual(r.steps_done, 3)
        self.assertEqual(heartbeats, [1, 2, 3])
        self.assertEqual(r.heartbeats, 3)

    # --- V8 NEG-1: clock не двигается -> cap на max_steps ---
    def test_v8_neg_clock_stuck_breaks_on_max_steps(self):
        clock = FakeClock(0)  # никогда не растёт
        session = LiveSession(
            adapters=self._profitable_adapters(),
            config=self._cfg(duration=100.0, interval=0.0, max_steps=5),
            clock=clock,
            sleep=lambda s: None,
        )
        r = session.run()
        self.assertEqual(r.steps_done, 5)
        self.assertEqual(r.duration_sec_actual, 0.0)


if __name__ == "__main__":
    unittest.main()
