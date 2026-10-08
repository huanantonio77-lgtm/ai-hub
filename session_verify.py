#!/usr/bin/env python3
"""
session_verify.py (s84-4) — исполнитель ПРАВИЛА №00.

Три режима:
  --in   Проверка в начале сессии (полная, с ALERTS).
  --mid  Проверка в середине (только stdout).
  --out  Проверка в конце (полная, с записью в память).

Что проверяет: фичи из strategy/_features.json.
Типы: launchd-сервис (runs), grep-проверка, артефакт по mtime.
Порог тревоги: ratio < 0.8 → regression.
"""
import argparse
import pathlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def _silent(tag, e):
    """s104-2d: emit silent except to errors.jsonl (K1 emission)."""
    try:
        from datetime import datetime as _dt, timezone as _tz
        log = Path(__file__).resolve().parent / ".cache" / "system" / "errors.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": _dt.now(_tz.utc).strftime("%Y-%m-%d %H:%M:%S"),
               "kind": "silent", "where": "session_verify.py",
               "detail": tag + ": " + type(e).__name__ + ": " + str(e)[:100]}
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as _e:
        _silent("sv_pass", _e)

ROOT = Path(__file__).resolve().parent
LB = chr(91)
RB = chr(93)
STRATEGY = ROOT / "strategy"
FEATURES = STRATEGY / "_features.json"
HEALTH = STRATEGY / "_autonomy_health.json"
HEALTH_LOG = STRATEGY / "_autonomy_health.jsonl"
ALERTS = STRATEGY / "ALERTS.md"
# s86-8: learning delta state
LEARNING_STATE = STRATEGY / "_session_verify_state.json"
LEARN_FILES = [
    ("self/evolution.md", ROOT / "self" / "evolution.md"),
    ("knowledge/lessons.md", ROOT / "knowledge" / "lessons.md"),
    ("knowledge/skills.md", ROOT / "knowledge" / "skills.md"),
    ("self/autonomy.jsonl", ROOT / "self" / "autonomy.jsonl"),
]
THRESHOLD = 0.8
KEEP_LAST = 10

def load_features():
    if not FEATURES.exists():
        print("[FAIL] нет " + str(FEATURES))
        return []
    try:
        d = json.loads(FEATURES.read_text(encoding="utf-8"))
        return d.get("features", [])
    except Exception as e:
        print("[FAIL] bad features json: " + str(e)[:120])
        return []


def _get_launchd_runs(label):
    """launchctl print gui/<uid>/<label> → runs, state, exit."""
    uid = os.getuid()
    try:
        r = subprocess.run(
            ["launchctl", "print", "gui/" + str(uid) + "/" + label],
            capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return None
        out = r.stdout
        runs = 0
        state = "unknown"
        exit_code = "?"
        for line in out.splitlines():
            s = line.strip()
            if s.startswith("runs = "):
                try: runs = int(s.split("=")[1].strip())
                except Exception as _e: _silent("sv_oneline", _e)
            elif s.startswith("state = "):
                state = s.split("=",1)[1].strip()
            elif s.startswith("last exit code = "):
                exit_code = s.split("=",1)[1].strip()
        return {"runs": runs, "state": state, "exit": exit_code}
    except Exception as _e:
        _silent("sv_return_none", _e)
        return None


def _check_grep(spec):
    """spec: \"grep <needle> <file>\""""
    parts = spec.split()
    if len(parts) != 3 or parts[0] != "grep":
        return {"ok": False, "reason": "bad grep spec"}
    needle, fname = parts[1], parts[2]
    p = ROOT / fname
    if not p.exists():
        return {"ok": False, "reason": "no file " + fname}
    try:
        t = p.read_text(encoding="utf-8", errors="ignore")
        return {"ok": needle in t, "reason": "grep " + needle + " in " + fname}
    except Exception as e:
        return {"ok": False, "reason": "read fail: " + str(e)[:80]}


def _check_artifact(path, window_hours):
    p = ROOT / path
    if not p.exists():
        return {"ok": False, "reason": "no artifact " + path}
    try:
        age_h = (datetime.now().timestamp() - p.stat().st_mtime) / 3600.0
        return {"ok": age_h <= window_hours, "age_hours": round(age_h,1), "reason": "age=" + str(round(age_h,1)) + "h <= " + str(window_hours)}
    except Exception as e:
        return {"ok": False, "reason": "stat fail: " + str(e)[:80]}

def _check_awake_catchup(fid):
    """s86-6a: awake-статус из catchup (если есть)."""
    try:
        import catchup as _cu
        rep = _cu.report()
        entry = rep.get(fid)
        if not entry:
            return None
        st = entry.get("status")
        if st not in ("alive", "regression"):
            return None
        gap = entry.get("gap_s")
        gap_h = round(gap / 3600.0, 2) if gap is not None else "?"
        return {
            "status": st,
            "actual": entry.get("expected_s"),
            "expected": entry.get("expected_s"),
            "ratio": 1.0 if st == "alive" else 0.0,
            "reason": "awake-catchup gap=" + str(gap_h) + "h",
            "kind": "service",
            "source": "catchup",
        }
    except Exception as _e:
        _silent("sv_return_none", _e)
        return None


def _snapshot_learning():
    's86-8: snapshot lines/bytes for learning files.'
    snap = {}
    for name, path in LEARN_FILES:
        try:
            text = path.read_text(encoding='utf-8')
            snap[name] = {'lines': len(text.splitlines()), 'bytes': path.stat().st_size}
        except Exception as e:
            snap[name] = {'lines': None, 'bytes': None, 'error': type(e).__name__}
    return snap


def _read_learning_state():
    's86-8: read learning baseline (None if missing).'
    if not LEARNING_STATE.exists():
        return None
    try:
        return json.loads(LEARNING_STATE.read_text(encoding='utf-8'))
    except Exception as _e:
        _silent("sv_return_none", _e)
        return None


def _max_session(autonomy_path):
    # s2.1b (s89): max session number in autonomy.jsonl
    mx = 0
    try:
        lines = autonomy_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return 0
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            rec = json.loads(raw)
        except Exception:
            continue
        s = rec.get("session")
        if isinstance(s, int) and s > mx:
            mx = s
    return mx


def _write_learning_state(snap):
    's86-8: write learning baseline to state file.'
    state = {
        'in_ts': datetime.now().isoformat(timespec='seconds'),
        'session': _max_session(ROOT / "self" / "autonomy.jsonl"),
        'baseline': snap,
    }
    LEARNING_STATE.parent.mkdir(parents=True, exist_ok=True)
    LEARNING_STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + chr(10), encoding='utf-8')
    print('=== s86-8 Baseline learning snapshot (' + state['in_ts'] + ') ===')
    for name, m in snap.items():
        print('  ' + name.ljust(24) + ' lines=' + str(m.get('lines')) + ' bytes=' + str(m.get('bytes')))


def _print_learning_delta(mode='out', warn_if_zero=False):
    's86-8: print delta of learning files since --in baseline.'
    state = _read_learning_state()
    if state is None:
        print('[INFO] learning: baseline missing (run --in first)')
        return
    baseline = state.get('baseline') or {}
    in_ts = state.get('in_ts', '?')
    cur = _snapshot_learning()
    print('=== s86-8 Delta learning (' + mode + ', since ' + in_ts + ') ===')
    total_lines = 0
    total_bytes = 0
    for name, _ in LEARN_FILES:
        b = baseline.get(name) or {}
        c = cur.get(name) or {}
        bl = b.get('lines') or 0
        cl = c.get('lines') or 0
        bb = b.get('bytes') or 0
        cb = c.get('bytes') or 0
        dl = cl - bl
        db = cb - bb
        total_lines += dl
        total_bytes += db
        sign_l = '+' if dl >= 0 else ''
        sign_b = '+' if db >= 0 else ''
        print('  ' + name.ljust(24) + ' ' + sign_l + str(dl) + ' lines  (' + sign_b + str(db) + ' bytes)')
    print('  ---')
    print('  TOTAL: ' + ('+' if total_lines >= 0 else '') + str(total_lines) + ' lines / ' + ('+' if total_bytes >= 0 else '') + str(total_bytes) + ' bytes')
    if total_lines <= 0 and total_bytes <= 0:
        if warn_if_zero:
            print('  [WARN] learning = 0 for session (Rule 02 p.2.5)')
            print('         did you work without writing to memory?')
    else:
        print('  [OK] learning > 0 (Rule 02 p.2.5 satisfied)')
    try:
        _print_extended_learning_delta(in_ts, mode)
    except Exception as _e:
        print('  [WARN] extended learning: ' + type(_e).__name__ + ': ' + str(_e))
    if mode == 'out':
        print('')
        print('  What the agent learned this session (fill in HANDOFF/current.md):')
        print('    1. ...')
        print('    2. ...')
        print('    3. ...')


def _snapshot_apply_delta(in_ts, log_path=None):
    # s2.1 (s89): count apply-log records since in_ts
    log = log_path if log_path is not None else (STRATEGY / "_apply_log.jsonl")
    total = 0
    applied = 0
    rejected = 0
    buckets = {}
    if not log.exists():
        return {"total": 0, "applied": 0, "rejected": 0, "buckets": {}}
    try:
        lines = log.read_text(encoding="utf-8").splitlines()
    except Exception:
        return {"total": 0, "applied": 0, "rejected": 0, "buckets": {}}
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            rec = json.loads(raw)
        except Exception:
            continue
        if "proposal_id" not in rec:
            continue
        ts = rec.get("ts") or ""
        if ts <= in_ts:
            continue
        total += 1
        if rec.get("applied"):
            applied += 1
        else:
            rejected += 1
        b = rec.get("bucket") or "?"
        buckets.update({b: buckets.get(b, 0) + 1})
    return {"total": total, "applied": applied, "rejected": rejected, "buckets": buckets}

def _snapshot_lessons_delta(lessons_path, since_date, baseline_lines):
    # s2.1 (s89): count new lesson headers by date OR by position past baseline
    total = 0
    by_date = 0
    by_tail = 0
    topics = {}
    try:
        lines = lessons_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return {"total": 0, "by_date": 0, "by_tail": 0, "topics": {}}
    pat = re.compile(r"^## (.+?)\s*(?:\((\d{4}-\d{2}-\d{2})\))?\s*$")
    for i, line in enumerate(lines):
        m = pat.match(line)
        if not m:
            continue
        title = (m.group(1) or "").strip().lower()
        d = m.group(2) or ""
        is_new = False
        if d and d >= since_date:
            by_date += 1
        if (i + 1) <= baseline_lines:
            continue
        by_tail += 1
        total += 1
        topic = "other"
        for kw in ("paste", "sig", "catchup", "security", "reflection", "verify", "baseline"):
            if kw in title:
                topic = kw
                break
        topics.update({topic: topics.get(topic, 0) + 1})
    return {"total": total, "by_date": by_date, "by_tail": by_tail, "topics": topics}

def _snapshot_steps_delta(autonomy_path, baseline_lines):
    # s2.1 (s89): count autonomy steps since in_ts
    total = 0
    done = 0
    failed = 0
    if not autonomy_path.exists():
        return {"total": 0, "done": 0, "failed": 0}
    try:
        lines = autonomy_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return {"total": 0, "done": 0, "failed": 0}
    for i, raw in enumerate(lines):
        if i < baseline_lines:
            continue
        raw = raw.strip()
        if not raw:
            continue
        try:
            rec = json.loads(raw)
        except Exception:
            continue
        total += 1
        st = rec.get("status") or ""
        if st == "done":
            done += 1
        elif st == "failed":
            failed += 1
    return {"total": total, "done": done, "failed": failed}

def _print_extended_learning_delta(in_ts, mode):
    # s2.1 (s89): print extended learning deltas
    state = _read_learning_state()
    baseline_lines = 0
    baseline_lines_auto = 0
    if state:
        bl = (state.get("baseline") or {}).get("knowledge/lessons.md") or {}
        baseline_lines = bl.get("lines") or 0
        auto = (state.get("baseline") or {}).get("self/autonomy.jsonl") or {}
        baseline_lines_auto = auto.get("lines") or 0
    since_date = in_ts.split("T").pop(0) if "T" in in_ts else in_ts

    a = _snapshot_apply_delta(in_ts)
    ls = _snapshot_lessons_delta(ROOT / "knowledge" / "lessons.md", since_date, baseline_lines)
    st = _snapshot_steps_delta(ROOT / "self" / "autonomy.jsonl", baseline_lines_auto)

    bstr = ", ".join("{}:{}".format(k, v) for k, v in (a.get("buckets") or {}).items())
    if not bstr:
        bstr = "-"
    tstr = ", ".join("{}:{}".format(k, v) for k, v in (ls.get("topics") or {}).items())
    if not tstr:
        tstr = "-"

    print("  {}LEARN{} apply:   applied={} rejected={} buckets={{{}}}".format(LB, RB, a.get("applied"), a.get("rejected"), bstr))
    print("  {}LEARN{} lessons: +{} new ({}) by_date={} by_tail={}".format(LB, RB, ls.get("total"), tstr, ls.get("by_date"), ls.get("by_tail")))
    print("  {}LEARN{} steps:   +{} (done:{} failed:{})".format(LB, RB, st.get("total"), st.get("done"), st.get("failed")))

    grand = (a.get("total") or 0) + (ls.get("total") or 0) + (st.get("total") or 0)
    if mode == "out":
        if grand == 0:
            print("  {}WARN{} learning delta=0 across apply/lessons/steps - why?".format(LB, RB))
        else:
            print("  {}OK{} extended learning delta > 0".format(LB, RB))

def check_feature(feat):
    """Возвращает dict: {status, actual, expected, ratio, reason, kind}."""
    fid = feat.get("id", "?")
    # s86-11: frozen short-circuit
    if feat.get("frozen"):
        return {
            "status": "frozen",
            "reason": "blocked_by=" + str(feat.get("blocked_by", "?")),
            "kind": "frozen",
        }
    service = feat.get("service")
    check = feat.get("check")
    artifact = feat.get("artifact")
    window = feat.get("window_hours", 24)
    expected = feat.get("expected_runs")
    keepalive = feat.get("keepalive", False)

    if service:
        # s86-6a: awake-catchup first
        _ac = _check_awake_catchup(fid)
        if _ac is not None:
            return _ac
        info = _get_launchd_runs(service)
        if info is None:
            return {"status": "unknown", "reason": "launchctl fail", "kind": "service"}
        runs = info["runs"]
        if keepalive:
            st = "alive" if info["state"] == "running" else "regression"
            return {"status": st, "actual": runs, "expected": 1, "ratio": 1.0, "reason": "keepalive state=" + info["state"], "kind": "service"}
        if expected and expected > 0:
            ratio = runs / float(expected)
            st = "alive" if ratio >= THRESHOLD else "regression"
            return {"status": st, "actual": runs, "expected": expected, "ratio": round(ratio,2), "reason": "runs=" + str(runs) + "/" + str(expected), "kind": "service"}
        return {"status": "unknown", "actual": runs, "reason": "no expected_runs", "kind": "service"}

    if check:
        res = _check_grep(check)
        st = "alive" if res["ok"] else "regression"
        return {"status": st, "reason": res.get("reason",""), "kind": "check"}

    if artifact:
        res = _check_artifact(artifact, window)
        st = "alive" if res["ok"] else "regression"
        return {"status": st, "reason": res.get("reason",""), "kind": "artifact"}

    return {"status": "unknown", "reason": "no service/check/artifact", "kind": "?"}


def _check_signing():
    # s1.6b: verify Ed25519 signatures over CORE_FILES
    try:
        from security import signing as _sg
    except Exception as e:
        return {"status": "unknown", "reason": "signing import fail: " + str(e)[:80]}
    try:
        r = _sg.verify_core()
    except Exception as e:
        return {"status": "unknown", "reason": "verify fail: " + str(e)[:80]}
    if r.get("valid"):
        return {"status": "sig_ok", "checked": r.get("checked", 0)}
    detail = r
    try:
        kill = ROOT / "strategy" / "_kill_flag.json"
        kill.write_text(json.dumps({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "expires_at": (datetime.now() + __import__("datetime").timedelta(hours=1)).isoformat(timespec="seconds"),
            "reason": "core tampered",
            "detail": detail,
        }, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")
    except Exception as _e:
        _silent("sv_pass", _e)
    return {"status": "sig_fail", "detail": detail, "reason": r.get("reason", "unknown")}


def run(mode="in"):
    _sig = _check_signing()
    if _sig["status"] == "sig_fail":
        print(LB + "SIG!" + RB + " CORE TAMPERED")
        _d = _sig.get("detail", {})
        print("  reason: " + str(_sig.get("reason")))
        print("  bad: " + str(_d.get("bad", []))[:200])
        print("---")
        print("mode=" + mode + " signing=FAIL")
        return 3
    elif _sig["status"] == "sig_ok":
        print(LB + "SIG" + RB + " core signed, checked=" + str(_sig.get("checked", 0)))
    else:
        print(LB + "SIG?" + RB + " " + str(_sig.get("reason", "unknown")))
    feats = load_features()
    if not feats:
        print("[FAIL] пустой реестр или не читается")
        return 1
    results = []
    n_alive = n_regr = n_unk = n_frozen = 0
    for f in feats:
        r = check_feature(f)
        r["id"] = f.get("id","?")
        r["desc"] = f.get("desc","")
        results.append(r)
        if r["status"] == "alive": n_alive += 1
        elif r["status"] == "regression": n_regr += 1
        elif r["status"] == "frozen": n_frozen += 1
        else: n_unk += 1

    # s93-S2: syntax_scan gate over all .py
    try:
        _ss = subprocess.run(
            [sys.executable, str(ROOT / "syntax_scan.py"), "--quiet"],
            capture_output=True, text=True, timeout=30,
        )
        if _ss.returncode != 0:
            _ss_err = (_ss.stdout or _ss.stderr or "").strip()[:200]
            results.append({
                "id": "syntax_scan_gate",
                "desc": "s93-S2: ast.parse gate over all .py",
                "status": "regression",
                "reason": "syntax_scan failed: " + _ss_err,
            })
            n_regr += 1
        else:
            results.append({
                "id": "syntax_scan_gate",
                "desc": "s93-S2: ast.parse gate over all .py",
                "status": "alive",
            })
            n_alive += 1

        # s103-0b: ПРАВИЛО №04 enforcement (soft grep)
        try:
            _rt = (ROOT / "strategy" / "00_rules.md").read_text(encoding="utf-8")
        except Exception:
            _rt = ""
        if "ПРАВИЛО №04" in _rt:
            results.append({"id": "s103_rule_04", "desc": "s103: ПРАВИЛО №04 in 00_rules.md", "status": "alive", "reason": "present"})
        else:
            results.append({"id": "s103_rule_04", "desc": "s103: ПРАВИЛО №04 in 00_rules.md", "status": "regression", "reason": "missing"})
        try:
            _ft = (ROOT / "strategy" / "_features.json").read_text(encoding="utf-8")
        except Exception:
            _ft = ""
        if "blindness_audit" in _ft:
            results.append({"id": "s103_features_blindness", "desc": "s103: blindness_audit in _features.json", "status": "alive", "reason": "present"})
        else:
            results.append({"id": "s103_features_blindness", "desc": "s103: blindness_audit in _features.json", "status": "regression", "reason": "missing"})
        # s103-0e: enforce blindness_audit for s103+ features (ПРАВИЛО №04)
        try:
            _fd = json.loads(_ft) if _ft else {}
            _miss = []
            _need = {"emission", "measurement", "actuation", "verification", "coverage", "meta"}
            def _sess_num(_s):
                _m = re.match(r"s(\d+)", str(_s or ""))
                return int(_m.group(1)) if _m else 0
            for _f in (_fd.get("features") or []):
                _c = _f.get("closed_in") or ""
                if _sess_num(_c) < 103:
                    continue
                _ba = _f.get("blindness_audit")
                _fid = _f.get("id") or _f.get("name") or "?"
                if not isinstance(_ba, dict):
                    _miss.append(_fid + ":none")
                    continue
                _m = _need - set(_ba.keys())
                if _m:
                    _miss.append(_fid + ":" + ",".join(sorted(_m)))
            if _miss:
                results.append({"id": "s103_blindness_enforce", "desc": "s103: blindness_audit for s103+ features", "status": "regression", "reason": str(len(_miss)) + " bad: " + ",".join(_miss[:3])})
                n_regr += 1
            else:
                results.append({"id": "s103_blindness_enforce", "desc": "s103: blindness_audit for s103+ features", "status": "alive", "reason": "all s103+ ok"})
                n_alive += 1
        except Exception as _e:
            results.append({"id": "s103_blindness_enforce", "desc": "s103: blindness_audit for s103+ features", "status": "unknown", "reason": type(_e).__name__ + ": " + str(_e)[:80]})
            n_unk += 1

    except Exception as _e:
        results.append({
            "id": "syntax_scan_gate",
            "desc": "s93-S2: ast.parse gate over all .py",
            "status": "unknown",
            "reason": type(_e).__name__ + ": " + str(_e)[:120],
        })
        n_unk += 1

    ts = datetime.now().isoformat(timespec="seconds")
    report = {
        "ts": ts,
        "mode": mode,
        "total": len(results),
        "alive": n_alive,
        "regression": n_regr,
        "unknown": n_unk,
        "frozen": n_frozen,
        "features": results,
    }

    for r in results:
        marker = {"alive": "[OK]  ", "regression": "[REGR]", "unknown": "[???] ", "frozen": "[FRZ] "}[r["status"]]
        extra = ""
        if "ratio" in r: extra = " ratio=" + str(r["ratio"])
        elif "reason" in r: extra = " " + str(r["reason"])[:60]
        print(marker + " " + r["id"].ljust(20) + extra)

    print("---")
    n_feats = len(feats)
    n_gates = len(results) - n_feats
    # s128-t7: [DOC] — STATE.md vs JOURNAL последняя сессия (информационно, не в regression)
    try:
        _cur_dir = ROOT / "self" / "curator"
        _state_p = _cur_dir / "STATE.md"
        _state_sess = "?"
        if _state_p.exists():
            _m = re.search(r"\*\*Текущая сессия:\*\*\s*(s\d+)", _state_p.read_text(encoding="utf-8"))
            if _m:
                _state_sess = _m.group(1)
        _journal_p = _cur_dir / "JOURNAL.jsonl"
        _journal_sess = "?"
        if _journal_p.exists():
            _lines = [l for l in _journal_p.read_text(encoding="utf-8").splitlines() if l.strip()]
            for _l in reversed(_lines):
                try:
                    _r = json.loads(_l)
                except Exception:
                    continue
                if _r.get("action") != "close":
                    continue
                _s = _r.get("session")
                if _s:
                    _journal_sess = _s
                    break
        if _state_sess != "?" and _journal_sess != "?" and _state_sess != _journal_sess:
            print("[DOC] DRIFT: STATE.md=" + _state_sess + " vs JOURNAL last=" + _journal_sess)
        else:
            print("[DOC] OK: STATE.md=" + _state_sess + " JOURNAL last=" + _journal_sess)
    except Exception as _e:
        print("[DOC] unknown: " + type(_e).__name__ + ": " + str(_e)[:80])

    print("mode=" + mode + " features=" + str(n_feats) + " gates=" + str(n_gates) + " checks=" + str(len(results)) + " alive=" + str(n_alive) + " regression=" + str(n_regr) + " unknown=" + str(n_unk) + " frozen=" + str(n_frozen))
    try:
        from llm_health import format_line as _llm_line
        print("[LLM] " + _llm_line())
    except Exception as _e:
        print("[LLM] unavailable (" + type(_e).__name__ + ")")
    try:
        from llm_preflight import check as _pf_check
        try:
            from llm_call import PROVIDERS as _pf_provs
        except Exception:
            _pf_provs = None
        _pf_res = _pf_check(_pf_provs)
        print(_pf_res.get("summary_line", "[LLM-PF] ?"))
    except Exception as _e:
        print("[LLM-PF] unavailable (" + type(_e).__name__ + ")")

    try:
        import catchup
        _rep = catchup.report()
        _sc = _rep.get("selfcheck", {})
        _gap = _sc.get("gap_s")
        _gap_h = "-" if _gap is None else "{:.1f}h".format(_gap / 3600.0)
        print("[INFO] catchup: selfcheck gap=" + _gap_h + " missed=" + str(_sc.get("missed_count", 0)))
    except Exception as _e:
        print("[INFO] catchup: unavailable (" + type(_e).__name__ + ")")

    if mode in ("in", "out"):
        try:
            HEALTH.parent.mkdir(parents=True, exist_ok=True)
            HEALTH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            with HEALTH_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps(report, ensure_ascii=False) + chr(10))
        except Exception as e:
            print("[WARN] не записал health: " + str(e)[:120])

        if n_regr > 0:
            try:
                from journal import log_event
                for r in results:
                    if r["status"] == "regression":
                        log_event(site="autonomy", action="verify", result="warn",
                                  note=r["id"] + ": " + str(r.get("reason",""))[:100])
            except Exception as e:
                print("[WARN] journal: " + str(e)[:120])

            try:
                with ALERTS.open("a", encoding="utf-8") as f:
                    for r in results:
                        if r["status"] == "regression":
                            f.write("- [" + ts + "] autonomy/" + r["id"] + " REGRESSION: " + str(r.get("reason",""))[:100] + chr(10))
            except Exception as e:
                print("[WARN] alerts: " + str(e)[:120])

    # s86-8: learning snapshot on --in
    if mode == "in":
        try:
            _write_learning_state(_snapshot_learning())
        except Exception as _e:
            print("[WARN] learning snapshot: " + type(_e).__name__ + ": " + str(_e)[:100])

    # s86-8: learning delta on --mid/--out
    if mode in ("mid", "out"):
        try:
            _print_learning_delta(mode=mode, warn_if_zero=(mode == "out"))
        except Exception as _e:
            print("[WARN] learning delta: " + type(_e).__name__ + ": " + str(_e)[:100])

    return 0 if n_regr == 0 else 2


def _self_lint_block():
    """s210: 6th axis pre-flight - self_lint check."""
    import subprocess, sys
    lint = pathlib.Path(__file__).resolve().parent / "scripts" / "self_lint.py"
    if not lint.exists():
        return
    print("=== 6. self_lint ===")
    try:
        r = subprocess.run([sys.executable, str(lint)], capture_output=True, text=True, timeout=60)
        out = (r.stdout or "").strip().splitlines()
        for line in out[:5]:
            print("  " + line)
    except Exception as e:
        print(f"  self_lint err: {e}")


def main(argv=None):
    p = argparse.ArgumentParser(description="session_verify (s84-4)")
    _self_lint_block()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--in", dest="mode", action="store_const", const="in")
    g.add_argument("--mid", dest="mode", action="store_const", const="mid")
    g.add_argument("--out", dest="mode", action="store_const", const="out")
    args = p.parse_args(argv)
    return run(args.mode)


if __name__ == "__main__":
    sys.exit(main())
