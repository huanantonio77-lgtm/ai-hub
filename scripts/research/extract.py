#!/usr/bin/env python3
"""extract.py — LLM извлекает идеи из abstract (s176-P4)."""
import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
INDEX = ROOT / "knowledge" / "research_index.json"
PROPOSALS = ROOT / "self" / "curator" / "PROPOSALS.jsonl"
OLLAMA = "http://127.0.0.1:11434/api/generate"
DEFAULT_MODEL = "qwen2.5-coder:1.5b"


def _now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(
        timespec="seconds")


PROMPT_TMPL = """You are an assistant for ai-hub project.
Read the scientific paper abstract below.

Answer STRICTLY in 3 lines:
TECHNIQUE: one technique from the paper (5-15 words, English)
APPLICABILITY: YES or NO (applicable to our project?)
SUGGESTION: if YES, what to change (one sentence, English)

Abstract:
{abstract}
"""





def _track(status, tokens_in=0, tokens_out=0):
    try:
        import sys as _s
        import os as _os
        root = _os.path.dirname(_os.path.dirname(
            _os.path.dirname(_os.path.abspath(__file__))))
        if str(root) not in _s.path:
            _s.path.insert(0, str(root))
        import limits as _lim
        _lim.record_call("ollama", status,
                         tokens_in=tokens_in, tokens_out=tokens_out)
    except Exception:
        pass


def _ollama(prompt, model=DEFAULT_MODEL, timeout=60):
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 200},
    }).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA, data=body,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        pin = data.get("prompt_eval_count") or 0
        pout = data.get("eval_count") or 0
        _track("ok", tokens_in=int(pin), tokens_out=int(pout))
        return data.get("response", "").strip()
    except urllib.error.HTTPError as e:
        _track("429" if e.code == 429 else "error")
        return "ERROR: HTTP " + str(e.code)
    except Exception as e:
        _track("error")
        return "ERROR: " + type(e).__name__ + ": " + str(e)[:150]


def parse_response(text):
    out = {"technique": "", "applicable": False, "suggestion": ""}
    if not text or text.startswith("ERROR:"):
        out["error"] = text[:200] if text else "empty"
        return out
    for line in text.splitlines():
        ln = line.strip()
        up = ln.upper()
        if up.startswith("TECHNIQUE:"):
            out["technique"] = ln.split(":", 1)[1].strip()
        elif up.startswith("APPLICABILITY:"):
            v = ln.split(":", 1)[1].strip().upper()
            out["applicable"] = v.startswith("YES")
        elif up.startswith("SUGGESTION:"):
            out["suggestion"] = ln.split(":", 1)[1].strip()
    return out


def process_one(item, model=DEFAULT_MODEL):
    if item.get("extracted_ideas"):
        return item, None
    abstract = (item.get("abstract") or "").strip()
    if not abstract:
        item["extracted_ideas"] = ["(no abstract)"]
        item["ts_indexed"] = _now_iso()
        return item, None
    text = _ollama(PROMPT_TMPL.format(abstract=abstract[:1800]),
                   model=model)
    parsed = parse_response(text)
    idea = parsed.get("technique") or "(no technique)"
    item["extracted_ideas"] = [idea]
    item["ts_indexed"] = _now_iso()
    item["_parse_raw"] = text[:400]
    prop = None
    if parsed.get("applicable") and parsed.get("suggestion"):
        prop = {
            "ts": _now_iso(),
            "paper_id": item.get("id"),
            "title": item.get("title", "")[:160],
            "technique": idea,
            "target": "unspecified",
            "suggestion": parsed["suggestion"][:300],
            "confidence": "low",
            "status": "pending",
        }
    return item, prop


def run_all(limit=5, model=DEFAULT_MODEL, dry=False):
    if not INDEX.exists():
        print("extract: no research_index.json")
        return 0, 0
    data = json.loads(INDEX.read_text(encoding="utf-8"))
    items = data.get("items", [])
    processed = 0
    proposed = 0
    for it in items:
        if processed >= limit:
            break
        if it.get("extracted_ideas"):
            continue
        _it, prop = process_one(it, model=model)
        if _it is not it:
            it.clear()
            it.update(_it)
        processed += 1
        if prop:
            proposed += 1
            if not dry:
                PROPOSALS.parent.mkdir(parents=True, exist_ok=True)
                with PROPOSALS.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(prop, ensure_ascii=False) + "\n")
            print("  +PROPOSAL:", prop["suggestion"][:90])
        else:
            print("  skip:", (it.get("title") or "")[:70])
    if not dry:
        data["count"] = len(items)
        INDEX.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    return processed, proposed





SELF_PROPOSALS = ROOT / "self" / "curator" / "SELF_PROPOSALS.jsonl"

FORMULATE_PROMPT = """You convert an AI agent's problem into a SHORT academic search query.

Rules:
- Output ONLY the query text: English, 5-10 words, one line, no quotes.
- Do NOT mention any database name (OpenAlex, Crossref, arXiv, OpenAIRE, Google, Brave).
- Do NOT add prefixes like "Search for", "Query:" or "OpenAlex:".
- REFORMULATE the problem as scientific topic keywords. Do NOT copy the problem verbatim.

Problem: {problem}
Query:
"""


SOURCES = ("openalex", "crossref", "arxiv", "openaire", "websearch", "pubmed", "semanticscholar")


def _norm_doi(doi):
    if not doi:
        return None
    d = str(doi).lower().strip()
    for pfx in ("https://doi.org/", "http://doi.org/", "doi:"):
        if d.startswith(pfx):
            d = d[len(pfx):]
    return d or None


def fetch_from_sources(query, limit=5, sources=SOURCES):
    import os as _os, importlib
    root = _os.path.dirname(_os.path.dirname(_os.path.dirname(
        _os.path.abspath(__file__))))
    if root not in sys.path:
        sys.path.insert(0, root)
    callers = {
        "openalex": lambda m: m.search_works(query, per_page=limit),
        "crossref": lambda m: m.search_works(query, rows=limit),
        "arxiv":    lambda m: m.search_works(query, max_results=limit),
        "openaire": lambda m: m.search_works(query, size=limit),
        "websearch": lambda m: m.search_works(query, max_results=limit),
        "pubmed": lambda m: m.search_works(query, max_results=limit),
        "semanticscholar": lambda m: m.search_works(query, max_results=limit),
    }
    seen_d, seen_t, merged, per_src = set(), set(), [], {}
    for s in sources:
        fn = callers.get(s)
        if not fn:
            continue
        try:
            mod = importlib.import_module("scripts.research." + s + "_client")
            items = fn(mod) or []
        except Exception as e:
            print("fetch: %s failed: %s" % (s, e))
            per_src[s] = 0
            continue
        n = 0
        for it in items:
            d = _norm_doi(it.get("doi"))
            t = (it.get("title") or "").strip().lower()
            if (d and d in seen_d) or (t and t in seen_t):
                continue
            if d:
                seen_d.add(d)
            if t:
                seen_t.add(t)
            merged.append(it)
            n += 1
        per_src[s] = n
    print("fetch: sources=%s per_src=%s merged=%d"
          % (list(sources), per_src, len(merged)))
    return merged


def formulate_query(problem, model=DEFAULT_MODEL):
    text = _ollama(FORMULATE_PROMPT.format(problem=problem), model=model)
    if not text or text.startswith("ERROR:"):
        return problem[:120]
    q = text.strip().strip('"').strip("'").splitlines()[0].strip()
    for pfx in (
        "Query:", "query:", "OpenAlex:", "Search for:", "search for:",
        "Search for ", "search for ", "Search:", "search:",
    ):
        if q.startswith(pfx): q = q[len(pfx):].strip()
    q = q.strip().strip('"').strip("'").strip()
    return q[:200]

def enrich_with_unpaywall(items, limit=3):
    """Enrich up to `limit` items that have DOI with OA status via Unpaywall."""
    try:
        from unpaywall_client import lookup_doi
    except Exception as e:
        print("unpaywall: import failed:", e); return items
    n = 0
    for it in items:
        if n >= limit: break
        doi = _norm_doi(it.get("doi") or "")
        if not doi: continue
        try:
            data = lookup_doi(doi)
        except Exception as e:
            print("unpaywall: lookup failed", doi, ":", e); continue
        if data:
            for k in ("is_oa", "oa_url", "oa_status"):
                if k in data: it[k] = data[k]
            n += 1
    print("unpaywall: enriched=" + str(n))
    return items


def run_self_problem(problem, limit=5, model=DEFAULT_MODEL, dry=False, out_path=None):
    query = formulate_query(problem, model=model)
    print("query:", query)
    import os as _os
    root = _os.path.dirname(_os.path.dirname(_os.path.dirname(
        _os.path.abspath(__file__))))
    if root not in sys.path:
        sys.path.insert(0, root)
    items = fetch_from_sources(query, limit=limit)
    items = enrich_with_unpaywall(items)
    print("found:", len(items))
    proposed = 0
    for it in items[:limit]:
        it2, prop = process_one(it, model=model)
        if prop:
            prop["problem"] = problem[:300]
            prop["source_query"] = query
            proposed += 1
            if not dry:
                target = Path(out_path) if out_path else SELF_PROPOSALS
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(prop, ensure_ascii=False) + "\n")
            print("  +SELF-PROPOSAL:",
                  str(prop.get("technique", ""))[:60])
    return proposed


def main(argv=None):
    ap = argparse.ArgumentParser(description="LLM extract (s176)")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--limit", type=int, default=3)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--self-problem", default=None)
    args = ap.parse_args(argv)
    if args.stats:
        if not INDEX.exists():
            print("no index"); return 1
        d = json.loads(INDEX.read_text(encoding="utf-8"))
        items = d.get("items", [])
        done = sum(1 for x in items if x.get("extracted_ideas"))
        props = 0
        if PROPOSALS.exists():
            props = sum(1 for _ in PROPOSALS.open(encoding="utf-8"))
        print("items=" + str(len(items)) + " extracted=" + str(done)
              + " proposals=" + str(props))
        return 0
    if args.self_problem:
        n = run_self_problem(args.self_problem,
                              limit=args.limit,
                              model=args.model,
                              dry=args.dry)
        print("self-problem: proposals=" + str(n))
        return 0
    if not args.run:
        ap.print_help(); return 2
    t0 = time.monotonic()
    p, pr = run_all(limit=args.limit, model=args.model, dry=args.dry)
    dt = int(time.monotonic() - t0)
    print("extract: processed=" + str(p) + " proposals=" + str(pr)
          + " dry=" + str(args.dry) + " time=" + str(dt) + "s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
