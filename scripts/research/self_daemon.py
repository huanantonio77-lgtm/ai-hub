#!/usr/bin/env python3
"""self_daemon.py (s180) — само-перезапускающийся цикл. Запускается из Terminal."""
import subprocess, sys, time, datetime
from pathlib import Path
ROOT = Path.home() / "Desktop" / "ai-hub"
LOG = ROOT / "self/curator/self_loop.log"
STATUS = ROOT / "self/curator/STATUS.md"
REPORT = ROOT / "self/curator/SELF_RESEARCH_REPORT.md"
PY = sys.executable

def log(m):
    with LOG.open("a", encoding="utf-8") as f: f.write(m + "\n")
    print(m, flush=True)  # s190-p2: also to stdout -> logs/self_daemon.out

def wc(p):
    try: return sum(1 for _ in p.open())
    except: return 0

def run(args, t=900):
    try:
        r = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True, timeout=t)
        log(f"rc={r.returncode} {' '.join(args[-2:])}")
        if r.stdout: log("OUT: " + r.stdout[-1200:])
        if r.stderr: log("ERR: " + r.stderr[-1200:])
    except Exception as e:
        log(f"FAILED: {e!r}")

def trading_research_daily():
    """s198-p15: DEX trading auto-research, once per day (marker guard)."""
    marker = ROOT / "self" / "curator" / ".trading_research_last"
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    try:
        if marker.exists() and marker.read_text(encoding="utf-8").strip() == today:
            log("trading_research: skip (already today)")
            return
    except Exception:
        pass
    run([PY, str(ROOT/"scripts/research/self_research_trading.py"),
         "--run", "--limit", "2"], t=600)
    run([PY, str(ROOT/"scripts/autonomous_apply.py"), "pipeline",
         "--write", "--props",
         str(ROOT/"self/curator/RESEARCH_TRADING.jsonl")], t=180)
    try:
        marker.write_text(today, encoding="utf-8")
    except Exception as e:
        log("trading_research: marker write failed: " + repr(e))


def arbitrage_stats_daily():
    """s199-p1: ARBITRAGE rolling stats, once per day (marker guard)."""
    marker = ROOT / "self" / "curator" / ".stats_last"
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    try:
        if marker.exists() and marker.read_text(encoding="utf-8").strip() == today:
            log("arbitrage_stats: skip (already today)")
            return
    except Exception:
        pass
    run([PY, str(ROOT/"scripts/arbitrage_stats.py"), "--days", "30", "--run"], t=120)
    try:
        marker.write_text(today, encoding="utf-8")
    except Exception as e:
        log("arbitrage_stats: marker write failed: " + repr(e))


def cycle():
    log(f"=== cycle start {datetime.datetime.now()} ===")
    run([PY, str(ROOT/"scripts/research/self_research.py"), "--run", "--limit", "2"])
    run([PY, str(ROOT/"scripts/autonomous_apply.py"), "pipeline", "--write"], t=300)
    run([PY, str(ROOT/"scripts/self_monitor.py"), "--apply"], t=60)
    run([PY, str(ROOT/"scripts/drafts_gc.py"), "--apply"], t=60)
    run([PY, str(ROOT/"scripts/lessons_hygiene.py"), "--apply", "--session", "auto"], t=60)
    run([PY, str(ROOT/"scripts/exchange_healthcheck.py"), "--apply"], t=120)
    run([PY, str(ROOT/"scripts/arbitrage_scan.py"), "--apply", "--write-stats"], t=120)  # s197-p1a
    trading_research_daily()  # s198-p15
    arbitrage_stats_daily()  # s199-p1
    # s196-p05: autonomous lesson extraction (P0 BACKLOG_LESSON_AUTONOMY).
    # Reads EVENTS.jsonl + autonomy.jsonl for current session -> updates
    # self/curator/drafts/lessons_session.md. Fail-open (run() handles).
    run([PY, str(ROOT/"scripts/research/session_lesson_extract.py"), "--apply"], t=60)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    body = REPORT.read_text(encoding="utf-8")[-2000:] if REPORT.exists() else "(no report yet)"
    try:
        import sys as _sys
        _td = str(ROOT / "scripts" / "research")
        if _td not in _sys.path:
            _sys.path.insert(0, _td)
        from host_telemetry import collect_host_telemetry, render_telemetry_block
        tele = render_telemetry_block(collect_host_telemetry())
    except Exception as _e:
        tele = "## Host telemetry\n\n(collection failed: " + repr(_e) + ")"
    STATUS.write_text(
        f"# STATUS (self_daemon.py)\n**Updated:** {now}\n\n"
        f"## Counters\n- PROPOSALS.jsonl: **{wc(ROOT/'self/curator/PROPOSALS.jsonl')}**\n"
        f"- SELF_PROPOSALS.jsonl: **{wc(ROOT/'self/curator/SELF_PROPOSALS.jsonl')}**\n\n"
        f"{tele}\n\n## Last research report\n\n{body}\n\n---\nlog: `self/curator/self_loop.log`\n",
        encoding="utf-8")
    log(f"=== cycle done {datetime.datetime.now()} ===")

if __name__ == "__main__":
    log(f"=== daemon start {datetime.datetime.now()} ===")
    while True:
        try: cycle()
        except Exception as e: log(f"cycle error: {e!r}")
        time.sleep(7200)
