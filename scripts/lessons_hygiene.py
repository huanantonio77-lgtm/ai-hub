#!/usr/bin/env python3
"""lessons_hygiene — авто-чистка мусора в knowledge/lessons.md.

Мусор (удаляем):
  ## [ERROR] YYYY-MM-DD ...
  ## [FABRICATION] YYYY-MM-DD ...
  ## [REVIEW] YYYY-MM-DD ...

НЕ трогаем (whitelist по префиксу):
  ## sN-rM, ## YYYY-MM-DD, ## Урок:
  ## [sNN-M], ## [untagged], и вообще всё остальное.

Usage:
  python3 scripts/lessons_hygiene.py           # dry-run
  python3 scripts/lessons_hygiene.py --apply   # удалить + backup
"""
from __future__ import annotations
import argparse
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LESSONS = ROOT / "knowledge" / "lessons.md"
REPORT = ROOT / "self" / "curator" / "LESSONS_HYGIENE_REPORT.md"

GARBAGE_PREFIXES = (
    "## [ERROR]",
    "## [FABRICATION]",
    "## [REVIEW]",
)
HEAD = re.compile(r"^## ")


def is_garbage_header(line: str) -> bool:
    return any(line.startswith(p) for p in GARBAGE_PREFIXES)


def scan(lines: list[str]) -> list[tuple[int, int, str]]:
    """Возвращает [(start, end, header)]. end — индекс следующего заголовка или len."""
    blocks = []
    n = len(lines)
    i = 0
    while i < n:
        ln = lines[i]
        if is_garbage_header(ln):
            j = i + 1
            while j < n and not HEAD.match(lines[j]):
                j += 1
            blocks.append((i, j, ln.strip()))
            i = j
        else:
            i += 1
    return blocks


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--session", default=None,
                    help="session tag for backup name, e.g. s192")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    if not LESSONS.exists():
        print("lessons.md not found:", LESSONS, file=sys.stderr)
        return 2

    text = LESSONS.read_text(encoding="utf-8")
    lines = text.splitlines()
    blocks = scan(lines)

    total_lines_to_drop = sum(e - s for s, e, _ in blocks)

    print(f"scan: {len(lines)} lines, garbage blocks: {len(blocks)}, "
          f"lines to drop: {total_lines_to_drop}")

    if not args.quiet:
        for s, e, h in blocks[:20]:
            print(f"  L{s+1}-{e}: {h[:90]}")
        if len(blocks) > 20:
            print(f"  ... +{len(blocks)-20} more")

    if not blocks:
        print("clean: nothing to do")
        return 0

    if not args.apply:
        print("dry-run only. use --apply to delete.")
        return 0

    sess = args.session or datetime.utcnow().strftime("s%Y%m%d-%H%M%S")
    bak = LESSONS.with_suffix(f".md.bak-{sess}-hygiene")
    shutil.copy2(LESSONS, bak)
    print("backup:", bak)

    drop_idx = set()
    for s, e, _ in blocks:
        for k in range(s, e):
            drop_idx.add(k)

    kept = [ln for k, ln in enumerate(lines) if k not in drop_idx]
    new_text = "\n".join(kept)
    if not new_text.endswith("\n"):
        new_text += "\n"
    LESSONS.write_text(new_text, encoding="utf-8")

    print(f"wrote: {LESSONS} ({len(lines)} -> {len(kept)} lines)")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT, "a", encoding="utf-8") as f:
        f.write(f"\n## {datetime.utcnow().isoformat(timespec='seconds')} "
                f"session={sess}\n")
        f.write(f"- blocks removed: {len(blocks)}\n")
        f.write(f"- lines removed: {total_lines_to_drop}\n")
        f.write(f"- backup: {bak.name}\n")
    print("report:", REPORT)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
