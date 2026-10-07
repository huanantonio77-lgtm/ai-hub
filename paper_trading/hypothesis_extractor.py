"""hypothesis_extractor.py - LLM extracts testable hypothesis from paper text.

LLM ROLE: extract only. Decisions made by decision_engine.py (pure python).
Output: paper_hypotheses_auto.jsonl
"""
import sys, json, time
from pathlib import Path
import llm_client

RT = Path("/Users/salamkhalikov/Desktop/ai-hub/.runtime")
EX = RT / "paper_extracts.jsonl"
OUT = RT / "paper_hypotheses_auto.jsonl"
MODEL = "qwen2.5-coder:3b"

PROMPT_TEMPLATE = """You are a data extractor. Read this article and extract ONE testable trading hypothesis.

STRICT RULES:
- Do NOT recommend anything. Only extract what the article claims.
- If the article does not contain a testable hypothesis, return {{"skip": true}}.
- Quote thresholds/parameters exactly as stated in the article.
- Output MUST be valid JSON, no prose.

Return ONLY this JSON structure:
{{
  "hypothesis": "one-sentence testable claim",
  "metric": "metric name (e.g. win_rate, sharpe, avg_bps)",
  "threshold": "numeric threshold if mentioned, else null",
  "test_method": "concrete method to test (e.g. maker-only run 30min)",
  "assets": ["asset classes mentioned"],
  "venues": ["venues mentioned"],
  "claimed_result": "what article claims (e.g. save 3x fees), or null"
}}

ARTICLE TEXT:
{text}
"""

def extract_one(rec):
    text = rec.get("abstract") or rec.get("text_head", "")
    if not text or len(text) < 200:
        return {"skip": True, "reason": "text_too_short"}
    prompt = PROMPT_TEMPLATE.format(text=text[:4000])
    j = llm_client.ask_json(prompt, model=MODEL, purpose="hypothesis_extract", timeout=180)
    if not j:
        return {"skip": True, "reason": "llm_no_json"}
    if j.get("skip"):
        return {"skip": True, "reason": "llm_skip"}
    # ensure required fields
    if not j.get("hypothesis") or not j.get("test_method"):
        return {"skip": True, "reason": "missing_fields"}
    j["source_url"] = rec.get("url", "")
    j["source_title"] = rec.get("title", "")
    j["source_domain"] = rec.get("domain", "")
    j["qid"] = rec.get("qid", "")
    j["topic"] = rec.get("topic", "")
    j["stage"] = "hypothesis"
    return j

def main():
    max_n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    if not EX.exists():
        print(f"[extract] no extracts file: {EX}"); return
    lines = [l for l in EX.read_text().strip().split("\n") if l]
    recs = []
    seen = set()
    for l in lines:
        try: r = json.loads(l)
        except: continue
        u = r.get("url", "")
        if u in seen: continue
        seen.add(u); recs.append(r)
        if len(recs) >= max_n: break

    print(f"[extract] processing {len(recs)} extracts (model={MODEL})", flush=True)
    ok = 0; skips = 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "a") as f:
        for i, r in enumerate(recs):
            print(f"[extract] {i+1}/{len(recs)} {r.get('domain','')[:30]}", flush=True)
            res = extract_one(r)
            if res.get("skip"):
                skips += 1
                print(f"[extract]   SKIP: {res.get('reason')}", flush=True)
            else:
                ok += 1
                f.write(json.dumps(res, ensure_ascii=False) + "\n")
                print(f"[extract]   OK: {res['hypothesis'][:100]}", flush=True)
            time.sleep(2)
    print(f"[extract] done: ok={ok} skip={skips}", flush=True)

if __name__ == "__main__":
    main()
