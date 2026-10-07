"""session_report.py - s204 summary for handoff."""
import json, time
from pathlib import Path
R = Path("/Users/salamkhalikov/Desktop/ai-hub/.runtime")
OUT = R / "paper_report_s204.json"

def read_json(p):
    if not p.exists(): return None
    try: return json.loads(p.read_text())
    except: return None

def tail_all(p):
    if not p.exists(): return []
    try:
        return [json.loads(l) for l in p.read_text().strip().split("\n") if l]
    except: return []

s = read_json(R / "paper_state.json") or {}
trades = tail_all(R / "paper_journal.jsonl")
near = tail_all(R / "paper_nearmiss.jsonl")
rej = tail_all(R / "paper_rejections.jsonl")
corrs = tail_all(R / "paper_corrs.jsonl")

nets = [t.get("net_bps", 0) for t in trades]
top_pairs = {}
for t in trades:
    k = f"{t.get('a')}->{t.get('b')}"
    top_pairs[k] = top_pairs.get(k, 0) + 1

report = {
    "session": "s204",
    "ts": time.time(),
    "cap_start": 100.0,
    "cap_end": s.get("cap", 100.0),
    "pnl_abs": round(s.get("cap", 100.0) - 100.0, 4),
    "pnl_pct": round((s.get("cap", 100.0) / 100.0 - 1) * 100, 4),
    "trades_total": len(trades),
    "signals_total": s.get("signals", 0),
    "near_total": s.get("near", 0),
    "rejects_total": s.get("rejects", 0),
    "avg_net_bps": round(sum(nets)/len(nets), 2) if nets else 0,
    "best_net_bps": round(max(nets), 2) if nets else 0,
    "min_net_bps": round(min(nets), 2) if nets else 0,
    "top_pair": max(top_pairs.items(), key=lambda x: x[1])[0] if top_pairs else None,
    "corrs_snapshots": len(corrs),
    "429s": s.get("429s", 0),
    "skips": s.get("skips", 0),
    "uptime_sec": round(time.time() - s.get("started", time.time()), 0),
    "logs": {
        "journal": len(trades),
        "nearmiss": len(near),
        "rejections": len(rej),
        "corrs": len(corrs),
    }
}
OUT.write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
