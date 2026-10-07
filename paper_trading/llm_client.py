"""llm_client.py - LLM as a TOOL (parse/codegen/report), not decision-maker.

Uses local ollama. All decisions are made by decision_engine.py (pure python).
"""
import os, json, time, subprocess
from pathlib import Path

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = os.environ.get("PAPER_LLM_MODEL", "qwen2.5-coder:3b")
RT = Path("/Users/salamkhalikov/Desktop/ai-hub/.runtime")
CALLS_LOG = RT / "paper_llm_calls.jsonl"
THROTTLE_SEC = int(os.environ.get("PAPER_LLM_THROTTLE", "60"))

def _throttle_ok():
    if not CALLS_LOG.exists(): return True
    try:
        lines = CALLS_LOG.read_text().strip().split("\n")
        last = json.loads(lines[-1]) if lines and lines[-1] else {}
        return (time.time() - last.get("ts", 0)) > THROTTLE_SEC
    except: return True

def _log_call(purpose, model, latency, ok):
    RT.mkdir(parents=True, exist_ok=True)
    with open(CALLS_LOG, "a") as f:
        f.write(json.dumps({
            "ts": time.time(), "purpose": purpose,
            "model": model, "latency_sec": round(latency, 2), "ok": ok
        }) + "\n")

def ask(prompt, model=DEFAULT_MODEL, purpose="general", timeout=120):
    """Raw text ask. Returns '' on failure."""
    if not _throttle_ok():
        print(f"[llm] throttled (last call < {THROTTLE_SEC}s)", flush=True)
        return ""
    body = {"model": model, "prompt": prompt, "stream": False}
    t0 = time.time()
    try:
        r = subprocess.run(
            ["curl", "-s", "-X", "POST", OLLAMA_URL,
             "-H", "Content-Type: application/json",
             "-d", json.dumps(body)],
            capture_output=True, text=True, timeout=timeout)
        latency = time.time() - t0
        if r.returncode != 0:
            _log_call(purpose, model, latency, False)
            print(f"[llm] curl failed: {r.stderr[:200]}", flush=True)
            return ""
        data = json.loads(r.stdout)
        _log_call(purpose, model, latency, True)
        return data.get("response", "")
    except Exception as e:
        _log_call(purpose, model, time.time() - t0, False)
        print(f"[llm] error: {e}", flush=True)
        return ""

def ask_json(prompt, model=DEFAULT_MODEL, purpose="json", timeout=120, retries=2):
    """Ask and parse JSON. Returns dict or None."""
    for attempt in range(retries):
        raw = ask(prompt, model=model, purpose=purpose, timeout=timeout)
        if not raw: continue
        # find first { ... last }
        i, j = raw.find("{"), raw.rfind("}")
        if i >= 0 and j > i:
            try: return json.loads(raw[i:j+1])
            except Exception as e:
                print(f"[llm] json parse failed (attempt {attempt+1}): {e}", flush=True)
    return None

if __name__ == "__main__":
    print("[llm_client] smoke test")
    print("model:", DEFAULT_MODEL)
    out = ask("Reply with one word: OK", purpose="smoke", timeout=30)
    print("reply:", out.strip()[:100])
    j = ask_json('Return JSON: {"x": 1, "y": "test"}', purpose="smoke-json", timeout=30)
    print("json:", j)
