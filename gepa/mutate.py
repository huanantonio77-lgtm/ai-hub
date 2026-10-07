# gepa/mutate.py - GEPA step: create challenger from incumbent via LLM mutation.
# s127-T2: challenger создаётся LLM-мутацией incumbent, а не вручную.
#
# Usage:
#   python3 gepa/mutate.py --target self_reflect [--dry-run]
#   python3 gepa/mutate.py --target self_reflect --report
#   python3 gepa/mutate.py --selftest
#
# Pipeline:
#   1. Read incumbent text from strategy/prompts/<target>/<incumbent>.md
#   2. Call llm() with meta-prompt asking for a single improvement
#   3. Write strategy/prompts/<target>/<new_id>.md
#   4. Update _registry.json: challenger = <new_id>, history += {action: mutate}

from __future__ import annotations
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PROMPTS = ROOT / "strategy" / "prompts"


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

META_SYSTEM = (
    "You are an editor of system prompts for an AI agent. "
    "You receive the current incumbent prompt. "
    "Propose one targeted improvement. "
    "Return ONLY the new prompt text, no explanations, no markdown fence."
)

META_USER_TEMPLATE = (
    "Target task: {target}\n\n"
    "Current incumbent prompt:\n"
    "---\n{incumbent}\n---\n\n"
    "Requirements:\n"
    "1. Keep ALL mandatory rules and structure of the incumbent.\n"
    "2. Strengthen ONE weak part: make criteria concrete, remove ambiguity, "
    "add an example of the 'allowed / not allowed' boundary.\n"
    "3. Return ONLY the new prompt text. No explanations, no markdown fence.\n"
)


def _target_dir(target):
    return PROMPTS / target


def _reg_path(target):
    return _target_dir(target) / "_registry.json"


def _load_reg(target):
    return json.loads(_reg_path(target).read_text(encoding="utf-8"))


def _save_reg(reg, target):
    p = _reg_path(target)
    if p.exists():
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        bak = p.parent / (p.name + ".bak-" + _next_session() + "-" + ts)
        bak.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    p.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")


def _next_vid(target):
    d = _target_dir(target)
    mx = -1
    for f in d.glob("v*_*.md"):
        m = re.match(r"v(\d+)_", f.name)
        if m:
            mx = max(mx, int(m.group(1)))
    return "v" + str(mx + 1) + "_mutated"


def mutate(target, dry_run=False):
    reg = _load_reg(target)
    inc_id = reg.get("incumbent")
    if not inc_id:
        return {"ok": False, "reason": "no incumbent"}
    inc_path = _target_dir(target) / (inc_id + ".md")
    if not inc_path.exists():
        return {"ok": False, "reason": "incumbent file missing: " + str(inc_path)}
    incumbent = inc_path.read_text(encoding="utf-8").strip()
    if not incumbent:
        return {"ok": False, "reason": "incumbent empty"}

    new_id = _next_vid(target)
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "target": target,
            "from": inc_id,
            "to": new_id,
            "chars_incumbent": len(incumbent),
        }

    try:
        from llm_call import llm
    except Exception as e:
        return {"ok": False, "reason": "llm_call import: " + type(e).__name__ + ": " + str(e)[:120]}

    user = META_USER_TEMPLATE.format(target=target, incumbent=incumbent)
    try:
        new_text = llm(META_SYSTEM, user, want_json=False, limit=1500, task="text")
    except Exception as e:
        return {"ok": False, "reason": "llm call: " + type(e).__name__ + ": " + str(e)[:160]}

    if not isinstance(new_text, str) or not new_text.strip():
        return {"ok": False, "reason": "llm returned empty/non-string"}
    new_text = new_text.strip()
    # reject markdown fence if LLM ignored instruction
    if new_text.startswith("```"):
        new_text = re.sub(r"^```[a-zA-Z]*\n", "", new_text)
        new_text = re.sub(r"\n```$", "", new_text).strip()
    if len(new_text) < 200:
        return {"ok": False, "reason": "mutated too short: " + str(len(new_text)) + " chars"}

    new_path = _target_dir(target) / (new_id + ".md")
    new_path.write_text(new_text + "\n", encoding="utf-8")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    reg.setdefault("history", []).append({
        "ts": now,
        "action": "mutate",
        "from": inc_id,
        "to": new_id,
        "method": "llm",
    })
    reg["challenger"] = new_id
    reg["generation"] = int(reg.get("generation", 0)) + 1
    reg["updated"] = now[:10]
    _save_reg(reg, target)

    return {
        "ok": True,
        "target": target,
        "from": inc_id,
        "to": new_id,
        "chars_incumbent": len(incumbent),
        "chars_new": len(new_text),
    }


def report(target):
    reg = _load_reg(target)
    d = _target_dir(target)
    lines = ["GEPA mutate · " + target]
    lines.append("incumbent:  " + str(reg.get("incumbent")))
    lines.append("challenger: " + str(reg.get("challenger")))
    lines.append("generation: " + str(reg.get("generation")))
    lines.append("variants:")
    for f in sorted(d.glob("v*.md")):
        lines.append("  " + f.name + " (" + str(f.stat().st_size) + "b)")
    return "\n".join(lines)


def _selftest():
    import tempfile, shutil
    tmp = Path(tempfile.mkdtemp(prefix="gepa_mut_"))
    global PROMPTS
    old = PROMPTS
    try:
        tgt = tmp / "test_target"
        tgt.mkdir()
        (tgt / "v0_incumbent.md").write_text("incumbent text " * 20, encoding="utf-8")
        (tgt / "v1_baseline.md").write_text("baseline text", encoding="utf-8")
        (tgt / "_registry.json").write_text(
            json.dumps({
                "target": "test_target", "incumbent": "v0_incumbent",
                "challenger": None, "generation": 1, "history": []
            }, ensure_ascii=False), encoding="utf-8")
        PROMPTS = tmp
        v = _next_vid("test_target")
        assert v == "v2_mutated", v
        r = mutate("test_target", dry_run=True)
        assert r["ok"] is True, r
        assert r["to"] == "v2_mutated", r
        assert r["from"] == "v0_incumbent", r
        rep = report("test_target")
        assert "v0_incumbent" in rep, rep
        print("gepa/mutate selftest: ok")
    finally:
        PROMPTS = old
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="self_reflect")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        _selftest()
        return 0
    if args.report:
        print(report(args.target))
        return 0
    r = mutate(args.target, dry_run=args.dry_run)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())