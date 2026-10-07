#!/usr/bin/env python3
"""Grounding helper (s125 / F8).

Обёртка над llm() + verify_answer().
Все LLM-выходы, попадающие в память/решения, должны проходить через ask_and_verify.
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HEALERS = ROOT / "self" / "healers"
JOURNAL = HEALERS / "grounding_audit.jsonl"


def _journal(rec):
    try:
        HEALERS.mkdir(parents=True, exist_ok=True)
        with JOURNAL.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def ask_and_verify(system, user, sources=None, want_json=False,
                   limit=60, task="text", verify=True, tag="default"):
    """Вызвать LLM и сразу проверить ответ на grounded.

    Возвращает dict:
      {"answer": str|None, "verdict": "grounded|partial|hallucinated|skip",
       "count_issues": int, "issues": list, "tag": str}
    """
    out = {"answer": None, "verdict": "skip",
           "count_issues": 0, "issues": [], "tag": tag}
    try:
        from llm_call import llm
        answer = llm(system, user, want_json=want_json, limit=limit, task=task)
    except Exception as e:
        out["issues"].append({"kind": "llm_call_fail", "err": type(e).__name__ + ": " + str(e)[:120]})
        out["verdict"] = "skip"
        _journal({"ts": int(time.time()), "tag": tag, "verdict": "skip",
                  "reason": "llm_call_fail", "err": str(e)[:120]})
        return out

    out["answer"] = answer
    if not answer:
        out["verdict"] = "skip"
        _journal({"ts": int(time.time()), "tag": tag, "verdict": "skip",
                  "reason": "empty_answer"})
        return out

    if not verify:
        out["verdict"] = "unchecked"
        _journal({"ts": int(time.time()), "tag": tag, "verdict": "unchecked"})
        return out

    try:
        from verify import verify_answer
        res = verify_answer(answer, search_chunks=sources or [])
        out["verdict"] = res.get("verdict", "skip")
        out["count_issues"] = res.get("count_issues", 0)
        out["issues"] = res.get("issues", [])[:5]
    except Exception as e:
        out["verdict"] = "skip"
        out["issues"].append({"kind": "verify_fail", "err": type(e).__name__ + ": " + str(e)[:120]})

    _journal({"ts": int(time.time()), "tag": tag, "verdict": out["verdict"],
              "count_issues": out["count_issues"]})
    return out


def selftest():
    assert ROOT.exists()
    assert (ROOT / "verify.py").exists()
    assert (ROOT / "llm_call.py").exists()
    print("grounding selftest: ok")


def main():
    if len(sys.argv) < 2 or sys.argv[1] == "--selftest":
        selftest()
        return 0
    if sys.argv[1] == "--report":
        n = 0
        if JOURNAL.exists():
            n = sum(1 for _ in JOURNAL.read_text(encoding="utf-8").splitlines() if _)
        print("grounding: journal entries=" + str(n))
        return 0
    print("usage: python3 grounding.py --selftest | --report")
    return 2


if __name__ == "__main__":
    sys.exit(main())
