"""
meta_drift_auto_close — актуатор петли s135 (симметрия с s134-A2B).
Закрывает meta_recurring_<kind> в DRIFT_LOG, когда базовый kind молчит
>= ttl_sessions сессий. Идемпотентно: если последняя запись по kind
уже closed — пропускаем.

Схема DRIFT_LOG (сверено s135):
  {ts, session, kind, status, severity, sessions?, note?, closed_in?, closed_ts?, note_extra?}
"""
from __future__ import annotations
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT       = Path(__file__).resolve().parent
DRIFT_LOG  = ROOT / "self" / "curator" / "DRIFT_LOG.jsonl"
TTL_PATH   = ROOT / "self" / "health" / "meta_drift_ttl.json"
STATE_MD   = ROOT / "self" / "curator" / "STATE.md"
JOURNAL    = ROOT / "self" / "curator" / "JOURNAL.jsonl"
PREFIX = "meta_recurring_"
BACKLOG = ROOT / "self" / "BACKLOG.md"


def _read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out, bad = [], 0
    for ln in p.read_text().splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            bad += 1
    if bad:
        print(f"[meta_drift_health] WARN: {bad} bad lines in {p}", file=sys.stderr)
    return out


def _load_ttl() -> dict:
    with TTL_PATH.open() as f:
        return json.load(f)


def _ttl_for(base: str, cfg: dict) -> dict:
    for w, v in cfg.get("wildcards", {}).items():
        if base.startswith(w):
            return v
    if base in cfg.get("rules", {}):
        return cfg["rules"][base]
    return cfg["default"]


def _session_num(s: str) -> Optional[int]:
    m = re.match(r"^s(\d+)$", s or "")
    return int(m.group(1)) if m else None


def _scan_max_session():
    nums = []
    if STATE_MD.exists():
        for mm in re.finditer(r"(s\d+)", STATE_MD.read_text()):
            n = _session_num(mm.group(1))
            if n is not None:
                nums.append(n)
    for r in _read_jsonl(JOURNAL):
        n = _session_num(r.get("session", "") or "")
        if n is not None:
            nums.append(n)
    for r in _read_jsonl(DRIFT_LOG):
        n = _session_num(r.get("session", "") or "")
        if n is not None:
            nums.append(n)
        for s in r.get("sessions") or []:
            n = _session_num(s)
            if n is not None:
                nums.append(n)
    return max(nums) if nums else None


def _current_session() -> str:
    # s137-smism: primary source = "Текущая сессия" line in STATE.md
    if STATE_MD.exists():
        for ln in STATE_MD.read_text(encoding="utf-8").splitlines():
            if "Текущая сессия" in ln:
                m = re.search(r"\bs(\d+)\b", ln)
                if m:
                    return "s" + m.group(1)
    # fallback: legacy max-scan (bootstrap / missing STATE)
    n = _scan_max_session()
    return ("s" + str(n)) if n is not None else ""

def _sign_valid() -> bool:
    r = subprocess.run(
        ["python3", "scripts/sign_core.py", "--verify"],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    return '"valid": true' in r.stdout or "valid=true" in r.stdout


def _last_by_kind(kind: str, log: list[dict]) -> Optional[dict]:
    hits = [r for r in log if r.get("kind") == kind]
    return hits[-1] if hits else None


def _already_closed(kind: str, log: list[dict]) -> bool:
    last = _last_by_kind(kind, log)
    return bool(last and last.get("status") == "closed")


def _is_silent(base: str, meta_rec: dict, ttl_sessions: int,
               cur_session: str) -> tuple[bool, str]:
    sessions = meta_rec.get("sessions") or []
    nums = [_session_num(s) for s in sessions]
    nums = [n for n in nums if n is not None]
    cur = _session_num(cur_session)
    if not nums or cur is None:
        return False, "no_session_data"
    last = max(nums)
    if cur - last >= ttl_sessions:
        return True, f"silent {cur - last} sessions (>= {ttl_sessions})"
    return False, f"seen {cur - last} sessions ago (< {ttl_sessions})"


def _append_closed(kind: str, session: str, reason: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    rec = {
        "ts": now,
        "session": session,
        "kind": kind,
        "status": "closed",
        "severity": "info",
        "closed_in": session,
        "closed_ts": now,
        "note_extra": f"auto-closed by meta_drift_health ({session}): {reason}",
    }
    with DRIFT_LOG.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _delegate_llm_storm() -> bool:
    try:
        import llm_health
        llm_health._close_drift_if_clear(llm_health._summarize(llm_health.report()))
        return True
    except Exception as e:
        print(f"[meta_drift_health] delegate llm_health failed: {e}", file=sys.stderr)
        return False


def _is_decided(base: str, meta_rec: dict, cur_session: str) -> tuple[bool, str]:
    """A2: motif in BACKLOG.md AND >=1 session passed since last recurrence."""
    if not BACKLOG.exists():
        return False, "no_backlog"
    txt = BACKLOG.read_text(encoding="utf-8")
    found = None
    for needle in (PREFIX + base, base):
        if f"| {needle} |" in txt:
            found = needle
            break
    if not found:
        return False, "no_backlog_marker"
    nums = [_session_num(s) for s in (meta_rec.get("sessions") or [])]
    nums = [n for n in nums if n is not None]
    # A2': cur = latest session seen anywhere. STATE.md updates "Текущая"
    # only on --close, so mid-session it lags by one. _scan_max_session()
    # reads STATE+JOURNAL+DRIFT and returns the actual current session.
    cur = _scan_max_session()
    if not nums or cur is None:
        return True, f"backlog_marker:{found} (no_session_gate)"
    last = max(nums)
    if cur - last >= 1:
        return True, f"backlog_marker:{found}; gap={cur - last}"
    return False, f"decided_fresh: seen {cur - last} sessions ago (backlog_marker:{found})"


def close_if_clear(kind: str, *, dry: bool = False, force: bool = False) -> dict:
    """kind — полный, с префиксом meta_recurring_. Возвращает отчёт."""
    if not kind.startswith(PREFIX):
        return {"kind": kind, "closed": False, "reason": "not_meta_recurring"}
    base = kind[len(PREFIX):]

    log = _read_jsonl(DRIFT_LOG)
    ttl = _ttl_for(base, _load_ttl())
    # A2'': closed_in must reflect the session doing the closing, not the
    # lagging STATE.md marker. Prefer _scan_max_session().
    _max = _scan_max_session()
    cur = ("s" + str(_max)) if _max is not None else _current_session()

    meta_rec = _last_by_kind(kind, log)
    if not meta_rec:
        return {"kind": kind, "closed": False, "reason": "no_record"}

    if _already_closed(kind, log):
        return {"kind": kind, "closed": False, "reason": "already_closed"}

    if meta_rec.get("status") != "open":
        return {"kind": kind, "closed": False,
                "reason": f"not_open:{meta_rec.get('status')}"}

    if not _sign_valid():
        return {"kind": kind, "closed": False, "reason": "sign_invalid"}

    decided, why_d = _is_decided(base, meta_rec, cur)
    if decided:
        if dry:
            if ttl.get("delegate") == "llm_health":
                return {"kind": kind, "closed": False,
                        "reason": f"dry_decided_ok(delegated): {why_d}"}
            return {"kind": kind, "closed": False,
                    "reason": f"dry_decided_ok: {why_d}"}
        if ttl.get("delegate") == "llm_health":
            if not _delegate_llm_storm():
                return {"kind": kind, "closed": False, "reason": "delegate_failed"}
            _append_closed(kind, cur, f"decided(delegated); {why_d}")
            return {"kind": kind, "closed": True,
                    "reason": f"decided(delegated); {why_d}"}
        _append_closed(kind, cur, f"decided; {why_d}")
        return {"kind": kind, "closed": True, "reason": f"decided; {why_d}"}

    silent, why = _is_silent(base, meta_rec, ttl["ttl_sessions"], cur)
    if not silent and not force:
        return {"kind": kind, "closed": False, "reason": f"not_silent: {why}"}

    if dry:
        if ttl.get("delegate") == "llm_health":
            return {"kind": kind, "closed": False,
                    "reason": f"dry_delegated_skipped: {why}"}
        return {"kind": kind, "closed": False, "reason": f"dry_ok: {why}"}

    if ttl.get("delegate") == "llm_health":
        if not _delegate_llm_storm():
            return {"kind": kind, "closed": False, "reason": "delegate_failed"}
        _append_closed(kind, cur, f"delegated to llm_health; {why}")
        return {"kind": kind, "closed": True, "reason": f"delegated; {why}"}

    final_reason = ("forced; " + why) if (force and not silent) else why
    _append_closed(kind, cur, final_reason)
    return {"kind": kind, "closed": True, "reason": final_reason}


def all_open_meta() -> list[str]:
    log = _read_jsonl(DRIFT_LOG)
    seen = {}
    for r in log:
        k = r.get("kind", "")
        if k.startswith(PREFIX):
            seen[k] = r.get("status")
    return [k for k, st in seen.items() if st == "open"]


def main(argv: list[str]) -> int:
    dry = "--dry" in argv
    force = "--force" in argv
    quiet = "--quiet" in argv
    argv = [a for a in argv if a not in ("--dry", "--force", "--quiet")]

    if "--all" in argv:
        kinds = all_open_meta()
        if not kinds:
            if not quiet:
                print("no open meta_recurring records")
            return 0
        closed_n = 0
        for k in kinds:
            r = close_if_clear(k, dry=dry, force=force)
            if not quiet or r["closed"]:
                print(f"{k}: closed={r['closed']} reason={r['reason']}")
            closed_n += int(r["closed"])
        if not quiet or closed_n > 0:
            print(f"--- total closed: {closed_n}/{len(kinds)} ---")
        return 0

    if len(argv) >= 3 and argv[1] == "--close-if-clear":
        r = close_if_clear(argv[2], dry=dry, force=force)
        print(f"{r['kind']}: closed={r['closed']} reason={r['reason']}")
        return 0

    print("usage: meta_drift_health.py --all [--dry] [--force] [--quiet] | --close-if-clear <meta_recurring_KIND> [--dry] [--force]",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
