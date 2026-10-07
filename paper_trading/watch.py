"""watch.py v2 - live panel: cap, corrs, nearmiss, rejects, trades."""
import sys, os, time, json, select
from pathlib import Path

R = Path("/Users/salamkhalikov/Desktop/ai-hub")
RT = R / ".runtime"
S = RT / "paper_state.json"

def read_json(p):
    if not p.exists(): return None
    try: return json.loads(p.read_text())
    except: return None

def tail(p, n=5):
    if not p.exists(): return []
    try:
        ls = [l for l in p.read_text().strip().split("\n") if l]
        return [json.loads(l) for l in ls[-n:]]
    except: return []

def alive():
    return bool(os.popen("pgrep -f 'paper_trading/agent.py'").read().strip())

def render():
    os.system("clear")
    s = read_json(S)
    st = "ALIVE" if alive() else "DEAD"
    print(f"=== $100 CORR PAPER TRADER  [agent: {st}] ===")
    if not s:
        print("(no state)")
    else:
        up = time.time() - s.get("started", time.time())
        pnl = s.get("cap", 100) - 100.0
        print(f"cap:      ${s.get('cap', 100):.4f}   pnl: {pnl:+.4f}")
        print(f"trades:   {s.get('trades', 0)}   ticks: {s.get('ticks', 0)}   uptime: {up:.0f}s")
        print(f"signals:  {s.get('signals', 0)}   near: {s.get('near', 0)}   rejects: {s.get('rejects', 0)}")
        print(f"best_net: {s.get('best', 0):.2f}bps   429s: {s.get('429s', 0)}  skips: {s.get('skips', 0)}")
        cs = s.get("corrs", {})
        if cs:
            top = sorted(cs.items(), key=lambda x: -abs(x[1]))[:4]
            print("\n--- top correlations (live) ---")
            for k, v in top:
                bar = "+" if v > 0 else "-"
                print(f"  {k:14} {v:+.3f}  {'#'*int(abs(v)*20)}")
    nr = tail(RT / "paper_nearmiss.jsonl", 5)
    if nr:
        print("\n--- last 5 near-misses ---")
        for r in nr:
            print(f"  {r.get('a')}->{r.get('b')}  z={r.get('z'):+.2f}")
    tr = tail(RT / "paper_journal.jsonl", 5)
    if tr:
        print("\n--- last 5 trades ---")
        for r in tr:
            print(f"  {r.get('a')}->{r.get('b')}  z={r.get('z'):+.2f}  net={r.get('net_bps'):+.2f}bps  cap=${r.get('cap'):.4f}")
    rj = tail(RT / "paper_rejections.jsonl", 3)
    if rj:
        print("\n--- last 3 rejections ---")
        for r in rj:
            print(f"  {r.get('a')}->{r.get('b')}  reason={r.get('reason')}")
    print("\n--- [q]uit (agent keeps running) | auto 2s ---")

print("watch v2 starting...")
while True:
    render()
    r, _, _ = select.select([sys.stdin], [], [], 2.0)
    if r:
        c = sys.stdin.readline().strip().lower()
        if c in ("q", "quit", "exit"): break
