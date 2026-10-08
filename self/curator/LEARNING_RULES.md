# LEARNING_RULES.md — правила самообучения ai-hub (s178, обновл. s183)

## 1. Приоритет источников
OpenAlex → Crossref → arXiv → Web (Brave/CSE)

## 2. APPLY (ценное)
technique ∈ {
  gateway, quota, billing, metering, enforcement,
  rate-limit, provider-adapter,
  self-heal, self-healing, self-evolv, self-planning,
  self-correct, self-correcting, self-organi, self-adapt,
  self-manag, autonomous, autonomy,
  monitoring, observability, telemetry,
  resilience, fault-toleran, retry, backoff,
  detection-engineering
}
OR field ∈ {cs.LG, cs.AI, cs.SE}

## 3. REJECT (авто)
survey, comparative, overview, analysis, review, taxonomy,
provenance-only без implementable technique

## 4. DEFER
confidence ∈ {low, medium} AND no APPLY-keyword · protocol без ясного пути
confidence == high → всегда APPLY-priority

## 5. Границы применения
apply только в self/curator/drafts/ · max 3 draft/сессия
не в прод scripts/ без human-approve

## 6. Human-in-the-loop
`curator --classify --review` (P5) · move drafts→scripts вручную
REJECT не стирается (SELF_PROPOSALS.jsonl)

## 7. Feedback-loop (s183+)
draft → verify → score → improve: classify --commit пишет статусы, drafts генерируются в daemon-loop

## s194-r0 — DEX-only (ЗАФИКСИРОВАНО)
Вся торговля — ТОЛЬКО на DEX. CEX запрещены до явной команды пользователя.
Куратор не предлагает CEX. Даже как альтернативу. Даже как "B" вариант.
Подключение CEX возможно только после прямого указания пользователя.

## s194-r1 — DEX 3 уровня подключения
Level 1: без регистрации (публичный REST). Batch'ем.
Level 2: API-key (ручная регистрация пользователя).
Level 3: подпись кошелька (EIP-712/SNIP-12/Solana, web3).
Строго по порядку. CEX — запрещены.

## s194-r2 — deep_dive ≠ search_works
deep_dive → научные техники (OpenAlex, arXiv, Crossref). Методы, паттерны.
search_works → веб-списки (webless+ddgs). Актуальные перечни объектов.
Не путать. Для «списка DEX 2026» → search_works. Для «как устроен DEX» → deep_dive.

## s195-r0 — AMM synthetic book (Orca/Raydium)
Orca/Raydium — AMM. Orderbook API нет. Синтетический 1-уровневый: bid = price*(1-fee/2),
ask = price*(1+fee/2). fee_bps: Orca=30, Raydium=25.

## s195-r1 — GMX oracle synthetic book
GMX V2: oracle prices, scale = 10^(30-decimals). mid = (min+max)/2. fee_bps=20.

## s195-r2 — User-Agent обязателен (403 fix)
orca/raydium/gmx: без UA → 403. С UA: Mozilla/5.0 ... → 200.

## s195-r3 — Aliases: WSOL (Raydium), SOL/USD (GMX)
Raydium: SOL → WSOL. GMX: "SOL/USD" (не SOL/USDC). Alias-map в клиенте.

## s195-r4 — Injective = gRPC-Web (BACKLOG P2)
REST orderbook 404. async_client_v2 в pyinjective v1.16. Отложено.

## s195-r5 — Паттерн DEX-клиента = 3 файла
Клиент + тест + registry. Healthcheck подхватывает автоматом (s193-r0).

## s195-r6 — Auto-lesson-extraction (BACKLOG P1)
Прямая формулировка пользователя: дыра. Должно быть: агент сам извлекает уроки
из работы с человеком. 4 задачи в BACKLOG_LESSON_AUTONOMY. Приоритет P1 после DEX.

## 6. Синтез, а не выбор (s211 — АБСОЛЮТНОЕ)

При сравнении двух стратегий (A vs B) — по умолчанию стремимся к **синтезу C**,
а не к «победителю». Даже если B провалилась — её **идея** может быть хорошей.

Правило:
- A > B → C = A-вход + лучшая идея B (не «B отбросить»)
- B > A → C = B-вход + лучшая идея A
- A ≈ B → C = лучший вход + лучший выход

Отказ от идеи — только если она **провалилась в изоляции** (сама по себе не работает).

Основание: run 3 показал, что winners имели ub>=9 — это идея из A.
A/B run показал, что flow-reversal не работает без фильтра входа — это идея из B.
Синтез C: A-вход (dev>=2, np>=0.3, ub>=3) + B-выход (flow reversal вместо timeout).

## 7. Одна переменная за раз, 30+ наблюдений (s211 — АБСОЛЮТНОЕ)

Меняем **только одну переменную** за раз, **только после 30+ наблюдений**.

Правило:
- 7 сделок = мало данных для оптимизации (риск overfitting)
- 30+ наблюдений = статистически значимо
- Меняешь одно — фиксируешь всё остальное
- Записываешь гипотезу → потом тестируешь → потом меняешь

Основание: run 3 показал ub>=9 у winners, но это 7 сделок.
Сейчас менять ub с 3 на 8 = premature optimization.
Правильно: записать гипотезу, накопить 30+ сделок, потом менять.


## Правило 8 — Live только после paper-плюса

**Источник:** s212 (пользователь, дословно: "A работает в трейдинге, а B мы тестим, A после успеха должно работать на реальных деньгах, а B и не торговать пока мы B не выведем в + значит она не будет применяться к реальным деньгам").

**Формулировка:**
- Стратегия с устойчивым paper-плюсом (30+ сделок, PnL>0) — допускается к live.
- Стратегия в тестировании (новая / модифицированная) — только paper.
- Стратегия с paper-PnL <= 0 — в live НЕ идёт вообще.
- Синтез (Правило 6) — новая стратегия C сначала в paper, live только после плюса.

**Следствие s212:**
- A (baseline) — устойчиво + → кандидат на live (после P0 persistent positions).
- B (flow-based) — 0/66 W, PnL<0 → ТОЛЬКО paper, live запрещён.
- C (A-вход + B-выход) — сначала paper.

**Проверка:** live-ордер разрешён только если стратегия в whitelist (paper-PnL>0 за 30+ сделок). Иначе — отказ.
