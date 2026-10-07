#!/usr/bin/env python3
"""meta_drift.py -- meta-learning on recurring DRIFT_LOG patterns.

T13 (s130): recurring drift kind in >=2 sessions.
T14 (s131): cross-domain motif in >=2 domains (feature.kind / healer.specialty / lessons.md).

Modes: --report (dry), --scan (write), --cross-domain-only (dry T14 only).
"""
import json
import pathlib
import re
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent
DRIFT = ROOT / "self/curator/DRIFT_LOG.jsonl"
BACKLOG = ROOT / "self/BACKLOG.md"
JOURNAL = ROOT / "self/curator/JOURNAL.jsonl"
STATE = ROOT / "self/curator/STATE.md"
FEATURES = ROOT / "strategy/_features.json"
HEALERS = ROOT / "strategy/healers.json"
LESSONS = ROOT / "knowledge/lessons.md"
MIN_SESSIONS = 2
MIN_DOMAINS = 2

MOTIFS = {
    "backup":     [r"\bbackup", r"\u0431\u044d\u043a\u0430\u043f"],
    "sign":       [r"sign_core", r"\bsign\b", r"\bsigning\b", r"\u043f\u0435\u0440\u0435\u043f\u043e\u0434\u043f\u0438\u0441", r"\u043f\u043e\u0434\u043f\u0438\u0441"],
    "verify":     [r"\bverify\b", r"--verify", r"\u043f\u0440\u043e\u0432\u0435\u0440\u043a"],
    "idempotent": [r"\u0438\u0434\u0435\u043c\u043f\u043e\u0442\u0435\u043d\u0442", r"\bidempotent", r"\u0443\u0436\u0435 \u0435\u0441\u0442\u044c"],
    "try_except": [r"try\s*/\s*except", r"except\s+Exception"],
    "hook":       [r"\bhooks?\b", r"\u0445\u0443\u043a"],
    "dry_run":    [r"dry[\s-]*run", r"dry[\s-]*\u0440\u0443\u043d"],
    "prod":       [r"\u0432\s+\u043f\u0440\u043e\u0434\u0435", r"\bprod\b", r"\u043f\u0440\u043e\u0434-"],
    "lesson":     [r"\blessons?\b", r"\u0443\u0440\u043e\u043a"],
    "blindness":  [r"blindness", r"\u0441\u043b\u0435\u043f"],
}
MOTIF_RE = {k: re.compile("|".join(v), re.IGNORECASE) for k, v in MOTIFS.items()}


def _session_num(s):
    """Parse 'sNNN' -> int or None. s146-r3."""
    if not s:
        return None
    m = re.search(r"\bs(\d+)\b", s)
    return int(m.group(1)) if m else None


def _read_jsonl(path):
    """Read JSONL -> list of dicts; skips bad lines. s146-r3."""
    if not path.exists():
        return []
    out = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except Exception:
            pass
    return out


def _current_session():
    """Read 'Текущая сессия' from STATE.md. Fixed s146-r3."""
    if not STATE.exists():
        return "s?" + datetime.now(timezone.utc).strftime("%Y%m%d")
    for line in STATE.read_text(encoding="utf-8").splitlines():
        if "Текущая сессия" in line:
            m = re.search(r"\bs(\d+)\b", line)
            if m:
                return "s" + m.group(1)
    return "s?" + datetime.now(timezone.utc).strftime("%Y%m%d")


def _scan_max_session():
    """Max session across STATE+JOURNAL+DRIFT. Mirrors meta_drift_health.py:64. s146-r3."""
    nums = []
    if STATE.exists():
        for mm in re.finditer(r"\bs(\d+)\b", STATE.read_text(encoding="utf-8")):
            nums.append(int(mm.group(1)))
    for r in _read_jsonl(JOURNAL):
        n = _session_num(r.get("session", "") or "")
        if n is not None:
            nums.append(n)
    for r in _read_jsonl(DRIFT):
        n = _session_num(r.get("session", "") or "")
        if n is not None:
            nums.append(n)
        for s in r.get("sessions") or []:
            n = _session_num(s)
            if n is not None:
                nums.append(n)
    return max(nums) if nums else None


def _write_session():
    """Session to tag WRITES. Prefers scan-max. s140-r1 fix, s146-r3."""
    n = _scan_max_session()
    if n is not None:
        return "s" + str(n)
    return _current_session()


def _load_drift():
    if not DRIFT.exists():
        return []
    out = []
    for ln in DRIFT.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except Exception:
            pass
    return out


# ---------------- T13: recurring kinds ----------------

def _recurring_kinds(entries):
    by_kind = {}
    for e in entries:
        k = e.get("kind") or ""
        if not k or k.startswith("meta_recurring_"):
            continue
        s = e.get("session") or ""
        if not s:
            continue
        by_kind.setdefault(k, set()).add(s)
    out = []
    for k, sess in by_kind.items():
        if len(sess) >= MIN_SESSIONS:
            out.append((k, sorted(sess)))
    return sorted(out)


def _existing_meta_kinds(entries):
    out = set()
    for e in entries:
        k = e.get("kind") or ""
        if k.startswith("meta_recurring_"):
            out.add(k[len("meta_recurring_"):])
    return out


def _backlog_has(kind):
    if not BACKLOG.exists():
        return False
    needle = "meta_recurring_" + kind
    return needle in BACKLOG.read_text(encoding="utf-8")


def _append_backlog(kind, sessions):
    BACKLOG.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    note = ("Recurring drift pattern detected by meta_drift.py. "
            "Sessions: " + ",".join(sessions) + ". "
            "Owner: review and decide (deep fix or accept).")
    line = "| meta_recurring_" + kind + " | " + today + " | P3 | " + note + " | new (s130-t13) |"
    with BACKLOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _append_drift(kind, sessions):
    entry = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        "session": _write_session(),
        "kind": "meta_recurring_" + kind,
        "status": "open",
        "severity": "info",
        "sessions": sessions,
        "note": "recurring drift pattern (>=%d sessions); candidate for BACKLOG" % MIN_SESSIONS,
    }
    with DRIFT.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _scan(write, quiet=False):
    entries = _load_drift()
    recurring = _recurring_kinds(entries)
    already = _existing_meta_kinds(entries)
    new = [(k, s) for (k, s) in recurring if k not in already]
    if not quiet or new:
        print("[meta_drift] recurring patterns:", len(recurring))
    for k, s in recurring:
        flag = "OK" if k in already else "NEW"
        if quiet and flag == "OK":
            continue
        print("  -", k, "sessions=" + ",".join(s), flag)
    if not write:
        if not quiet or new:
            print("[meta_drift] dry-run: %d new" % len(new))
        return 0
    n = 0
    for k, s in new:
        _append_drift(k, s)
        if not _backlog_has(k):
            _append_backlog(k, s)
        n += 1
    if not quiet or n > 0:
        print("[meta_drift] wrote %d new meta entries" % n)
    return 0


# ---------------- T14: cross-domain motifs (s131) ----------------

def _load_corpus():
    corpus = {"features": [], "healers": [], "lessons": ""}
    if FEATURES.exists():
        try:
            data = json.loads(FEATURES.read_text(encoding="utf-8"))
            corpus["features"] = data if isinstance(data, list) else data.get("features", [])
        except Exception:
            pass
    if HEALERS.exists():
        try:
            data = json.loads(HEALERS.read_text(encoding="utf-8"))
            corpus["healers"] = data if isinstance(data, list) else data.get("healers", [])
        except Exception:
            pass
    if LESSONS.exists():
        try:
            corpus["lessons"] = LESSONS.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            pass
    return corpus


def _motif_domains():
    corpus = _load_corpus()
    by_motif = {}
    for f in corpus["features"]:
        txt = " ".join(str(f.get(x, "")) for x in ("name", "desc"))
        dom = "kind:" + (f.get("kind") or "feature")
        for m, rx in MOTIF_RE.items():
            if rx.search(txt):
                by_motif.setdefault(m, set()).add(dom)
    for h in corpus["healers"]:
        txt = " ".join(str(h.get(x, "")) for x in ("scope", "specialty", "role"))
        dom = "spec:" + (h.get("specialty") or "unknown")
        for m, rx in MOTIF_RE.items():
            if rx.search(txt):
                by_motif.setdefault(m, set()).add(dom)
    if corpus["lessons"]:
        for m, rx in MOTIF_RE.items():
            if rx.search(corpus["lessons"]):
                by_motif.setdefault(m, set()).add("lessons:lessons.md")
    return by_motif


def _is_cross_domain(domains):
    kinds = {d for d in domains if d.startswith("kind:")}
    specs = {d for d in domains if d.startswith("spec:")}
    return ((len(kinds) >= MIN_DOMAINS) or (len(specs) >= MIN_DOMAINS)
            or (len(kinds) >= 1 and len(specs) >= 1))


def _existing_cross_domain_kinds(entries):
    out = set()
    for e in entries:
        k = e.get("kind") or ""
        if k.startswith("cross_domain_"):
            out.add(k[len("cross_domain_"):])
    return out


def _backlog_has_cross_domain(motif):
    if not BACKLOG.exists():
        return False
    needle = "cross_domain_" + motif
    return needle in BACKLOG.read_text(encoding="utf-8")


def _append_cross_domain_drift(motif, domains):
    entry = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        "session": _write_session(),
        "kind": "cross_domain_" + motif,
        "status": "open",
        "severity": "info",
        "domains": sorted(domains),
        "note": "same motif in >=2 domains; candidate for BACKLOG (s131-t14)",
    }
    with DRIFT.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _append_cross_domain_backlog(motif, domains):
    BACKLOG.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    note = ("Cross-domain motif detected by meta_drift.py. "
            "Domains: " + ",".join(sorted(domains)) + ". "
            "Owner: review as systemic design pattern.")
    line = "| cross_domain_" + motif + " | " + today + " | P3 | " + note + " | new (s131-t14) |"
    with BACKLOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _scan_cross_domain(write, quiet=False):
    entries = _load_drift()
    by_motif = _motif_domains()
    cross = []
    for m in sorted(by_motif):
        doms = by_motif[m]
        if _is_cross_domain(doms):
            cross.append((m, doms))
    already = _existing_cross_domain_kinds(entries)
    new = [(m, d) for (m, d) in cross if m not in already]
    if not quiet or new:
        print("[meta_drift] cross-domain motifs:", len(cross))
    for m, d in cross:
        flag = "OK" if m in already else "NEW"
        if quiet and flag == "OK":
            continue
        print("  -", m, "domains=" + ",".join(sorted(d)), flag)
    if not write:
        if not quiet or new:
            print("[meta_drift] cross-domain dry-run: %d new" % len(new))
        return 0
    n = 0
    for m, d in new:
        _append_cross_domain_drift(m, d)
        if not _backlog_has_cross_domain(m):
            _append_cross_domain_backlog(m, d)
        n += 1
    if not quiet or n > 0:
        print("[meta_drift] wrote %d new cross-domain entries" % n)
    return 0


# ---------------- CLI ----------------

def main(argv):
    quiet = "--quiet" in argv
    argv = [a for a in argv if a != "--quiet"]
    if not argv:
        argv = ["--report"]
    mode = argv[0]
    if mode == "--report":
        rc = _scan(False, quiet=quiet)
        rc |= _scan_cross_domain(False, quiet=quiet)
        return rc
    if mode == "--scan":
        rc = _scan(True, quiet=quiet)
        rc |= _scan_cross_domain(True, quiet=quiet)
        return rc
    if mode == "--cross-domain-only":
        return _scan_cross_domain(False, quiet=quiet)
    print("usage: meta_drift.py [--report|--scan|--cross-domain-only] [--quiet]")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
