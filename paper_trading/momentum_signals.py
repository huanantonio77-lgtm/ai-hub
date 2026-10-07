"""Momentum signals for F3 - pure python (LLM extract only).

S1 breakout, S2 volume spike. Uses HLBookStream + HLTradesStream.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict, field
from typing import Optional

@dataclass
class MomentumSignal:
    kind: str          # "S1_breakout" | "S2_volume_spike"
    coin: str
    ts: int
    price: float
    score: float       # [0, 1]
    meta: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)

def volume_spike(trades_stream, short_s: int = 30, long_s: int = 300,
                 k: float = 3.0) -> Optional[dict]:
    """S2: short-window volume > k * (long/k_ratio per short)."""
    v_short = trades_stream.volume(short_s)
    v_long = trades_stream.volume(long_s)
    if v_long["sz"] <= 0:
        return None
    base = v_long["sz"] * (short_s / long_s)
    if base <= 0:
        return None
    ratio = v_short["sz"] / base
    if ratio < k:
        return None
    score = min(1.0, (ratio - k) / k)
    return {"ratio": ratio, "short": v_short, "long": v_long,
            "score": score, "k": k}

def breakout(book_stream, lookback: int = 60, pct: float = 0.0015,
             need_spike: Optional[dict] = None) -> Optional[dict]:
    """S1: current mid > max(prior mids) * (1+pct)."""
    snaps = list(book_stream.snapshots)
    if len(snaps) < lookback + 1:
        return None
    prior = [s["mid"] for s in snaps[-lookback - 1:-1] if s.get("mid")]
    if not prior:
        return None
    last = snaps[-1]
    if not last.get("mid"):
        return None
    hi = max(prior)
    if last["mid"] <= hi * (1.0 + pct):
        return None
    dev = last["mid"] / hi - 1.0
    score = min(1.0, dev / (pct * 5.0))
    if need_spike is not None:
        score = min(score, need_spike["score"])
    return {"mid": last["mid"], "prior_high": hi, "dev": dev,
            "score": score, "lookback": lookback, "pct": pct}

def detect(book_stream, trades_stream, coin: str = "BTC",
           lookback: int = 60, pct: float = 0.0015,
           vol_k: float = 3.0, require_volume: bool = True):
    """Run S1+S2, return best signal or None. Pure numeric."""
    spike = volume_spike(trades_stream, k=vol_k)
    if require_volume and spike is None:
        return None
    bo = breakout(book_stream, lookback=lookback, pct=pct,
                  need_spike=spike)
    if bo is None:
        return None
    ts = book_stream.snapshots[-1].get("ts") or 0
    return MomentumSignal(
        kind="S1_breakout", coin=coin, ts=int(ts),
        price=float(bo["mid"]), score=float(bo["score"]),
        meta={"breakout": bo, "spike": spike},
    )
