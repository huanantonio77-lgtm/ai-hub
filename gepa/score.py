# gepa/score.py - GEPA v0: metrics for prompt variants
# Public API:
#   score(window_days=None, runs_path=None, state_path=None, registry_path=None) -> dict
#   report(window_days=None) -> str
#   _selftest() -> None

from __future__ import annotations
import json, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = ROOT / "strategy" / "prompts"
RUNS_FILE = PROMPTS_DIR / "_runs.jsonl"
DEFAULT_TARGET = "repair_task"
REGISTRY_FILE = PROMPTS_DIR / DEFAULT_TARGET / "_registry.json"  # legacy default

def _registry_file(target=None):
    return PROMPTS_DIR / (target or DEFAULT_TARGET) / "_registry.json"
STATE_FILE = ROOT / "strategy" / "tasks" / "_state.json"


def _read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _read_runs(path=None):
    p = path or RUNS_FILE
    try:
        if not p.exists():
            return []
        text = p.read_text(encoding="utf-8")
    except Exception:
        return []
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def _parse_ts(s):
    if not isinstance(s, str):
        return None
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(t)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except Exception:
        return None


def score(window_days=None, runs_path=None, state_path=None, registry_path=None, target=None):
    runs = _read_runs(runs_path)
    state = _read_json(state_path or STATE_FILE, {})
    if not isinstance(state, dict):
        state = {}
    _tgt = target or DEFAULT_TARGET
    _reg_path = registry_path or _registry_file(_tgt)
    reg = _read_json(_reg_path, {})
    wd = window_days
    if wd is None:
        wd = reg.get("window_days", 14) if isinstance(reg, dict) else 14
    try:
        wd = int(wd)
    except Exception:
        wd = 14

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=wd)

    by_variant = {}
    for r in runs:
        if not isinstance(r, dict):
            continue
        ts = _parse_ts(r.get("ts"))
        if ts is None or ts < cutoff:
            continue
        rt = r.get("target") or DEFAULT_TARGET
        if rt != _tgt:
            continue
        vid = r.get("variant_id")
        if not vid:
            continue
        by_variant.setdefault(vid, []).append(r)

    result = {}
    for vid, rs in by_variant.items():
        keys = [r.get("task_key") for r in rs if r.get("task_key")]
        tracked = [k for k in keys if k in state]
        closed = 0
        attempts = []
        quality_scores = []
        grounded = 0
        for k in tracked:
            s = state.get(k) or {}
            if s.get("status") == "done":
                closed += 1
            a = s.get("attempts")
            if isinstance(a, int):
                attempts.append(a)
            q = s.get("quality_score")
            if isinstance(q, (int, float)):
                quality_scores.append(q)
                if q >= 0.8:
                    grounded += 1
        chars = [r.get("chars", 0) for r in rs if isinstance(r.get("chars"), int)]
        result[vid] = {
            "runs": len(rs),
            "keys_total": len(keys),
            "keys_tracked": len(tracked),
            "closed": closed,
            "success_rate": (closed / len(tracked)) if tracked else 0.0,
            "mean_attempts": (sum(attempts) / len(attempts)) if attempts else 0.0,
            "mean_chars": (sum(chars) / len(chars)) if chars else 0.0,
            "mean_quality": (sum(quality_scores) / len(quality_scores)) if quality_scores else 0.0,
            "grounded": grounded,
            "grounded_rate": (grounded / len(tracked)) if tracked else 0.0,
        }
    return result


FMT = "{:<20s} {:>4d}  {:>7d}  {:>6d}  {:>5.1f}   {:>8.2f}  {:>5.0f}  {:>6.2f}"


def report(window_days=None, target=None):
    _tgt = target or DEFAULT_TARGET
    reg = _read_json(_registry_file(_tgt), {})
    inc = reg.get("incumbent") if isinstance(reg, dict) else None
    chl = reg.get("challenger") if isinstance(reg, dict) else None
    wd = window_days or (reg.get("window_days", 14) if isinstance(reg, dict) else 14)
    sc = score(window_days=wd, target=_tgt)
    lines = []
    lines.append("=== GEPA score (window " + str(wd) + " days) ===")
    lines.append("incumbent=" + str(inc) + "  challenger=" + str(chl))
    lines.append("")
    lines.append("variant_id           runs  tracked  closed  succ%   mean_att  chars   mean_q")
    if not sc:
        lines.append("(no data yet)")
    else:
        for vid in sorted(sc.keys()):
            m = sc[vid]
            lines.append(FMT.format(vid, m["runs"], m["keys_tracked"], m["closed"], m["success_rate"] * 100.0, m["mean_attempts"], m["mean_chars"], m["mean_quality"]))
    return chr(10).join(lines)


def _cli_target():
    try:
        i = sys.argv.index("--target")
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    except ValueError:
        pass
    return None


def _selftest():
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="gepa_score_"))
    now = datetime.now(timezone.utc)
    runs = [
        {"ts": now.isoformat(timespec="seconds"), "variant_id": "v0_incumbent", "task_key": "task_01_aaa", "chars": 0},
        {"ts": now.isoformat(timespec="seconds"), "variant_id": "v0_incumbent", "task_key": "task_02_bbb", "chars": 0},
        {"ts": now.isoformat(timespec="seconds"), "variant_id": "v1_baseline", "task_key": "task_03_ccc", "chars": 2000},
        {"ts": now.isoformat(timespec="seconds"), "variant_id": "v1_baseline", "task_key": "task_04_ddd", "chars": 2000},
    ]
    rp = tmp / "runs.jsonl"
    rp.write_text(chr(10).join(json.dumps(r, ensure_ascii=False) for r in runs) + chr(10), encoding="utf-8")
    sp = tmp / "state.json"
    state = {
        "task_01_aaa": {"status": "done", "attempts": 1, "quality_score": 1.0},
        "task_02_bbb": {"status": "open", "attempts": 3},
        "task_03_ccc": {"status": "done", "attempts": 1, "quality_score": 1.0},
        "task_04_ddd": {"status": "done", "attempts": 1, "quality_score": 1.0},
    }
    sp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    gp = tmp / "reg.json"
    gp.write_text(json.dumps({"window_days": 14}), encoding="utf-8")

    sc = score(runs_path=rp, state_path=sp, registry_path=gp)
    assert set(sc.keys()) == {"v0_incumbent", "v1_baseline"}, "keys=" + str(sorted(sc.keys()))
    assert sc["v0_incumbent"]["runs"] == 2
    assert sc["v0_incumbent"]["closed"] == 1
    assert abs(sc["v0_incumbent"]["success_rate"] - 0.5) < 1e-9
    assert sc["v1_baseline"]["runs"] == 2
    assert sc["v1_baseline"]["closed"] == 2
    assert abs(sc["v1_baseline"]["success_rate"] - 1.0) < 1e-9
    assert abs(sc["v0_incumbent"]["mean_quality"] - 1.0) < 1e-9
    assert sc["v0_incumbent"]["grounded"] == 1
    assert abs(sc["v0_incumbent"]["grounded_rate"] - 0.5) < 1e-9
    assert abs(sc["v1_baseline"]["mean_quality"] - 1.0) < 1e-9
    assert sc["v1_baseline"]["grounded"] == 2
    assert abs(sc["v1_baseline"]["grounded_rate"] - 1.0) < 1e-9
    print("SELFTEST-PASS variants=" + str(len(sc)) + " v1_succ=1.00 v0_succ=0.50")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    elif "--report" in sys.argv:
        print(report(target=_cli_target()))
    else:
        print("gepa/score.py - use --selftest or --report")

