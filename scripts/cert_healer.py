"""Daily SSL cert healer - handshake check to critical hosts."""
from __future__ import annotations
import ssl, socket, sys
from datetime import datetime, timezone
import certifi
from pathlib import Path
import json
ROOT = Path(__file__).resolve().parent.parent
JOURNAL = ROOT / "self" / "healers" / "cert_healer.jsonl"

HOSTS = [
    ("api.hyperliquid.xyz", 443),
    ("api.dydx.exchange", 443),
    ("api.github.com", 443),
]

def check_host(host, port, ctx):
    try:
        with socket.create_connection((host, port), timeout=5) as s:
            with ctx.wrap_socket(s, server_hostname=host) as ss:
                return True, ss.version()
    except Exception as e:
        return False, repr(e)

def main():
    ctx = ssl.create_default_context(cafile=certifi.where())
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    results = []
    for h, p in HOSTS:
        ok, info = check_host(h, p, ctx)
        results.append((h, ok, info))
        print(f"  [{'OK' if ok else 'FAIL'}] {h}  {info}")
    failed = [r for r in results if not r[1]]
    print(f"certifi: {certifi.where()}")
    print(f"summary: {len(results)-len(failed)}/{len(results)} OK  ts={ts}")
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with open(JOURNAL, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": ts, "session": "s206", "healer": "cert_healer",
            "diagnosis": f"{len(results)-len(failed)}/{len(results)} OK",
            "action": "report", "effect": len(results)-len(failed),
            "outcome": "ok" if not failed else "fail",
            "note": "; ".join(f"{h}={i}" for h,ok,i in results),
        }, ensure_ascii=False) + "\n")
    return 0 if not failed else 1

if __name__ == "__main__":
    sys.exit(main())
