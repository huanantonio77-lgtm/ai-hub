#!/usr/bin/env python3
"""s199-p1: ARBITRAGE ROLLING STATS.

Читает ARBITRAGE_STATS.jsonl за rolling-окно, считает метрики,
append-ит отчёт в SELF_TRADING.md.

Usage:
    python3 scripts/arbitrage_stats.py --dry          # только stdout
    python3 scripts/arbitrage_stats.py --run          # + append в SELF_TRADING.md
    python3 scripts/arbitrage_stats.py --days 7 --run # окно 7 дней
"""
from __future__ import annotations
import argparse, datetime as dt, json, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATS = ROOT / "self" / "curator" / "ARBITRAGE_STATS.jsonl"
REPORT = ROOT / "self" / "curator" / "SELF_TRADING.md"


def load_rows(path: Path, days: int) -> list[dict]:
    if not path.exists():
        return []
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = r.get("ts", "")
        try:
            d = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            d = None
        if d is not None and d < cutoff:
            continue
        r["_dt"] = d
        rows.append(r)
    return rows


def _fmt(vals):
    if not vals:
        return "—"
    return f"min={min(vals):+.4f} max={max(vals):+.4f} avg={sum(vals)/len(vals):+.4f}"


def compute(rows: list[dict]) -> dict:
    by_sym: dict = defaultdict(list)
    by_pair: dict = defaultdict(int)
    by_hour_net: dict = defaultdict(list)
    decisions: dict = defaultdict(int)
    gross_all, net_all, fee_buy, fee_sell = [], [], [], []
    for r in rows:
        sym = r.get("symbol", "?")
        by_sym[sym].append(r)
        pair = f'{r.get("buy_exchange","?")}->{r.get("sell_exchange","?")}'
        by_pair[pair] += 1
        g = r.get("gross_percent")
        n = r.get("net_percent")
        if g is not None:
            gross_all.append(g)
        if n is not None:
            net_all.append(n)
            if r.get("_dt"):
                by_hour_net[r["_dt"].hour].append(n)
        decisions[r.get("decision", "?")] += 1
        fees = r.get("fees_percent", {})
        if isinstance(fees, dict):
            if "buy" in fees:
                fee_buy.append(fees["buy"])
            if "sell" in fees:
                fee_sell.append(fees["sell"])
    return {
        "total": len(rows), "by_sym": by_sym, "by_pair": by_pair,
        "by_hour_net": by_hour_net, "decisions": decisions,
        "gross_all": gross_all, "net_all": net_all,
        "fee_buy": fee_buy, "fee_sell": fee_sell,
    }


def render(rows: list[dict], days: int) -> str:
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out = ["", "", "---", "",
           f"## Rolling stats (s199, window={days}d, updated {ts})", ""]
    if not rows:
        out.append("_No data in window._")
        return "\n".join(out) + "\n"
    m = compute(rows)
    out.append(f"- rows: **{m['total']}**")
    if m["net_all"]:
        out.append(f"- net:   {_fmt(m['net_all'])}")
    if m["gross_all"]:
        out.append(f"- gross: {_fmt(m['gross_all'])}")
    out.append(f"- decisions: {dict(m['decisions'])}")
    yes = m["decisions"].get("yes", 0)
    out.append(f"- hit rate: {yes}/{m['total']} = {100*yes/max(m['total'],1):.1f}%")
    out += ["", "### Per symbol", "",
            "| symbol | n | net avg | net best | gross avg |",
            "|---|---|---|---|---|"]
    for sym in sorted(m["by_sym"]):
        rs = m["by_sym"][sym]
        nets = [r["net_percent"] for r in rs if r.get("net_percent") is not None]
        gross = [r["gross_percent"] for r in rs if r.get("gross_percent") is not None]
        na = f"{sum(nets)/len(nets):+.4f}" if nets else "—"
        nb = f"{max(nets):+.4f}" if nets else "—"
        ga = f"{sum(gross)/len(gross):+.4f}" if gross else "—"
        out.append(f"| {sym} | {len(rs)} | {na} | {nb} | {ga} |")
    if m["by_hour_net"]:
        out += ["", "### Best hours (net closest to 0, UTC)", ""]
        for h in sorted(m["by_hour_net"], key=lambda k: -max(m["by_hour_net"][k]))[:5]:
            v = m["by_hour_net"][h]
            out.append(f"- {h:02d}:00 — n={len(v)} best_net={max(v):+.4f}")
    if m["by_pair"]:
        out += ["", "### Exchange pairs", ""]
        for p, n in sorted(m["by_pair"].items(), key=lambda x: -x[1]):
            out.append(f"- {p}: {n}")
    if m["fee_buy"] or m["fee_sell"]:
        out += ["", "### Fees (taker, %)", "",
                f"- buy:  {_fmt(m['fee_buy'])}",
                f"- sell: {_fmt(m['fee_sell'])}"]
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--run", action="store_true", help="append to SELF_TRADING.md")
    ap.add_argument("--dry", action="store_true", help="print only")
    args = ap.parse_args()
    rows = load_rows(STATS, args.days)
    report = render(rows, args.days)
    print(report)
    if args.run and not args.dry:
        with REPORT.open("a", encoding="utf-8") as fh:
            fh.write(report)
        print(f"[arbitrage_stats] appended {len(report)} bytes -> {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
