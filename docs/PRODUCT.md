# PRODUCT — ai-hub (design, s199)

**Status:** design only. Реализация — s200+.
**Session:** s199, P3-C (open-source packaging).
**Chosen direction:** C (open-source продукт).

---

## 1. Vision

**ai-hub** — открытый «автономный read-only трейдер + research-агент»:

- 7 DEX live (Hyperliquid, dYdX, Paradex, Orca, Raydium, GMX, Injective).
- 4 self-оси по 100% (Автономность / Самообслуживание / Самообучение / Самодиагностика).
- 27 healers, sign 14/14, 0 drift, 0 regression.
- Автономное извлечение уроков (s196), auto-research по трейдингу (s198), rolling stats (s199).
- Ноль LLM-API в runtime (R1), ноль ML (R2), сеть только к публичным DEX (R4).
- Локальный Ollama (qwen2.5-coder:3b + bge-m3) — без облачных ключей.

**Ценность для сообщества:** эталонный пример self-improving autonomous agent на чистом Python-stdlib + Ollama, воспроизводимо, без финансовых рисков.

---

## 2. Target users

| Кто | Зачем |
|---|---|
| Разработчики LLM-агентов | Референс: self-healing loop без LangChain/фреймворков |
| Quant / алготрейдеры | Read-only DEX-сканер + healthcheck как база для стратегий |
| ML/NLP исследователи | Auto-research pipeline (8 источников, LLM-формулировка запросов) |
| Self-hosting enthusiasts | Поставил у себя — работает автономно |

---

## 3. Non-goals

- НЕ торгуем за пользователя (phase 1, place_order = no-op).
- НЕ даём финсоветы (дисклеймер в README / PRODUCT / CLI).
- НЕ храним ключи (нет приватных ключей, нет аккаунтов, нет подписок).
- НЕ SaaS (направления A/B — только если community подтвердит интерес).
- НЕ production-ready (research/education, не для реальных денег).

---

## 4. Структура файлов (в s200)

```
ai-hub/
├── README.md              — 1 экран: что, кому, quickstart 2 мин
├── LICENSE                — MIT
├── docs/
│   ├── PRODUCT.md         — этот файл
│   ├── QUICKSTART.md      — install -> pre-flight -> scan
│   ├── ARCHITECTURE.md    — 4 оси, daemon loop, healers, R1-R5
│   └── DISCLAIMER.md      — юр-текст: не финсовет, read-only
└── (существующий код)
```

Dockerfile — s201 (после первого feedback).

---

## 5. README.md — структура

1. Заголовок + 1-line description.
2. Дисклеймер: Read-only. No trading. No API keys. Educational use only.
3. What it does (4 пункта).
4. Quickstart (2 команды).
5. Status (последняя сессия, ключевые метрики).
6. Philosophy (Self-service -> ... -> product).
7. License + ссылка на DISCLAIMER.md.

**Язык README:** английский (HN / r/LocalLLaMA / r/algotrading).

---

## 6. Roadmap публикации

| Сессия | Шаг |
|---|---|
| s200 | README + LICENSE (MIT) + 4 файла в docs/ |
| s201 | Docker + полировка, скриншоты (pre-flight, scan) |
| s202 | Публикация: GitHub public + 1 пост (HN Show / r/LocalLLaMA / r/algotrading) |
| s203+ | Обработка feedback -> приоритизация issue -> roadmap v2 |

---

## 7. Критерии успеха

| Метрика | 30 дней | 90 дней |
|---|---|---|
| GitHub stars | 10+ | 100+ |
| Внешних issue/PR | 1+ | 5+ |
| Форков | 0 | 10+ |
| Community-предложений (валидация A/B) | 1+ | 5+ |

Если 30-дневные цели не достигнуты — это тоже данные: community не заинтересован -> A/B под вопросом.

---

## 8. Риски и митигации

| Риск | Митигация |
|---|---|
| Примут за финсовет | Дисклеймер в README / PRODUCT / CLI-banner / LICENSE |
| Используют для реальной торговли | place_order = no-op + gate-правило (Автономность >= 97%) |
| Критика «зачем ещё один агент» | Позиционирование: без фреймворков, фокус на self-healing |
| Юр-риск (крипта, РФ/ЕС) | Read-only, без брокерских услуг, MIT без гарантий |
| Слив секретов при публикации | git-secrets перед push, .env отсутствует, ключей нет |

---

## 9. Решения по дефолтам (s199)

- **Лицензия:** MIT (permissive, проще для community).
- **Название:** ai-hub (публичный бренд — если community попросит).
- **Язык README:** английский.
- **Docker:** skip в s200, добавить в s201 при запросе.

---

## 10. Что НЕ входит в P3-C

- Никакого кода агента — только README, docs, LICENSE.
- Никаких изменений в scripts/, arbitrage_bot/, knowledge/.
- Никакой публикации в s199 — только подготовка (публикация s202).
