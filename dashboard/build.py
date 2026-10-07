#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Собирает dashboard/index.html из реальных данных ai-hub."""
import os
from datetime import datetime
from pathlib import Path

HUB = Path.home() / "Desktop" / "ai-hub"
OUT = HUB / "dashboard" / "index.html"

def list_dirs(p):
    if not p.exists(): return []
    return sorted([d.name for d in p.iterdir() if d.is_dir() and not d.name.startswith('.')])

def list_files(p):
    if not p.exists(): return []
    return sorted([f.name for f in p.iterdir() if f.is_file() and not f.name.startswith('.')])

def md_lines(p):
    if not p.exists(): return 0
    try:
        return len([l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()])
    except Exception:
        return 0

def build():
    projects = list_dirs(HUB / "projects")
    logs = list_files(HUB / "logs")
    knowledge = list_files(HUB / "knowledge")
    agents = list_files(HUB / "agents")

    # --- Проекты ---
    proj_items = ""
    for name in projects:
        files = list_files(HUB / "projects" / name)
        proj_items += f'<li><b>{name}</b> <span class="badge">{len(files)} файлов</span></li>'
    if not proj_items:
        proj_items = '<li><span class="wait">—</span> Пока пусто.</li>'

    # --- База знаний ---
    kb_items = ""
    for f in knowledge:
        n = md_lines(HUB / "knowledge" / f)
        kb_items += f'<li>{f} <span class="badge">{n} строк</span></li>'
    if not kb_items:
        kb_items = '<li><span class="wait">—</span> Пусто.</li>'

    # --- Логи ---
    log_items = ""
    for f in logs[-10:]:
        log_items += f'<li>{f}</li>'
    if not log_items:
        log_items = '<li><span class="wait">—</span> Пока пусто.</li>'

    # --- Агенты ---
    agent_items = ""
    for f in agents:
        agent_items += f'<li><b>{f.replace(".md","")}</b> <span class="ok">✓</span></li>'
    if not agent_items:
        agent_items = '<li><span class="wait">—</span> Нет агентов.</li>'

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    html = f'''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>ai-hub — штаб агентов</title>
<meta http-equiv="refresh" content="30">
<style>
  body {{ font-family: -apple-system, sans-serif; background:#fff; color:#111; margin:0; padding:24px; }}
  h1 {{ margin:0 0 4px 0; font-size:22px; }}
  .sub {{ color:#666; margin-bottom:24px; font-size:13px; }}
  .layout {{ display:grid; grid-template-columns: 1fr 380px; gap:20px; }}
  .grid {{ display:grid; grid-template-columns: 1fr 1fr; gap:14px; }}
  .card {{ background:#fafafa; border:1px solid #e5e5e5; border-radius:10px; padding:14px; }}
  .card h2 {{ margin:0 0 10px 0; font-size:14px; color:#0a6cff; }}
  ul {{ margin:0; padding-left:18px; font-size:13px; line-height:1.7; }}
  .ok {{ color:#1a9b3c; }}
  .wait {{ color:#c78a00; }}
  .badge {{ display:inline-block; font-size:11px; padding:2px 8px; border-radius:10px; background:#eee; color:#666; margin-left:6px; }}
  .chat {{ background:#fafafa; border:1px solid #e5e5e5; border-radius:10px; padding:14px; display:flex; flex-direction:column; height:600px; }}
  .chat h2 {{ margin:0 0 8px 0; font-size:14px; color:#0a6cff; }}
  .msgs {{ flex:1; overflow-y:auto; background:#fff; border:1px solid #eee; border-radius:8px; padding:10px; margin-bottom:10px; }}
  .msg {{ margin-bottom:8px; padding:8px 10px; border-radius:8px; font-size:13px; line-height:1.5; }}
  .msg.me {{ background:#e7f0ff; }}
  .msg .t {{ font-size:10px; color:#888; display:block; margin-bottom:2px; }}
  textarea {{ width:100%; box-sizing:border-box; min-height:60px; border:1px solid #ccc; border-radius:8px; padding:8px; font-family:inherit; font-size:13px; resize:vertical; }}
  .row {{ display:flex; gap:8px; margin-top:8px; }}
  button {{ flex:1; padding:8px 12px; border:1px solid #ccc; background:#fff; border-radius:8px; font-size:13px; cursor:pointer; }}
  button.primary {{ background:#0a6cff; color:#fff; border-color:#0a6cff; }}
  button:hover {{ opacity:0.9; }}
</style>
</head>
<body>
  <h1>ai-hub — штаб агентов</h1>
  <div class="sub">Обновлено: {now}. Слева — состояние системы. Справа — твой блокнот-чат.</div>

  <div class="layout">
    <div class="grid">
      <div class="card">
        <h2>Агенты <span class="badge">{len(agents)}</span></h2>
        <ul>{agent_items}</ul>
      </div>

      <div class="card">
        <h2>Проекты <span class="badge">{len(projects)}</span></h2>
        <ul>{proj_items}</ul>
      </div>

      <div class="card">
        <h2>База знаний <span class="badge">{len(knowledge)} файлов</span></h2>
        <ul>{kb_items}</ul>
      </div>

      <div class="card">
        <h2>Логи <span class="badge">{len(logs)} записей</span></h2>
        <ul>{log_items}</ul>
      </div>

      <div class="card">
        <h2>О пользователе</h2>
        <ul>
          <li><b>AI NOVA</b>, автономный AI-агент</li>
          <li>Сайт: ainova.ooo</li>
          <li>Ниши: IT + детский сад</li>
          <li>Аудитория: международная</li>
        </ul>
      </div>

      <div class="card">
        <h2>Что дальше</h2>
        <ul>
          <li>Уровень 4.5: старший зовёт младших (работает)</li>
          <li>Поиск: Tavily + автоприкрепление к researcher</li>
          <li>Уровень 5: кэш, ретраи, параллельные вызовы</li>
        </ul>
      </div>
    </div>

    <div class="chat">
      <h2>Мой чат-блокнот</h2>
      <div class="msgs" id="msgs"></div>
      <textarea id="input" placeholder="Напиши задачу или заметку... (Ctrl+Enter — отправить)"></textarea>
      <div class="row">
        <button class="primary" onclick="send()">Добавить</button>
        <button onclick="exportMd()">Экспорт</button>
        <button onclick="clearAll()">Очистить</button>
      </div>
    </div>
  </div>

<script>
  const KEY = 'ai-hub-chat';
  const msgs = document.getElementById('msgs');
  const input = document.getElementById('input');

  function load() {{
    const data = JSON.parse(localStorage.getItem(KEY) || '[]');
    msgs.innerHTML = '';
    data.forEach(m => addToView(m));
  }}

  function addToView(m) {{
    const div = document.createElement('div');
    div.className = 'msg me';
    div.innerHTML = '<span class="t">' + m.t + '</span>' + m.text.replace(/</g,'&lt;');
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
  }}

  function send() {{
    const text = input.value.trim();
    if (!text) return;
    const data = JSON.parse(localStorage.getItem(KEY) || '[]');
    const m = {{ t: new Date().toLocaleString('ru-RU'), text: text }};
    data.push(m);
    localStorage.setItem(KEY, JSON.stringify(data));
    addToView(m);
    input.value = '';
  }}

  function clearAll() {{
    if (!confirm('Стереть все сообщения?')) return;
    localStorage.removeItem(KEY);
    load();
  }}

  function exportMd() {{
    const data = JSON.parse(localStorage.getItem(KEY) || '[]');
    let out = '# Чат-блокнот ai-hub\\n\\n';
    data.forEach(m => {{ out += '**' + m.t + '**\\n\\n' + m.text + '\\n\\n---\\n\\n'; }});
    const blob = new Blob([out], {{type: 'text/markdown'}});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'chat.md';
    a.click();
  }}

  input.addEventListener('keydown', e => {{
    if (e.ctrlKey && e.key === 'Enter') send();
  }});

  load();
</script>
</body>
</html>'''

    OUT.write_text(html, encoding="utf-8")
    print(f"✓ Дашборд обновлён: {OUT}")
    print(f"  Проектов: {len(projects)} | Логов: {len(logs)} | Знаний: {len(knowledge)} | Агентов: {len(agents)}")

if __name__ == "__main__":
    build()