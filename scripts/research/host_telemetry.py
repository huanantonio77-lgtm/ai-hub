# scripts/research/host_telemetry.py (s188, non-CORE)
"""Host telemetry: RAM / CPU / disk / Ollama. stdlib only (psutil optional)."""
import json
import os
import re
import shutil
import subprocess
import urllib.request


def _sh(cmd, timeout=4):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout or ""
    except Exception:
        return ""


def _psutil():
    try:
        import psutil
        return psutil
    except ImportError:
        return None


def _cpu_pct():
    p = _psutil()
    if p:
        try:
            return round(float(p.cpu_percent(interval=0.1)), 1)
        except Exception:
            pass
    out = _sh(["top", "-l", "1", "-n", "0"])
    m = re.search(r"CPU usage:\s*([\d.]+)% user,\s*([\d.]+)% sys,\s*([\d.]+)% idle", out)
    if m:
        u, s, i = map(float, m.groups())
        return round(u + s, 1)
    return None


def _ram():
    p = _psutil()
    if p:
        try:
            vm = p.virtual_memory()
            return round(vm.used / 1024 ** 2, 1), round(vm.total / 1024 ** 2, 1)
        except Exception:
            pass
    # macOS: parse `top -l 1 -n 0` PhysMem line. It correctly accounts for inactive + compressor.
    out = _sh(["top", "-l", "1", "-n", "0"])
    m = re.search(r"PhysMem:\s*(\d+)M used.*?(\d+)M unused", out)
    if m:
        used_mb = float(m.group(1))
        unused_mb = float(m.group(2))
        return round(used_mb, 1), round(used_mb + unused_mb, 1)
    # Fallback: vm_stat free + inactive + speculative are "available"
    out2 = _sh(["vm_stat"])
    total_b = _sh(["sysctl", "-n", "hw.memsize"]).strip()
    total_mb = round(int(total_b) / 1024 ** 2, 1) if total_b.isdigit() else None
    if not total_mb:
        return None, None
    m_ps = re.search(r"page size of (\d+) bytes", out2)
    ps = int(m_ps.group(1)) if m_ps else os.sysconf("SC_PAGE_SIZE")

    def _pg(name):
        m = re.search(name + r":\s+(\d+)", out2)
        return int(m.group(1)) if m else 0

    free = (_pg("Pages free") + _pg("Pages inactive") + _pg("Pages speculative"))
    used_mb = round((total_mb * 1024 ** 2 - free * ps) / 1024 ** 2, 1)
    return used_mb, total_mb


def _ollama():
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2) as r:
            data = json.loads(r.read().decode("utf-8"))
        return True, [m.get("name", "?") for m in data.get("models", [])]
    except Exception:
        return False, []


def collect_host_telemetry():
    cpu_pct = _cpu_pct()
    ram_used, ram_total = _ram()
    ram_pct = round(ram_used / ram_total * 100, 1) if (ram_used and ram_total) else None
    try:
        load1 = round(os.getloadavg()[0], 2)
    except Exception:
        load1 = None
    try:
        d = shutil.disk_usage("/")
        disk_free, disk_pct = round(d.free / 1024 ** 3, 2), round(d.used / d.total * 100, 1)
    except Exception:
        disk_free, disk_pct = None, None
    o_ok, o_models = _ollama()
    return {
        "cpu_pct": cpu_pct, "cpu_count": os.cpu_count(), "load_1m": load1,
        "ram_used_mb": ram_used, "ram_total_mb": ram_total, "ram_pct": ram_pct,
        "disk_free_gb": disk_free, "disk_pct": disk_pct,
        "ollama_ok": o_ok, "ollama_models": o_models,
    }


def render_telemetry_block(t):
    L = ["## Host telemetry", "", "| metric | value |", "|---|---|"]
    if t["load_1m"] is not None and t["cpu_count"]:
        note = " WARN overload" if t["load_1m"] > t["cpu_count"] else ""
        L.append("| load 1m | %s / %s CPU%s |" % (t["load_1m"], t["cpu_count"], note))
    if t["cpu_pct"] is not None:
        L.append("| CPU | %s%% |" % t["cpu_pct"])
    if t["ram_used_mb"] and t["ram_total_mb"]:
        L.append("| RAM | %s / %s MB (%s%%) |" % (t["ram_used_mb"], t["ram_total_mb"], t["ram_pct"]))
    if t["disk_free_gb"] is not None:
        L.append("| disk free | %s GB (%s%% used) |" % (t["disk_free_gb"], t["disk_pct"]))
    if t["ollama_ok"]:
        L.append("| ollama | OK %s |" % (", ".join(t["ollama_models"]) or "(none)"))
    else:
        L.append("| ollama | FAIL not responding |")
    return "\n".join(L)


if __name__ == "__main__":
    t = collect_host_telemetry()
    print(json.dumps(t, ensure_ascii=False, indent=2))
    print("---")
    print(render_telemetry_block(t))
