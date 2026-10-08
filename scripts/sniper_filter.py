#!/usr/bin/env python3
"""sniper_filter.py (s208) — dev-reputation filter for fresh pump.fun mints.

Reads .runtime/mint_watch.jsonl (create events), scores each mint by dev-reputation
(bucket != serial + total_sigs + span_days), writes passed/failed to
.runtime/sniper_filter.jsonl.

v1: dev filter only (proven edge, 60% serial in fresh mints).
v2 plan: holders count, buy pressure, LP locked (after migration).

CLI:
  python3 scripts/sniper_filter.py --run         # score all unique devs
  python3 scripts/sniper_filter.py --run --limit 10
  python3 scripts/sniper_filter.py --recheck     # re-score all (ignore journal)
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from dev_reputation import dev_score  # reuse RPC wrapper

MINT_WATCH = ROOT / ".runtime" / "mint_watch.jsonl"
JOURNAL    = ROOT / ".runtime" / "sniper_filter.jsonl"
SLEEP_BETWEEN_RPC = 0.7  # public RPC ~10 req/10s

# Weights (v1)
W_BUCKET = 0.6   # bucket != serial
W_SIGS   = 0.2   # total_sigs < 50
W_SPAN   = 0.2   # span_days > 1
PASS_THRESHOLD = 0.5


def _load_mints():
    if not MINT_WATCH.exists():
        return []
    out = []
    for line in MINT_WATCH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def _load_cache():
    """dev -> record from prior runs (to avoid re-calling RPC)."""
    cache = {}
    if JOURNAL.exists():
        for line in JOURNAL.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
                dev = d.get("dev")
                if dev and dev not in cache:
                    cache[dev] = d
            except Exception:
                pass
    return cache


def _score_one(mint_rec, dev_rec):
    """Compute score from dev_reputation record. Returns (score, reasons)."""
    score = 0.0
    reasons = []
    bucket = dev_rec.get("bucket", "unknown")
    sigs = dev_rec.get("total_sigs", 0)
    span = dev_rec.get("span_days", 0.0)

    if bucket != "serial":
        score += W_BUCKET
        reasons.append(f"bucket={bucket}(+{W_BUCKET})")
    else:
        reasons.append(f"bucket=serial(+0)")

    if sigs < 50:
        score += W_SIGS
        reasons.append(f"sigs={sigs}<50(+{W_SIGS})")
    else:
        reasons.append(f"sigs={sigs}(+0)")

    if span > 1.0:
        score += W_SPAN
        reasons.append(f"span={span}d>1(+{W_SPAN})")
    else:
        reasons.append(f"span={span}d(+0)")

    return round(score, 2), reasons


def _append(rec):
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def run(limit=None, recheck=False):
    mints = _load_mints()
    if not mints:
        print("sniper_filter: no mints in .runtime/mint_watch.jsonl")
        return 0

    if limit:
        mints = mints[-limit:]

    cache = {} if recheck else _load_cache()

    # unique devs in order of appearance
    seen_devs = []
    for m in mints:
        d = m.get("dev")
        if d and d not in seen_devs:
            seen_devs.append(d)

    print(f"sniper_filter: {len(mints)} mints, {len(seen_devs)} unique devs")

    # score devs
    for i, dev in enumerate(seen_devs, 1):
        if dev in cache:
            print(f"  [{i}/{len(seen_devs)}] {dev[:8]}..  CACHED")
            continue
        try:
            rec = dev_score(dev, limit=100)
            cache[dev] = rec if rec else {"dev": dev, "bucket": "unknown",
                                          "total_sigs": 0, "span_days": 0.0}
            b = cache[dev].get("bucket", "?")
            s = cache[dev].get("total_sigs", 0)
            print(f"  [{i}/{len(seen_devs)}] {dev[:8]}..  bucket={b} sigs={s}")
        except Exception as e:
            print(f"  [{i}/{len(seen_devs)}] {dev[:8]}..  ERR: {type(e).__name__}")
            cache[dev] = {"dev": dev, "bucket": "unknown", "total_sigs": 0, "span_days": 0.0}
        time.sleep(SLEEP_BETWEEN_RPC)

    # score mints
    n_passed = 0
    for m in mints:
        dev = m.get("dev")
        dev_rec = cache.get(dev, {})
        score, reasons = _score_one(m, dev_rec)
        passed = score >= PASS_THRESHOLD
        if passed:
            n_passed += 1
        rec = {
            "ts": m.get("ts"),
            "mint": m.get("mint"),
            "symbol": m.get("symbol"),
            "dev": dev,
            "bucket": dev_rec.get("bucket"),
            "total_sigs": dev_rec.get("total_sigs"),
            "span_days": dev_rec.get("span_days"),
            "score": score,
            "passed": passed,
            "reasons": reasons,
            "check_ts": int(time.time()),
        }
        _append(rec)

    print(f"sniper_filter: {n_passed}/{len(mints)} passed (threshold={PASS_THRESHOLD})")
    print(f"journal: {JOURNAL}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--recheck", action="store_true")
    a = ap.parse_args()
    if not a.run:
        print("use --run"); return 0
    return run(limit=a.limit, recheck=a.recheck)


if __name__ == "__main__":
    sys.exit(main())
