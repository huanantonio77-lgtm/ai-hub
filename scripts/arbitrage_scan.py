"""arbitrage_scan (s193).

Обёртка над scanner.scan_pair / scan_exchanges.
Берёт биржи из registry, мапит символы, считает net% (комиссии,
slippage, safety), пишет ARBITRAGE_REPORT.md + arbitrage_opportunities.json.

Usage:
  python3 scripts/arbitrage_scan.py
  python3 scripts/arbitrage_scan.py --apply
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from arbitrage_bot.app.exchanges.registry import all_exchanges
from arbitrage_bot.app.strategy.profitability import ProfitabilityConfig
from arbitrage_bot.app.strategy.scanner import ScannerConfig, scan_pair

JSON_OUT = ROOT / "self/curator/arbitrage_opportunities.json"
MD_OUT   = ROOT / "self/curator/ARBITRAGE_REPORT.md"
STATS_OUT = ROOT / "self/curator/ARBITRAGE_STATS.jsonl"
CFG_PATH = ROOT / "arbitrage_bot/app/config/default.json"

BASE_SYMBOLS = ["BTC", "ETH", "SOL"]

DEFAULT_FEES = {"hyperliquid": 0.035, "dydx": 0.050}


def _load_class(spec: str):
    mod_name, _, cls_name = spec.partition(":")
    return getattr(importlib.import_module(mod_name), cls_name)


def symbol_for(exchange_name: str, base: str) -> str:
    if exchange_name == "dydx":
        return base + "-USD"
    return base


def load_fees():
    raw = {}
    if CFG_PATH.exists():
        try:
            cfg = json.loads(CFG_PATH.read_text())
            raw = cfg.get("taker_fees_percent") or cfg.get("exchange_fees_percent") or {}
        except Exception:
            raw = {}
    out = dict(DEFAULT_FEES)
    for k, v in raw.items():
        try:
            out[k] = float(v)
        except Exception:
            pass
    return out


def load_profit_config():
    raw = {}
    if CFG_PATH.exists():
        try:
            raw = json.loads(CFG_PATH.read_text())
        except Exception:
            raw = {}
    return ProfitabilityConfig(
        min_profit_percent=float(raw.get("min_profit_percent", 0.10)),
        safety_buffer_percent=float(raw.get("safety_buffer_percent", 0.05)),
        max_slippage_percent=float(raw.get("max_slippage_percent", 0.05)),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--write-stats", action="store_true", help="s197-p1a: append findings to ARBITRAGE_STATS.jsonl")
    ap.add_argument("--size", type=float, default=0.01)
    args = ap.parse_args()

    prof_cfg = load_profit_config()
    fees = load_fees()
    entries = all_exchanges()

    clients = {}
    for e in entries:
        try:
            cls = _load_class(e["class"])
            clients[e["name"]] = cls()
        except Exception as ex:
            print(f"CLIENT FAIL {e['name']}: {type(ex).__name__}: {ex}")

    findings = []
    per_symbol_rows = []

    for base in BASE_SYMBOLS:
        books = {}
        for e in entries:
            name = e["name"]
            if name not in clients:
                continue
            sym = symbol_for(name, base)
            try:
                books[name] = clients[name].get_orderbook(sym)
            except Exception as ex:
                print(f"WARN {name} {sym}: {type(ex).__name__}: {ex}")

        live_books = {n: b for n, b in books.items()
                      if b is not None and b.is_valid()}
        if len(live_books) < 2:
            per_symbol_rows.append({
                "symbol": base, "alive": len(live_books),
                "best_net_percent": None, "passes": False,
            })
            continue

        names = sorted(live_books.keys())
        best_net = None
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                cfg = ScannerConfig(
                    profitability=prof_cfg,
                    taker_fee_a_percent=fees.get(a, 0.05),
                    taker_fee_b_percent=fees.get(b, 0.05),
                    size=args.size,
                )
                for opp in scan_pair(base, live_books[a], live_books[b], cfg, a, b):
                    row = {
                        "symbol": opp.symbol,
                        "buy_exchange": opp.buy_exchange,
                        "sell_exchange": opp.sell_exchange,
                        "buy_price": opp.buy_price,
                        "sell_price": opp.sell_price,
                        "gross_percent": round(opp.gross_percent, 4),
                        "net_percent": round(opp.net_percent, 4),
                        "net_abs": round(opp.net_abs, 6),
                        "size": opp.size,
                        "passes": bool(opp.passes),
                    }
                    findings.append(row)
                    if best_net is None or row["net_percent"] > best_net:
                        best_net = row["net_percent"]
        per_symbol_rows.append({
            "symbol": base,
            "alive": len(live_books),
            "best_net_percent": best_net,
            "passes": bool(best_net is not None and best_net >= prof_cfg.min_profit_percent),
        })

    passing = [f for f in findings if f["passes"]]
    report = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": {
            "min_profit_percent": prof_cfg.min_profit_percent,
            "safety_buffer_percent": prof_cfg.safety_buffer_percent,
            "max_slippage_percent": prof_cfg.max_slippage_percent,
            "size": args.size,
            "fees_percent": fees,
        },
        "summary": {
            "total_findings": len(findings),
            "passing": len(passing),
            "symbols_scanned": len(BASE_SYMBOLS),
        },
        "per_symbol": per_symbol_rows,
        "opportunities": findings,
    }

    md = []
    md.append("# ARBITRAGE REPORT")
    md.append("")
    md.append("Generated: " + report["ts"])
    md.append("")
    md.append("## Summary")
    md.append("- scanned symbols: **" + str(len(BASE_SYMBOLS)) + "**")
    md.append("- total findings: **" + str(len(findings)) + "**")
    md.append("- passing (net >= " + str(prof_cfg.min_profit_percent) + "%): **" + str(len(passing)) + "**")
    md.append("")
    md.append("## Per symbol")
    md.append("| symbol | alive exchanges | best net % | passes |")
    md.append("|---|---|---|---|")
    for r in per_symbol_rows:
        md.append("| " + r["symbol"] + " | " + str(r["alive"]) + " | "
                  + str(r["best_net_percent"]) + " | "
                  + ("YES" if r["passes"] else "no") + " |")
    md.append("")
    md.append("## Opportunities")
    if findings:
        md.append("| symbol | buy @ | sell @ | buy_px | sell_px | gross% | net% | passes |")
        md.append("|---|---|---|---|---|---|---|---|")
        for f in sorted(findings, key=lambda x: -x["net_percent"]):
            md.append("| " + f["symbol"] + " | " + f["buy_exchange"] + " | " + f["sell_exchange"]
                      + " | " + str(f["buy_price"]) + " | " + str(f["sell_price"])
                      + " | " + str(f["gross_percent"]) + " | " + str(f["net_percent"])
                      + " | " + ("YES" if f["passes"] else "no") + " |")
    else:
        md.append("(no spreads beyond book validity)")
    md.append("")

    print("\n".join(md))

    # s197-p1a: append findings to ARBITRAGE_STATS.jsonl (fail-open)
    if getattr(args, "write_stats", False):
        try:
            STATS_OUT.parent.mkdir(parents=True, exist_ok=True)
            with STATS_OUT.open("a", encoding="utf-8") as f:
                for r in findings:
                    rec = {
                        "ts": report["ts"],
                        "symbol": r["symbol"],
                        "buy_exchange": r["buy_exchange"],
                        "sell_exchange": r["sell_exchange"],
                        "buy_price": r["buy_price"],
                        "sell_price": r["sell_price"],
                        "gross_percent": r["gross_percent"],
                        "net_percent": r["net_percent"],
                        "slippage_est_percent": prof_cfg.max_slippage_percent,
                        "fees_percent": {
                            "buy": fees.get(r["buy_exchange"], 0.05),
                            "sell": fees.get(r["sell_exchange"], 0.05),
                        },
                        "decision": "pass" if r["passes"] else "no",
                    }
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print("stats: appended " + str(len(findings)) + " rows to " + str(STATS_OUT))
        except Exception as ex:
            print("stats: WARN " + type(ex).__name__ + ": " + str(ex))

    if args.apply:
        JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
        JSON_OUT.write_text(json.dumps(report, indent=2))
        MD_OUT.write_text("\n".join(md) + "\n")
        print("wrote " + str(JSON_OUT))
        print("wrote " + str(MD_OUT))


if __name__ == "__main__":
    main()
