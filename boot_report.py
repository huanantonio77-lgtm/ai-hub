#!/usr/bin/env python3
"""boot_report.py — отчёт о старте агента после загрузки/рестарта."""
import subprocess, re, os
from datetime import datetime
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
               "kind": "silent", "where": "boot_report",
               "detail": tag + ": " + type(e).__name__ + ": " + str(e)[:100]}
        with log.open("a", encoding="utf-8") as f:
            f.write(_j.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass

ROOT = Path.home() / "Desktop/ai-hub"
REPORT = ROOT / "strategy" / "BOOT_REPORT.md"
INFRA_LOG = ROOT / "knowledge" / "infra-log.md"


def _launchd_jobs():
    try:
        r = subprocess.run(["launchctl", "list"], capture_output=True,
                           text=True, timeout=10)
        out = []
        for ln in (r.stdout or "").splitlines():
            if "com.ainova" in ln:
                parts = ln.split()
                pid = parts[0] if parts else "-"
                label = parts[-1] if parts else "?"
                out.append({"label": label, "pid": pid})
        return out
    except Exception:
        return []


def _net_mode():
    try:
        import netcheck
        return netcheck.get_network_mode_cached()
    except Exception:
        return ("unknown", "?", False, "netcheck unavailable")


def _chrome():
    try:
        import selfcheck
        ch = selfcheck.check_chrome()
        try:
            cpu = selfcheck.chrome_cpu_total()
        except Exception:
            cpu = 0.0
        try:
            idle = selfcheck.chrome_idle_sec()
        except Exception:
            idle = None
        return {"alive": ch.get("alive"), "pid": ch.get("pid"),
                "cdp": ch.get("cdp"), "cpu": cpu, "idle": idle}
    except Exception as e:
        return {"alive": False, "pid": None, "cdp": 0,
                "cpu": 0.0, "idle": None, "err": str(e)}


def _free_mem_pct():
    try:
        r = subprocess.run(["memory_pressure"], capture_output=True,
                           text=True, timeout=10)
        m = re.search(r"free percentage:\s*(\d+)", r.stdout or "")
        if m:
            return int(m.group(1))
    except Exception as _e:
        _silent('boot_report_L62', _e)
    return None


def _session_num():
    try:
        cur = ROOT / "self" / "current.md"
        if cur.exists():
            txt = cur.read_text(encoding="utf-8")
            m = re.search(r"Последняя сессия:\s*(\d+)", txt)
            if m:
                return int(m.group(1))
    except Exception as _e:
        _silent('boot_report_L75', _e)
    return None


def collect():
    net = _net_mode()
    mode = net[0] if len(net) > 0 else "unknown"
    country = net[1] if len(net) > 1 else "?"
    proxy_ok = bool(net[2]) if len(net) > 2 else False
    detail = net[3] if len(net) > 3 else ""

    vpn_off = country in ("RU", "GE", "BY") and mode != "direct"
    chrome = _chrome()
    jobs = _launchd_jobs()
    try:
        load = os.getloadavg()
    except Exception:
        load = (0.0, 0.0, 0.0)

    needs = False
    reason = None
    if vpn_off and not proxy_ok:
        needs = True
        reason = "VPN off AND proxy off — изоляция"
    if not chrome.get("alive"):
        needs = True
        reason = ((reason + "; ") if reason else "") + "Chrome не поднялся"

    return {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "session": _session_num(),
        "launchd_jobs": jobs,
        "launchd_count": len(jobs),
        "chrome": chrome,
        "net_mode": mode,
        "country": country,
        "proxy_ok": proxy_ok,
        "net_detail": detail,
        "vpn_off": vpn_off,
        "loadavg": load,
        "free_mem_pct": _free_mem_pct(),
        "needs_intervention": needs,
        "intervention_reason": reason,
    }


def render_md(d):
    L = []
    L.append("# BOOT_REPORT — запуск агента")
    L.append("")
    L.append("**Время:** " + str(d.get("ts")))
    if d.get("session"):
        L.append("**Сессия:** " + str(d.get("session")))
    L.append("")
    L.append("## Система")
    L.append("")
    L.append("- launchd: " + str(d.get("launchd_count")) + "/5")
    for j in (d.get("launchd_jobs") or []):
        L.append("  - " + str(j.get("label")) + " pid=" + str(j.get("pid")))
    la = d.get("loadavg") or (0, 0, 0)
    L.append("- load: {:.2f} {:.2f} {:.2f}".format(la[0], la[1], la[2]))
    if d.get("free_mem_pct") is not None:
        L.append("- free mem: " + str(d.get("free_mem_pct")) + "%")
    L.append("")
    L.append("## Сеть")
    L.append("")
    L.append("- режим: " + str(d.get("net_mode")))
    L.append("- страна: " + str(d.get("country")))
    L.append("- прокси: " + ("OK" if d.get("proxy_ok") else "FAIL")
             + " — " + str(d.get("net_detail")))
    if d.get("vpn_off"):
        L.append("- ВНИМАНИЕ: VPN выключен, работаем через прокси")
    L.append("")
    L.append("## Chrome")
    L.append("")
    ch = d.get("chrome") or {}
    L.append("- жив: " + str(ch.get("alive")))
    L.append("- pid: " + str(ch.get("pid")))
    L.append("- CDP: " + str(ch.get("cdp")))
    L.append("- CPU: " + str(round(ch.get("cpu") or 0.0, 1)) + "%")
    idle = ch.get("idle")
    if idle is not None:
        L.append("- idle: " + str(int(idle)) + " сек")
    L.append("")
    if d.get("needs_intervention"):
        L.append("## ТРЕБУЕТСЯ ВМЕШАТЕЛЬСТВО")
        L.append("")
        L.append(str(d.get("intervention_reason")))
        L.append("")
    return "\n".join(L) + "\n"


def _notify(title, msg):
    try:
        script = 'display notification "' + msg + '" with title "' + title + '"'
        subprocess.run(["osascript", "-e", script],
                       capture_output=True, timeout=10)
        return True
    except Exception:
        return False


def write(data=None):
    if data is None:
        data = collect()
    md = render_md(data)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(md, encoding="utf-8")
    try:
        INFRA_LOG.parent.mkdir(parents=True, exist_ok=True)
        ch = data.get("chrome") or {}
        line = ("\n[BOOT] " + str(data.get("ts"))
                + " launchd=" + str(data.get("launchd_count")) + "/5"
                + " chrome=" + ("ok" if ch.get("alive") else "FAIL")
                + " net=" + str(data.get("net_mode"))
                + " interventions=" + ("1" if data.get("needs_intervention") else "0"))
        with open(INFRA_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as _e:
        _silent('boot_report_L194', _e)
    if data.get("needs_intervention"):
        _notify("AI NOVA: нужно внимание",
                "Смотри strategy/BOOT_REPORT.md — " + str(data.get("intervention_reason")))
    elif data.get("vpn_off") and data.get("proxy_ok"):
        _notify("AI NOVA: агент запущен",
                "VPN off, работаем через прокси. Всё ок.")
    return REPORT


if __name__ == "__main__":
    p = write()
    print("wrote:", p)
