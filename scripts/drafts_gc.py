#!/usr/bin/env python3
# scripts/drafts_gc.py (s188, non-CORE)
"""Drafts GC: dedup by technique + cap by count."""
import argparse, hashlib, json, re, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRAFTS_DIR = ROOT / "self" / "curator" / "drafts"
MAX_DRAFTS = 20

def _is_session_idx_dir(name):
    # s189-p4: accept any sN_idxN dir (was s177-only)
    return bool(re.match(r"^s\d+_idx\d+$", name))


def _tech_of(main_file):
    try:
        text = main_file.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    m = re.search(r"^# technique:\s*(.+)$", text, re.MULTILINE)
    if m: return m.group(1).strip().lower()
    m = re.search(r"^# title:\s*(.+)$", text, re.MULTILINE)
    return m.group(1).strip().lower() if m else None

def _key(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:10] if s else None

def _idx_of(name):
    m = re.search(r"idx(\d+)", name)
    return int(m.group(1)) if m else -1

def scan():
    rows = []
    if not DRAFTS_DIR.exists(): return rows
    for d in sorted(DRAFTS_DIR.iterdir()):
        if not d.is_dir() or not _is_session_idx_dir(d.name): continue
        mains = [p for p in d.iterdir() if p.suffix == ".py" and not p.name.startswith("test_")]
        if not mains: continue
        tech = _tech_of(mains[0])
        rows.append({"dir": str(d), "name": d.name, "idx": _idx_of(d.name),
                     "tech": tech, "key": _key(tech) if tech else None})
    return rows

def plan(rows, max_drafts=MAX_DRAFTS):
    keep, drop = set(), []
    groups = {}
    for r in rows:
        if r["key"] is None:
            keep.add(r["dir"]); continue
        groups.setdefault(r["key"], []).append(r)
    for k, items in groups.items():
        items.sort(key=lambda x: x["idx"], reverse=True)
        keep.add(items[0]["dir"])
        for loser in items[1:]:
            drop.append({"dir": loser["dir"], "reason": "dedup " + k})
    cur = [r for r in rows if r["dir"] in keep]
    cur.sort(key=lambda x: x["idx"], reverse=True)
    if len(cur) > max_drafts:
        for r in cur[max_drafts:]:
            if r["dir"] not in [d["dir"] for d in drop]:
                drop.append({"dir": r["dir"], "reason": "cap=%d idx=%d" % (max_drafts, r["idx"])})
    return keep, drop

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--max", type=int, default=MAX_DRAFTS)
    a = ap.parse_args()
    rows = scan()
    keep, drop = plan(rows, a.max)
    print(json.dumps({"scanned": len(rows), "keep": len([r for r in rows if r["dir"] in keep]),
                      "drop": len(drop), "max": a.max, "dry": not a.apply}, ensure_ascii=False))
    for d in drop:
        print("  DROP", d["reason"], "->", Path(d["dir"]).name)
        if a.apply: shutil.rmtree(d["dir"], ignore_errors=True)
    if a.apply: print("applied: %d dirs removed" % len(drop))

if __name__ == "__main__": main()
