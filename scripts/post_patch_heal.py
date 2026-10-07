#!/usr/bin/env python3
"""s107-2 + s107-3-fix1: post-patch heal.
Order matters: MUTATIONS FIRST, SIGN LAST.
  1. fix_features_format (may mutate _features.json)
  2. compile recent .py (read-only)
  3. sign_core --verify -> --sign if invalid (reflects ALL mutations above)
  4. final verify (must pass, else log heal_broken)
Logs effect:N to autonomy.jsonl.
"""
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUTONOMY = ROOT / "self" / "autonomy.jsonl"


def _run(args, timeout=30):
    try:
        r = subprocess.run(args, cwd=str(ROOT), capture_output=True,
                           text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return 1, "", str(e)


def _log(effect, note):
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "session": "s107",
        "action": "post_patch_heal",
        "note": note,
        "effect": int(effect),
    }
    try:
        AUTONOMY.parent.mkdir(parents=True, exist_ok=True)
        with AUTONOMY.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def main():
    effect = 0
    notes = []
    py = sys.executable

    # 1. features format (mutation)
    rc, out, err = _run([py, "scripts/fix_features_format.py"])
    if "no bad entries" not in out:
        effect += 1
        notes.append("features_fixed")
    else:
        notes.append("features_ok")

    # 2. compile recent .py (read-only)
    now = time.time()
    recent = []
    for p in ROOT.glob("*.py"):
        try:
            if now - p.stat().st_mtime < 3600:
                recent.append(p.name)
        except Exception:
            pass
    if recent:
        rc, out, err = _run([py, "-m", "py_compile"] + recent, timeout=60)
        if rc != 0:
            notes.append("compile_fail:" + ",".join(recent[:3]))
        else:
            notes.append("compile_ok_" + str(len(recent)))
    else:
        notes.append("compile_none")

    # 3. sign LAST (reflects all mutations above)
    rc, out, err = _run([py, "scripts/sign_core.py", "--verify"])
    if rc != 0 or '"valid": true' not in out:
        rc2, out2, err2 = _run([py, "scripts/sign_core.py", "--sign"])
        if rc2 == 0:
            effect += 1
            notes.append("signed")
        else:
            notes.append("sign_fail")
    else:
        notes.append("sign_ok")

    # 4. final verify (must be valid)
    rc, out, err = _run([py, "scripts/sign_core.py", "--verify"])
    if rc == 0 and '"valid": true' in out:
        notes.append("final_ok")
    else:
        notes.append("final_FAIL")
        _log(effect, "heal_broken " + ";".join(notes))
        print("post_patch_heal: heal_broken " + ";".join(notes) + " effect=" + str(effect))
        return 1

    note = "heal " + ";".join(notes)
    _log(effect, note)
    print("post_patch_heal: " + note + " effect=" + str(effect))
    return 0


if __name__ == "__main__":
    sys.exit(main())
