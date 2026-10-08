import sys,subprocess,json
from pathlib import Path
R=Path(__file__).resolve().parent
c=sys.argv[1] if len(sys.argv)>1 else "help"
if c=="status":
    o=subprocess.run("pgrep -fl self_daemon;pgrep -fl agent_daemon",shell=True,capture_output=True,text=True).stdout.strip()
    print("daemons:"); print(o if o else "  (none)")
    print("paused:",(R/".runtime/trading_paused.flag").exists())
elif c=="pause":
    (R/".runtime/trading_paused.flag").write_text("{}");print("PAUSED")
elif c=="resume":
    p=R/".runtime/trading_paused.flag"
    if p.exists(): p.unlink()
    print("ACTIVE")
else:
    print("commands: status | pause | resume")
