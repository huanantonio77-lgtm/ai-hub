#!/usr/bin/env python3
"""validate_providers.py — L3.5.2: авто-валидация LLM-провайдеров.

Прогоняет ping через _ask_provider_full и пишет в providers_registry.json:
  - validated_at: ISO-8601
  - latency_ms:   int
  - last_error:   str | null

Команды:
  validate_providers.py --all
  validate_providers.py --name mistral
  validate_providers.py --name mistral --dry
"""
import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FTimeout
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / "providers_registry.json"
DEFAULT_TIMEOUT = 15


def validate_one(name: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Пингует одного провайдера. Возвращает dict: ok, latency_ms, last_error, text_len."""
    try:
        import orchestrator as orch
    except Exception as e:
        return {"ok": False, "latency_ms": 0, "last_error": "import orchestrator: " + str(e)[:180], "text_len": 0}

    t0 = time.monotonic()
    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(
                orch._ask_provider_full,
                name,
                "ping",
                [{"role": "user", "content": "1"}],
            )
            text, usage = fut.result(timeout=timeout)
    except FTimeout:
        return {"ok": False, "latency_ms": int((time.monotonic() - t0) * 1000),
                "last_error": "timeout {}s".format(timeout), "text_len": 0}
    except Exception as e:
        return {"ok": False, "latency_ms": int((time.monotonic() - t0) * 1000),
                "last_error": type(e).__name__ + ": " + str(e)[:180], "text_len": 0}

    lat = int((time.monotonic() - t0) * 1000)
    if text is None or not str(text).strip():
        _err = None
        if isinstance(usage, dict):
            _err = usage.get("_error")
        if _err:
            _err = str(_err)[:180]
        elif text == "":
            _err = "empty response (HTTP 200)"
        else:
            _err = "empty response or no key_file"
        return {"ok": False, "latency_ms": lat, "last_error": _err, "text_len": 0}
    return {"ok": True, "latency_ms": lat, "last_error": None, "text_len": len(str(text))}


def validate_all(names=None, timeout=DEFAULT_TIMEOUT, workers=4) -> dict:
    """Прогоняет провайдеров параллельно. names=None -> все из реестра."""
    try:
        import providers as prov
        all_provs = prov.all_providers()
    except Exception as e:
        print("! import providers: " + str(e)[:200])
        return {}
    if names is None:
        names = list(all_provs.keys())

    def _one(nm):
        res = validate_one(nm, timeout=timeout)
        mark = "OK " if res["ok"] else "ERR"
        err = (" | " + (res["last_error"] or "")[:60]) if res["last_error"] else ""
        print("  [{}] {:14s} {:>6d} ms{}".format(mark, nm, res["latency_ms"], err))
        return nm, res

    results = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for nm, res in ex.map(_one, names):
            results[nm] = res
    return results


def write_results(results: dict) -> bool:
    """Merge результатов в registry. Бэкап + атомарная запись через .tmp + os.replace."""
    if not results:
        print("! нечего писать: results пуст")
        return False
    try:
        reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except Exception as e:
        print("! не читается registry: " + str(e)[:200])
        return False
    provs = reg.get("providers")
    if not isinstance(provs, dict):
        print("! providers не dict — формат неожиданный, не пишу")
        return False

    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    written = 0
    for name, res in results.items():
        if name not in provs:
            continue
        provs[name]["validated_at"] = ts
        provs[name]["latency_ms"] = int(res.get("latency_ms", 0))
        provs[name]["last_error"] = res.get("last_error")
        written += 1

    bak = REGISTRY.with_suffix(".json.bak-val-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    bak.write_text(REGISTRY.read_text(encoding="utf-8"), encoding="utf-8")
    print("  бэкап: " + bak.name)

    tmp = REGISTRY.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(reg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, REGISTRY)
    print("  записано записей: " + str(written))
    return True


def main() -> int:
    # s86-1b-gate: heavy LLM task - only in window 22:00-08:00
    try:
        import catchup as _cu
        if not _cu._in_window():
            print("[s86-1b-gate] out of window 22:00-08:00, skip")
            return 0
    except Exception as _e:
        print("[s86-1b-gate] window check failed (" + type(_e).__name__ + "), proceeding")
    ap = argparse.ArgumentParser(description="Валидация LLM-провайдеров (L3.5.2)")
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--all", action="store_true", help="все провайдеры из реестра")
    grp.add_argument("--name", help="один провайдер по имени")
    ap.add_argument("--dry", action="store_true", help="не писать в registry, только показать")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="секунд на провайдера")
    ap.add_argument("--workers", type=int, default=4, help="параллельных воркеров при --all")
    args = ap.parse_args()

    names = [args.name] if args.name else None
    print("=== validate_providers: timeout={}s, dry={} ===".format(args.timeout, args.dry))
    results = validate_all(names=names, timeout=args.timeout, workers=args.workers)
    ok = sum(1 for r in results.values() if r["ok"])
    err = len(results) - ok
    print("=== итог: OK={}, ERR={}, всего={} ===".format(ok, err, len(results)))

    if args.dry:
        print("--dry: registry НЕ изменён")
        return 0
    if not results:
        print("! пустой результат, не пишу")
        return 1
    write_results(results)
    # s86-7-validate
    try:
        import catchup as _cu
        _cu.record("validate-providers", by="validate_providers.py")
    except Exception as _e:
        print(f"[catchup] record failed: {type(_e).__name__}: {_e}")
    # s98-F5b: registry audit hook (report only, no apply)
    try:
        import registry_audit as _ra
        _ra.run_report(quiet=True)
        # s101-2b: registry_audit auto_safe (apply within limits)
        try:
            _ra.auto_safe(quiet=True)
        except Exception as _e:
            print(f"[registry_audit] auto_safe failed: {type(_e).__name__}: {_e}")

        # s102-4: llm_models_sync auto_safe
        try:
            import llm_models_sync as _lms
            _lms.auto_safe(quiet=True)
        except Exception as _e:
            print("[llm_models_sync] auto_safe failed: " + type(_e).__name__)
    except Exception as _e:
        print(f"[registry_audit] hook failed: {type(_e).__name__}: {_e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
