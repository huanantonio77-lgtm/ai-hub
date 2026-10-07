#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""disk_janitor.py - s99-5: agent sam chistit .bak* i tmp-musor.

Report-only default. --apply: arhiv .bak* starshе MIN_AGE_DAYS v archive/backups/,
potom udalenie. /tmp/*.bak* i starye logi udalyayutsya bez arhiva.
"""
import argparse
import json
import subprocess
import sys
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path
import session_meta as _sm


def _silent(tag, e):
    """s105-3: emit silent except to errors.jsonl (K1 emission)."""
    try:
        from datetime import datetime as _dt, timezone as _tz
        import json as _j
        _root = Path(__file__).resolve().parent
        log = _root / ".cache" / "system" / "errors.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": _dt.now(_tz.utc).strftime("%Y-%m-%d %H:%M:%S"),
               "kind": "silent", "where": "disk_janitor",
               "detail": tag + ": " + type(e).__name__ + ": " + str(e)[:100]}
        with log.open("a", encoding="utf-8") as f:
            f.write(_j.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent
AUDIT_MD = ROOT / "strategy" / "disk_janitor.md"
AUTONOMY = ROOT / "self" / "autonomy.jsonl"

SESSION = _sm.current()
ARCH_DIR = ROOT / "archive" / "backups"
TMP_BAK_GLOB = "/tmp/*.bak*"
LOGS_DIR = Path("/tmp/ai-hub-logs")

# s124-stage3: extra scan dirs outside ROOT (e.g. LaunchAgents)
EXTRA_SCAN_DIRS = [Path.home() / "Library" / "LaunchAgents"]

MIN_AGE_DAYS = 2  # s124-stage3: 3 -> 2

LOG_AGE_DAYS = 14
KEEP_PREFIXES = (".bak-s99",)
EXCLUDE_SUBSTR = ("archive/backups", ".git/")

def _age_days(p):
    try:
        return (time.time() - p.stat().st_mtime) / 86400.0
    except Exception:
        return 0.0

def _in_exclude(rel):
    return any(s in rel for s in EXCLUDE_SUBSTR)

def _is_current_session_bak(name):
    return any(name.startswith(pre) for pre in KEEP_PREFIXES) or any(pre in name for pre in KEEP_PREFIXES)

def detect():
    """Vozvrashchaet {"archive": [paths], "delete_only": [paths], "summary": {...}}."""
    archive = []
    delete_only = []
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        rel = str(p.relative_to(ROOT))
        if _in_exclude(rel):
            continue
        name = p.name
        is_bak = ".bak" in name
        is_broken = ".broken-" in name
        is_patched = ".patched-" in name
        if not (is_bak or is_broken or is_patched):
            continue
        if is_bak and _is_current_session_bak(name):
            continue
        if _age_days(p) >= MIN_AGE_DAYS:
            archive.append(str(p))

    # s124-stage3: extra scan dirs (outside ROOT)
    for extra in EXTRA_SCAN_DIRS:
        try:
            if not extra.exists():
                continue
            for p in extra.rglob("*"):
                if not p.is_file():
                    continue
                name = p.name
                is_bak = ".bak" in name
                is_broken = ".broken-" in name
                is_patched = ".patched-" in name
                if not (is_bak or is_broken or is_patched):
                    continue
                if is_bak and _is_current_session_bak(name):
                    continue
                if _age_days(p) >= MIN_AGE_DAYS:
                    archive.append(str(p))
        except Exception as _e:
            _silent('disk_janitor_extra', _e)

    try:
        r = subprocess.run("ls -1 " + TMP_BAK_GLOB, shell=True, capture_output=True, text=True)
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                line = line.strip()
                if line:
                    delete_only.append(line)
    except Exception as _e:
        _silent('disk_janitor_L72', _e)

    if LOGS_DIR.exists():
        for p in LOGS_DIR.glob("*.log"):
            if _age_days(p) >= LOG_AGE_DAYS:
                delete_only.append(str(p))

    def _sz(paths):
        s = 0
        for x in paths:
            try:
                s += Path(x).stat().st_size
            except Exception as _e:
                _silent('disk_janitor_L85', _e)
        return s

    summary = {
        "archive_n": len(archive),
        "archive_bytes": _sz(archive),
        "delete_only_n": len(delete_only),
        "delete_only_bytes": _sz(delete_only),
    }
    return {"archive": archive, "delete_only": delete_only, "summary": summary}

def _fmt_mb(b):
    return "{:.1f} MB".format(b / 1024 / 1024)

def _render_report(d, ts=None):
    ts = ts or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = ["## " + ts, ""]
    s = d.get("summary") or {}
    an = s.get("archive_n", 0)
    ab = s.get("archive_bytes", 0)
    dn = s.get("delete_only_n", 0)
    db = s.get("delete_only_bytes", 0)
    if not an and not dn:
        lines.append("OK: no stale .bak*, no tmp junk.")
        lines.append("")
        return chr(10).join(lines)
    if an:
        lines.append("### Archive candidates (older than " + str(MIN_AGE_DAYS) + "d)")
        lines.append("- files: " + str(an) + " (" + _fmt_mb(ab) + ")")
        for x in (d.get("archive") or [])[:10]:
            lines.append("  - " + x)
        if an > 10:
            lines.append("  - ... and " + str(an - 10) + " more")
        lines.append("")
    if dn:
        lines.append("### Delete only (no archive)")
        lines.append("- files: " + str(dn) + " (" + _fmt_mb(db) + ")")
        for x in (d.get("delete_only") or [])[:10]:
            lines.append("  - " + x)
        if dn > 10:
            lines.append("  - ... and " + str(dn - 10) + " more")
        lines.append("")
    return chr(10).join(lines)

def _append_md(text):
    AUDIT_MD.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_MD.open("a", encoding="utf-8") as f:
        f.write(text)

def _append_autonomy(note, effect=None):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    ev = {"ts": ts, "session": SESSION, "action": "disk_janitor", "note": note}
    if effect is not None:
        ev["effect"] = int(effect)
    try:
        with AUTONOMY.open("a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + chr(10))
    except Exception as _e:
        _silent('disk_janitor_L141', _e)
    # s108 A3: личный журнал лекаря (fail-open)
    try:
        from healer_log import healer_log
        healer_log("disk_janitor", diagnosis=note, effect=effect)
    except Exception:
        pass

def _add_repair_task(d):
    s = d.get("summary") or {}
    if not s.get("archive_n"):
        return False
    marker = "[repair:disk-janitor]"
    _n = str(s.get("archive_n", 0))
    _mb = _fmt_mb(s.get("archive_bytes", 0))
    text = marker + " Stale .bak*: " + _n + " files (" + _mb + "). Run: python3 disk_janitor.py --apply"
    try:
        import memory as _mem_mod
        _m = _mem_mod.Memory()
        actions = list(_m.get("next_actions", []) or [])
        replaced = False
        for i, a in enumerate(actions):
            if isinstance(a, str) and a.startswith(marker):
                actions[i] = text
                replaced = True
                break
        if not replaced:
            actions.append(text)
        _m.update("next_actions", actions)
        return True
    except Exception as e:
        print("repair_task: fail " + type(e).__name__)
        return False

def run_report(quiet=False):
    d = detect()
    text = _render_report(d)
    if not quiet:
        print(text)
    _append_md(text)
    s = d.get("summary") or {}
    _append_autonomy("archive=" + str(s.get("archive_n", 0)) + " delete_only=" + str(s.get("delete_only_n", 0)))
    if s.get("archive_n"):
        _add_repair_task(d)
    return d

def apply_archive(d=None):
    """Arhiviruet d["archive"] v tar.gz + manifest. Zatem udalyaet vse: archive + delete_only."""
    d = d or detect()
    arch = list(d.get("archive") or [])
    d_only = list(d.get("delete_only") or [])
    if not arch and not d_only:
        print("apply: nothing to do")
        return (0, 0, None)
    ARCH_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    tar_path = None
    if arch:
        tar_path = ARCH_DIR / ("disk_janitor-" + ts + ".tar.gz")
        manifest = ARCH_DIR / ("disk_janitor-" + ts + ".list.txt")
        manifest.write_text(chr(10).join(arch), encoding="utf-8")
        with tarfile.open(tar_path, "w:gz") as tar:
            for f in arch:
                try:
                    tar.add(f)
                except Exception as e:
                    print("tar add fail: " + f + " " + type(e).__name__)
        with tarfile.open(tar_path, "r:gz") as tar:
            n = len(tar.getnames())
        if n != len(arch):
            print("ABORT: tar entries " + str(n) + " != " + str(len(arch)))
            return (0, 0, None)
        print("tar: " + tar_path.name + " (" + _fmt_mb(tar_path.stat().st_size) + ", " + str(n) + " entries)")
    deleted = 0
    failed = 0
    for f in arch + d_only:
        try:
            Path(f).unlink()
            deleted += 1
        except Exception:
            failed += 1
    print("deleted=" + str(deleted) + "/" + str(len(arch) + len(d_only)) + " failed=" + str(failed))
    _append_autonomy("apply archive=" + str(len(arch)) + " delete_only=" + str(len(d_only)) + " deleted=" + str(deleted))
    return (len(arch), deleted, str(tar_path) if tar_path else None)

AUTO_SAFE_MAX_FILES = 500  # s124-stage3: 50 -> 500
AUTO_SAFE_MAX_BYTES = 100 * 1024 * 1024
AUTO_SAFE_LOCK = ROOT / ".cache" / "system" / "disk_janitor_auto_safe.ts"


def auto_safe(quiet=False):
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    effect = 0
    try:
        already = AUTO_SAFE_LOCK.read_text(encoding="utf-8").strip() == today
    except Exception:
        already = False
    if already:
        reason = "already_today"
    else:
        d = detect()
        s = d.get("summary") or {}
        n = s.get("archive_n", 0) + s.get("delete_only_n", 0)
        b = s.get("archive_bytes", 0) + s.get("delete_only_bytes", 0)
        if n == 0:
            reason = "nothing_to_do"
        elif n > AUTO_SAFE_MAX_FILES:
            reason = "too_many_files_" + str(n)
        elif b > AUTO_SAFE_MAX_BYTES:
            reason = "too_many_bytes_" + str(b)
        else:
            apply_archive(d)
            AUTO_SAFE_LOCK.parent.mkdir(parents=True, exist_ok=True)
            AUTO_SAFE_LOCK.write_text(today, encoding="utf-8")
            reason = "applied"
            effect = n
    note = "auto_safe reason=" + reason
    _append_autonomy(note, effect=effect)
    if not quiet:
        print("auto_safe: " + reason)
    return reason
def _selftest():
    ok = 0
    total = 0
    def chk(name, cond):
        nonlocal ok, total
        total += 1
        if cond:
            ok += 1
            print("  [OK] " + name)
        else:
            print("  [FAIL] " + name)
    chk("render_empty", "OK" in _render_report({"archive": [], "delete_only": [], "summary": {"archive_n": 0, "archive_bytes": 0, "delete_only_n": 0, "delete_only_bytes": 0}}, ts="TEST"))
    t = _render_report({"archive": ["/tmp/x.bak-a"], "delete_only": ["/tmp/y.bak"], "summary": {"archive_n": 1, "archive_bytes": 100, "delete_only_n": 1, "delete_only_bytes": 50}}, ts="TEST")
    chk("render_has_archive", "Archive candidates" in t)
    chk("render_has_delete_only", "Delete only" in t)
    chk("exclude_archive", _in_exclude("archive/backups/x.bak"))
    chk("exclude_git", _in_exclude(".git/objects/x.bak"))
    chk("keep_s99", _is_current_session_bak("orchestrator.py.bak-s99-3"))
    chk("not_keep_old", not _is_current_session_bak("orchestrator.py.bak-s85-3b"))
    print("passed " + str(ok) + "/" + str(total))
    return 0 if ok == total else 1

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--auto-safe", action="store_true")
    a = ap.parse_args()
    if a.auto_safe:
        return auto_safe(quiet=a.quiet)
    if a.selftest:
        return _selftest()
    d = run_report(quiet=a.quiet)
    if a.apply:
        apply_archive(d)
    return 0

if __name__ == "__main__":
    sys.exit(main())
