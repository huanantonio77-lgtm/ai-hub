"""Paper trader v2 POC: TradeStream-based, net_pressure filter.

s211 fast-entry v2 proof-of-concept. NOT for live trading.
PnL estimate: pump.fun approx price ~ v_sol^2.
"""
import asyncio, json, time, pathlib, sys, statistics
from dataclasses import dataclass
from typing import Optional

sys.path.insert(0, "scripts")
from trade_stream import TradeStream

# Config
MIN_DEV_BUY_SOL   = 2.0
MIN_WAIT_S        = 30
FILTER_NP_MIN     = 0.3
FILTER_UB_MIN     = 3
FILTER_BUY_SOL    = 0.5
HOLD_S            = 120
SIZE_SOL          = 0.01
TICK_S            = 5
SMOKE_DURATION_S  = 360
INITIAL_V_SOL     = 30.0  # pump.fun virtual reserve


@dataclass
class Candidate:
    mint: str
    dev_buy: float
    seen_at: float
    v_sol_at_create: float


@dataclass
class Position:
    mint: str
    entry_time: float
    entry_v_sol: float
    size_sol: float
    peak_chg: float = 0.0


async def main():
    env = {}
    for line in pathlib.Path(".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()

    candidates: dict[str, Candidate] = {}
    positions: dict[str, Position] = {}
    closed: list[dict] = []
    ts: Optional[TradeStream] = None

    async def on_new(data):
        mint = data.get("mint")
        try:
            dev_buy = float(data.get("solAmount", 0))
        except Exception:
            dev_buy = 0.0
        if dev_buy < MIN_DEV_BUY_SOL or mint in candidates:
            return
        candidates[mint] = Candidate(
            mint=mint, dev_buy=dev_buy, seen_at=time.time(),
            v_sol_at_create=INITIAL_V_SOL + dev_buy,
        )
        await ts.subscribe_token(mint)
        print(f"  [cand] {mint[:16]}... dev={dev_buy:.3f}")

    ts = TradeStream(env["PUMPPORTAL_API_KEY"], on_new_token=on_new)
    await ts.start()
    print(f"  paper_fast_v2 | dev>={MIN_DEV_BUY_SOL} wait={MIN_WAIT_S}s "
          f"np>={FILTER_NP_MIN} ub>={FILTER_UB_MIN} hold={HOLD_S}s")

    start = time.time()
    while time.time() - start < SMOKE_DURATION_S:
        await asyncio.sleep(TICK_S)
        now = time.time()

        # Candidates -> entry check
        for mint, c in list(candidates.items()):
            if mint in positions: continue
            if now - c.seen_at < MIN_WAIT_S: continue
            s = ts.stats_for(mint)
            if s is None: continue
            if (s["net_pressure"] >= FILTER_NP_MIN and
                s["unique_buyers"] >= FILTER_UB_MIN and
                s["buy_sol"] >= FILTER_BUY_SOL):
                cur_v = c.v_sol_at_create + (s["buy_sol"] - s["sell_sol"])
                positions[mint] = Position(
                    mint=mint, entry_time=now,
                    entry_v_sol=cur_v, size_sol=SIZE_SOL,
                )
                print(f"  [ENTER] {mint[:16]}... np={s['net_pressure']:+.2f} "
                      f"ub={s['unique_buyers']} buy={s['buy_sol']:.3f} v_sol={cur_v:.2f}")
                candidates.pop(mint, None)

        # Positions -> exit check
        for mint, p in list(positions.items()):
            s = ts.stats_for(mint)
            if s is None: continue
            cur_v = p.entry_v_sol + (s["buy_sol"] - s["sell_sol"])
            chg = (cur_v / p.entry_v_sol) ** 2 - 1.0
            if chg > p.peak_chg: p.peak_chg = chg
            age = now - p.entry_time
            reason = None
            if chg >= 0.5: reason = "partial_1"
            elif chg <= -0.30: reason = "stop"
            elif age >= HOLD_S: reason = "hold_timeout"
            if reason:
                pnl = chg * p.size_sol
                closed.append({"mint": mint, "chg": chg, "pnl": pnl, "reason": reason})
                print(f"  [EXIT/{reason}] {mint[:16]}... chg={chg:+.1%} pnl={pnl:+.5f}")
                positions.pop(mint, None)
                candidates.pop(mint, None)
                await ts.unsubscribe_token(mint)

    await ts.stop()
    print()
    print(f"  === PAPER RESULTS ({SMOKE_DURATION_S}s) ===")
    print(f"  total candidates seen: {len(candidates) + len(positions) + len(closed)}")
    print(f"  closed: {len(closed)}  open: {len(positions)}")
    total_pnl = sum(c["pnl"] for c in closed)
    print(f"  total PnL: {total_pnl:+.5f} SOL")
    if closed:
        wins = [c for c in closed if c["pnl"] > 0]
        print(f"  win rate: {len(wins)}/{len(closed)}")
        print(f"  avg chg: {statistics.mean(c['chg'] for c in closed):+.1%}")
    print(f"  stream cost: {ts.cost_sol():.8f} SOL")

asyncio.run(main())
