"""""memory.py — работа с memory.json.
Память агента: конкуренты, ЦА, ниши, что работает, что нет, открытые вопросы.

Использование:
    from memory import mem
    mem.get("positioning.slogan")
    mem.append("learnings", {"date": "2026-09-21", "insight": "..."})
    mem.update("market.prices_known", [...])
    mem.summary(verbose=False)  # печатает короткую выжимку, только если verbose=True
"""

import json
import sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent
MEM_FILE = ROOT / "memory_product.json"  # s208-C4: split product/agent

class Memory:
    def __init__(self):
        self._load()

    def _load(self):
        if MEM_FILE.exists():
            self.data = json.loads(MEM_FILE.read_text(encoding="utf-8"))
        else:
            self.data = {"version": 1, "learnings": [], "open_questions": []}

    def _save(self):
        self.data["updated"] = datetime.now().strftime("%Y-%m-%d")
        MEM_FILE.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8")

    def get(self, path, default=None):
        """Доступ по пути 'market.prices_known'. Безопасно."""
        cur = self.data
        for key in path.split("."):
            if isinstance(cur, dict) and key in cur:
                cur = cur[key]
            else:
                return default
        return cur

    def update(self, path, value):
        """Перезаписать по пути. Создаёт вложенные dict по необходимости."""
        keys = path.split(".")
        cur = self.data
        for k in keys[:-1]:
            if k not in cur or not isinstance(cur[k], dict):
                cur[k] = {}
            cur = cur[k]
        cur[keys[-1]] = value
        self._save()

    def append(self, path, value):
        """Добавить в список по пути."""
        cur = self.data
        keys = path.split(".")
        for k in keys:
            if k not in cur:
                cur[k] = []
            cur = cur[k]
        if not isinstance(cur, list):
            raise ValueError(f"{path} — не список")
        cur.append(value)
        self._save()

    def summary(self, verbose=False):
        """Короткая выжимка для старта сессии."""
        d = self.data
        lines = []
        if verbose:
            lines.append("=== ЧТО Я ПОМНЮ ===")
            p = d.get("project", {})
            lines.append(f"Проект: {p.get('name')} — {p.get('what', '')[:80]}")
            pos = d.get("positioning", {})
            if pos.get("slogan"):
                lines.append(f"Слоган: {pos['slogan']}")
            if pos.get("niche"):
                lines.append(f"Ниша: {pos['niche'][:120]}")
            market = d.get("market", {})
            groups = market.get("competitor_groups", [])
            if groups:
                lines.append(f"Конкурентов (групп): {len(groups)}")
            stats = d.get("stats", {})
            if stats:
                lines.append(f"Собрано: конкурентов {stats.get('competitors_found', '?')}, "
                            f"цен {stats.get('prices_found', '?')}, "
                            f"инсайтов {stats.get('insights_found', '?')}")
            learnings = d.get("learnings", [])
            if learnings:
                lines.append(f"Ключевых уроков: {len(learnings)}")
                for l in learnings[-3:]:
                    lines.append(f"  - {l.get('insight', '')[:100]}")
            q = d.get("open_questions", [])
            if q:
                lines.append(f"Открытых вопросов: {len(q)}")
            lines.append(f"Обновлено: {d.get('updated')} (сессия {d.get('session')})")
        return "\n".join(lines)

mem = Memory()

if __name__ == "__main__":
    verbose = "--verbose" in sys.argv
    print(mem.summary(verbose=verbose))
""