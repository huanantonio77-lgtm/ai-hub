"""test_runner.py - compute metrics from paper-trading logs (no LLM).

Reads paper_journal.jsonl + paper_losses.jsonl (or custom path).
Computes: trades, win_rate, avg_bps, sharpe, max_dd_pct, profit_factor.
Output: metrics.json for decision_engine.
"""
import sys, os, json, math, time
from pathlib import Path

RT = Path("/Users/salamkhalikov/Desktop/ai-hub/.runtime")

def load_records(journal, losses):
    """Load closed trades from both files."""
    recs = []
    for p in (journal, losses):
        if not p.exists(): continue
        for line in p.read_text().strip().split("\n"):
            if not line: continue
            try:
                r = json.loads(line)
                if "realized_bps" in r: recs.append(r)
            except: pass
    recs.sort(key=lambda r: r.get("ts", 0))
    return recs

def compute_metrics(recs, state=None):
    n = len(recs)
    if n == 0:
        return {"trades": 0, "win_rate": 0, "avg_bps": 0, "sharpe": 0,
                "max_dd_pct": 0, "profit_factor": 0, "note": "no trades"}
    bps = [r.get("realized_bps", 0) for r in recs]
    wins = [b for b in bps if b > 0]
    losses = [b for b in bps if b <= 0]
    win_rate = len(wins) / n
    avg = sum(bps) / n
    if n > 1:
        var = sum((b - avg) ** 2 for b in bps) / (n - 1)
        sd = math.sqrt(var)
    else:
        sd = 0
    sharpe = avg / sd if sd > 0 else 0
    # max drawdown in bps
    cum = 0; peak = 0; dd = 0
    for b in bps:
        cum += b
        peak = max(peak, cum)
        dd = min(dd, cum - peak)
    max_dd_bps = abs(dd)
    max_dd_pct = max_dd_bps / 100.0
    pf = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else 0
    return {
        "trades": n,
        "win_rate": round(win_rate, 4),
        "avg_bps": round(avg, 2),
        "sharpe": round(sharpe, 3),
        "max_dd_pct": round(max_dd_pct, 3),
        "profit_factor": round(pf, 3),
        "sum_bps": round(sum(bps), 2),
    }

def run_on_logs(hid, strategy, session, journal=None, losses=None):
    """Compute metrics from existing logs, save to paper_test_metrics.jsonl."""
    j = Path(journal) if journal else RT / "paper_journal.jsonl"
    l = Path(losses) if losses else RT / "paper_losses.jsonl"
    recs = load_records(j, l)
    m = compute_metrics(recs)
    m["hid"] = hid
    m["strategy"] = strategy
    m["session"] = session
    m["journal"] = str(j)
    m["losses"] = str(l)
    m["ts"] = time.time()
    out = RT / "paper_test_metrics.jsonl"
    RT.mkdir(parents=True, exist_ok=True)
    with open(out, "a") as f:
        f.write(json.dumps(m, ensure_ascii=False) + "\n")
    print(f"[runner] metrics for {hid}/{strategy}: {json.dumps(m, ensure_ascii=False)}", flush=True)
    return m

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--hid", default="H1")
    ap.add_argument("--strategy", default="corr_pairs_maker")
    ap.add_argument("--session", default="s205")
    ap.add_argument("--journal", default=None)
    ap.add_argument("--losses", default=None)
    ap.add_argument("--metrics-only", action="store_true",
                    help="print metrics, do not append to jsonl")
    args = ap.parse_args()
    if args.metrics_only:
        j = Path(args.journal) if args.journal else RT / "paper_journal.jsonl"
        l = Path(args.losses) if args.losses else RT / "paper_losses.jsonl"
        recs = load_records(j, l)
        m = compute_metrics(recs)
        print(json.dumps(m, indent=2, ensure_ascii=False))
    else:
        run_on_logs(args.hid, args.strategy, args.session, args.journal, args.losses)
