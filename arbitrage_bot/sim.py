"""End-to-end демонстрация stage 1 arbitrage_bot (без биржевого I/O).

CLI:
    python3 -m arbitrage_bot.sim --demo              # печатает summary+csv+json
    python3 -m arbitrage_bot.sim --demo --out DIR    # пишет DIR/trades.csv + DIR/trades.json
    python3 -m arbitrage_bot.sim                     # без --demo: hint, код 2

Сценарий: два виртуальных стакана (exchange A — покупаем, exchange B — продаём),
profitability.evaluate находит возможность, VirtualTrade проигрывает сделку,
report выгружает CSV/JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from arbitrage_bot.app.execution.state_machine import VirtualTrade
from arbitrage_bot.app.market_data.orderbook import OrderBook
from arbitrage_bot.app.monitoring.report import summary, to_csv, to_json
from arbitrage_bot.app.strategy.profitability import ProfitabilityConfig, evaluate


DEFAULT_CFG = ProfitabilityConfig(
    min_profit_percent=0.25,
    safety_buffer_percent=0.10,
    max_slippage_percent=0.08,
)


def run_demo() -> list[VirtualTrade]:
    """Строит 2 стакана, находит возможность, проигрывает 1 сделку."""
    book_buy = OrderBook("BTC/USDT")
    book_sell = OrderBook("BTC/USDT")
    book_buy.apply_snapshot(bids=[(99.95, 1.0)], asks=[(100.0, 1.0)])
    book_sell.apply_snapshot(bids=[(101.0, 1.0)], asks=[(101.05, 1.0)])

    opp = evaluate(
        symbol="BTC/USDT",
        buy_exchange="A",
        sell_exchange="B",
        buy_price=book_buy.best_ask(),    # покупаем по лучшей продаже на A
        sell_price=book_sell.best_bid(),  # продаём по лучшей покупке на B
        size=1.0,
        taker_fee_buy_percent=0.10,
        taker_fee_sell_percent=0.10,
        cfg=DEFAULT_CFG,
    )

    t = VirtualTrade("BTC/USDT", target_size=1.0)
    t.on_fill("buy", "A", opp.buy_price, 1.0, ts=1)
    t.on_fill("sell", "B", opp.sell_price, 1.0, ts=2)
    t.close()
    return [t]


def run_scan_demo(initial_capital: float = 100000.0) -> int:
    """E2E прод-док: scanner -> liquidity (s157).

    Локальные импорты — чтобы не трогать топ модуля (s157-r4).
    Строит 2 стакана с реальным спредом, зовёт scan_exchanges,
    затем check_liquidity. Печатает одну строку.
    """
    from arbitrage_bot.app.market_data.orderbook import OrderBook
    from arbitrage_bot.app.strategy.profitability import ProfitabilityConfig
    from arbitrage_bot.app.strategy.scanner import ScannerConfig, scan_exchanges
    from arbitrage_bot.app.strategy.liquidity import LiquidityConfig, check_liquidity

    book_a = OrderBook("BTC/USDT")
    book_a.apply_snapshot(bids=[(101.0, 10.0)], asks=[(102.0, 10.0)])
    book_b = OrderBook("BTC/USDT")
    book_b.apply_snapshot(bids=[(99.0, 10.0)], asks=[(99.5, 10.0)])

    scan_cfg = ScannerConfig(
        profitability=ProfitabilityConfig(
            min_profit_percent=0.25,
            safety_buffer_percent=0.10,
            max_slippage_percent=0.08,
        ),
        taker_fee_a_percent=0.1,
        taker_fee_b_percent=0.1,
        size=1.0,
    )
    liq_cfg = LiquidityConfig(
        max_orderbook_consumption_percent=15.0,
        max_slippage_percent=0.08,
        min_liquidity_usdt=10.0,
        min_depth_levels=1,
    )

    opps = scan_exchanges(
        "BTC/USDT",
        {"A": book_a, "B": book_b},
        scan_cfg,
        only_passing=True,
    )
    if not opps:
        print("scan-demo: no opportunities")
        return 0

    for opp in opps:
        book_buy = book_b if opp.buy_exchange == "B" else book_a
        book_sell = book_a if opp.sell_exchange == "A" else book_b
        liq_buy = check_liquidity(book_buy, "buy", opp.size, liq_cfg)
        liq_sell = check_liquidity(book_sell, "sell", opp.size, liq_cfg)
        print(
            f"opp buy={opp.buy_exchange} sell={opp.sell_exchange} "
            f"net={opp.net_percent:.4f}% "
            f"liq_buy={'ok' if liq_buy.ok else liq_buy.reason} "
            f"liq_sell={'ok' if liq_sell.ok else liq_sell.reason}"
        )
    return 0


def run_backtest_demo() -> int:
    """E2E прод-док stage 3: backtest + paper_trader (s158).

    Локальные импорты — чтобы не трогать топ модуля (s157-r4).
    Строит 2 снапшота с реальным спредом, прогоняет paper-портфель
    с начальным капиталом 10000 USDT. Печатает equity + drawdown.
    """
    from arbitrage_bot.app.execution.paper_trader import PaperPortfolio
    from arbitrage_bot.app.learning.backtest import BookSnapshot, run_backtest
    from arbitrage_bot.app.market_data.orderbook import OrderBook
    from arbitrage_bot.app.strategy.liquidity import LiquidityConfig
    from arbitrage_bot.app.strategy.profitability import ProfitabilityConfig
    from arbitrage_bot.app.strategy.scanner import ScannerConfig

    def make_snap(ts, bid_a, ask_a, bid_b, ask_b, sz=10.0):
        a = OrderBook("BTC/USDT")
        a.apply_snapshot(bids=[(bid_a, sz)], asks=[(ask_a, sz)])
        b = OrderBook("BTC/USDT")
        b.apply_snapshot(bids=[(bid_b, sz)], asks=[(ask_b, sz)])
        return BookSnapshot(ts=ts, symbol="BTC/USDT", books={"A": a, "B": b})

    scan_cfg = ScannerConfig(
        profitability=ProfitabilityConfig(
            min_profit_percent=0.25,
            safety_buffer_percent=0.10,
            max_slippage_percent=0.08,
        ),
        taker_fee_a_percent=0.10,
        taker_fee_b_percent=0.10,
        size=1.0,
    )
    liq_cfg = LiquidityConfig(
        max_orderbook_consumption_percent=50.0,
        max_slippage_percent=1.0,
        min_liquidity_usdt=10.0,
        min_depth_levels=1,
    )

    snaps = [
        make_snap(1, 101.0, 102.0, 99.0, 99.5),
        make_snap(2, 102.0, 103.0, 100.0, 100.5),
    ]

    bt = run_backtest(snaps, scan_cfg, liq_cfg)
    print(
        f"backtest: snapshots={bt.snapshots} passing={bt.passing} "
        f"liquid={bt.liquid} trades={len(bt.trades)} "
        f"pnl={bt.total_pnl_abs:.4f}"
    )

    p = PaperPortfolio(10_000.0, scan_cfg, liq_cfg)
    pr = p.run(snaps)
    print(
        f"paper: initial={pr.initial_capital:.2f} "
        f"final={pr.final_capital:.4f} "
        f"trades={len(pr.trades)} max_dd={pr.max_drawdown():.4f}"
    )
    return 0


def run_stage4_demo() -> int:
    """E2E prod-doc stage 4: adapter + risk + emergency_stop (s159).

    Локальные импорты - чтобы не трогать топ модуля (s157-r4).
    """
    from arbitrage_bot.app.exchanges.base import NoopExchange, OrderRequest
    from arbitrage_bot.app.risk.emergency_stop import EmergencyStop
    from arbitrage_bot.app.risk.limits import RiskGuard, RiskLimits

    adapter = NoopExchange()
    guard = RiskGuard(RiskLimits(max_trade_notional_usdt=100.0))
    estop = EmergencyStop()

    print(f"adapter.name={adapter.name} can_trade={estop.can_trade()}")

    req = OrderRequest(symbol="BTC/USDT", side="buy", price=99.5, size=1.0)
    res = adapter.place_order(req)
    print(f"place_order: accepted={res.accepted} reason={res.reason}")

    d1 = guard.check_new_trade(99.5)
    d2 = guard.check_new_trade(101.0)
    print(f"risk: 99.5->allow={d1.allow} ; 101.0->allow={d2.allow} "
          f"reason={d2.reason}")

    estop.trigger("daily_loss_exceeded")
    print(f"estop: tripped={estop.tripped} reason={estop.reason} "
          f"can_trade={estop.can_trade()} "
          f"actions={estop.drain_actions()}")
    return 0


def run_stage5_demo() -> int:
    """E2E prod-doc stage 5: ExchangeA + ExchangeB + RiskGuard (s160).

    Локальные импорты - чтобы не трогать топ модуля (s157-r4).
    """
    from arbitrage_bot.app.exchanges import ExchangeA, ExchangeB
    from arbitrage_bot.app.exchanges.base import OrderRequest
    from arbitrage_bot.app.risk.limits import RiskGuard, RiskLimits

    a = ExchangeA()
    b = ExchangeB()
    guard = RiskGuard(RiskLimits(max_trade_notional_usdt=100.0))

    print(f"adapters: a={a.name} b={b.name}")

    book_a = a.get_orderbook("BTC/USDT")
    book_b = b.get_orderbook("BTC/USDT")
    book_a.apply_snapshot(bids=[(101.0, 10.0)], asks=[(102.0, 10.0)])
    book_b.apply_snapshot(bids=[(99.0, 10.0)], asks=[(99.5, 10.0)])

    buy_p = book_b.best_ask()
    sell_p = book_a.best_bid()
    print(f"books: buy_p={buy_p} sell_p={sell_p} spread={sell_p - buy_p:.4f}")

    notional = buy_p * 1.0
    d = guard.check_new_trade(notional)
    print(f"risk: notional={notional} allow={d.allow} reason={d.reason}")

    req_b = OrderRequest(symbol="BTC/USDT", side="buy", price=buy_p, size=1.0)
    req_a = OrderRequest(symbol="BTC/USDT", side="sell", price=sell_p, size=1.0)
    res_b = b.place_order(req_b)
    res_a = a.place_order(req_a)
    print(f"place B: accepted={res_b.accepted} reason={res_b.reason}")
    print(f"place A: accepted={res_a.accepted} reason={res_a.reason}")
    return 0


def run_stage6_demo() -> int:
    """E2E prod-doc stage 6: TestnetAdapter + mock http_call (s163).

    Локальные импорты (s157-r4). HTTP-вызов инжектируется (R3):
    без сети, детерминированный результат.
    """
    import json as _json

    from arbitrage_bot.app.exchanges.base import OrderRequest
    from arbitrage_bot.app.exchanges.testnet_adapter import TestnetAdapter
    from arbitrage_bot.app.risk.limits import RiskGuard, RiskLimits

    def mock_http(method, url, headers, body):
        if "/depth" in url:
            return 200, _json.dumps({
                "bids": [["100.0", "1.5"], ["99.5", "2.0"]],
                "asks": [["100.5", "1.0"], ["101.0", "3.0"]],
            })
        if "/order" in url and method == "POST":
            return 200, _json.dumps({
                "orderId": "TX-42",
                "executedQty": "1.5",
                "price": "100.0",
            })
        if "/order" in url and method == "DELETE":
            return 200, "{}"
        return 404, "{}"

    adapter = TestnetAdapter(
        "https://testnet.binance.vision", http_call=mock_http
    )
    guard = RiskGuard(RiskLimits(max_trade_notional_usdt=100.0))

    book = adapter.get_orderbook("BTCUSDT")
    print(f"adapter.name={adapter.name} symbol={book.symbol} valid={book.is_valid()}")
    print(f"book: best_bid={book.best_bid()} best_ask={book.best_ask()} "
          f"spread={book.spread()}")

    req = OrderRequest(symbol="BTCUSDT", side="buy", price=100.0, size=1.5)
    notional = req.price * req.size
    d = guard.check_new_trade(notional)
    print(f"risk: notional={notional:.2f} allow={d.allow} reason={d.reason}")

    res = adapter.place_order(req)
    print(f"place_order: accepted={res.accepted} order_id={res.order_id} "
          f"filled={res.filled_size}")

    cancel_ok = adapter.cancel_order(res.order_id)
    print(f"cancel_order: ok={cancel_ok}")
    return 0


def run_stage7_demo(initial_capital: float = 100000.0) -> int:
    """E2E stage 7: LivePaperTrader на testnet-данных (s165).

    Локальные импорты (s157-r4). HTTP-вызов инжектируется (R3):
    без сети, детерминированный результат.
    """
    import json as _json

    from arbitrage_bot.app.exchanges.testnet_adapter import TestnetAdapter
    from arbitrage_bot.app.execution.live_paper import (
        LivePaperConfig,
        LivePaperTrader,
    )
    from arbitrage_bot.app.strategy.liquidity import LiquidityConfig
    from arbitrage_bot.app.strategy.profitability import ProfitabilityConfig
    from arbitrage_bot.app.strategy.scanner import ScannerConfig

    def mock_http_a(method, url, headers, body):
        if "/depth" in url:
            return 200, _json.dumps({
                "bids": [["99.5", "5000.0"], ["99.0", "5000.0"]],
                "asks": [["100.0", "5000.0"], ["100.5", "5000.0"]],
            })
        return 404, "{}"

    def mock_http_b(method, url, headers, body):
        if "/depth" in url:
            return 200, _json.dumps({
                "bids": [["101.0", "5000.0"], ["100.5", "5000.0"]],
                "asks": [["101.5", "5000.0"], ["102.0", "5000.0"]],
            })
        return 404, "{}"

    adapters = {
        "A": TestnetAdapter(
            "https://testnet.binance.vision", http_call=mock_http_a
        ),
        "B": TestnetAdapter(
            "https://testnet.binance.vision", http_call=mock_http_b
        ),
    }
    scan_cfg = ScannerConfig(
        profitability=ProfitabilityConfig(
            min_profit_percent=0.10,
            safety_buffer_percent=0.05,
            max_slippage_percent=0.08,
        ),
        taker_fee_a_percent=0.10,
        taker_fee_b_percent=0.10,
        size=100.0,
    )
    liq_cfg = LiquidityConfig(
        max_orderbook_consumption_percent=15.0,
        max_slippage_percent=0.08,
        min_liquidity_usdt=100.0,
        min_depth_levels=1,
    )
    cfg = LivePaperConfig(
        symbol="BTCUSDT",
        initial_capital=initial_capital,
        steps=3,
        scan_cfg=scan_cfg,
        liq_cfg=liq_cfg,
    )
    trader = LivePaperTrader(adapters, cfg)
    result = trader.run()
    print(f"adapters=A,B symbol={cfg.symbol} steps={cfg.steps}")
    print(f"result: initial={result.initial_capital:.2f} "
          f"final={result.final_capital:.2f} trades={len(result.trades)} "
          f"pnl={result.total_pnl_abs:.2f}")
    print(f"skipped: no_cap={result.skipped_no_capital} "
          f"no_liq={result.skipped_no_liq}")
    print(f"max_drawdown={result.max_drawdown():.2f}")
    print(f"equity_curve={result.equity_curve}")
    return 0


def run_stage8_demo(initial_capital: float = 100000.0) -> int:
    """E2E stage 8: LiveSession (live-сессия paper на testnet-данных, s167).

    Локальные импорты (s157-r4). HTTP + clock + sleep инжектируются (R3):
    без сети, детерминированный результат.
    """
    import json as _json

    from arbitrage_bot.app.exchanges.testnet_adapter import TestnetAdapter
    from arbitrage_bot.app.execution.live_session import (
        LiveSession,
        LiveSessionConfig,
    )
    from arbitrage_bot.app.strategy.liquidity import LiquidityConfig
    from arbitrage_bot.app.strategy.profitability import ProfitabilityConfig
    from arbitrage_bot.app.strategy.scanner import ScannerConfig

    def mock_http_a(method, url, headers, body):
        if "/depth" in url:
            return 200, _json.dumps({
                "bids": [["99.5", "5000.0"], ["99.0", "5000.0"]],
                "asks": [["100.0", "5000.0"], ["100.5", "5000.0"]],
            })
        return 404, "{}"

    def mock_http_b(method, url, headers, body):
        if "/depth" in url:
            return 200, _json.dumps({
                "bids": [["101.0", "5000.0"], ["100.5", "5000.0"]],
                "asks": [["101.5", "5000.0"], ["102.0", "5000.0"]],
            })
        return 404, "{}"

    adapters = {
        "A": TestnetAdapter(
            "https://testnet.binance.vision", http_call=mock_http_a
        ),
        "B": TestnetAdapter(
            "https://testnet.binance.vision", http_call=mock_http_b
        ),
    }

    class _FakeClock:
        def __init__(self, start=1000):
            self.t = start

        def __call__(self):
            return self.t

        def advance(self, dt):
            self.t += int(dt)

    clock = _FakeClock(1000)

    def _fake_sleep(sec):
        clock.advance(sec)

    scan_cfg = ScannerConfig(
        profitability=ProfitabilityConfig(
            min_profit_percent=0.10,
            safety_buffer_percent=0.05,
            max_slippage_percent=0.08,
        ),
        taker_fee_a_percent=0.10,
        taker_fee_b_percent=0.10,
        size=100.0,
    )
    liq_cfg = LiquidityConfig(
        max_orderbook_consumption_percent=15.0,
        max_slippage_percent=0.08,
        min_liquidity_usdt=100.0,
        min_depth_levels=1,
    )
    cfg = LiveSessionConfig(
        symbol="BTCUSDT",
        initial_capital=initial_capital,
        duration_sec=5.0,
        interval_sec=1.0,
        max_steps=100,
        heartbeat_every=1,
        scan_cfg=scan_cfg,
        liq_cfg=liq_cfg,
    )
    session = LiveSession(
        adapters=adapters,
        config=cfg,
        clock=clock,
        sleep=_fake_sleep,
    )
    r = session.run()
    print(f"adapters=A,B symbol={cfg.symbol} "
          f"duration={cfg.duration_sec}s interval={cfg.interval_sec}s")
    print(f"session: steps={r.steps_done} start_ts={r.start_ts} "
          f"end_ts={r.end_ts} duration_actual={r.duration_sec_actual:.1f}s "
          f"heartbeats={r.heartbeats}")
    print(f"result: initial={r.inner.initial_capital:.2f} "
          f"final={r.inner.final_capital:.2f} "
          f"trades={len(r.inner.trades)} pnl={r.inner.total_pnl_abs:.2f}")
    print(f"skipped: no_cap={r.inner.skipped_no_capital} "
          f"no_liq={r.inner.skipped_no_liq}")
    print(f"max_drawdown={r.inner.max_drawdown():.2f}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="arbitrage_bot.sim")
    p.add_argument("--demo", action="store_true",
                   help="запустить демо-сценарий")
    p.add_argument("--scan-demo", action="store_true",
                   help="e2e: scanner + liquidity prod-doc (s157)"),
    p.add_argument("--backtest-demo", action="store_true",
                   help="e2e stage 3: backtest + paper_trader (s158)"),
    p.add_argument("--stage4-demo", action="store_true",
                   help="e2e stage 4: adapter + risk + emergency_stop (s159)"),
    p.add_argument("--stage5-demo", action="store_true",
                   help="e2e stage 5: ExchangeA + ExchangeB + RiskGuard (s160)"),
    p.add_argument("--stage6-demo", action="store_true",
                   help="e2e stage 6: TestnetAdapter + mock http (s163)"),
    p.add_argument("--stage7-demo", action="store_true",
                   help="e2e stage 7: LivePaperTrader на testnet-данных (s165)"),
    p.add_argument("--stage8-demo", action="store_true",
                   help="e2e stage 8: LiveSession (live-сессия paper, s167)"),
    p.add_argument("--balance", type=float, default=100000.0,
                   help="s172: стартовый капитал для --scan-demo / --stage8-demo"),
    p.add_argument("--out", type=str, default=None,
                   help="каталог для записи trades.csv / trades.json")
    args = p.parse_args(argv)

    if args.stage8_demo:
        return run_stage8_demo(initial_capital=args.balance)

    if args.stage7_demo:
        return run_stage7_demo(initial_capital=args.balance)

    if args.stage6_demo:
        return run_stage6_demo()

    if args.stage5_demo:
        return run_stage5_demo()

    if args.stage4_demo:
        return run_stage4_demo()

    if args.backtest_demo:
        return run_backtest_demo()

    if args.scan_demo:
        return run_scan_demo(initial_capital=args.balance)

    if not args.demo:
        print("arbitrage_bot.sim: stage 1 scaffold. Запусти с --demo.",
              file=sys.stderr)
        return 2

    trades = run_demo()
    s = summary(trades)

    print("=== SUMMARY ===")
    print(json.dumps(s, indent=2, ensure_ascii=False))
    print("=== CSV ===")
    print(to_csv(trades), end="")
    print("=== JSON (first 400 chars) ===")
    print(to_json(trades)[:400])

    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "trades.csv").write_text(to_csv(trades), encoding="utf-8")
        (out / "trades.json").write_text(to_json(trades), encoding="utf-8")
        print(f"=== WROTE {out}/trades.csv + trades.json ===")

    return 0


if __name__ == "__main__":
    sys.exit(main())
