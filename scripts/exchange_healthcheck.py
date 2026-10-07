"""exchange_healthcheck (s193).

Пингует все биржи из registry, пишет отчёт.
Запускается в цикле self_daemon (каждые 2ч).

Usage:
  python3 scripts/exchange_healthcheck.py           # dry: печать
  python3 scripts/exchange_healthcheck.py --apply   # записать отчёты
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

JSON_OUT = ROOT / "self/curator/exchanges_health.json"
MD_OUT = ROOT / "self/curator/EXCHANGES_HEALTH.md"


def _load_class(spec: str):
    mod_name, _, cls_name = spec.partition(":")
    mod = importlib.import_module(mod_name)
    return getattr(mod, cls_name)


def probe_exchange(entry: dict) -> dict:
    out = {
        "name": entry["name"],
        "kind": entry.get("kind"),
        "endpoint": entry.get("endpoint"),
        "status": "unknown",
        "checks": [],
        "error": "",
        "latency_ms": 0,
        "alive_symbols": 0,
        "total_symbols": len(entry.get("symbols", [])),
    }
    try:
        cls = _load_class(entry["class"])
        client = cls()
    except Exception as e:
        out["status"] = "import_error"
        out["error"] = type(e).__name__ + ": " + str(e)
        return out

    alive = 0
    latencies = []
    for sym in entry.get("symbols", []):
        chk = {"symbol": sym}
        try:
            t0 = time.time()
            book = client.get_orderbook(sym)
            dt_ms = (time.time() - t0) * 1000
            chk["latency_ms"] = round(dt_ms, 1)
            chk["valid"] = bool(book.is_valid())
            chk["best_bid"] = book.best_bid()
            chk["best_ask"] = book.best_ask()
            if chk["valid"]:
                alive += 1
                latencies.append(dt_ms)
        except Exception as e:
            chk["error"] = type(e).__name__ + ": " + str(e)
            chk["valid"] = False
        out["checks"].append(chk)

    out["alive_symbols"] = alive
    out["latency_ms"] = round(sum(latencies) / len(latencies), 1) if latencies else 0
    n = out["total_symbols"]
    if n > 0 and alive == n:
        out["status"] = "ok"
    elif alive > 0:
        out["status"] = "degraded"
    else:
        out["status"] = "down"
    return out


def render_md(report: dict) -> str:
    lines = []
    lines.append("# EXCHANGES HEALTH")
    lines.append("")
    lines.append("Generated: " + report["ts"])
    lines.append(
        "Summary: "
        + str(report["summary"]["alive"])
        + "/"
        + str(report["summary"]["total"])
        + " alive"
    )
    lines.append("")
    lines.append("| exchange | kind | status | symbols | latency_ms | endpoint |")
    lines.append("|---|---|---|---|---|---|")
    for e in report["exchanges"]:
        lines.append(
            "| " + e["name"]
            + " | " + str(e.get("kind", "?"))
            + " | " + e["status"]
            + " | " + str(e.get("alive_symbols", 0)) + "/" + str(e.get("total_symbols", 0))
            + " | " + str(e.get("latency_ms", 0))
            + " | " + str(e.get("endpoint", ""))
            + " |"
        )
    lines.append("")
    lines.append("## Details")
    for e in report["exchanges"]:
        lines.append("### " + e["name"] + " (" + e["status"] + ")")
        if e.get("error"):
            lines.append("- error: `" + e["error"] + "`")
        for c in e.get("checks", []):
            if c.get("valid"):
                lines.append(
                    "- `" + c["symbol"] + "`: bid="
                    + str(c.get("best_bid")) + " ask=" + str(c.get("best_ask"))
                    + " latency=" + str(c.get("latency_ms")) + "ms"
                )
            else:
                lines.append("- `" + c["symbol"] + "`: FAIL - " + str(c.get("error", "invalid")))
        lines.append("")
    return "\n".join(lines) + "\n"


def _emit_health_events(results: list) -> None:
    """s196-p03: emit FAIL events to EVENTS.jsonl. Fail-open, never raises.
    Feeds session_lesson_extract (P0 BACKLOG_LESSON_AUTONOMY)."""
    try:
        sys.path.insert(0, str(ROOT / "scripts" / "research"))
        from events import emit_event  # type: ignore
    except Exception:
        return
    for r in results:
        name = r.get("name") or "?"
        status = r.get("status") or "unknown"
        if status != "ok":
            detail = "status=" + str(status)
            if r.get("error"):
                detail += " error=" + str(r["error"])[:180]
            try:
                emit_event("healthcheck_fail", name, detail)
            except Exception:
                pass
        for chk in (r.get("checks") or []):
            if chk.get("error"):
                sym = chk.get("symbol") or "?"
                try:
                    emit_event("healthcheck_symbol_fail", name + ":" + sym,
                               str(chk["error"])[:200])
                except Exception:
                    pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    from arbitrage_bot.app.exchanges.registry import all_exchanges
    entries = all_exchanges()

    results = []
    for entry in entries:
        results.append(probe_exchange(entry))

    alive = sum(1 for r in results if r["status"] == "ok")
    # s196-p03: emit FAIL events to EVENTS.jsonl (P0 BACKLOG_LESSON_AUTONOMY).
    _emit_health_events(results)
    report = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": {
            "total": len(results),
            "alive": alive,
            "dead": len(results) - alive,
        },
        "exchanges": results,
    }

    md = render_md(report)
    print(md)

    if args.apply:
        JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
        JSON_OUT.write_text(json.dumps(report, indent=2))
        MD_OUT.write_text(md)
        print("wrote " + str(JSON_OUT))
        print("wrote " + str(MD_OUT))


if __name__ == "__main__":
    main()
