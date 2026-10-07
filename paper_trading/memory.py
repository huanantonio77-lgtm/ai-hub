"""memory.py - live trading memory API.

Usage from any script:
    from memory import record_hypothesis_status, record_strategy_verdict, record_lesson, record_test_result

All functions: append-only + update machine-readable state.
"""
import os, time, json
from pathlib import Path

R = Path("/Users/salamkhalikov/Desktop/ai-hub")
RT = R / ".runtime"
PT = R / "paper_trading"

REG = PT / "strategy_registry.json"
HYP = PT / "hypothesis_status.jsonl"
LIVE_LESSONS = R / "knowledge" / "trading_lessons_live.md"
TESTS = RT / "paper_test_results.jsonl"

def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())

def _load_registry():
    if REG.exists():
        try: return json.loads(REG.read_text())
        except: pass
    return {"version": 1, "session_updated": "unknown", "strategies": []}

def _save_registry(d):
    t = REG.with_suffix(".tmp")
    t.write_text(json.dumps(d, indent=2, ensure_ascii=False))
    os.replace(t, REG)

def _append_jsonl(p, rec):
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(json.dumps({**rec, "ts": time.time()}, ensure_ascii=False) + "\n")

def _append_md(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(text)

def record_strategy_verdict(name, verdict, session, evidence="", reason=""):
    """Update verdict for strategy in registry. Append-only in registry."""
    d = _load_registry()
    d["session_updated"] = session
    found = False
    for s in d.get("strategies", []):
        if s.get("name") == name:
            s["verdict"] = verdict
            s["verdict_session"] = session
            s["verdict_evidence"] = evidence
            s["verdict_reason"] = reason
            found = True
            break
    if not found:
        d.setdefault("strategies", []).append({
            "name": name, "verdict": verdict, "verdict_session": session,
            "verdict_evidence": evidence, "verdict_reason": reason,
        })
    _save_registry(d)
    print(f"[memory] strategy {name} -> {verdict} ({session})", flush=True)

def record_hypothesis_status(hid, status, session, note=""):
    """Append status change for hypothesis. Status: pending/testing/confirmed/rejected."""
    _append_jsonl(HYP, {"id": hid, "status": status, "session": session, "note": note})
    print(f"[memory] hypothesis {hid} -> {status} ({session})", flush=True)

def record_test_result(hid, strategy, result, session):
    """Append test result. result dict: {metric: value}."""
    _append_jsonl(TESTS, {"hid": hid, "strategy": strategy, "session": session, "result": result})
    print(f"[memory] test {hid}/{strategy} recorded", flush=True)

def record_lesson(session, rid, title, what, fix, generalize, evidence):
    """Append live lesson in the same format as knowledge/lessons.md."""
    txt = (
        f"\n## {session}-{rid} — {title}\n\n"
        f"Что: {what}\n"
        f"Фикс: {fix}\n"
        f"Обобщение: {generalize}\n"
        f"Проверено: {evidence}\n"
    )
    _append_md(LIVE_LESSONS, txt)
    print(f"[memory] lesson {session}-{rid} appended", flush=True)

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: python3 memory.py <cmd> [args...]"); raise SystemExit(1)
    cmd = sys.argv[1]
    if cmd == "test-runner":
        print("[memory] helper: use functions directly from your script"); raise SystemExit(0)
    print(f"[memory] unknown command: {cmd}")
