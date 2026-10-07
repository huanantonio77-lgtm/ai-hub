#!/usr/bin/env python3
"""clean_state_orphans.py — удаляет сирот из strategy/tasks/_state.json.

Сирота — запись в state, ключ которой не совпадает ни с одной текущей
задачей из memory.json:next_actions. Появляется, когда текст задачи
меняется: task_key = task_{idx:02d}_{md5(text)[:8]}.

По умолчанию dry-run. Реальное удаление: --apply.
"""
import argparse, hashlib, json, shutil, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEM_FILE = ROOT / "memory.json"
STATE_FILE = ROOT / "strategy/tasks/_state.json"


def task_key(text, idx):
    h = hashlib.md5(text.encode("utf-8")).hexdigest()[:8]
    return f"task_{idx:02d}_{h}"


def live_keys():
    mem = json.loads(MEM_FILE.read_text(encoding="utf-8"))
    tasks = mem.get("next_actions", []) or []
    return {task_key(t, i): t for i, t in enumerate(tasks, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="реально удалить сирот (по умолчанию dry-run)")
    ap.add_argument("--state", default=str(STATE_FILE),
                    help="путь к _state.json")
    args = ap.parse_args()

    state_path = Path(args.state)
    if not state_path.exists():
        print(f"нет файла {state_path}"); return 1
    if not MEM_FILE.exists():
        print(f"нет файла {MEM_FILE}"); return 1

    state = json.loads(state_path.read_text(encoding="utf-8"))
    live = live_keys()

    live_in_state = [k for k in state if k in live]
    orphans = [k for k in state if k not in live]

    print(f"state: {len(state)} записей")
    print(f"live в next_actions: {len(live)}")
    print(f"LIVE в state: {len(live_in_state)}")
    print(f"ORPHAN: {len(orphans)}")
    for k in orphans:
        v = state[k]
        print(f"  {k}  status={v.get('status')}  attempts={v.get('attempts')}  last_run={v.get('last_run')}")

    if not orphans:
        print("нечего чистить")
        return 0

    if not args.apply:
        print()
        print("DRY-RUN: ничего не записано. Для удаления: --apply")
        return 0

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = state_path.with_suffix(f".json.bak-orphans-{ts}")
    shutil.copy2(state_path, bak)
    print(f"бэкап: {bak.name}")

    for k in orphans:
        del state[k]

    tmp = state_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(state_path)
    print(f"удалено {len(orphans)}, осталось {len(state)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
