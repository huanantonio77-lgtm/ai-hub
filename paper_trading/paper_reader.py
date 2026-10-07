"""paper_reader.py - fetch URL and extract clean text (no LLM)."""
import re, sys, json, time, urllib.request, ssl
from pathlib import Path
try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = ssl.create_default_context()


RT = Path("/Users/salamkhalikov/Desktop/ai-hub/.runtime")
EX = RT / "paper_extracts.jsonl"
UA = "Mozilla/5.0 (compatible; ai-hub-research/1.0)"

def fetch(url, timeout=20):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as r:
            return r.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"[reader] fetch fail {url[:60]}: {e}", flush=True)
        return ""

def clean_html(html):
    if not html: return ""
    # remove scripts/styles
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.S|re.I)
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.S|re.I)
    # strip tags
    txt = re.sub(r"<[^>]+>", " ", html)
    # decode entities
    for ent, ch in [("&nbsp;"," "),("&amp;","&"),("&lt;","<"),("&gt;",">"),
                    ("&quot;",'"'),("&#39;","'"),("&mdash;","—"),("&ndash;","–")]:
        txt = txt.replace(ent, ch)
    # collapse whitespace
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt

def extract_abstract(text):
    """Try to find abstract/summary section."""
    # arxiv abstract
    m = re.search(r"(?:Abstract|ABSTRACT)[\s:.\-—]+(.{200,3000}?)(?:Introduction|1\.|Keywords|$)",
                  text, flags=re.S)
    if m: return m.group(1).strip()[:2000]
    return text[:2000]

def read_one(rec):
    url = rec.get("url", "")
    html = fetch(url)
    if not html: return None
    text = clean_html(html)
    if len(text) < 200: return None
    return {
        "qid": rec.get("qid", ""),
        "topic": rec.get("topic", ""),
        "url": url,
        "domain": rec.get("domain", ""),
        "title": rec.get("title", ""),
        "text_len": len(text),
        "abstract": extract_abstract(text),
        "text_head": text[:3000],
        "stage": "extract",
    }

def main():
    inp = sys.argv[1] if len(sys.argv) > 1 else str(RT / "paper_research_findings.jsonl")
    max_n = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    p = Path(inp)
    if not p.exists():
        print(f"[reader] no input: {inp}"); return
    lines = [l for l in p.read_text().strip().split("\n") if l]
    seen = set(); recs = []
    for l in lines:
        try: r = json.loads(l)
        except: continue
        u = r.get("url", "")
        if u in seen: continue
        seen.add(u); recs.append(r)
        if len(recs) >= max_n: break
    print(f"[reader] processing {len(recs)} urls", flush=True)
    ok = 0
    RT.mkdir(parents=True, exist_ok=True)
    with open(EX, "a") as f:
        for r in recs:
            out = read_one(r)
            if out:
                f.write(json.dumps(out, ensure_ascii=False) + "\n")
                ok += 1
                print(f"[reader] OK {out['domain'][:30]} len={out['text_len']}", flush=True)
            time.sleep(1)  # polite
    print(f"[reader] done: {ok}/{len(recs)}", flush=True)

if __name__ == "__main__":
    main()
