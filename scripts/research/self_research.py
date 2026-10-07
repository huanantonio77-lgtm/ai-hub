#!/usr/bin/env python3
"""self_research.py (s180) — autonomous self-research driver."""
import argparse, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from scripts.research import extract as E

QUERIES = [
    ("feedback-loop", "self-refine code generation large language models"),
    ("self-blindness", "runtime self-monitoring autonomous software agents"),
    ("auto-move", "safe code deployment autonomous systems staging"),
    ("telemetry", "observability autonomous agents telemetry"),
    ("self-healing", "self-healing software autonomic computing systems"),
]
REPORT = ROOT / "self" / "curator" / "SELF_RESEARCH_REPORT.md"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--limit", type=int, default=3)
    ap.add_argument("--model", default="qwen2.5-coder:3b")
    a = ap.parse_args()
    if not a.run:
        print("dry; pass --run"); return 0
    L = ["# SELF_RESEARCH_REPORT (s180)", "",
         "model: " + a.model + " limit: " + str(a.limit), ""]
    t0 = time.time(); total = 0
    for tag, q in QUERIES:
        L.append("## " + tag); L.append("- q: " + q)
        try:
            n = E.run_self_problem(q, limit=a.limit, model=a.model)
            total += n; L.append("- proposals: " + str(n))
        except Exception as e:
            L.append("- ERROR: " + repr(e))
        L.append("")
    dt = round(time.time() - t0, 1)
    L += ["---", "total: " + str(total), "elapsed: " + str(dt) + "s"]
    REPORT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("report: " + str(REPORT)); print("total: " + str(total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
