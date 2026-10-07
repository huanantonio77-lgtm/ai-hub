#!/usr/bin/env python3
# dlp_guard.py (s122) -- Safety Layer 9 v2 pre-flight guard.
#
# Wraps dlp_scan._scan_text/_redact_text. Called from llm_call._openai_style
# right before returning the model response. Sanitizes text before it can
# ever reach any log or file.
#
# Rights: record_finding.
# Cannot: mutate_core, delete_file, write_files, set_cooldown.
#
# Journal: self/healers/dlp.jsonl (via dlp.py convention)
# Not CORE. Not sensitive. Fail-open by design.

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AUTONOMY = ROOT / "self" / "autonomy.jsonl"
HEALER_JOURNAL = ROOT / "self" / "healers" / "dlp.jsonl"

# Make sure dlp_scan is importable regardless of cwd or launch context.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ts():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _session():
    try:
        import session_meta as _sm
        return _sm.current()
    except Exception:
        return "unknown"


def _append(path, rec):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def guard(text):
    """Return (sanitized_text, hits_list). Fail-open on any error."""
    if not isinstance(text, str) or not text:
        return text, []
    try:
        from dlp_scan import _scan_text, _redact_text
    except Exception:
        return text, []
    try:
        hits = _scan_text(text, emails=False)
    except Exception:
        return text, []
    if not hits:
        return text, []
    try:
        sanitized, n = _redact_text(text, hits)
    except Exception:
        return text, []
    kinds = {}
    for h in hits:
        k = h.get("kind") or "unknown"
        kinds[k] = kinds.get(k, 0) + 1
    summary = ",".join(k + "=" + str(v) for k, v in sorted(kinds.items()))
    note = "preflight_redact n=" + str(n) + " kinds=" + summary
    _append(HEALER_JOURNAL, {
        "ts": _ts(), "session": _session(), "healer": "dlp",
        "diagnosis": "dirty", "action": "preflight_redact",
        "effect": 1, "outcome": "redacted", "note": note,
    })
    _append(AUTONOMY, {
        "ts": _ts(), "session": _session(),
        "action": "dlp_preflight_hit",
        "note": note, "effect": 1,
    })
    return sanitized, hits


if __name__ == "__main__":
    t1, h1 = guard("hello world")
    print("clean:", repr(t1), "hits=", len(h1))
    t2, h2 = guard("api_key = " + "AIza" + "B" * 30)
    print("secret_google:", repr(t2), "hits=", len(h2))
    t3, h3 = guard("token = " + "sk-ant-" + "C" * 40)
    print("secret_anthropic:", repr(t3), "hits=", len(h3))