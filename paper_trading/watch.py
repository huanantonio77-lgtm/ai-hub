"""watch.py v3 - live panel for corr-coint agent v4.2."""
import sys, os, time, json, select
from pathlib import Path

R = Path("/Users/salamkhalikov/Desktop/ai-hub")
RT = R / ".runtime"
S = RT / "paper_state.json"

def tail(p, n=12):
    if not p.exists(): return []
    try:
        ls = [l for l in p.read_text().strip().split("\n") if l]
        return [json.loads(l) for l in ls[-n:]]
    except: return []

def read1(p):
    if not p.exists(): return None
    try: return json.loads(p.read_text())
    except: return None

def alive():
    pf = RT / "agent.pid"
    if pf.exists():
        try:
            pid = int(pf.read_text().strip())
            os.kill(pid, 0)
            return True
        except Exception:
            pass
    return bool(os.popen("pgrep -f 'python3 -u agent.py'").read().strip())

def render():
    os.system("clear")
    s = read1(S)
    st = "ALIVE" if alive() else "DEAD"
    print(f"=== $100 PAPER DEX TRADER (corr-coint v4.2) [agent: {st}] ===")
    if not s:
        print("(no state)")
        return

    up = time.time() - s.get("started", time.time())
    pnl = s.get("cap", 100) - 100.0
    ops = s.get("open_positions", [])
    print(f"cap ${s.get('cap',100):.4f}  pnl {pnl:+.4f} ({pnl:+.2f}%)  uptime {up:.0f}s  ticks {s.get('ticks',0)}")
    print(f"signals {s.get('signals',0)}  near {s.get('near',0)}  rejects {s.get('rejects',0)}")
    print(f"closed {s.get('closed',0)}  W/L {s.get('wins',0)}/{s.get('losses',0)}  open {len(ops)}")
    print(f"realized {s.get('realized_pnl_bps',0):+.2f}bps  best {s.get('best',0):+.2f}  worst {s.get('worst',0):+.2f}")
    print(f"429s {s.get('429s',0)}  skips {s.get('skips',0)}")
    cs = s.get("corrs", {})
    if cs:
        print("--- corrs ---")
        for k, v in sorted(cs.items(), key=lambda x: -abs(x[1]))[:6]:
            print(f"  {k:14} {v:+.3f}")
    if ops:
        print(f"--- OPEN ({len(ops)}) ---")
        for p in ops:
            print(f"  {p['a']}->{p['b']} entry_z={p.get('entry_z',0):+.2f} beta={p.get('beta',0):.3f}")

    all_tr = tail(RT/"paper_journal.jsonl", 12) + tail(RT/"paper_losses.jsonl", 12)
    all_tr.sort(key=lambda r: r.get("ts", 0))
    last = all_tr[-10:]
    if last:
        print("--- last 10 closed (W/L) ---")
        for r in last:
            tag = "W" if r.get("realized_bps", 0) > 0 else "L"
            print(f"  [{tag}] {r.get('a')}->{r.get('b')} entry_z={r.get('entry_z',0):+.2f} exit_z={r.get('exit_z',0):+.2f} realized={r.get('realized_bps',0):+.2f}bps costs={r.get('costs_bps',0):.1f} reason={r.get('reason','?')} cap=${r.get('cap',0):.2f}")
    print("\n--- [q]uit | auto 2s ---")

print("watch v3 starting...")
while True:
    render()
    r, _, _ = select.select([sys.stdin], [], [], 2.0)
    if r:
        c = sys.stdin.readline().strip().lower()
        if c in ("q","quit","exit"): break
