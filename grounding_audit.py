#!/usr/bin/env python3
"""grounding_audit — лекарь (s125 / F8, часть C).

Пост-фактум аудит LLM-выходов: сколько grounded / partial / hallucinated.
Детектор без правды = dead sensor (правило s119) — поэтому источник: journal grounding.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HEALERS = ROOT / "self" / "healers"
GRD_JOURNAL = HEALERS / "grounding_audit.jsonl"
AUDIT_JOURNAL = HEALERS / "grounding_audit_healer.jsonl"
LOCK = ROOT / "self" / "_locks" / "grounding_audit.ts"


def _read_journal():
    if not GRD_JOURNAL.exists():
        return []
    recs = []
    for line in GRD_JOURNAL.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            recs.append(json.loads(line))
        except Exception:
            pass
    return recs


def _write_healer(rec):
    try:
        HEALERS.mkdir(parents=True, exist_ok=True)
        with AUDIT_JOURNAL.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def report():
    recs = _read_journal()
    total = len(recs)
    by_verdict = {}
    for r in recs:
        v = r.get("verdict", "unknown")
        by_verdict[v] = by_verdict.get(v, 0) + 1
    bad = by_verdict.get("hallucinated", 0) + by_verdict.get("partial", 0)
    print("grounding_audit: total=" + str(total) +
          " grounded=" + str(by_verdict.get("grounded", 0)) +
          " partial=" + str(by_verdict.get("partial", 0)) +
          " hallucinated=" + str(by_verdict.get("hallucinated", 0)) +
          " skip=" + str(by_verdict.get("skip", 0)) +
          " unchecked=" + str(by_verdict.get("unchecked", 0)))
    return {"total": total, "bad": bad, "by_verdict": by_verdict}


def run():
    r = report()
    if r["bad"] > 0:
        _write_healer({"ts": int(time.time()), "action": "finding",
                       "total": r["total"], "bad": r["bad"],
                       "by_verdict": r["by_verdict"]})
        print("[grounding_audit] findings=" + str(r["bad"]))
    else:
        _write_healer({"ts": int(time.time()), "action": "ok",
                       "total": r["total"]})
    try:
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        LOCK.write_text(str(int(time.time())), encoding="utf-8")
    except Exception:
        pass
    return 0


def selftest():
    assert ROOT.exists()
    assert GRD_JOURNAL.parent == HEALERS
    print("grounding_audit selftest: ok")


def main():
    ap = argparse.ArgumentParser(prog="grounding_audit")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--report", action="store_true")
    g.add_argument("--run", action="store_true")
    g.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.run:
        return run()
    if args.selftest:
        return selftest()
    return 0 if report() else 0


if __name__ == "__main__":
    sys.exit(main())
