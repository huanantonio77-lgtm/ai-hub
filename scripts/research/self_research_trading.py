#!/usr/bin/env python3
"""self_research_trading.py (s198-p15) — trading auto-research.

Wrapper вокруг scripts/research/extract.py::run_self_problem,
пишет в RESEARCH_TRADING.jsonl (отдельно от SELF_PROPOSALS).
Паттерн: s193-r1 (обёртка), s195-r5 (3-файловый DEX-паттерн).
"""
import argparse, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from scripts.research import extract as E  # noqa: E402

OUT = ROOT / "self" / "curator" / "RESEARCH_TRADING.jsonl"
REPORT = ROOT / "self" / "curator" / "SELF_TRADING.md"

QUERIES = [
    ("dex-arbitrage",    "DEX arbitrage strategies 2025 2026 cross-exchange"),
    ("amm-fees",         "AMM fee optimization cross-DEX decentralized exchanges"),
    ("impermanent-loss", "impermanent loss concentrated liquidity AMM"),
    ("mev-dex",          "MEV extraction decentralized exchanges arbitrage"),
    ("slippage-models",  "slippage modeling CLOB vs AMM order book"),
    ("oracle-latency",   "oracle price latency perpetual DEX"),
    ("flash-loans",      "flash loan arbitrage DeFi protocols"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--limit", type=int, default=2)
    ap.add_argument("--model", default="qwen2.5-coder:3b")
    a = ap.parse_args()
    if not a.run:
        print("dry; pass --run"); return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    L = ["# SELF_TRADING (auto-research)", "",
         "model: " + a.model + " limit: " + str(a.limit), ""]
    t0 = time.time(); total = 0
    for tag, q in QUERIES:
        L.append("## " + tag); L.append("- q: " + q)
        try:
            n = E.run_self_problem(q, limit=a.limit, model=a.model, out_path=OUT)
            total += n; L.append("- proposals: " + str(n))
        except Exception as e:
            L.append("- ERROR: " + repr(e))
        L.append("")

    try:
        cnt = sum(1 for _ in OUT.open(encoding="utf-8")) if OUT.exists() else 0
    except Exception:
        cnt = -1
    dt = round(time.time() - t0, 1)
    L += ["---",
          "total this run: " + str(total),
          "total in file: " + str(cnt),
          "elapsed: " + str(dt) + "s"]
    REPORT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("report: " + str(REPORT))
    print("out: " + str(OUT))
    print("total: " + str(total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
