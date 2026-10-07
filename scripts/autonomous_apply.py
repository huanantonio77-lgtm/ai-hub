#!/usr/bin/env python3
# s177: autonomous classify of SELF_PROPOSALS.
# Closes cycle steps 4-8: assess -> design -> apply -> verify -> mark.
# MVP: heuristic rules; skeleton generation; NO code write yet (safe).
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROPOSALS = ROOT / "self" / "curator" / "SELF_PROPOSALS.jsonl"
REPORT = ROOT / "self" / "curator" / "CLASSIFY_REPORT.jsonl"
NEXT_SESS = ROOT / "self" / "curator" / "NEXT_SESSION.md"

# s189-p1a: session tag from STATE.md (fallback s189)
def _read_session_tag():
    try:
        st = (ROOT / 'self' / 'curator' / 'STATE.md').read_text(encoding='utf-8')
        for ln in st.splitlines():
            if 'Следующая сессия' in ln:  # s191-p4
                for tok in ln.replace('*',' ').replace(':',' ').split():
                    t = tok.rstrip('.')
                    if len(t) > 1 and t[0] == 's' and t[1:].isdigit():
                        return t
    except Exception:
        pass
    return 's191'  # s191-p4

SESSION_TAG = _read_session_tag()

def _is_session_idx_dir(name):
    if '_idx' not in name: return False
    pre = name.split('_idx', 1)[0]
    return pre.startswith('s') and pre[1:].isdigit()


if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import scripts.limits_gateway as gw


# --- step 4: assess (deterministic keyword heuristic) ---
APPLY_WORDS = (
    "gateway", "quota", "billing", "metering", "enforcement",
    "rate-limit", "rate limit", "provider-adapter", "provider adapter",
)
REJECT_WORDS = (
    "provenance", "comparative", "survey", "overview", "analysis",
    "review", "taxonomy",
)
DEFER_WORDS = (
    "protocol", "framework", "architecture", "contract",
)


def _blob(rec):
    # s177-r5: only CONTENT fields (title, technique).
    # problem/source_query are IDENTICAL for a batch -> flood signal.
    parts = []
    for k in ("title", "technique"):
        v = rec.get(k)
        if isinstance(v, str):
            parts.append(v.lower())
    return " ".join(parts)


def classify_one(rec):
    # returns (action: "apply"|"reject"|"defer", reason: str)
    if rec.get("status") != "pending":
        return ("skip", "not pending: " + str(rec.get("status")))
    text = _blob(rec)
    # s179: rules from LEARNING_RULES.md (fallback: hardcoded tuples).
    try:
        from scripts.learning_rules import load_rules
        _r = load_rules()
    except Exception:
        _r = None
    if _r:
        _apply = _r["apply_techniques"]
        _reject = _r["reject_words"]
        _defer = _r["defer_words"]
    else:
        _apply, _reject, _defer = APPLY_WORDS, REJECT_WORDS, DEFER_WORDS
    # s177-r5: REJECT first -> APPLY -> DEFER.
    for w in _reject:
        if w in text:
            return ("reject", "kw: " + w)
    for w in _apply:
        if w in text:
            return ("apply", "kw: " + w)
    for w in _defer:
        if w in text:
            return ("defer", "kw: " + w)
    return ("defer", "no keyword matched")


# --- step 5-8 pipeline (called per proposal) ---
def _append_report(rec):
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with REPORT.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def classify_all(proposals_path=None, dry=True, verbose=True):
    # returns dict summary: {apply, reject, defer, skip, total}
    path = Path(proposals_path) if proposals_path else PROPOSALS
    if not path.exists():
        return {"total": 0, "error": "no proposals file"}
    lines = path.read_text(encoding="utf-8").splitlines()
    summary = {"apply": 0, "reject": 0, "defer": 0, "skip": 0,
               "total": len(lines), "dry": dry, "ts": int(time.time())}
    for i, ln in enumerate(lines):
        try:
            rec = json.loads(ln)
        except Exception:
            summary["skip"] += 1
            continue
        action, reason = classify_one(rec)
        # s192-p5: classify_all не пишет артефакты -> apply без файла недопустим
        if action == "apply" and not dry:
            action = "defer"
            reason = "classify_all:no_artifact (s192-p5)"
        summary[action] = summary.get(action, 0) + 1
        if verbose:
            print("  [%d] %s | %s | %s"
                  % (i, action, reason, (rec.get("title") or "")[:50]))
        if action in ("apply", "reject", "defer") and not dry:
            ok, msg = gw.set_status(i, action,
                                    note="classify_all: " + reason)
            _append_report({"ts": int(time.time()), "idx": i,
                            "action": action, "reason": reason,
                            "ok": ok, "msg": msg,
                            "title": (rec.get("title") or "")[:120]})
    return summary


# --- step 5: design skeleton ---
DRAFTS_DIR = ROOT / "self" / "curator" / "drafts"
MAX_DRAFTS = 20  # s188-a2: cap draft dirs

# s189-p1b: detect TODO-only skeleton (no real code)
def _is_skeleton_only(text):
    return 'TODO (design):' in text and 'def ' not in text



def _slug(s, maxlen=40):
    out = []
    for ch in (s or "").lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in " -_/.":
            out.append("_")
    s2 = "".join(out).strip("_")
    while "__" in s2:
        s2 = s2.replace("__", "_")
    return (s2[:maxlen] or "proposal")


def _tech_hash(tech):
    import hashlib
    if not tech:
        return None
    return hashlib.md5(tech.strip().lower().encode("utf-8")).hexdigest()[:10]


def _existing_tech_hashes():
    import re
    hashes = set()
    if not DRAFTS_DIR.exists():
        return hashes
    for d in DRAFTS_DIR.iterdir():
        if not d.is_dir() or not _is_session_idx_dir(d.name):
            continue
        for f in d.iterdir():
            if f.suffix != ".py" or f.name.startswith("test_"):
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            m = re.search(r"^# technique:\s*(.+)$", text, re.MULTILINE)
            if m:
                h = _tech_hash(m.group(1))
                if h:
                    hashes.add(h)
    return hashes


def _draft_dir_count():
    if not DRAFTS_DIR.exists():
        return 0
    return sum(1 for d in DRAFTS_DIR.iterdir()
               if d.is_dir() and _is_session_idx_dir(d.name))


def design_skeleton(rec, idx):
    # returns dict: {slug, module_name, draft_dir, module_text, todo}
    slug = _slug(rec.get("technique") or rec.get("title") or "")
    mod_name = "auto_" + slug + "_" + SESSION_TAG
    draft_dir = DRAFTS_DIR / (SESSION_TAG + "_idx" + str(idx))
    header = (
        "#!/usr/bin/env python3\n"
        "# " + SESSION_TAG + " DRAFT (autonomous_apply) - idx=" + str(idx) + "\n"
        "# source: " + str(rec.get("paper_id") or "") + "\n"
        "# title: " + str(rec.get("title") or "")[:120] + "\n"
        "# technique: " + str(rec.get("technique") or "")[:120] + "\n"
        "# NOTE: this is a SKELETON. Human review required before move.\n"
        "import json\nimport sys\nimport time\nfrom pathlib import Path\n\n"
        "ROOT = Path(__file__).resolve().parent.parent\n"
    )
    todo = (
        "# TODO (design):\n"
        "# 1. identify concrete API surface (check/call/track?)\n"
        "# 2. wire into scripts/limits_gateway if quota-related\n"
        "# 3. add test <name>_" + SESSION_TAG + ".py\n"
        "# 4. run test + sign_gate\n"
    )
    module_text = header + "\n" + todo + "\n"
    return {"slug": slug, "module_name": mod_name,
            "draft_dir": str(draft_dir), "module_text": module_text,
            "todo": todo}


def write_draft(rec, idx, dry=True, verbose=True):
    plan = design_skeleton(rec, idx)
    if _is_skeleton_only(plan["module_text"]):
        if verbose:
            print("  skip skeleton-only:", plan["module_name"])
        return plan
    d = Path(plan["draft_dir"])
    f = d / (plan["module_name"] + ".py")
    if verbose:
        print("  draft:", f)
    if not dry:
        d.mkdir(parents=True, exist_ok=True)
        f.write_text(plan["module_text"], encoding="utf-8")
    return plan


# --- step 7: test skeleton ---
def write_test_draft(rec, idx, plan, dry=True, verbose=True):
    # s189-p1b-fix: same skeleton-only guard as write_draft
    if _is_skeleton_only(plan.get("module_text", "")):
        if verbose:
            print("  skip test skeleton-only:", plan["module_name"])
        return
    d = Path(plan["draft_dir"])  # _p1b_fix
    name = plan["module_name"]
    test_name = "test_" + name + ".py"
    f = d / test_name
    text = (
        "#!/usr/bin/env python3\n"
        "# " + SESSION_TAG + " DRAFT test - idx=" + str(idx) + "\n"
        "# auto-generated by autonomous_apply.py\n"
        "import unittest\n\n"
        "class AutoIdx" + str(idx) + "Test(unittest.TestCase):\n"
        "    def test_placeholder(self):\n"
        "        # TODO: real checks after human review\n"
        "        self.assertTrue(True)\n\n"
        "if __name__ == '__main__':\n"
        "    unittest.main()\n"
    )
    if verbose:
        print("  test draft:", f)
    if not dry:
        d.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    return {"test_path": str(f)}


# --- step 8 (part): verify sign-gate ---
def verify_draft(plan):
    # AST-check module_text and test_text (if any).
    import ast as _ast
    res = {"ast_module": False, "ast_test": False, "err": ""}
    try:
        _ast.parse(plan["module_text"])
        res["ast_module"] = True
    except Exception as e:
        res["err"] = "module: " + str(e)[:150]
        return res
    t = plan.get("test_text")
    if t:
        try:
            _ast.parse(t)
            res["ast_test"] = True
        except Exception as e:
            res["err"] = "test: " + str(e)[:150]
    else:
        res["ast_test"] = True
    return res


# --- orchestrator: full cycle step 4 -> 8 ---
def verify_artifact_status(row, dry=False):
    """s192-p5: единый финальный чекер — системное закрытие класса
    s188-r5 -> s189-r1 -> s190-r0 -> s191-r0 -> s192-r0 (6-я точка).
    row['action'] — source of truth. Синхронизирует row при понижении.
    """
    act = row.get("action") or "skip"
    if act != "apply":
        return act
    if dry:
        return act
    d = row.get("draft_dir")
    if not d or not Path(d).exists():
        row["action"] = "defer"
        row["reason"] = "artifact_missing (s192-p5)"
        row["artifact_missing"] = str(d)
        return "defer"
    if not row.get("verify_ok", False):
        row["action"] = "defer"
        row["reason"] = "verify_not_ok (s192-p5)"
        return "defer"
    return "apply"


def run_pipeline(proposals_path=None, dry=True, verbose=True,
                 drafts=True):
    # returns list of per-proposal results (dicts).
    path = Path(proposals_path) if proposals_path else PROPOSALS
    if not path.exists():
        return [{"error": "no proposals file: " + str(path)}]
    results = []
    _existing_techs = _existing_tech_hashes()
    _draft_count_cur = _draft_dir_count()
    for i, ln in enumerate(path.read_text(encoding="utf-8").splitlines()):
        try:
            rec = json.loads(ln)
        except Exception as e:
            results.append({"idx": i, "action": "skip",
                            "reason": "bad json: " + str(e)[:80]})
            continue
        action, reason = classify_one(rec)
        row = {"idx": i, "action": action, "reason": reason,
               "title": (rec.get("title") or "")[:80]}
        if action == "apply":
            plan = design_skeleton(rec, i)
            _skip = None
            if drafts:
                _th = _tech_hash(rec.get("technique") or "")
                if _th and _th in _existing_techs:
                    _skip = "dedup"
                elif _draft_count_cur >= MAX_DRAFTS:
                    _skip = "cap"
                else:
                    write_draft(rec, i, dry=dry, verbose=verbose)
                    write_test_draft(rec, i, plan, dry=dry, verbose=verbose)
                    if not dry:
                        if not Path(plan["draft_dir"]).exists():
                            _skip = "skeleton_only"
                        else:
                            if _th:
                                _existing_techs.add(_th)
                            _draft_count_cur += 1
            if _skip:
                row["draft_skipped"] = _skip
                if _skip in ("skeleton_only", "dedup", "cap"):  # s191-p0
                    action = "defer"
                    row["action"] = "defer"
                    row["reason"] = _skip  # s191-p0
            v = verify_draft(plan)
            row["ast_module"] = v["ast_module"]
            row["ast_test"] = v["ast_test"]
            row["draft_dir"] = plan["draft_dir"]
            row["module_name"] = plan["module_name"]
            row["verify_ok"] = bool(v["ast_module"] and v["ast_test"])
            if not row["verify_ok"]:
                row["action"] = "defer"
                row["reason"] = "verify failed: " + v.get("err", "")
        # s192-p5: финальный чекер — row['action']/row['reason'] как source of truth
        action = verify_artifact_status(row, dry=dry)
        reason = row.get("reason", reason)
        if action in ("apply", "reject", "defer") and not dry:
            ok, msg = gw.set_status(i, action,
                                    note="run_pipeline: " + reason)
            row["set_status_ok"] = ok
            row["set_status_msg"] = msg
            _append_report({"ts": int(time.time()), "idx": i,
                            "action": action, "reason": reason,
                            "ok": ok, "msg": msg, "source": "run_pipeline",
                            "title": (rec.get("title") or "")[:120]})
        results.append(row)
        if verbose:
            print("  [%d] %s | %s" % (i, row["action"], reason))
    return results


def _main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: autonomous_apply.py")
        print("       classify [--commit] [--props PATH]")
        print("       pipeline [--write] [--props PATH]")
        return 0
    cmd = argv[0]
    dry = "--commit" not in argv and "--write" not in argv
    props = None
    if "--props" in argv:
        props = argv[argv.index("--props") + 1]
    if cmd == "classify":
        print(classify_all(proposals_path=props, dry=dry, verbose=True))
        return 0
    if cmd == "pipeline":
        res = run_pipeline(proposals_path=props, dry=dry, verbose=True)
        ok = sum(1 for r in res if r.get("verify_ok"))
        print("pipeline: total=%d verified=%d dry=%s"
              % (len(res), ok, dry))
        return 0
    print("unknown cmd: " + cmd); return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
