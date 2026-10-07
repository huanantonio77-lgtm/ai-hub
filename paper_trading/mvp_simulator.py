"""MVP: $100 paper trading on BTC across 5 DEX. Read-only, no orders."""
from __future__ import annotations
import sys, time, json, importlib
from pathlib import Path
ROOT = Path("/Users/salamkhalikov/Desktop/ai-hub")
sys.path.insert(0, str(ROOT))
from arbitrage_bot.app.exchanges.registry import all_exchanges
from arbitrage_bot.app.strategy.profitability import ProfitabilityConfig
from arbitrage_bot.app.strategy.scanner import ScannerConfig, scan_pair

INITIAL_USD = 100.0
TICK_SEC = 3.0
DURATION_SEC = 30
SYMBOL_MAP = {"hyperliquid":"BTC","dydx":"BTC-USD","paradex":"BTC-USD-PERP",
              "injective":"BTC","gmx":"BTC/USD"}
DEX_FEES = {"hyperliquid":0.035,"dydx":0.050,"paradex":0.030,"injective":0.020,"gmx":0.050}

def build_clients():
    clients = {}
    for e in all_exchanges():
        n = e["name"]
        if n not in SYMBOL_MAP: continue
        mod, _, cls = e["class"].partition(":")
        try:
            clients[n] = getattr(importlib.import_module(mod), cls)()
        except Exception as ex:
            print(f"[skip] {n}: {type(ex).__name__}: {ex}")
    return clients

def main():
    clients = build_clients()
    print(f"clients: {list(clients)}")
    cap = INITIAL_USD
    trades = []
    t0 = time.time()
    tick = 0
    while time.time() - t0 < DURATION_SEC:
        tick += 1
        books = {}
        for n, c in clients.items():
            try:
                b = c.get_orderbook(SYMBOL_MAP[n])
                if b is not None and b.is_valid(): books[n] = b
            except Exception:
                pass
        names = sorted(books.keys())
        best = None
        for i in range(len(names)):
            for j in range(i+1, len(names)):
                a, b = names[i], names[j]
                cfg = ScannerConfig(
                    profitability=ProfitabilityConfig(
                        min_profit_percent=0.05,
                        safety_buffer_percent=0.02,
                        max_slippage_percent=0.10),
                    taker_fee_a_percent=DEX_FEES.get(a, 0.05),
                    taker_fee_b_percent=DEX_FEES.get(b, 0.05),
                    size=0.001)
                for opp in scan_pair("BTC", books[a], books[b], cfg, a, b):
                    if opp.passes and (best is None or opp.net_percent > best.net_percent):
                        best = opp
        if best:
            cap *= (1.0 + best.net_percent/100.0)
            trades.append({"tick":tick,"buy":best.buy_exchange,"sell":best.sell_exchange,
                           "net_pct":round(best.net_percent,4),"cap":round(cap,2)})
            print(f"TRADE t{tick} {best.buy_exchange}->{best.sell_exchange} net={best.net_percent:.4f}% cap=${cap:.2f}")
        time.sleep(TICK_SEC)
    print(f"=== DONE: cap=${cap:.2f} (from ${INITIAL_USD}) trades={len(trades)} duration={DURATION_SEC}s")
    print(json.dumps(trades[:20], indent=2))

if __name__ == "__main__":
    main()
