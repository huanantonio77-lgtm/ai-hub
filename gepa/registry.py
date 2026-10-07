# gepa/registry.py - GEPA v0: registry of prompt variants (target: repair_task)
# Public API:
#   gepa_prompt_block(task, task_key) -> str
#   pick_and_log(task, task_key) -> (variant_id, chars)
#   load_registry() / load_rotation() / read_variant_text(id)

from __future__ import annotations
import json, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = ROOT / "strategy" / "prompts"
DEFAULT_TARGET = "repair_task"
MARKERS = {"repair_task": "[repair:"}
TARGET_DIR = PROMPTS_DIR / DEFAULT_TARGET  # back-compat default
REGISTRY_FILE = TARGET_DIR / "_registry.json"
ROTATION_FILE = TARGET_DIR / "_rotation.json"

def _target_dir(target=None):
    return PROMPTS_DIR / (target or DEFAULT_TARGET)

def _registry_file(target=None):
    return _target_dir(target) / "_registry.json"

def _rotation_file(target=None):
    return _target_dir(target) / "_rotation.json"
RUNS_FILE = PROMPTS_DIR / "_runs.jsonl"

MARKER = "[repair:"


def _is_repair_task(task):
    return isinstance(task, str) and task.strip().startswith(MARKER)

def _matches_target(task, target=None):
    t = target or DEFAULT_TARGET
    marker = MARKERS.get(t)
    if marker is None:
        return True
    return isinstance(task, str) and task.strip().startswith(marker)


def _read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def load_registry(target=None):
    d = _read_json(_registry_file(target), None)
    if not isinstance(d, dict) or not d.get("incumbent"):
        return None
    return d


def load_rotation(target=None):
    d = _read_json(_rotation_file(target), None)
    if not isinstance(d, dict):
        return {"counter": 0, "period": 2}
    if not isinstance(d.get("counter"), int):
        d["counter"] = 0
    if not isinstance(d.get("period"), int) or d["period"] < 1:
        d["period"] = 2
    return d


def save_rotation(rot, target=None):
    try:
        _rotation_file(target).write_text(
            json.dumps(rot, ensure_ascii=False, indent=2) + chr(10),
            encoding="utf-8",
        )
    except Exception:
        pass


def read_variant_text(variant_id, target=None):
    if not variant_id or not isinstance(variant_id, str):
        return ""
    p = _target_dir(target) / (variant_id + ".md")
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def pick_variant_id(registry, rotation):
    incumbent = registry.get("incumbent")
    challenger = registry.get("challenger")
    if not challenger:
        return incumbent
    period = rotation.get("period", 2)
    counter = rotation.get("counter", 0)
    if counter > 0 and period >= 2 and (counter % period == 0):
        return challenger
    return incumbent


def _append_run(rec):
    try:
        PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
        with RUNS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + chr(10))
    except Exception:
        pass


def pick_and_log(task, task_key="", target=None):
    try:
        registry = load_registry(target)
        if not registry:
            return None, 0
        rotation = load_rotation(target)
        variant_id = pick_variant_id(registry, rotation)
        text = read_variant_text(variant_id, target)
        nxt = rotation.get("counter", 0) + 1
        rotation["counter"] = nxt
        save_rotation(rotation, target)
        _append_run({
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "target": (registry.get("target") if registry else None) or (target or DEFAULT_TARGET),
            "variant_id": variant_id,
            "task_key": task_key or "",
            "chars": len(text),
            "counter": nxt,
        })
        return variant_id, len(text)
    except Exception:
        return None, 0


def gepa_prompt_block(task, task_key="", target=None):
    if not _matches_target(task, target):
        return ""
    try:
        variant_id, _ = pick_and_log(task, task_key, target)
        if not variant_id:
            return ""
        return read_variant_text(variant_id, target)
    except Exception:
        return ""


def _selftest():
    reg = {"target": "repair_task", "incumbent": "v0_incumbent", "challenger": "v1_baseline"}
    rot = {"counter": 0, "period": 2}
    picks = []
    for _ in range(6):
        vid = pick_variant_id(reg, rot)
        picks.append(vid)
        rot["counter"] = rot["counter"] + 1
    expected = ["v0_incumbent", "v0_incumbent", "v1_baseline",
                "v0_incumbent", "v1_baseline", "v0_incumbent"]
    assert picks == expected, "picks=" + str(picks)
    assert not _is_repair_task("обычная задача")
    assert _is_repair_task("[repair:json-parse] текст")
    assert not _matches_target("обычная задача", "repair_task")
    assert _matches_target("[repair:json-parse] текст", "repair_task")
    assert _matches_target("any task text", "self_reflect")
    reg2 = dict(reg)
    reg2["challenger"] = None
    rot2 = {"counter": 0, "period": 2}
    assert pick_variant_id(reg2, rot2) == "v0_incumbent"
    print("SELFTEST-PASS picks=" + str(picks))


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print("gepa/registry.py - use --selftest")

