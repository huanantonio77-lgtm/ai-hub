# tools/anti_ai_slop — vendor (MIT)

**Источник:** https://github.com/misbahsy/anti-ai-slop
**Лицензия:** MIT (см. LICENSE)
**Дата вендоринга:** 2026-09-27 (сессия 49)

## Что это

Детерминистический линтер AI-«slop» в текстах: 41 правило (англ.),
zero dependencies, Python 3.8+. Плюс sanitizer невидимых символов
(zero-width, bidi, tag chars).

## Что взято

| Файл | Размер | Назначение |
|---|---|---|
| slopcheck.py | 21 KB | линтер, CLI: `slopcheck.py DRAFT.md [--json] [--gate 90]` |
| sanitize.py | 8 KB | очистка invisible chars: `sanitize.py DRAFT.md [--fix]` |
| rules.json | 24 KB | 41 правило + scoring (start=100, gate=90) |
| tests/fixtures/*.md | ~2 KB | тестовые образцы (slop, clean, masking) |
| README.upstream.md | 7.5 KB | оригинальный README (для истории) |

## Что НЕ взято

- `grade.py` — LLM-панель через LiteLLM SDK (нужен свой ключ)
- `detect.py` — внешний сервис sapling.ai (утечка данных)
- `credentials.py` — управление ключами

## Применение у нас

Планируется как quality gate в пайплайне агента:
- валидация текстов writer-агента перед публикацией,
- валидация lessons.md / HANDOFF перед close,
- враппер `self.py slop <file>`.

## Обновление

Чтобы обновить из upstream — скачать 3 файла из
`skills/anti-ai-slop/scripts/` заново (slopcheck.py, sanitize.py, rules.json).
Сверить LICENSE, обновить дату вендоринга.
