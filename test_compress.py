import re, sys
sys.path.insert(0, '.')

# Импорт не через orchestrator (он тяжёлый) — копируем логику для теста
_SEARCH_BLOCK_RE = re.compile(
    r'(--- (?:web_search|fetch_url|fetch_render)[^\n]*---\n)(.*?)(\n--- конец ---)',
    re.DOTALL,
)
_KEEP = 500

def _compress(contents, keep_recent=1):
    user_idx = [i for i, m in enumerate(contents) if m.get("role") == "user"]
    if len(user_idx) <= keep_recent:
        return 0
    keep_set = set(user_idx[-keep_recent:])
    saved = 0
    for i, msg in enumerate(contents):
        if i in keep_set or msg.get("role") != "user":
            continue
        for part in msg.get("parts", []):
            t = part.get("text") or ""
            if "--- web_search" not in t and "--- fetch_url" not in t and "--- fetch_render" not in t:
                continue
            def _short(m):
                head, body, tail = m.group(1), m.group(2), m.group(3)
                if len(body) <= _KEEP:
                    return head + body + tail
                cut = len(body) - _KEEP
                return head + body[:_KEEP] + f"\n...[сжато {cut} симв.]\n" + tail
            new_t, n = _SEARCH_BLOCK_RE.subn(_short, t)
            if n:
                saved += len(t) - len(new_t)
                part["text"] = new_t
    return saved

# Синтетика
big_body = "x" * 3000
contents = [
    {"role": "user", "parts": [{"text": "задача"}]},
    {"role": "model", "parts": [{"text": "ok"}]},
    {"role": "user", "parts": [{"text": f"--- web_search: q1 ---\n{big_body}\n--- конец ---"}]},
    {"role": "model", "parts": [{"text": "ok"}]},
    {"role": "user", "parts": [{"text": f"--- web_search: q2 ---\n{big_body}\n--- конец ---"}]},
    {"role": "model", "parts": [{"text": "ok"}]},
    {"role": "user", "parts": [{"text": f"--- web_search: q3 (свежий) ---\n{big_body}\n--- конец ---"}]},
]
before = sum(len(p.get("text") or "") for m in contents for p in m.get("parts", []))
saved = _compress(contents, keep_recent=1)
after = sum(len(p.get("text") or "") for m in contents for p in m.get("parts", []))
print(f"before={before}  after={after}  saved={saved}")
assert "сжато" in contents[2]["parts"][0]["text"], "q1 не сжат"
assert "сжато" in contents[4]["parts"][0]["text"], "q2 не сжат"
assert "сжато" not in contents[6]["parts"][0]["text"], "q3 НЕ должен быть сжат (свежий)"
print("OK: логика сжатия верна")
