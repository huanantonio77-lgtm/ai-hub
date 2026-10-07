#!/usr/bin/env python3
"""inventory.py — завхоз ai-hub: инвентарь модулей, поиск, gap-детектор (s176)."""
import argparse
import ast
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "knowledge" / "inventory.json"

EXCLUDE_DIRS = {
    "__pycache__", ".git", ".cache", "archive",
    "node_modules", ".venv", "venv", "projects",
    "strategy", "team", "agents",
}
INTERESTING_IMPORTS = (
    "urllib", "requests", "ollama", "limits",
    "quota_watch", "api_health",
)


HEARTBEAT = ROOT / ".cache" / "system" / "inventory_heartbeat.json"
BLINDNESS = ROOT / "self" / "curator" / "inventory_blindness.jsonl"


def _now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(
        timespec="seconds")


def _walk(root, suffixes):
    hits = []
    root = Path(root)
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in p.parts):
            continue
        if p.suffix in suffixes:
            hits.append(p)
    return sorted(hits)


def _first_docstring(src):
    try:
        tree = ast.parse(src)
    except Exception:
        return ""
    return (ast.get_docstring(tree) or "").split("\n")[0][:160]


def _scan_python(path):
    src = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(src)
    except Exception:
        return {"path": str(path.relative_to(ROOT)), "err": "parse",
                "loc": len(src.splitlines())}
    funcs = [n.name for n in tree.body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    classes = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
    imports = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imports += [a.name.split(".")[0] for a in n.names]
        elif isinstance(n, ast.ImportFrom) and n.module:
            imports.append(n.module.split(".")[0])
    hot = [i for i in set(imports) if i in INTERESTING_IMPORTS]
    return {
        "path": str(path.relative_to(ROOT)),
        "loc": len(src.splitlines()),
        "doc": _first_docstring(src),
        "funcs": funcs[:20],
        "classes": classes[:10],
        "hot_imports": hot,
    }


def build_inventory():
    root = Path(ROOT)
    py = [p for p in _walk(root, {".py"})
          if not any(x in str(p) for x in (".bak", ".pyc"))]
    js = [p for p in _walk(root, {".json"})]
    md = [p for p in _walk(root, {".md"})]
    py_info = [_scan_python(p) for p in py]
    hot = [it for it in py_info if it.get("hot_imports")]
    return {
        "version": 1,
        "built_ts": _now_iso(),
        "counts": {
            "py": len(py),
            "json": len(js),
            "md": len(md),
            "hot_imports": len(hot),
        },
        "py": py_info,
        "hot": [{"path": it["path"], "imports": it["hot_imports"]}
                for it in hot],
        "json_files": [str(p.relative_to(root)) for p in js],
        "md_files": [str(p.relative_to(root)) for p in md],
    }




API_LOGGER_TARGETS = (
    "scripts/api_health.py",
    "scripts/lesson_embed.py",
    "scripts/research/extract.py",
    "scripts/research/openalex_client.py",
    "arbitrage_bot/app/exchanges/testnet_adapter.py",
)

FALSE_POSITIVE_PATTERNS = (
    "_test_", "_list_", "test_",
    "browser_", "chrome_", "inspect_",
    "make_cover", "netcheck", "check_provider",
    "health_check", "llm_call", "llm_models_sync",
    "search_backends", "search_models",
    "security/enforcer", "self_research",
    "task_daemon", "verify.py", "research.py",
    "research_feeds",
)

KNOWN_SYSTEM_PLISTS = {
    "ollama",            # launches ollama binary, no .py
    "external-backup",   # external shell script
    "fb-sync",           # external sync
    "autonomy-recheck",  # schedules curator autonomously
    "log-rotate",        # system log rotation
    "catchup",           # cron-style catchup
    "weekly-review",     # scheduled report
}



USAGE_MARKERS = ("limits", "limits_gateway", "api_health",
                 "api_usage", "quota_watch", "record_call",
                 "_common")


def detect_unlogged_http(inv):
    gaps = []
    for it in inv.get("hot", []):
        path = it.get("path", "")
        if path not in API_LOGGER_TARGETS:
            continue
        if any(p in path for p in FALSE_POSITIVE_PATTERNS):
            continue
        imports = it.get("imports") or []
        if "urllib" not in imports and "requests" not in imports:
            continue
        # s184: text-scan (from-imports of limits_gateway / _common).
        try:
            _txt = (ROOT / path).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            _txt = ""
        if any(m in imports for m in USAGE_MARKERS) or \
           any(m in _txt for m in USAGE_MARKERS):
            continue
        gaps.append({
            "kind": "UNLOGGED-HTTP",
            "path": it["path"],
            "sev": "P1",
            "desc": ("HTTP client without usage logging "
                     "(imports " + ",".join(imports) + ")"),
        })
    return gaps


LIMIT_REGISTRY_HINTS = (
    "provider_limits", "token_limits",
    "limits_usage", "quota",
)


def detect_duplicate_registries(inv):
    hits = []
    for f in inv.get("json_files", []):
        low = f.lower()
        if any(h in low for h in LIMIT_REGISTRY_HINTS):
            hits.append(f)
    if len(hits) <= 1:
        return []
    return [{
        "kind": "DUPLICATE-LIMIT-REGISTRY",
        "path": ",".join(hits),
        "sev": "P1",
        "desc": (str(len(hits)) + " limit registries found: "
                 + " ; ".join(hits)),
    }]


def _load_registry():
    p = ROOT / "provider_limits.json"
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {k: v for k, v in d.items() if not k.startswith("_")}


def _load_secret_keys():
    p = Path.home() / ".ai-hub-secrets.env"
    keys = set()
    if not p.exists():
        return keys
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[len("export "):]
            if "=" in line and not line.startswith("#"):
                keys.add(line.split("=", 1)[0].strip())
    except Exception:
        pass
    return keys




def detect_registry_mismatches(inv):
    gaps = []
    reg = _load_registry()
    secret_keys = _load_secret_keys()
    declared_env = {v.get("env_key") for v in reg.values() if v.get("env_key")}

    # 1. UNREGISTERED-KEY
    for k in sorted(secret_keys):
        if k in declared_env:
            continue
        if "EMAIL" in k:
            continue
        gaps.append({
            "kind": "UNREGISTERED-KEY",
            "path": "~/.ai-hub-secrets.env",
            "sev": "P1",
            "desc": ("env key " + k + " not declared in provider_limits.json"),
        })

    # 2. DECLARED-NOT-LOGGING
    file_cache = {}
    for name, meta in reg.items():
        loggers = meta.get("logger") or []
        if isinstance(loggers, str):
            loggers = [loggers]
        for lf in loggers:
            fp = ROOT / lf
            if not fp.exists():
                gaps.append({
                    "kind": "DECLARED-NOT-LOGGING",
                    "path": lf,
                    "sev": "P1",
                    "desc": ("registry says " + name + " logs here, file missing"),
                })
                continue
            if lf not in file_cache:
                try:
                    file_cache[lf] = fp.read_text(encoding="utf-8")
                except Exception:
                    file_cache[lf] = ""
            txt = file_cache[lf]
            has_literal = (
                'record_call("' + name + '"' in txt
                or "record_call('" + name + "'" in txt
            )
            has_dynamic = (
                ("_track(" in txt and ("import limits" in txt
                                       or "limits_gateway" in txt))
                or "gateway_call" in txt
            )
            if not (has_literal or has_dynamic):
                gaps.append({
                    "kind": "DECLARED-NOT-LOGGING",
                    "path": lf,
                    "sev": "P1",
                    "desc": ("registry says " + name
                             + " logs here, but no record_call(\""
                             + name + "\") found"),
                })

    # 3. UNKNOWN-CALLER
    known = set(reg.keys())
    for it in inv.get("py", []):
        fp = ROOT / it["path"]
        if not fp.exists():
            continue
        try:
            txt = fp.read_text(encoding="utf-8")
        except Exception:
            continue
        for m in __import__("re").finditer(
                r'record_call\(\s*["\']([a-zA-Z0-9_\-]+)["\']', txt):
            called = m.group(1)
            if called not in known:
                gaps.append({
                    "kind": "UNKNOWN-CALLER",
                    "path": it["path"],
                    "sev": "P2",
                    "desc": ("record_call(\"" + called
                             + "\") not in registry"),
                })
    return gaps


def detect_gaps(inv):
    gaps = []
    gaps += detect_unlogged_http(inv)
    gaps += detect_duplicate_registries(inv)
    gaps += detect_registry_mismatches(inv)
    return gaps


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def verify_lessons(inv):
    idx = ROOT / "knowledge" / "lessons_index.json"
    d = _read_json(idx)
    if not d:
        return []
    want = int(d.get("count") or 0)
    have = 0
    for it in inv.get("py", []):
        if it.get("path") == "scripts/lesson_index.py":
            have += 1
    if have == 0:
        return [{
            "kind": "BLIND-LESSONS",
            "path": "scripts/lesson_index.py",
            "sev": "P1",
            "desc": ("lessons_index count=" + str(want)
                     + " but inventory missing lesson_index.py"),
        }]
    return []


def verify_healers(inv):
    h_dir = ROOT / "self" / "healers"
    if not h_dir.exists():
        return []
    known = {it.get("path", "") for it in inv.get("py", [])}
    gaps = []
    for f in sorted(h_dir.glob("*.jsonl")):
        name = f.stem
        # s176: healers are .jsonl journals, not .py modules.
        # Skip if journal just has no dedicated .py (may live in curator.py).
        # Only flag if name matches an obviously missing category.
        if name in ("unknown",):
            gaps.append({
                "kind": "BLIND-HEALER",
                "path": "self/healers/" + f.name,
                "sev": "P2",
                "desc": ("healer journal exists but no "
                         + name + ".py in inventory"),
            })
    return gaps


def verify_launchagents(inv):
    import os
    la_dir = Path.home() / "Library" / "LaunchAgents"
    if not la_dir.exists():
        return []
    known = {it.get("path", "") for it in inv.get("py", [])}
    known_md = {f for f in inv.get("md_files", [])}
    gaps = []
    for f in sorted(la_dir.glob("com.ainova.*.plist")):
        stem = f.stem.replace("com.ainova.", "")
        if stem in KNOWN_SYSTEM_PLISTS:
            continue
        token = stem.replace("-", "_")
        if any(token in p for p in known):
            continue
        if any(token in p for p in known_md):
            continue
        gaps.append({
            "kind": "BLIND-LAUNCHAGENT",
            "path": str(f),
            "sev": "P2",
            "desc": ("plist " + f.name
                     + " but no matching script/module"),
        })
    return gaps


def verify_against_truth(inv):
    all_gaps = []
    all_gaps += verify_lessons(inv)
    all_gaps += verify_healers(inv)
    all_gaps += verify_launchagents(inv)
    return all_gaps


def write_heartbeat(inv, gaps):
    HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": _now_iso(),
           "counts": inv.get("counts", {}),
           "gaps": len(gaps)}
    HEARTBEAT.write_text(
        json.dumps(rec, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return rec


def write_blindness(items):
    if not items:
        return 0
    BLINDNESS.parent.mkdir(parents=True, exist_ok=True)
    with BLINDNESS.open("a", encoding="utf-8") as f:
        for it in items:
            rec = {"ts": _now_iso(), **it}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return len(items)


def _search(inv, term):
    t = term.lower()
    hits = []
    for it in inv.get("py", []):
        blob = (it.get("path", "") + " " + it.get("doc", "")
                + " " + " ".join(it.get("funcs", []))
                + " " + " ".join(it.get("hot_imports", []))).lower()
        if t in blob:
            hits.append(it.get("path"))
    return hits


def main(argv=None):
    ap = argparse.ArgumentParser(description="inventory (s176)")
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--search", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    inv = build_inventory()
    gaps = detect_gaps(inv)
    truth = verify_against_truth(inv)
    all_gaps = gaps + truth
    if args.search:
        for h in _search(inv, args.search):
            print("  " + h)
        return 0
    if args.json:
        inv["gaps"] = all_gaps
        print(json.dumps(inv, ensure_ascii=False, indent=2))
        return 0
    if not args.quiet:
        c = inv["counts"]
        print("ЗАВХОЗ · " + inv["built_ts"])
        print("  .py=" + str(c["py"]) + "  .json=" + str(c["json"])
              + "  .md=" + str(c["md"])
              + "  hot=" + str(c["hot_imports"]))
        print("  gaps=" + str(len(all_gaps)))
        for g in all_gaps[:10]:
            print("    ! " + g["kind"] + " · "
                  + str(g.get("path", ""))[:70])
    # s176: heartbeat + OUT + blindness пишутся ВСЕГДА,
    # даже под --quiet (используется LaunchAgent).
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(inv, ensure_ascii=False, indent=2),
        encoding="utf-8")
    write_heartbeat(inv, all_gaps)
    write_blindness(truth)
    return 1 if truth else 0


if __name__ == "__main__":
    sys.exit(main())


