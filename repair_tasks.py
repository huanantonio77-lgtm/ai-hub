# repair_tasks.py - s90-2.2b: turn top skills into repair tasks.

import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from memory import mem

SKILLS_JSON = ROOT / "knowledge" / "skills.json"
MARKER_PREFIX = "[repair:"
MARKER_SUFFIX = "]"
FROZEN_PREFIXES = ("marketing", "video", "persona", "hire", "delegate", "subagent")
_SELF_REFLECT_DIR = "strategy/self-reflections"
DEFAULT_WINDOW = 7
DEFAULT_MIN = 15
MAX_NEW_PER_RUN = 5


def _load_skills(path=None):
    path = path or SKILLS_JSON
    if not path.exists():
        return list()
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return list()
    return d.get("skills") or list()


def _is_frozen_key(key):
    k = str(key or "").lower()
    for p in FROZEN_PREFIXES:
        if k.startswith(p) or p in k:
            return True
    return False


def _make_marker(key):
    return MARKER_PREFIX + str(key) + MARKER_SUFFIX


def _make_task_text(skill, window=DEFAULT_WINDOW):
    key = str(skill.get("key") or "")
    kind = str(skill.get("kind") or "pattern")
    count = int(skill.get("count") or 0)
    files_n = int(skill.get("files_n") or 0)
    exs = skill.get("examples") or list()
    files = list()
    for e in exs:
        if isinstance(e, dict) and e.get("file"):
            files.append(_resolve_example_path(e.get("file")))
    files_str = ", ".join(files[:3]) if files else "(no examples)"
    word = "pattern" if kind == "pattern" else "gap"
    head = _make_marker(key) + " Investigate " + word + " " + key + " (x" + str(count) + " / " + str(window) + "d, " + str(files_n) + " files)."
    n = min(3, len(files))
    body1 = "Analyze " + str(n) + " recent cases: " + files_str + "."
    body2 = "Propose a fix (code/prompt/process). Do not commit without approval."
    return head + chr(10) + body1 + chr(10) + body2


def _resolve_example_path(fname):
    # Bare self_reflect_*.json -> strategy/self-reflections/...json
    s = str(fname or "").strip()
    if not s:
        return ""
    if s.startswith("self_reflect_") and s.endswith(".json"):
        return _SELF_REFLECT_DIR + "/" + s
    return s

def _find_marker_index(actions, marker):
    for i, a in enumerate(actions):
        if isinstance(a, str) and a.startswith(marker):
            return i
    return -1


def generate(skills, existing_actions, min_count, limit, window=DEFAULT_WINDOW):
    actions = list(existing_actions)
    added = 0
    updated = 0
    skipped_frozen = 0
    skipped_low = 0
    for s in sorted(skills, key=lambda x: -(x.get("count") or 0)):
        cnt = int(s.get("count") or 0)
        if cnt < min_count:
            skipped_low += 1
            continue
        key = str(s.get("key") or "")
        if _is_frozen_key(key):
            skipped_frozen += 1
            continue
        marker = _make_marker(key)
        new_text = _make_task_text(s, window=window)
        idx = _find_marker_index(actions, marker)
        if idx >= 0:
            actions[idx] = new_text
            updated += 1
        else:
            if added >= limit:
                continue
            actions.append(new_text)
            added += 1
    stats = {
        "added": added,
        "updated": updated,
        "skipped_frozen": skipped_frozen,
        "skipped_low": skipped_low,
        "total_after": len(actions),
    }
    return actions, stats


def run(dry=False, window=DEFAULT_WINDOW, min_count=DEFAULT_MIN, limit=MAX_NEW_PER_RUN, skills_path=None):
    skills = _load_skills(skills_path)
    existing = mem.get("next_actions", []) or []
    new_actions, stats = generate(skills, existing, min_count, limit, window=window)
    print("skills_loaded:", len(skills))
    print("existing_actions:", len(existing))
    print("added:", stats["added"], "updated:", stats["updated"], "skipped_frozen:", stats["skipped_frozen"], "skipped_low:", stats["skipped_low"])
    if dry:
        print("DRY: not saved")
        for a in new_actions:
            if a.startswith(MARKER_PREFIX) and a not in existing:
                print("  + " + a[:120].replace(chr(10), " / "))
        return stats
    if new_actions == existing:
        print("no changes")
        return stats
    mem.update("next_actions", new_actions)
    print("saved: next_actions len=" + str(len(new_actions)))
    return stats


def _selftest():
    skills = list()
    skills.append({
        "kind": "pattern", "key": "json-parse", "count": 23, "files_n": 22,
        "examples": [
            {"file": "f1.json", "text": "x"},
            {"file": "f2.json", "text": "y"},
            {"file": "f3.json", "text": "z"},
        ],
    })
    skills.append({"kind": "gap", "key": "marketing", "count": 20, "files_n": 5, "examples": []})
    skills.append({"kind": "pattern", "key": "low-count", "count": 5, "files_n": 1, "examples": []})
    existing = list()
    existing.append(_make_marker("json-parse") + " old text")
    existing.append("other task")
    new_actions, stats = generate(skills, existing, min_count=15, limit=5)
    assert stats["added"] == 0, "added=" + str(stats)
    assert stats["updated"] == 1, "updated=" + str(stats)
    assert stats["skipped_frozen"] == 1, "frozen=" + str(stats)
    assert stats["skipped_low"] == 1, "low=" + str(stats)
    assert any("x23" in a and "json-parse" in a for a in new_actions), "count not updated"
    assert not any("marketing" in a for a in new_actions if a.startswith(MARKER_PREFIX)), "marketing leaked"
    fresh = list()
    new2, s2 = generate(skills, fresh, min_count=15, limit=5)
    assert s2["added"] == 1, "fresh added=" + str(s2)
    assert len(new2) == 1, "fresh len=" + str(len(new2))
    many = list()
    for i in range(10):
        many.append({"kind": "pattern", "key": "k" + str(i), "count": 20, "files_n": 1, "examples": []})
    _, s3 = generate(many, list(), min_count=15, limit=3)
    assert s3["added"] == 3, "limit=" + str(s3)
    rp = _resolve_example_path("self_reflect_2026-01-01_000000.json")
    assert rp == "strategy/self-reflections/self_reflect_2026-01-01_000000.json", "path=" + rp
    assert _resolve_example_path("other.json") == "other.json"
    print("SELFTEST-PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    ap.add_argument("--min", type=int, default=DEFAULT_MIN)
    ap.add_argument("--limit", type=int, default=MAX_NEW_PER_RUN)
    ap.add_argument("--skills", type=str, default=None)
    args = ap.parse_args()
    if args.selftest:
        _selftest()
        return
    if args.run or args.dry:
        sp = Path(args.skills) if args.skills else None
        run(dry=args.dry, window=args.window, min_count=args.min, limit=args.limit, skills_path=sp)
        return
    ap.print_help()


if __name__ == "__main__":
    main()

