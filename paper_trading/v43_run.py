"""v43_run.py - run agent_v43 (maker-only) for N minutes and record to memory."""
import os, sys, time, json, subprocess, signal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import memory

R = Path("/Users/salamkhalikov/Desktop/ai-hub")
RT = R / ".runtime"
S = RT / "paper_state_v43.json"
J = RT / "paper_journal.jsonl"
L = RT / "paper_losses.jsonl"

DURATION_SEC = int(os.environ.get("DURATION_SEC", "1800"))  # 30 min default
HID = os.environ.get("HID", "H1")
STRATEGY = os.environ.get("STRATEGY", "corr_pairs_maker")
SESSION = os.environ.get("SESSION", "s205")

def kill_old():
    subprocess.run(["pkill", "-9", "-f", "agent_v43.py"], capture_output=True)
    time.sleep(1)

def count_log(p):
    if not p.exists(): return []
    out = []
    for line in p.read_text().strip().split("\n"):
        if line:
            try: out.append(json.loads(line))
            except: pass
    return out

def main():
    kill_old()
    if S.exists(): S.unlink()
    log = RT / "agent_v43.log"
    if log.exists(): log.unlink()

    print(f"[v43_run] starting for {DURATION_SEC}s ...", flush=True)
    proc = subprocess.Popen(
        ["python3", "-u", "agent_v43.py"],
        stdout=open(log, "w"), stderr=subprocess.STDOUT,
        cwd=str(Path(__file__).parent))
    time.sleep(DURATION_SEC)
    proc.send_signal(signal.SIGTERM)
    time.sleep(2)
    try: proc.kill()
    except: pass

    print(f"[v43_run] reading state ...", flush=True)
    if not S.exists():
        print("[v43_run] NO STATE — recording as failed")
        memory.record_hypothesis_status(HID, "rejected", SESSION, "no state, run failed")
        return
    st = json.loads(S.read_text())
    journal = count_log(J)
    losses = count_log(L)
    all_trades = journal + losses

    wins = st.get("wins", 0)
    loss = st.get("losses", 0)
    realized = st.get("realized_pnl_bps", 0.0)
    cap_start = 100.0
    cap_now = st.get("cap", 100.0)
    pnl_pct = cap_now - cap_start
    closed = st.get("closed", 0)
    avg = realized / max(1, closed)

    result = {
        "wins": wins, "losses": loss, "closed": closed,
        "realized_bps": round(realized, 2),
        "avg_bps_per_trade": round(avg, 2),
        "cap_start": cap_start, "cap_now": round(cap_now, 4),
        "pnl_pct": round(pnl_pct, 4),
        "ticks": st.get("ticks", 0),
        "duration_sec": DURATION_SEC,
        "fee_model": "maker-only",
        "known_limitation": "fill probability not modeled — actual maker fills < 100%",
    }
    print(f"[v43_run] result: {json.dumps(result, ensure_ascii=False)}")
    memory.record_test_result(HID, STRATEGY, result, SESSION)

    if closed < 3:
        verdict = "inconclusive"
        note = f"only {closed} trades in {DURATION_SEC}s"
    elif wins > loss and avg > 0:
        verdict = "confirmed"
        note = f"W/L {wins}/{loss}, avg {avg:+.2f} bps"
    else:
        verdict = "rejected"
        note = f"W/L {wins}/{loss}, avg {avg:+.2f} bps"

    memory.record_hypothesis_status(HID, verdict if verdict != "inconclusive" else "testing", SESSION, note)
    memory.record_strategy_verdict(STRATEGY,
        "alive" if verdict == "confirmed" else ("killed" if verdict == "rejected" else "testing"),
        SESSION, evidence=f"v43_run {DURATION_SEC}s",
        reason=f"maker fees {result['fee_model']}: W/L {wins}/{loss}, avg {avg:+.2f} bps")

    memory.record_lesson(SESSION, "r10-live",
        f"v4.3 maker-only test — {verdict}",
        f"agent_v43.py run {DURATION_SEC}s. W/L {wins}/{loss}, closed {closed}, realized {realized:+.2f} bps, cap {cap_start}->{cap_now:.4f}.",
        "FEE_MAKER: HL 1.5 / dydx 1.0 / gmx 5.0 / inj 1.0 bps. Confirmed maker fees from H1 sources.",
        f"maker-only {verdict}: edge {'recovered' if verdict=='confirmed' else 'still insufficient'} on 4 CLOB DEX. Fill probability NOT modeled (limitation).",
        f"v43_run.py auto-recorded at {time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())}")

    print(f"[v43_run] verdict={verdict}, recorded to memory")

if __name__ == "__main__":
    main()
