"""research_agent.py - search loop for paper-trading research."""
import sys, os, time, json, signal
from pathlib import Path

R = Path("/Users/salamkhalikov/Desktop/ai-hub")
RT = R / ".runtime"
QT = R / "paper_trading" / "research_queries.json"
FD = RT / "paper_research_findings.jsonl"
ST = RT / "paper_research_state.json"
RUN = [True]

def stop(*_): RUN[0] = False

def load_queries():
    if not QT.exists(): return []
    return json.loads(QT.read_text()).get("queries", [])

def load_state():
    if ST.exists():
        try: return json.loads(ST.read_text())
        except: pass
    return {"q_idx": 0, "cycles": 0, "findings_total": 0}

def save_state(s):
    RT.mkdir(parents=True, exist_ok=True)
    t = ST.with_suffix(".tmp")
    t.write_text(json.dumps(s, indent=2))
    os.replace(t, ST)

def save_finding(rec):
    RT.mkdir(parents=True, exist_ok=True)
    with open(FD, "a") as f:
        f.write(json.dumps({**rec, "ts": time.time()}) + "\n")

PRIORITY_DOMAINS = [
    "arxiv.org", "ssrn.com", "github.com", "quant.stackexchange.com",
    "hyperliquid.xyz", "dydx.exchange", "jup.ag", "raydium.io",
    "meteora.ag", "orca.so", "scholar.google",
]

def is_good(domain, snippet_len):
    if snippet_len < 50: return False
    for d in PRIORITY_DOMAINS:
        if d in domain: return True
    return len(domain) > 0

def search_one(query_obj, max_results=8):
    try:
        from ddgs import DDGS
    except Exception as e:
        print(f"[research] ddgs unavailable: {e}", flush=True)
        return []
    qid = query_obj["id"]; q = query_obj["q"]
    try:
        with DDGS() as d:
            raw = list(d.text(q, max_results=max_results))
    except Exception as e:
        print(f"[research] {qid} failed: {e}", flush=True)
        return []
    out = []
    for r in raw:
        url = r.get("href", "")
        domain = url.split("/")[2] if "://" in url else ""
        snippet = r.get("body", "")
        if not is_good(domain, len(snippet)): continue
        out.append({
            "qid": qid, "topic": query_obj.get("topic", ""),
            "priority": query_obj.get("priority", "P2"),
            "query": q, "title": r.get("title", ""),
            "url": url, "domain": domain,
            "snippet": snippet[:500], "stage": "search",
        })
    return out

def cycle(state, queries):
    if not queries:
        print("[research] no queries", flush=True)
        return 0
    idx = state.get("q_idx", 0) % len(queries)
    qobj = queries[idx]
    findings = search_one(qobj, max_results=8)
    for f in findings: save_finding(f)
    state["q_idx"] = (idx + 1) % len(queries)
    state["cycles"] = state.get("cycles", 0) + 1
    state["findings_total"] = state.get("findings_total", 0) + len(findings)
    save_state(state)
    print(f"[research] c{state['cycles']} q={qobj['id']} topic={qobj['topic']} found={len(findings)} total={state['findings_total']}", flush=True)
    return len(findings)

def main():
    signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop)
    queries = load_queries(); state = load_state()
    print(f"[research] start: {len(queries)} q, from_idx={state.get('q_idx',0)}", flush=True)
    while RUN[0]:
        try: cycle(state, queries)
        except Exception as e: print(f"[research] err: {e}", flush=True)
        for _ in range(30):
            if not RUN[0]: break
            time.sleep(1)
    print("[research] stopped", flush=True)

if __name__ == "__main__":
    main()
