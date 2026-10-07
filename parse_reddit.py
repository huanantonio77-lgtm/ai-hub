#!/usr/bin/env python3
"""parse_reddit.py - вытащить посты с текущей страницы Reddit.
Возвращает JSON: заголовок, ссылка, автор, голоса, комменты.
"""
import sys, json, subprocess, tempfile
from pathlib import Path

ROOT = Path.home() / "Desktop/ai-hub"

JS = r'''
(() => {
  const out = [];
  const seen = new Set();
  const all = document.querySelectorAll('a[href*="/comments/"]');
  for (const a of all) {
    const href = a.href.split('?')[0];
    if (seen.has(href)) continue;
    seen.add(href);
    const t = (a.innerText || '').trim();
    if (t.length < 15) continue;
    let post = a.closest('article') || a.parentElement;
    let score = '', comments = '', author = '';
    if (post) {
      const txt = (post.innerText || '');
      const m = txt.match(/(\d+)\s*(голос|vote|upvote)/i);
      if (m) score = m[1];
      const c = txt.match(/(\d+)\s*(коммент|comment)/i);
      if (c) comments = c[1];
      const au = txt.match(/u\/([A-Za-z0-9_-]+)/);
      if (au) author = au[1];
    }
    out.push({title: t.slice(0, 200), url: href, score, comments, author});
    if (out.length >= 25) break;
  }
  return JSON.stringify(out);
})()
'''

def main():
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
        f.write(JS); path = f.name
    cmd = [sys.executable, 'js_run.py', path, '--on-url', 'reddit.com']
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if '[js on' in line:
            payload = line.split('] ', 1)[1] if '] ' in line else ''
            try:
                posts = json.loads(payload)
                for i, p in enumerate(posts, 1):
                    print(f"[{i}] {p['title']}")
                    print(f"    {p['url']}")
                    print(f"    score={p['score'] or '?'} comments={p['comments'] or '?'} author=u/{p['author'] or '?'}")
                    print()
                return
            except Exception as e:
                print('parse error:', e)
                print(payload[:300])
                return
    print('NO OUTPUT'); print(r.stdout[-500:]); print(r.stderr[-300:])

if __name__ == "__main__":
    main()