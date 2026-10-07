"""session_meta.py — thin facade over session_reader (s149).

s149: extraction. Все парсеры STATE.md / _features.json перенесены в
session_reader.py (независимый модуль, только stdlib). Этот файл —
тонкий реэкспорт для обратной совместимости с 21 импортёром.

Fallback: если session_reader недоступен (удалён / битый / циклический
импорт) — фасад сам возвращает sentinel "unknown" (s148-r6: fallback
не может быть функцией из модуля, который упал — держим его локально).
"""
from __future__ import annotations

import re as _re

_RE_SNNN = _re.compile(r"^s\d+$")
ROOT = STATE = FEATURES = None

try:
    from session_reader import current as _reader_current  # noqa: F401
    try:
        from session_reader import ROOT, STATE, FEATURES, _RE_SNNN  # noqa: F401
    except Exception:
        pass  # константы не критичны; API — только current()

    def current() -> str:
        return _reader_current()
except Exception:
    def current() -> str:
        return "unknown"


def _selftest() -> None:
    v = current()
    print("session_meta.current() =", v)


if __name__ == "__main__":
    _selftest()
