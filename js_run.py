#!/usr/bin/env python3
"""js_run.py - выполнить JS из файла в Chrome агента.
Использование:
  js_run.py <путь.js> [--on-url URL]

JS-код читается из файла, поэтому не ломается от zsh:
символы !, &, ~, кавычки в файле безопасны.
"""
import sys, subprocess
from pathlib import Path

ROOT = Path.home() / "Desktop/ai-hub"
BA = ROOT / "browser_actions.py"

def main():
    if len(sys.argv) < 2:
        print("usage: js_run.py <file.js> [--on-url URL]"); sys.exit(1)
    js_file = Path(sys.argv[1])
    if not js_file.exists():
        print("ERROR: файл не найден:", js_file); sys.exit(2)
    js = js_file.read_text(encoding='utf-8')
    cmd = [sys.executable, str(BA), 'js']
    if '--on-url' in sys.argv:
        i = sys.argv.index('--on-url')
        cmd += ['--on-url', sys.argv[i+1]]
    cmd.append(js)
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    out = r.stdout + r.stderr
    for line in out.splitlines():
        if 'DeprecationWarning' in line or 'trace-deprecation' in line:
            continue
        if line.startswith('(node:'):
            continue
        print(line)

if __name__ == "__main__":
    main()