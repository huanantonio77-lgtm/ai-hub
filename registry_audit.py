#!/usr/bin/env python3
"""registry_audit.py - s98-F5: авто-чистка реестра провайдеров.

Детектирует:
  - dead models  : есть в реестре, но нет в /v1/models провайдера (removed из sync).
  - filtered     : есть в реестре, но llm_call._map его отбрасывает (по условиям).

Режимы:
  --report (default) : отчёт + repair_task + autonomy-запись.
  --apply            : + удалить dead models из реестра (с backup).
  --selftest         : 6 кейсов на фикстурах.
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import session_meta as _sm

ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / "providers_registry.json"
SYNC_LOG = ROOT / ".cache" / "system" / "models_sync.jsonl"
AUDIT_MD = ROOT / "strategy" / "registry_audit.md"
AUTONOMY = ROOT / "self" / "autonomy.jsonl"

SESSION = _sm.current()
VALIDATED_TTL_OK = 24 * 3600


def _read_registry(path=None):
    p = Path(path) if path else REGISTRY
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print("registry_audit: read fail: " + type(e).__name__)
        return {}


def _read_last_sync(path=None):
    p = Path(path) if path else SYNC_LOG
    out = {}
    if not p.exists():
        return out
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            prov = r.get("provider")
            if not prov:
                continue
            if "removed" in r or "added" in r:
                out[prov] = r
    except Exception:
        pass
    return out


def _key_exists(kf_rel):
    if not kf_rel:
        return False
    p = ROOT / kf_rel
    return p.exists() and p.stat().st_size > 0


def _filter_reason(name, info):
    """Возвращает причину, по которой _map(llm_call) отбросит провайдера, или None."""
    if not isinstance(info, dict):
        return "not a dict"
    if info.get("enabled") is False:
        return "enabled=false"
    at = (info.get("api_type") or "")
    if at != "openai_compatible":
        return "api_type=" + str(at)
    url = (info.get("api_url") or "").strip()
    kf = (info.get("key_file") or "").strip()
    models = info.get("models") or []
    if not url:
        return "no api_url"
    if not kf:
        return "no key_file"
    if not models:
        return "no models"
    if not _key_exists(kf):
        return "key_file missing: " + kf
    # s100-F2: provider-level last_error filter removed (mirrors llm_call._map s100-F1).
    return None


def detect(reg=None, sync=None):
    """Возвращает {"dead": {prov: [model,...]}, "filtered": {prov: reason}}."""
    r = reg if reg is not None else _read_registry()
    s = sync if sync is not None else _read_last_sync()
    provs = (r.get("providers") or {})
    dead = {}
    for prov, row in s.items():
        rm = row.get("removed") or []
        if rm:
            dead[prov] = list(rm)
    filtered = {}
    for name, info in provs.items():
        reason = _filter_reason(name, info)
        if reason:
            filtered[name] = reason
    return {"dead": dead, "filtered": filtered}


def _render_report(d, ts=None):
    ts = ts or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = ["## " + ts, ""]
    dead = d.get("dead") or {}
    filt = d.get("filtered") or {}
    if not dead and not filt:
        lines.append("OK: no dead models, no filtered providers.")
        lines.append("")
        return chr(10).join(lines)
    if dead:
        lines.append("### Dead models")
        for prov in sorted(dead):
            for m in dead[prov]:
                lines.append("- " + prov + "/" + str(m))
        lines.append("")
    if filt:
        lines.append("### Filtered providers")
        for prov in sorted(filt):
            lines.append("- " + prov + ": " + str(filt[prov]))
        lines.append("")
    return chr(10).join(lines)


def _append_md(text):
    AUDIT_MD.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_MD.open("a", encoding="utf-8") as f:
        f.write(text)


def _append_autonomy(note, effect=None):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    ev = {"ts": ts, "session": SESSION, "action": "registry_audit", "note": note}
    if effect is not None:
        ev["effect"] = int(effect)
    try:
        with AUTONOMY.open("a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + chr(10))
    except Exception:
        pass
    # s108 A3: личный журнал лекаря (fail-open)
    try:
        from healer_log import healer_log
        healer_log("registry_audit", diagnosis=note, effect=effect)
    except Exception:
        pass


def _add_repair_task(d):
    dead = d.get("dead") or {}
    if not dead:
        return False
    marker = "[repair:registry-audit]"
    flat = []
    for prov in sorted(dead):
        for m in dead[prov]:
            flat.append(prov + "/" + str(m))
    text = marker + " Dead models: " + ", ".join(flat[:10]) + ". Run: python3 registry_audit.py --apply"
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
    n_dead = sum(len(v) for v in (d.get("dead") or {}).values())
    n_filt = len(d.get("filtered") or {})
    _append_autonomy("dead=" + str(n_dead) + " filtered=" + str(n_filt))
    if n_dead:
        _add_repair_task(d)
    return d


def apply_dead(d=None):
    """Удаляет dead models из реестра. Backup с таймстампом. Возвращает (removed_count, backup_path)."""
    d = d or detect()
    dead = d.get("dead") or {}
    if not dead:
        print("apply: no dead models")
        return 0, None
    raw = REGISTRY.read_text(encoding="utf-8")
    reg = json.loads(raw)
    provs = reg.get("providers") or {}
    removed = 0
    for prov, models in dead.items():
        info = provs.get(prov)
        if not isinstance(info, dict):
            continue
        cur = list(info.get("models") or [])
        kill = set(str(m) for m in models)
        new = [m for m in cur if str(m) not in kill]
        if len(new) != len(cur):
            info["models"] = new
            removed += len(cur) - len(new)
    if removed == 0:
        print("apply: nothing to remove")
        return 0, None
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    bak = REGISTRY.with_name(REGISTRY.name + ".bak-s98-f5-" + ts)
    bak.write_text(raw, encoding="utf-8")
    REGISTRY.write_text(json.dumps(reg, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")
    print("apply: removed=" + str(removed) + " backup=" + bak.name)
    _append_autonomy("apply removed=" + str(removed) + " backup=" + bak.name)
    return removed, str(bak)


AUTO_SAFE_MAX_DEAD = 10
AUTO_SAFE_LOCK = ROOT / ".cache" / "system" / "registry_audit_auto_safe.ts"


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
        dead = d.get("dead") or {}
        n = sum(len(v) for v in dead.values())
        if n == 0:
            reason = "nothing_to_do"
        elif len(dead) > AUTO_SAFE_MAX_DEAD:
            reason = "too_many_providers_" + str(len(dead))
        else:
            try:
                import llm_cooldown as _lc
                cd = _lc.active_count() if hasattr(_lc, "active_count") else 0
            except Exception:
                cd = 0
            if cd > 0:
                reason = "cooldowns_active_" + str(cd)
            else:
                apply_dead(d)
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
    reg1 = {"providers": {
        "groq": {"api_type": "openai_compatible", "api_url": "u", "key_file": "x", "models": ["m1"]},
        "cohere": {"api_type": "cohere", "api_url": "u", "key_file": "x", "models": ["m"]},
        "dead1": {"api_type": "openai_compatible", "api_url": "u", "key_file": ".nonexistent-kf", "models": ["x"]},
        "no_key": {"api_type": "openai_compatible", "api_url": "u", "key_file": "", "models": ["x"]},
    }}
    sync1 = {"groq": {"removed": ["m2", "m3"]}}
    d = detect(reg=reg1, sync=sync1)
    chk("dead_groq_2", d["dead"].get("groq") == ["m2", "m3"])
    chk("cohere_filtered_apitype", "cohere" in d["filtered"] and "api_type" in d["filtered"]["cohere"])
    chk("dead1_filtered_keyfile", "dead1" in d["filtered"] and "missing" in d["filtered"]["dead1"])
    chk("no_key_filtered", "no_key" in d["filtered"] and "no key_file" in d["filtered"]["no_key"])
    d2 = detect(reg={"providers": {}}, sync={})
    chk("empty_no_findings", (not d2["dead"]) and (not d2["filtered"]))
    text = _render_report(d, ts="TEST")
    chk("render_has_dead", ("groq/m2" in text) and ("cohere" in text))
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
        apply_dead(d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
