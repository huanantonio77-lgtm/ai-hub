"""session_reader.py — независимый парсер STATE.md / _features.json.

s149: extracted from session_meta.current() to break fallback duplication
(s148-r6: fallback не может жить в модуле, который может упасть импортом).

Reads STATE.md directly (primary), falls back to _features.json, returns
sentinel "unknown" on total failure.

Design (s148-r6):
  - only stdlib imports (json, re, pathlib)
  - NO project imports — neither session_meta nor anything else
  - session_meta imports this module as a thin facade, never the reverse
  - pilots may import session_reader directly
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "self" / "curator" / "STATE.md"
FEATURES = ROOT / "strategy" / "_features.json"
_RE_SNNN = re.compile(r"^s\d+$")


def current() -> str:
    """Return current session id ('sNNN') or 'unknown' on total failure."""
    # 1) primary: STATE.md -> "**Текущая сессия:** sNNN."
    try:
        if STATE.exists():
            for line in STATE.read_text(encoding="utf-8").splitlines():
                if "Текущая сессия" in line:
                    m = re.search(r"\bs(\d+)\b", line)
                    if m:
                        return f"s{m.group(1)}"
    except Exception:
        pass
    # 2) fallback: _features.json
    try:
        d = json.loads(FEATURES.read_text(encoding="utf-8"))
        v = d.get("session") if isinstance(d, dict) else None
        if isinstance(v, str) and _RE_SNNN.match(v):
            return v
    except Exception:
        pass
    return "unknown"


def _selftest() -> None:
    v = current()
    assert v == "unknown" or _RE_SNNN.match(v), f"bad format: {v!r}"
    print("session_reader.current() =", v)


if __name__ == "__main__":
    _selftest()
