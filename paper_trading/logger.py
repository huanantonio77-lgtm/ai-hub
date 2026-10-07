"""logger.py - extended paper-trading logging. Append-only."""
import json, time
from pathlib import Path
R = Path("/Users/salamkhalikov/Desktop/ai-hub/.runtime")

def _app(fn, rec):
    with open(R / fn, "a") as f:
        f.write(json.dumps({**rec, "ts": time.time()}) + "\n")

def trade(**kw):   _app("paper_journal.jsonl", kw)
def reject(**kw):  _app("paper_rejections.jsonl", kw)
def corrs(**kw):   _app("paper_corrs.jsonl", kw)
def near(**kw):    _app("paper_nearmiss.jsonl", kw)
def insight(**kw): _app("paper_insights.jsonl", kw)
def research(**kw): _app("research_queue.jsonl", kw)
