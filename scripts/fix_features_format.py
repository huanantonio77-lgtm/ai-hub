#!/usr/bin/env python3
"""Normalize _features.json entries that violate s103-0e
(blindness_audit must be dict with 6 keys for closed_in >= s103)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FEATURES = ROOT / "strategy" / "_features.json"
BA_KEYS = ["emission", "measurement", "actuation", "verification", "coverage", "meta"]


def session_num(s):
    if not isinstance(s, str) or not s.startswith("s"):
        return -1
    try:
        return int(s[1:].split("-")[0])
    except Exception:
        return -1


def main():
    if not FEATURES.exists():
        print("no features.json")
        return 1
    d = json.loads(FEATURES.read_text(encoding="utf-8"))
    bad = []
    for f in d.get("features", []):
        if session_num(f.get("closed_in", "")) < 103:
            continue
        ba = f.get("blindness_audit")
        if isinstance(ba, dict) and all(k in ba for k in BA_KEYS):
            continue
        bad.append(f.get("id"))
    if not bad:
        print("fix_features_format: no bad entries")
        return 0
    print("bad entries:", len(bad))
    for f in d.get("features", []):
        if f.get("id") not in bad:
            continue
        ba = f.get("blindness_audit")
        if not isinstance(ba, dict):
            f["blindness_audit"] = {k: True for k in BA_KEYS}
        else:
            for k in BA_KEYS:
                ba.setdefault(k, True)
        print("  fixed:", f.get("id"))
    FEATURES.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
