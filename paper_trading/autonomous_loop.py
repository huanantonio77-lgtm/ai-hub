"""autonomous_loop.py - orchestrate: findings -> extracts -> hypotheses -> baseline check -> memory.

LLM role: extract hypothesis only.
Verdict: decision_engine (pure python) on real metrics.

Phase 1 (s205): stages A-B-C only. Real test codegen deferred to s206.
"""
import sys, os, json, time, subprocess
from pathlib import Path
import memory

R = Path("/Users/salamkhalikov/Desktop/ai-hub")
PT = R / "paper_trading"
RT = R / ".runtime"
LOG = RT / "paper_autonomous_loop.jsonl"

def _log(stage, data):
    RT.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as f:
        f.write(json.dumps({"ts": time.time(), "stage": stage, **data}, ensure_ascii=False) + "\n")

def _run(cmd, timeout=300):
    """Run a python script, return (ok, stdout)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(PT))
        return r.returncode == 0, (r.stdout + r.stderr)[-2000:]
    except Exception as e:
        return False, str(e)

def stage_a_reader(max_n=3):
    """fetch top-N URLs from findings -> extracts."""
    ok, out = _run(["python3", "paper_reader.py", str(RT/"paper_research_findings.jsonl"), str(max_n)], timeout=180)
    _log("A_reader", {"ok": ok, "tail": out[-400:]})
    print(f"[loop] A_reader ok={ok}", flush=True)
    return ok

def stage_b_extract(max_n=3):
    """extracts -> hypotheses (LLM)."""
    env = {**os.environ, "PAPER_LLM_THROTTLE": "0"}
    try:
        r = subprocess.run(
            ["python3", "hypothesis_extractor.py", str(max_n)],
            capture_output=True, text=True, timeout=900, cwd=str(PT), env=env)
        ok = r.returncode == 0
        out = (r.stdout + r.stderr)[-2000:]
    except Exception as e:
        ok, out = False, str(e)
    _log("B_extract", {"ok": ok, "tail": out[-400:]})
    print(f"[loop] B_extract ok={ok}", flush=True)
    return ok

def stage_c_baseline_check():
    """compute metrics on existing logs, decide verdict, record to memory."""
    try:
        from test_runner import load_records, compute_metrics
        from decision_engine import decide
    except Exception as e:
        _log("C_baseline", {"ok": False, "error": str(e)})
        return
    j = RT / "paper_journal.jsonl"
    l = RT / "paper_losses.jsonl"
    recs = load_records(j, l)
    if not recs:
        _log("C_baseline", {"ok": True, "note": "no logs"})
        print("[loop] C_baseline: no logs", flush=True)
        return
    m = compute_metrics(recs)
    verdict = decide(m)
    _log("C_baseline", {"ok": True, "metrics": m, "verdict": verdict})
    print(f"[loop] C_baseline: verdict={verdict['verdict']} reason={verdict.get('reason')}", flush=True)

    # record to memory (only if not already recorded for this session)
    session = os.environ.get("LOOP_SESSION", "s205-auto")
    strategy = "corr_pairs_taker"  # current logs = baseline
    memory.record_strategy_verdict(
        strategy, verdict["verdict"], session,
        evidence=f"auto baseline {m['trades']} trades",
        reason=verdict.get("reason", ""))
    memory.record_lesson(session, "auto-baseline",
        f"autonomous baseline check - {verdict['verdict']}",
        f"auto-detected: trades={m['trades']}, win_rate={m['win_rate']}, avg_bps={m['avg_bps']}, sharpe={m['sharpe']}, max_dd={m['max_dd_pct']}%",
        "test_runner + decision_engine computed from real logs, no LLM in verdict",
        "deterministic verdict from metrics is the only truth source; LLM extracts, python decides",
        f"autonomous_loop.py stage C at {time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())}")

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("all", "a"): stage_a_reader(max_n=3)
    if mode in ("all", "b"): stage_b_extract(max_n=3)
    if mode in ("all", "c"): stage_c_baseline_check()
    _log("done", {"mode": mode})
    print(f"[loop] done mode={mode}", flush=True)

if __name__ == "__main__":
    main()
