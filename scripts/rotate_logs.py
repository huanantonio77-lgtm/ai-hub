#!/usr/bin/env python3
"""rotate_logs.py — ротация /tmp/ai-hub-logs/*.log для ai-hub.

Подход: launchd держит fd с O_APPEND, поэтому mv-ротация ломается.
Решение: mv + gzip + launchctl kickstart -k для переоткрытия fd.

По умолчанию dry-run. Реальная ротация — только с --apply.
"""
import argparse
import gzip
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

LOG_DIR = Path("/tmp/ai-hub-logs")
DEFAULT_SIZE_MB = 10
DEFAULT_MAX_AGE_DAYS = 7
DEFAULT_KEEP = 7

DAEMONS = {
    "agent.log": "com.ainova.agent-daemon",
    "tasks.log": "com.ainova.task-daemon",
    "infra.log": "com.ainova.infra-agent",
    "weekly.log": "com.ainova.weekly-review",
}


def log(msg):
    """Пишет в stdout. Под launchd stdout идёт в StandardOutPath (rotate.log),
    при ручном запуске — в терминал. Дублирующей записи в файл нет."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def list_logs():
    """Возвращает [(path, size, age_days), ...] для *.log, кроме rotate.log."""
    if not LOG_DIR.exists():
        return []
    now = time.time()
    out = []
    for p in sorted(LOG_DIR.glob("*.log")):
        if p.name == "rotate.log":
            continue
        try:
            st = p.stat()
        except Exception:
            continue
        age_days = (now - st.st_mtime) / 86400
        out.append((p, st.st_size, age_days))
    return out


def should_rotate(size, age_days, size_mb, max_age_days):
    """(bool, reason)."""
    if size >= size_mb * 1024 * 1024:
        return True, f"size {human_size(size)} >= {size_mb}MB"
    if age_days >= max_age_days:
        return True, f"age {age_days:.1f}d >= {max_age_days}d"
    return False, ""


def rotate_file(path, apply_=False):
    """mv path -> path.TS, gzip. Возвращает (ok, msg, gz_path|None)."""
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive = Path(str(path) + "." + ts)
    if not apply_:
        return True, f"plan rotate: {path.name} -> {archive.name}.gz", None
    try:
        os.rename(path, archive)
        gz = Path(str(archive) + ".gz")
        with open(archive, "rb") as src, gzip.open(gz, "wb") as dst:
            shutil.copyfileobj(src, dst)
        archive.unlink()
        return True, f"rotated: {path.name} -> {gz.name}", gz
    except Exception as e:
        return False, f"failed rotate {path.name}: {e}", None


def cleanup_old(log_path, keep, apply_=False):
    """Оставить keep свежих .gz рядом с log_path. Вернуть список удалённых."""
    base = log_path.name
    pattern = base + ".*.gz"
    archives = sorted(LOG_DIR.glob(pattern),
                      key=lambda p: p.stat().st_mtime, reverse=True)
    to_delete = archives[keep:]
    if not to_delete:
        return []
    if not apply_:
        return [f"plan delete: {p.name}" for p in to_delete]
    deleted = []
    for p in to_delete:
        try:
            p.unlink()
            deleted.append(f"deleted: {p.name}")
        except Exception as e:
            deleted.append(f"failed delete {p.name}: {e}")
    return deleted


def restart_daemon(log_name, apply_=False):
    """launchctl kickstart -k для демона, пишущего в log_name."""
    label = DAEMONS.get(log_name)
    if not label:
        return f"no daemon mapping for {log_name}"
    if not apply_:
        return f"plan kickstart: {label}"
    uid = os.getuid()
    try:
        r = subprocess.run(
            ["launchctl", "kickstart", "-k", f"gui/{uid}/{label}"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0:
            return f"kickstarted: {label}"
        return f"kickstart failed {label}: rc={r.returncode} {r.stderr.strip()[:120]}"
    except Exception as e:
        return f"kickstart error {label}: {e}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="выполнить ротацию (default: dry-run)")
    ap.add_argument("--size-mb", type=int, default=DEFAULT_SIZE_MB)
    ap.add_argument("--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS)
    ap.add_argument("--keep", type=int, default=DEFAULT_KEEP)
    args = ap.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    log(f"=== rotate_logs {mode} ===")
    log(f"dir={LOG_DIR} size_mb={args.size_mb} max_age_days={args.max_age_days} keep={args.keep}")

    logs = list_logs()
    if not logs:
        log("нет .log файлов")
        return 0

    rotated = 0
    for path, size, age_days in logs:
        do, reason = should_rotate(size, age_days, args.size_mb, args.max_age_days)
        log(f"  {path.name}: {human_size(size)}, age={age_days:.1f}d -> "
            + ("ROTATE (" + reason + ")" if do else "skip"))
        if not do:
            continue
        ok, msg, _ = rotate_file(path, apply_=args.apply)
        log(f"    {msg}")
        if not ok:
            continue
        rotated += 1
        for line in cleanup_old(path, args.keep, apply_=args.apply):
            log(f"    {line}")
        log(f"    {restart_daemon(path.name, apply_=args.apply)}")

    log(f"=== done, rotated {rotated} ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
