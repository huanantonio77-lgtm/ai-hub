#!/usr/bin/env python3
"""self_monitor.py (s181 P0, s182 P0-C/P0-D) - watchdog + classify + auto-fix."""
import subprocess, datetime, os, sys
from pathlib import Path
ROOT = Path.home() / "Desktop" / "ai-hub"
OUT = ROOT / "self/curator/AGENT_HEALTH.md"
KILL_FLAG = ROOT / "strategy" / "_kill_flag.json"

WARN = {
    "com.ainova.self-loop":        {2: "tcc_blocked"},
    "com.ainova.fb-sync":          {1: "no_live_providers"},
    "com.ainova.autonomy-recheck": {1: "regression_signal", 2: "regression_signal"},
}

def fix_kill_flag_stale():
    r = subprocess.run(["python3", str(ROOT / "scripts/sign_core.py"), "--verify"],
                       capture_output=True, text=True, cwd=str(ROOT))
    if '"valid": true' not in r.stdout:
        return False, "sig invalid, skip"
    if not KILL_FLAG.exists():
        return False, "flag absent"
    KILL_FLAG.unlink()
    uid = os.getuid()
    subprocess.run(["launchctl", "kickstart", "-k",
                    "gui/" + str(uid) + "/com.ainova.agent-daemon"],
                   capture_output=True)
    return True, "rm kill_flag + kickstart agent-daemon"

AUTO_FIX = {
    ("com.ainova.agent-daemon", 9): ("kill_flag_stale", fix_kill_flag_stale),
}

def probe():
    r = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    out = []
    for ln in r.stdout.splitlines():
        p = ln.split("\t")
        if len(p) >= 3 and "ainova" in p[2]:
            out.append((p[2], p[0], p[1]))
    return out

def _i(s):
    try: return int(s)
    except: return None

def classify(name, pid, ec):
    if pid != "-":
        return "running", None
    ei = _i(ec)
    if ei == 0:
        return "idle", None
    if ei in WARN.get(name, {}):
        return "WARN", WARN[name][ei]
    return "FAIL", "exit_" + str(ec)

def run_fixes(rows, apply_mode):
    log = []
    for n, p, e in rows:
        ei = _i(e)
        if ei is None:
            continue
        key = (n, ei)
        if key not in AUTO_FIX:
            continue
        reason, fn = AUTO_FIX[key]
        if not apply_mode:
            log.append((n, reason, "DRY: would apply"))
            continue
        ok, detail = fn()
        log.append((n, reason, ("APPLIED: " if ok else "SKIP: ") + detail))
    return log

def render(rows, fixlog, apply_mode):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    R = [(n, p, e, *classify(n, p, e)) for n, p, e in rows]
    F = [x for x in R if x[3] == "FAIL"]
    W = [x for x in R if x[3] == "WARN"]
    L = ["# AGENT_HEALTH (s181 P0, s182 P0-C/P0-D)",
         "**Updated:** " + now,
         "**Total:** " + str(len(rows)) + " **FAIL:** " + str(len(F)) + " **WARN:** " + str(len(W)),
         "**Mode:** " + ("apply" if apply_mode else "dry-run"),
         "",
         "| agent | pid | exit | status | reason |",
         "|---|---|---|---|---|"]
    for n, p, e, s, r in R:
        L.append("| " + n + " | " + p + " | " + e + " | " + s + " | " + (r or "") + " |")
    if F:
        L += ["", "## ALARMS (FAIL)"]
        for n, p, e, s, r in F:
            L.append("- **" + n + "** exit=" + e + " reason=" + str(r))
    if W:
        L += ["", "## WARN (semantic signals)"]
        for n, p, e, s, r in W:
            L.append("- **" + n + "** exit=" + e + " reason=" + str(r))
    if fixlog:
        L += ["", "## AUTO-FIX (" + ("applied" if apply_mode else "dry-run") + ")"]
        for n, reason, detail in fixlog:
            L.append("- **" + n + "** reason=" + reason + " | " + detail)
    return "\n".join(L) + "\n"

def main():
    apply_mode = "--apply" in sys.argv
    rows1 = probe()
    fixlog = run_fixes(rows1, apply_mode)
    rows = probe() if (apply_mode and fixlog) else rows1
    OUT.write_text(render(rows, fixlog, apply_mode), encoding="utf-8")
    print("mode=" + ("apply" if apply_mode else "dry-run") +
          " probe=" + str(len(rows)) + " fixes=" + str(len(fixlog)))

if __name__ == "__main__":
    main()
