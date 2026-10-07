# gepa/hook.py - GEPA v0: orchestrator bridge.
# Safe wrapper: never raises. Returns empty string on any error.

from __future__ import annotations
import hashlib, sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _repair_task_key(task):
    try:
        from memory import mem as _mem
        na = _mem.get("next_actions", []) or []
        for i, t in enumerate(na, 1):
            if t == task:
                h = hashlib.md5(t.encode("utf-8")).hexdigest()[:8]
                return "task_" + format(i, "02d") + "_" + h
    except Exception:
        pass
    return ""


def build_block_for(task):
    if not isinstance(task, str) or not task.strip().startswith("[repair:"):
        return ""
    try:
        from gepa import registry as _reg
        key = _repair_task_key(task)
        text = _reg.gepa_prompt_block(task, key)
        if text:
            print("-> [GEPA] block injected chars=" + str(len(text)) + " key=" + (key or "?"))
            return chr(10) + chr(10) + text + chr(10) + chr(10)
        print("-> [GEPA] empty block key=" + (key or "?"))
        return ""
    except Exception as e:
        print("-> [GEPA] skip: " + str(e)[:120])
        return ""


if __name__ == "__main__":
    print("hook: repair -> ", repr(build_block_for("[repair:test] foo")[:80]))
    print("hook: normal -> ", repr(build_block_for("напиши статью")))

