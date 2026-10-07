"""decision_engine.py - DETERMINISTIC verdict. NO LLM.

Input: metrics dict from test_runner.
Output: verdict in {confirmed, rejected, marginal, inconclusive}.

Rules are pure python, auditable, no ML.
"""
import json
from pathlib import Path

MIN_TRADES = 20
MIN_SHARPE = 1.0
MIN_WINRATE = 0.50
MIN_AVG_BPS = 5.0
MAX_DD_PCT = 20.0

def decide(metrics):
    n = metrics.get("trades", 0)
    if n < MIN_TRADES:
        return {
            "verdict": "inconclusive",
            "reason": f"only {n} trades (min {MIN_TRADES})",
            "rules_checked": ["min_trades"],
        }

    sharpe = metrics.get("sharpe", 0)
    wr = metrics.get("win_rate", 0)
    avg = metrics.get("avg_bps", 0)
    dd = metrics.get("max_dd_pct", 100)

    checks = {
        "sharpe>=" + str(MIN_SHARPE): sharpe >= MIN_SHARPE,
        "win_rate>=" + str(MIN_WINRATE): wr >= MIN_WINRATE,
        "avg_bps>=" + str(MIN_AVG_BPS): avg >= MIN_AVG_BPS,
        "max_dd<=" + str(MAX_DD_PCT): dd <= MAX_DD_PCT,
    }
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)

    if passed == total:
        verdict = "confirmed"
    elif passed == 0:
        verdict = "rejected"
    elif passed <= total // 2:
        verdict = "rejected"
    else:
        verdict = "marginal"

    return {
        "verdict": verdict,
        "passed": passed, "total": total,
        "checks": checks,
        "metrics": {"trades": n, "sharpe": sharpe, "win_rate": wr,
                    "avg_bps": avg, "max_dd_pct": dd},
        "reason": f"{passed}/{total} rules passed",
    }

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        m = json.loads(Path(sys.argv[1]).read_text())
    else:
        m = {"trades": 30, "sharpe": 1.5, "win_rate": 0.6, "avg_bps": 8.0, "max_dd_pct": 10.0}
    print(json.dumps(decide(m), indent=2, ensure_ascii=False))
