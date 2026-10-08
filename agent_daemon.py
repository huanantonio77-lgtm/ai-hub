#!/usr/bin/env python3
"""agent_daemon.py — фоновый сторож ai-hub.

Раз в INTERVAL секунд:
  1. Проверяет Chrome (CDP порт).
  2. Проверяет VPN + прокси (netcheck).
  3. Проверяет LLM (Groq через llm_call).
  4. Пишет состояние в strategy/_journal.log.
  5. При падении Chrome — перезапускает.
  6. При падении провайдеров — пишет в журнал, спит до следующего цикла.

Запуск:
  python3 agent_daemon.py                  # интервал 300 сек
  python3 agent_daemon.py --interval 60    # интервал 60 сек
  python3 agent_daemon.py --once           # один прогон (для теста)
"""
import argparse, time, sys, subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from journal import log_event
from netcheck import check_vpn, check_proxy, is_llm_blocked
from selfcheck import (
    check_chrome, restart_chrome, chrome_cpu_total,
    chrome_idle_sec, chrome_stop, CHROME_IDLE_SEC_DEFAULT,
)
import sysmon


def _silent(tag, e):
    """s105-3: emit silent except to errors.jsonl (K1 emission)."""
    try:
        from datetime import datetime as _dt, timezone as _tz
        import json as _j
        _root = Path(__file__).resolve().parent
        log = _root / ".cache" / "system" / "errors.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": _dt.now(_tz.utc).strftime("%Y-%m-%d %H:%M:%S"),
               "kind": "silent", "where": "agent_daemon",
               "detail": tag + ": " + type(e).__name__ + ": " + str(e)[:100]}
        with log.open("a", encoding="utf-8") as f:
            f.write(_j.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


CHROME_CPU_LIMIT = 80.0   # % — при превышении считаем перегревом
CHROME_CPU_STREAK_NEEDED = 2  # сколько проверок подряд нужно для restart
_chrome_cpu_streak = 0


CHROME_LAZY_ENABLED = False
_boot_reported = False
# P1.5 (сессия 42): дедупликация net-событий в журнале.
# Считаем сигнатуру (vpn_ok, country, proxy_ok); пишем log_event только при смене.
_last_net_sig = None
CHROME_IDLE_SEC = CHROME_IDLE_SEC_DEFAULT


def tick(once=False):
    # s1.6b: kill-flag check (core tampered)
    try:
        _kill = ROOT / "strategy" / "_kill_flag.json"
        if _kill.exists():
            import json as _j, datetime as _dt
            _data = _j.loads(_kill.read_text(encoding="utf-8"))
            _exp = _data.get("expires_at")
            if not _exp:
                _mt = _dt.datetime.fromtimestamp(_kill.stat().st_mtime)
                _exp = (_mt + _dt.timedelta(seconds=3600)).isoformat()
            _now = _dt.datetime.now().isoformat()
            if _now > _exp:
                log("KILL FLAG expired (" + _exp + ") — ignoring, daemon continues")
                try:
                    _kill.rename(_kill.with_suffix(".expired"))
                except Exception:
                    pass
            else:
                log("KILL FLAG: " + str(_data.get("reason", "?")) + " exp=" + _exp)
                log("agent_daemon exiting (exit=9)")
                sys.exit(9)
    except SystemExit:
        raise
    except Exception as _e:
        _silent('agent_daemon_L63', _e)
    log("--- проверка ---")

    # 1. Chrome
    global _chrome_cpu_streak
    _restarted_this_tick = False
    ch = check_chrome()
    if ch.get("alive"):
        log(f"✓ Chrome: pid={ch.get('pid')}")
        try:
            cpu = chrome_cpu_total()
            if cpu > CHROME_CPU_LIMIT:
                _chrome_cpu_streak += 1
                log("⚠ Chrome CPU " + str(round(cpu, 1)) + "% > "
                    + str(CHROME_CPU_LIMIT) + "% (streak "
                    + str(_chrome_cpu_streak) + "/" + str(CHROME_CPU_STREAK_NEEDED) + ")")
                if _chrome_cpu_streak >= CHROME_CPU_STREAK_NEEDED:
                    log("⚠ Chrome перегрев " + str(round(cpu, 1))
                        + "% — перезапускаю")
                    log_event(site="chrome", action="overheat",
                              result="restart", note="cpu=" + str(round(cpu, 1)))
                    restart_chrome()
                    time.sleep(5)
                    _chrome_cpu_streak = 0
                    _restarted_this_tick = True
            else:
                if _chrome_cpu_streak > 0:
                    log("✓ Chrome CPU " + str(round(cpu, 1))
                        + "% — в норме, streak сброшен")
                _chrome_cpu_streak = 0
        except Exception as _ce:
            log("! Chrome CPU check failed: " + str(_ce))

        if CHROME_LAZY_ENABLED and not _restarted_this_tick:
            try:
                idle = chrome_idle_sec()
                if idle is not None and idle > CHROME_IDLE_SEC:
                    log("i Chrome idle " + str(int(idle)) + "s > "
                        + str(CHROME_IDLE_SEC) + "s — останавливаю (lazy)")
                    log_event(site="chrome", action="idle_stop",
                              result="ok", note="idle=" + str(int(idle)))
                    ok_stop, detail_stop = chrome_stop()
                    if not ok_stop:
                        log("! chrome_stop fail: " + str(detail_stop))
            except Exception as _ie:
                log("! Chrome idle check failed: " + str(_ie))
    else:
        if CHROME_LAZY_ENABLED:
            log("✓ Chrome не запущен (lazy mode) — не поднимаю без запроса")
        else:
            log("✗ Chrome мёртв → перезапускаю")
            try:
                restart_chrome()
                time.sleep(5)
                ch = check_chrome()
                if ch.get("alive"):
                    log(f"✓ Chrome перезапущен: pid={ch.get('pid')}")
                    log_event(site="chrome", action="restart", result="ok")
                else:
                    log("✗ Chrome не поднялся")
                    log_event(site="chrome", action="restart", result="fail")
            except Exception as e:
                log(f"✗ Ошибка перезапуска: {e}")
                log_event(site="chrome", action="restart", result="error", note=str(e))

    # 2. VPN + прокси
    global _last_net_sig
    vpn_ok, ip, country, org, vpn_note = check_vpn()
    proxy_ok, proxy_note = check_proxy()
    _sig = (vpn_ok, country, proxy_ok)
    _changed = (_sig != _last_net_sig)
    _last_net_sig = _sig
    if not vpn_ok:
        log(f"✗ VPN: {vpn_note}")
        if _changed:
            log_event(site="vpn", action="check", result="fail", note=str(vpn_note))
    elif country == "GE":
        log(f"⚠ VPN выключен (страна {country}) — Groq даст 403")
        if _changed:
            log_event(site="vpn", action="check", result="warn", note="country=GE")
    else:
        if is_llm_blocked(country):
            log(f"⚠ VPN: {country} ({ip}) — Groq/OpenAI дадут 403")
            if _changed:
                log_event(site="vpn", action="check", result="warn",
                          note=f"country={country} llm_blocked")
        else:
            log(f"✓ VPN: {country} ({ip})")
    if proxy_ok:
        log(f"✓ Прокси: {proxy_note}")
    else:
        log(f"✗ Прокси: {proxy_note}")
        if _changed:
            log_event(site="proxy", action="check", result="fail", note=str(proxy_note))

    # 3. LLM-ping убран (сессия 21). llm_call.llm() идёт мимо cooldown-логики,
    # давал ~20 fail/20мин. LLM-инфраструктурой занимается infra_agent.py.


    # 4. Sysmon (CPU/temp/mem, s79-1d)
    try:
        _s = sysmon.snapshot()
        _alerts = sysmon.evaluate(_s)
        sysmon.record(_s, _alerts)
        _load1 = _s.get('load', {}).get('1', 0)
        _idle = _s.get('cpu', {}).get('idle', 0)
        _th = _s.get('thermal_level')
        _tl = _s.get('throttle', {})
        log('\u2713 Sys: load=' + str(_load1) + '/' + str(_s.get('ncpu', '?'))
            + ' cpu_idle=' + str(_idle) + '%'
            + ' thermal=' + str(_th)
            + ' throttle=' + str(_tl.get('scheduler_limit'))
            + '/' + str(_tl.get('available_cpus')))
        for _m, _lvl, _v, _thr in _alerts:
            log('\u26a0 Sys alert: ' + _m + '=' + str(_v)
                + ' (' + _lvl + ', \u043f\u043e\u0440\u043e\u0433 ' + str(_thr) + ')')
    except Exception as _se:
        log('! sysmon check failed: ' + str(_se))

    log("--- конец проверки ---\n")

    # Boot-report — один раз после старта демона
    global _boot_reported
    if not _boot_reported and not once:
        try:
            import boot_report
            p_rep = boot_report.write()
            log("boot-report: " + str(p_rep))
        except Exception as _be:
            log("! boot-report fail: " + str(_be))
        _boot_reported = True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=300, help="секунд между проверками")
    ap.add_argument("--once", action="store_true", help="один прогон и выход")
    ap.add_argument("--chrome-lazy", action="store_true",
                    help="не держать Chrome, поднимать по запросу, останавливать при idle")
    ap.add_argument("--chrome-idle-min", type=int, default=15,
                    help="минут idle до остановки Chrome (lazy)")
    args = ap.parse_args()

    global CHROME_LAZY_ENABLED, CHROME_IDLE_SEC
    CHROME_LAZY_ENABLED = bool(args.chrome_lazy)
    CHROME_IDLE_SEC = max(60, args.chrome_idle_min * 60)
    if CHROME_LAZY_ENABLED:
        log(f"Chrome-lazy: ON, idle-stop через {args.chrome_idle_min} мин")

    if args.once:
        tick(once=True)
        return

    log(f"Демон запущен, интервал {args.interval} сек. Ctrl+C — стоп.")
    while True:
        try:
            tick()
            time.sleep(args.interval)
        except KeyboardInterrupt:
            log("Стоп по Ctrl+C.")
            break
        except Exception as e:
            log(f"Ошибка в цикле: {e}")
            time.sleep(30)


if __name__ == "__main__":
    main()
