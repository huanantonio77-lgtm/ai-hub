#!/usr/bin/env python3
"""paper_sniper.py (s208) — paper PnL for passed mints from sniper_filter.

Reads .runtime/sniper_filter.jsonl (passed=true, check_ts < 1h),
enters virtual $5 at current price via price_lamports,
tracks each position every TICK_S up to HOLD_S,
exits on target +50% / stop -30% / time.
Fees: 400 bps RT. Journal: .runtime/sniper_trades.jsonl.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from paper_trading.data_layer import price_lamports

FILTER = ROOT / ".runtime" / "sniper_filter.jsonl"
TRADES = ROOT / ".runtime" / "sniper_trades.jsonl"

TARGET_PCT = 0.50
STOP_PCT   = -0.30
HOLD_S     = 120
TICK_S     = 15
FEE_RT_BPS = 400
SIZE_USD   = 5.0
MAX_TRADES = 8
DUST = 27608


def _price(mint):
    """Try 1B, then 100M, 10M, 1M. Returns SOL per token unit or None."""
    for amt in (1_000_000_000, 100_000_000, 10_000_000, 1_000_000):
        px = price_lamports(mint, amt)
        if px and px != DUST:
            return px / amt
    return None


def load_passed(max_age_s=3600):
    if not FILTER.exists():
        return []
    now = int(time.time())
    out = []
    for l in FILTER.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(l)
            if d.get("passed") and (now - d.get("check_ts", 0)) < max_age_s:
                out.append(d)
        except Exception:
            pass
    return out


def load_done():
    if not TRADES.exists():
        return set()
    done = set()
    for l in TRADES.read_text(encoding="utf-8").splitlines():
        try:
            done.add(json.loads(l).get("mint"))
        except Exception:
            pass
    return done


def append_trade(rec):
    TRADES.parent.mkdir(parents=True, exist_ok=True)
    with TRADES.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def close_pos(mint, pos, exit_px, reason, t):
    pct = (exit_px - pos["entry"]) / pos["entry"] if pos["entry"] else 0.0
    fee = FEE_RT_BPS / 10000.0
    net_pct = pct - fee
    pnl_usd = SIZE_USD * net_pct
    rec = {
        "mint": mint,
        "symbol": pos["symbol"],
        "entry_ts": pos["entry_ts"],
        "exit_ts": int(time.time()),
        "entry_px": pos["entry"],
        "exit_px": exit_px,
        "hold_s": t,
        "chg_pct": round(pct * 100, 2),
        "net_pct": round(net_pct * 100, 2),
        "pnl_usd": round(pnl_usd, 4),
        "reason": reason,
        "bucket": pos["info"].get("bucket"),
        "score": pos["info"].get("score"),
    }
    append_trade(rec)
    print(f"  {pos['symbol'][:15]:15s}  {reason:6s}  chg={pct*100:+6.1f}%  net={net_pct*100:+6.1f}%  pnl=${pnl_usd:+.2f}  ({t}s)")


def run(hold_s=HOLD_S, tick_s=TICK_S, max_age_s=3600):
    passed = load_passed(max_age_s)
    done = load_done()
    todo = [d for d in passed if d["mint"] not in done][:MAX_TRADES]

    if not todo:
        print(f"no fresh passed mints (passed={len(passed)}, done={len(done)})")
        return 0

    print(f"paper_sniper: {len(todo)} mints (hold={hold_s}s, tick={tick_s}s, size=${SIZE_USD})")

    # ENTRY
    positions = {}
    now = int(time.time())
    for d in todo:
        mint = d["mint"]
        px = _price(mint)
        if px is None:
            print(f"  {d['symbol'][:15]:15s}  SKIP entry (no price)")
            continue
        positions[mint] = {
            "symbol": d["symbol"],
            "entry": px,
            "entry_ts": now,
            "info": d,
        }
        print(f"  {d['symbol'][:15]:15s}  entry={px:.10f} SOL/u  bucket={d.get('bucket')} score={d.get('score')}")
        time.sleep(0.5)

    if not positions:
        print("no positions opened")
        return 0

    # TRACK
    t = 0
    while positions and t < hold_s:
        time.sleep(tick_s)
        t += tick_s
        for mint in list(positions.keys()):
            pos = positions[mint]
            px = _price(mint)
            if px is None:
                continue
            pct = (px - pos["entry"]) / pos["entry"]
            reason = None
            if pct >= TARGET_PCT:
                reason = "target"
            elif pct <= STOP_PCT:
                reason = "stop"
            elif t >= hold_s:
                reason = "time"
            if reason:
                close_pos(mint, pos, px, reason, t)
                del positions[mint]

    # Force-close remaining
    for mint in list(positions.keys()):
        pos = positions[mint]
        px = _price(mint) or pos["entry"]
        close_pos(mint, pos, px, "time", hold_s)

    print(f"paper_sniper: done, journal={TRADES}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--hold", type=int, default=HOLD_S)
    ap.add_argument("--tick", type=int, default=TICK_S)
    ap.add_argument("--max-age", type=int, default=3600)
    a = ap.parse_args()
    if not a.run:
        print("use --run")
        return 0
    return run(hold_s=a.hold, tick_s=a.tick, max_age_s=a.max_age)


if __name__ == "__main__":
    sys.exit(main())
