"""learning_rules.py — parses LEARNING_RULES.md (s179)."""
import re
from pathlib import Path
MD = Path(__file__).resolve().parent.parent / "self/curator/LEARNING_RULES.md"
def _sec(t, n):
    m = re.search(rf"^##\s+{n}\.(.*?)(?=^##\s+\d+\.|\Z)", t, re.M | re.S)
    if not m: return ""
    b = m.group(1)
    return b.split("\n", 1)[1] if "\n" in b else b
def _words(b):
    out = []
    for x in re.split(r"[,\n\u00b7/]", b):
        x = x.strip().strip(".")
        if not x: continue
        if " " in x: x = x.split()[0]
        x = x.split("-")[0].strip().lower()
        if len(x) > 2 and x.isalpha() and x not in out: out.append(x)
    return out
def _br(b, k):
    m = re.search(rf"{k}\s*\u2208\s*\{{([^}}]+)\}}", b)
    return [x.strip().lower() for x in m.group(1).split(",")] if m else []
def load_rules(p=None):
    """Parse LEARNING_RULES.md sections 2/3/4.

    s201: supports BOTH numeric (s179: `confidence < 0.6`) and
    categorical (s194+: `confidence \u2208 {low, medium}`) §4 formats.
    """
    try: t = (Path(p) if p else MD).read_text(encoding="utf-8")
    except Exception: return None
    a, r, d = _sec(t, 2), _sec(t, 3), _sec(t, 4)
    if not (a and r and d): return None
    # Numeric boundary: `confidence < 0.6`
    m_num = re.search(r"confidence\s*<\s*([\d.]+)", d)
    # Categorical set:   `confidence \u2208 {low, medium, ...}`
    m_cat = re.search(r"confidence\s*\u2208\s*\{([^}]+)\}", d)
    # Strip ALL confidence-lines before extracting defer_words
    d_clean = re.sub(
        r"confidence\s*(?:<[^\n\u00b7]*|\u2208\s*\{[^}]+\}[^\n\u00b7]*|==[^\n\u00b7]*)",
        "", d)
    if m_num:
        conf = float(m_num.group(1))
    elif m_cat:
        cats = [x.strip().lower() for x in m_cat.group(1).split(",")]
        # low/medium => defer => boundary 0.6 (back-compat for s179 test)
        conf = 0.6 if ("low" in cats or "medium" in cats) else None
    else:
        conf = None
    return {"apply_techniques": _br(a, "technique"),
            "apply_fields": _br(a, "field"),
            "reject_words": _words(r), "defer_words": _words(d_clean),
            "defer_confidence": conf}
