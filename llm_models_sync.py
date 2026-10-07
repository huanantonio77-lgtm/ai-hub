# -*- coding: utf-8 -*-
"""S-LLM-6b: sync models list from provider /v1/models. Report-only default."""
import argparse
import json
import sys
import time
from pathlib import Path


def _silent(tag, e):
    """s105-3: emit silent except to errors.jsonl (K1 emission)."""
    try:
        from datetime import datetime as _dt, timezone as _tz
        import json as _j
        _root = Path(__file__).resolve().parent
        log = _root / ".cache" / "system" / "errors.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": _dt.now(_tz.utc).strftime("%Y-%m-%d %H:%M:%S"),
               "kind": "silent", "where": "llm_models_sync",
               "detail": tag + ": " + type(e).__name__ + ": " + str(e)[:100]}
        with log.open("a", encoding="utf-8") as f:
            f.write(_j.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / "providers_registry.json"
SYSTEM = ROOT / ".cache" / "system"
LOG = SYSTEM / "models_sync.jsonl"

# s102-4: llm_auto_update
AUTO_SAFE_MAX_PROVIDERS = 10
AUTO_SAFE_MAX_PER_PROVIDER = 500
AUTO_SAFE_MAX_TOTAL = 2000
AUTO_SAFE_LOCK = SYSTEM / "llm_models_sync_auto_safe.ts"
TIMEOUT = 15


def _load_registry():
    try:
        d = json.loads(REGISTRY.read_text(encoding="utf-8"))
        return d.get("providers") or {}
    except Exception as e:
        print("[models_sync] registry read failed: " + type(e).__name__)
        return {}


def _key_path(kf):
    kf = (kf or "").strip()
    if not kf:
        return None
    p = ROOT / kf
    return p if p.exists() else None


def _models_url(api_url):
    u = (api_url or "").strip().rstrip("/")
    if u.endswith("/chat/completions"):
        u = u[: -len("/chat/completions")]
    if not u:
        return None
    return u + "/models"


def _read_key(p):
    try:
        return p.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _fetch(url, key):
    try:
        import requests
    except Exception:
        return 0, None, "no_requests"
    hdrs = {"Authorization": "Bearer " + key} if key else {}
    try:
        r = requests.get(url, headers=hdrs, timeout=TIMEOUT)
    except Exception as e:
        return 0, None, type(e).__name__
    if r.status_code != 200:
        return r.status_code, None, "http"
    try:
        j = r.json()
    except Exception:
        return r.status_code, None, "bad_json"
    rows = j.get("data") or j.get("models") or []
    ids = []
    for m in rows:
        if isinstance(m, dict):
            n = m.get("id") or m.get("name")
            if n:
                ids.append(str(n))
    return 200, ids, "ok"


def _log_row(row):
    try:
        SYSTEM.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + chr(10))
    except Exception as _e:
        _silent('llm_models_sync_L86', _e)


def sync_one(name, info, apply_flag, only=None):
    if only and name != only:
        return None
    if (info.get("api_type") or "") != "openai_compatible":
        return {"provider": name, "skip": "api_type"}
    kf = info.get("key_file") or ""
    kp = _key_path(kf)
    if kp is None:
        return {"provider": name, "skip": "no_key_file"}
    url = _models_url(info.get("api_url") or "")
    if not url:
        return {"provider": name, "skip": "no_url"}
    key = _read_key(kp)
    code, live, note = _fetch(url, key)
    if live is None:
        return {"provider": name, "http": code, "err": note, "url": url}
    current = list(info.get("models") or [])
    cur_set = set(current)
    live_set = set(live)
    added = sorted(live_set - cur_set)
    removed = sorted(cur_set - live_set)
    row = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "provider": name,
        "http": code,
        "n_live": len(live),
        "n_current": len(current),
        "added": added,
        "removed": removed,
        "apply": bool(apply_flag),
    }
    if apply_flag:
        try:
            import providers as _p
            for m in added:
                _p.add_model(name, m)
            for m in removed:
                _p.remove_model(name, m)
            row["applied_ok"] = True
        except Exception as e:
            row["applied_err"] = type(e).__name__
    return row



def auto_safe(quiet=False):
    from datetime import datetime as _dt, timezone as _tz
    today = _dt.now(_tz.utc).strftime("%Y-%m-%d")
    effect = 0
    try:
        already = AUTO_SAFE_LOCK.read_text(encoding="utf-8").strip() == today
    except Exception:
        already = False
    if already:
        reason = "already_today"
    else:
        reg = _load_registry()
        if not reg:
            reason = "no_registry"
        else:
            plan_raw = {}
            for name, info in reg.items():
                if not isinstance(info, dict):
                    continue
                r = sync_one(name, info, apply_flag=False)
                if r is None or "skip" in r or "err" in r:
                    continue
                add = r.get("added") or []
                if add:
                    plan_raw[name] = add
            plan = {}
            skipped = []
            for _n, _v in plan_raw.items():
                if len(_v) > AUTO_SAFE_MAX_PER_PROVIDER:
                    skipped.append(_n + chr(34) + chr(34) + chr(58) + str(len(_v)))
                else:
                    plan[_n] = _v
            n_prov = len(plan)
            n_mod = sum(len(v) for v in plan.values())
            if n_mod == 0 and not skipped:
                reason = "nothing_to_do"
            elif n_mod == 0 and skipped:
                reason = "all_skipped_by_per_provider"
            elif n_prov > AUTO_SAFE_MAX_PROVIDERS:
                reason = "too_many_providers_" + str(n_prov)
            elif n_mod > AUTO_SAFE_MAX_TOTAL:
                reason = "too_many_total_" + str(n_mod)
            else:
                raw = REGISTRY.read_text(encoding="utf-8")
                ts = _dt.now(_tz.utc).strftime("%Y%m%d-%H%M%S")
                bak = REGISTRY.with_name(REGISTRY.name + ".bak-s102-4-" + ts)
                bak.write_text(raw, encoding="utf-8")
                import providers as _p
                applied = 0
                for name, add in plan.items():
                    for m in add:
                        try:
                            _p.add_model(name, m)
                            applied += 1
                        except Exception as e:
                            print("add_model fail " + name + "/" + m + ": " + type(e).__name__)
                AUTO_SAFE_LOCK.parent.mkdir(parents=True, exist_ok=True)
                AUTO_SAFE_LOCK.write_text(today, encoding="utf-8")
                reason = "applied_prov=" + str(n_prov) + "_added=" + str(applied) + "_bak=" + bak.name
                effect = applied
    _append_autonomy(reason, effect=effect)
    if not quiet:
        print("auto_safe: " + reason)
    return reason
def _append_autonomy(note, effect=None):
    try:
        from datetime import datetime as _dt, timezone as _tz
        A = ROOT / "self" / "autonomy.jsonl"
        A.parent.mkdir(parents=True, exist_ok=True)
        ts = _dt.now(_tz.utc).isoformat(timespec="seconds")
        rec = {"ts": ts, "session": "s102", "action": "llm_models_sync", "note": note}
        if effect is not None:
            rec["effect"] = int(effect)
        with A.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + chr(10))
    except Exception as _e:
        _silent('llm_models_sync_L207', _e)
    # s108 A3: личный журнал лекаря (fail-open)
    try:
        from healer_log import healer_log
        healer_log("llm_models_sync", diagnosis=note, effect=effect)
    except Exception:
        pass

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--auto-safe", action="store_true")
    ap.add_argument("--provider", default=None)
    a = ap.parse_args()
    if a.auto_safe:
        auto_safe()
        return
    reg = _load_registry()
    if not reg:
        print("[models_sync] registry empty")
        return
    apply_flag = bool(a.apply)
    rows = []
    for name, info in reg.items():
        if not isinstance(info, dict):
            continue
        r = sync_one(name, info, apply_flag, only=a.provider)
        if r is None:
            continue
        rows.append(r)
        if "skip" in r:
            print(name + ": skip (" + r["skip"] + ")")
        elif "err" in r:
            print(name + ": FAIL http=" + str(r.get("http")) + " " + str(r.get("err", "")))
        else:
            print(name + ": live=" + str(r["n_live"]) + " current=" + str(r["n_current"]) + " +" + str(len(r["added"])) + " -" + str(len(r["removed"])))
            if r["added"]:
                print("   added: " + ", ".join(r["added"][:10]))
            if r["removed"]:
                print("   removed: " + ", ".join(r["removed"][:10]))
        _log_row(r)
    print("[models_sync] done: " + str(len(rows)) + " providers, apply=" + str(apply_flag))


if __name__ == "__main__":
    main()
