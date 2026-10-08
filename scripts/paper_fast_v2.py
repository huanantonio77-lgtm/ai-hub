"""Paper trader v2 POC: TradeStream-based, net_pressure filter.

s211 fast-entry v2 proof-of-concept. NOT for live trading.
PnL estimate: pump.fun approx price ~ v_sol^2.
"""
import asyncio, json, time, pathlib, sys, statistics
from dataclasses import dataclass, asdict
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

POSITIONS_FILE = pathlib.Path(".runtime/paper_v2_positions.json")
JOURNAL_FILE   = pathlib.Path(".runtime/paper_v2_trades.jsonl")
PAUSE_FLAG     = pathlib.Path(".runtime/trading_paused.flag")


def _save_positions(positions):
    try:
        POSITIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {m: asdict(p) for m, p in positions.items()}
        POSITIONS_FILE.write_text(json.dumps(data))
    except Exception as e:
        print(f"  [positions] save failed: {e}")


def _load_positions():
    if not POSITIONS_FILE.exists():
        return {}
    try:
        data = json.loads(POSITIONS_FILE.read_text())
        return {m: Position(**d) for m, d in data.items()}
    except Exception as e:
        print(f"  [positions] load failed: {e}")
        return {}


def _append_journal(rec):
    try:
        JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
        with JOURNAL_FILE.open("a") as fh:
            fh.write(json.dumps(rec) + chr(10))
    except Exception as e:
        print(f"  [journal] append failed: {e}")



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


async def main(duration: int = SMOKE_DURATION_S):
    env = {}
    for line in pathlib.Path(".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()

    if PAUSE_FLAG.exists():
        print("  [s212] trading paused by flag, exiting cleanly")
        return
    candidates: dict[str, Candidate] = {}
    positions = _load_positions()
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
    while time.time() - start < duration:
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
                _save_positions(positions)
            elif now - c.seen_at > MIN_WAIT_S * 2:
                # cost-bug fix: age-out зав. candidates (s211-p5)
                print(f"  [skip] {mint[:16]}... aged={now-c.seen_at:.0f}s "
                      f"np={s['net_pressure']:+.2f} ub={s['unique_buyers']}")
                candidates.pop(mint, None)
                await ts.unsubscribe_token(mint)

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
                rec = {"mint": mint, "chg": chg, "pnl": pnl, "reason": reason, "ts": now, "age": age}
                closed.append(rec)
                print(f"  [EXIT/{reason}] {mint[:16]}... chg={chg:+.1%} pnl={pnl:+.5f}")
                positions.pop(mint, None)
                candidates.pop(mint, None)
                await ts.unsubscribe_token(mint)
                _save_positions(positions)
                _append_journal(rec)

    await ts.stop()
    print()
    print(f"  === PAPER RESULTS ({duration}s) ===")
    print(f"  total candidates seen: {len(candidates) + len(positions) + len(closed)}")
    print(f"  closed: {len(closed)}  open: {len(positions)}")
    total_pnl = sum(c["pnl"] for c in closed)
    print(f"  total PnL: {total_pnl:+.5f} SOL")
    if closed:
        wins = [c for c in closed if c["pnl"] > 0]
        print(f"  win rate: {len(wins)}/{len(closed)}")
        print(f"  avg chg: {statistics.mean(c['chg'] for c in closed):+.1%}")
    print(f"  stream cost: {ts.cost_sol():.8f} SOL")

if __name__ == "__main__":
    _dur = int(sys.argv[1]) if len(sys.argv) > 1 else SMOKE_DURATION_S
    asyncio.run(main(_dur))
