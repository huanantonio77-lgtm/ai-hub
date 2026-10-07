# gepa/gepa_step.py - GEPA v0 CLI: report / promote / reject
# Manual control only. No LLM calls. No auto-switch.

from __future__ import annotations
import argparse, json, shutil, sys
import re
from datetime import datetime, timezone
from pathlib import Path

THIS = Path(__file__).resolve()
ROOT = THIS.parent.parent
sys.path.insert(0, str(ROOT))

from gepa import registry as R
from gepa import score as S

REG = R.REGISTRY_FILE

def _reg_path(target=None):
    return R._registry_file(target) if target else REG
AUTONOMY = ROOT / "self" / "autonomy.jsonl"


def _next_session():
    """Working session id from STATE.md (e.g. 's134')."""
    p = ROOT / "self" / "curator" / "STATE.md"
    if not p.exists():
        return "s000"
    try:
        txt = p.read_text(encoding="utf-8")
    except Exception:
        return "s000"
    for line in txt.splitlines():
        if "\u0421\u043b\u0435\u0434\u0443\u044e\u0449\u0430\u044f \u0441\u0435\u0441\u0441\u0438\u044f" in line:
            m = re.search(r"s(\d+)", line)
            if m:
                return "s" + m.group(1)
    return "s000"


def _ts():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _backup(path):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = path.with_name(path.name + ".bak-" + _next_session() + "-" + ts)
    shutil.copy2(path, bak)
    return bak


def _append_autonomy(rec):
    try:
        AUTONOMY.parent.mkdir(parents=True, exist_ok=True)
        with AUTONOMY.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + chr(10))
    except Exception:
        pass


def report(target=None):
    reg = R.load_registry(target) or {}
    lines = []
    lines.append(S.report(target=target))
    lines.append("")
    lines.append("=== registry ===")
    lines.append("  target:     " + str(reg.get("target")))
    lines.append("  incumbent:  " + str(reg.get("incumbent")))
    lines.append("  challenger: " + str(reg.get("challenger")))
    lines.append("  generation: " + str(reg.get("generation")))
    hist = reg.get("history") or []
    lines.append("  history:    " + str(len(hist)) + " events")
    for h in hist[-5:]:
        lines.append("    - " + str(h.get("ts")) + "  " + str(h.get("action")) + "  " + str(h.get("from")) + " -> " + str(h.get("to")))
    return chr(10).join(lines)


def _load_reg_strict(target=None):
    _p = _reg_path(target)
    if not _p.exists():
        raise RuntimeError("registry not found: " + str(_p))
    return json.loads(_p.read_text(encoding="utf-8"))


def _save_reg(reg, target=None):
    _reg_path(target).write_text(json.dumps(reg, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")


def promote(target=None):
    reg = _load_reg_strict(target)
    old_inc = reg.get("incumbent")
    new_inc = reg.get("challenger")
    if not new_inc:
        return {"ok": False, "reason": "no challenger to promote"}
    bak = _backup(_reg_path(target))
    reg["incumbent"] = new_inc
    reg["challenger"] = None
    reg["generation"] = int(reg.get("generation", 1)) + 1
    reg["updated"] = datetime.now().date().isoformat()
    entry = {
        "ts": _ts(),
        "action": "promote",
        "from": old_inc,
        "to": new_inc,
        "backup": bak.name,
    }
    hist = reg.get("history") or []
    hist.append(entry)
    reg["history"] = hist
    _save_reg(reg, target)
    _append_autonomy({"ts": _ts(), "event": "gepa_promote", "from": old_inc, "to": new_inc})
    return {"ok": True, "from": old_inc, "to": new_inc, "backup": bak.name}


def reject(target=None):
    reg = _load_reg_strict(target)
    old_chl = reg.get("challenger")
    if not old_chl:
        return {"ok": False, "reason": "no challenger to reject"}
    bak = _backup(_reg_path(target))
    reg["challenger"] = None
    reg["updated"] = datetime.now().date().isoformat()
    entry = {
        "ts": _ts(),
        "action": "reject",
        "from": old_chl,
        "to": None,
        "backup": bak.name,
    }
    hist = reg.get("history") or []
    hist.append(entry)
    reg["history"] = hist
    _save_reg(reg, target)
    _append_autonomy({"ts": _ts(), "event": "gepa_reject", "variant": old_chl})
    return {"ok": True, "rejected": old_chl, "backup": bak.name}


def _selftest():
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="gepa_step_"))
    tmp_reg = tmp / "_registry.json"
    tmp_aut = tmp / "autonomy.jsonl"
    global REG, AUTONOMY
    old_reg, old_aut = REG, AUTONOMY
    REG = tmp_reg
    AUTONOMY = tmp_aut
    try:
        base = {"target": "repair_task", "incumbent": "v0_incumbent", "challenger": "v1_baseline", "generation": 1, "history": []}
        REG.write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
        out = promote()
        assert out["ok"] is True, str(out)
        assert out["from"] == "v0_incumbent", str(out)
        assert out["to"] == "v1_baseline", str(out)
        reg1 = json.loads(REG.read_text(encoding="utf-8"))
        assert reg1["incumbent"] == "v1_baseline", str(reg1)
        assert reg1["challenger"] is None
        assert reg1["generation"] == 2
        assert len(reg1["history"]) == 1
        out2 = promote()
        assert out2["ok"] is False, str(out2)
        REG.write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
        out3 = reject()
        assert out3["ok"] is True, str(out3)
        assert out3["rejected"] == "v1_baseline", str(out3)
        reg3 = json.loads(REG.read_text(encoding="utf-8"))
        assert reg3["incumbent"] == "v0_incumbent"
        assert reg3["challenger"] is None
        assert len(reg3["history"]) == 1
        out4 = reject()
        assert out4["ok"] is False, str(out4)
        print("SELFTEST-PASS promote+reject ok")
    finally:
        REG = old_reg
        AUTONOMY = old_aut


def main():
    ap = argparse.ArgumentParser(description="GEPA v0 step CLI")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--promote", action="store_true")
    ap.add_argument("--reject", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--target", default=None)
    args = ap.parse_args()
    if args.selftest:
        _selftest()
        return
    if args.promote:
        print(json.dumps(promote(target=args.target), ensure_ascii=False))
        return
    if args.reject:
        print(json.dumps(reject(target=args.target), ensure_ascii=False))
        return
    if args.report or len(sys.argv) == 1:
        print(report(target=args.target))
        return
    ap.print_help()


if __name__ == "__main__":
    main()

