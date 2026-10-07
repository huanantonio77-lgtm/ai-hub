# F3 — Momentum Strategy for Solana Memecoins (Design)

**Session:** s205
**Статус:** design (не реализовано)
**Цель:** закрыть TZ «$100 -> $200 fast» — gross 100-1000 bps/сделку вместо 3-6 bps corr_pairs.

---

## 1. Контекст

### 1.1. Почему corr_pairs провалился (s205-r6)

- 4 CLOB DEX (HL, dYdX, GMX, Injective) слишком эффективны — spread схлопывается за 1-3 тика.
- Gross edge 3-6 bps, honest costs 12-18 bps -> систематический убыток.
- Verdict: corr_pairs остаётся как **baseline** для сравнения, не как рабочий двигатель.

### 1.2. Почему momentum

- Solana memecoins: **gross движения 100-1000+ bps** за минуты-часы.
- AMM fees (25-100 bps) на таком gross — незначимы.
- Так делают «10x за час» — это моментум на низкой капитализации + свежие пулы.

### 1.3. Принципы

- **DEX-only.** Никаких CEX (правило s194-r0).
- **Read-only phase 1.** `place_order = no-op` до явного разрешения.
- **WebSocket > REST.** REST AMM кэширует (s204-r1), только live WS для моментума.
- **Все costs учтены.** Если не знаем cost — не открываем.
- **Risk-first.** Каждая сделка — с заранее определённым max loss.

---

## 2. Scope

**В фазе s205/s206:**
- Детекция новых/свежих пулов (pump.fun graduated, Raydium new).
- Live mid-price через Solana RPC WebSocket.
- 2-3 сигнала momentum.
- Paper-trading (без реального place_order).

**Отложено:**
- Real trading (по разрешению).
- MEV protection (Jito bundles).
- Multi-wallet execution.


---

## 3. Данные и источники

### 3.1. Пул источников

| Источник | Тип | Что даёт | Auth | Free tier |
|---|---|---|---|---|
| pump.fun API | REST | Новые токены, bonding curve | — | да |
| Raydium API v3 | REST | Pools, price cache (stale) | — | да |
| Raydium WS | WebSocket | Account updates (live) | — | да |
| Meteora DLMM API | REST | Pools, bins, liquidity | — | да |
| Orca Whirlpool API | REST | Pools, ticks | — | да |
| Jupiter Aggregator | REST /quote | Best route over AMM, live | — | да |
| Birdeye API | REST | Price, volume, holders | API key | 10k/day |
| DexScreener API | REST | Aggregated DEX price | — | 30 req/min |
| Solana RPC | RPC + WS | On-chain accounts, logs | URL | 100k/day |
| Helius RPC | RPC + WS | Enhanced tx, WS | API key | 100k/day |


### 3.2. Ключевые endpoints

**pump.fun - новые токены:**

    GET https://frontend-api.pump.fun/coins?offset=0&limit=50&sort=created&order=DESC
    GET https://frontend-api.pump.fun/coins/{mint}
    GET https://frontend-api.pump.fun/coins/{mint}/trades

Bonding curve: migrate на Raydium при market cap около 69 SOL.

**Raydium - pool info:**

    GET https://api-v3.raydium.io/pools/info/mint?mint1={mint}&poolType=standard
    GET https://api-v3.raydium.io/pools/info/ids?ids={poolId}

ВНИМАНИЕ: pool.price - cache (s204-r1). НЕ для momentum.


**Raydium WebSocket:**

    wss://api-v3.raydium.io/ws
    {"type":"subscribe","channel":"pool","ids":[poolId]}

Live mid-price из аккаунтов пула.

**Meteora DLMM:**

    GET https://dlmm-api.meteora.ag/pair/all_with_pagination?limit=100
    GET https://dlmm-api.meteora.ag/pair/{poolAddress}

**Orca Whirlpool:**

    GET https://api.mainnet.orca.so/v1/whirlpool/list
    GET https://api.mainnet.orca.so/v1/whirlpool/{address}

**Jupiter - best route:**

    GET https://quote-api.jup.ag/v6/quote?inputMint={mint}&outputMint=So11111111111111111111111111111111111111112&amount=1000000000&slippageBps=100


**Birdeye - цена + volume + holders:**

    GET https://public-api.birdeye.so/defi/price?address={mint}
    GET https://public-api.birdeye.so/defi/token_overview?address={mint}
    Headers: X-API-KEY: key, x-chain: solana

**Solana RPC WebSocket - live pool account:**

    wss://api.mainnet-beta.solana.com
    {"jsonrpc":"2.0","id":1,"method":"accountSubscribe","params":[poolAddress,{"encoding":"base64","commitment":"confirmed"}]}

**Helius (рекомендуется для prod):**

    wss://mainnet.helius-rpc.com/?api-key=KEY

### 3.3. Приоритеты F3.0

| P | Источник | Зачем |
|---|---|---|
| P0 | Jupiter /quote | Live mid-price |
| P0 | Solana RPC WebSocket | accountSubscribe |
| P1 | Raydium WS | Live mid |
| P1 | Meteora API | Новые DLMM пулы |
| P2 | Birdeye API | Volume, holders |
| P2 | pump.fun API | Детекция graduated |
| P3 | DexScreener | Cross-venue check |

### 3.4. Data pipeline

- Latency budget: менее 500 мс.
- Backpressure: queue, не drop.
- Reconnect: WS + exponential backoff.
- Dedup: pool event - один update.
- Persistence: paper_momentum_ticks.jsonl.


---

## 4. Сигналы momentum

### 4.1. Принципы

- 2-3 сигнала, не больше. Сложность -> переобучение на микро-выборке.
- Каждый сигнал логируется в paper_momentum_signals.jsonl (accept + reject).
- Все проверки - на live WS data, не на REST cache.
- Никаких сигналов без exit-плана (стоп или target).

### 4.2. Сигнал S1: breakout

**Гипотеза:** цена пробивает локальный максимум на объёме -> продолжение вверх.

**Условия входа:**

- current_price > max(price[t-60:t]) (пробой 60-сек high)
- volume_last_10s > 3 * volume_mean_60s (объём x3)
- liquidity_usd >= 20000 (минимум ликвидности)
- holders >= 50 (не rug-кандидат)
- age_seconds >= 60 (не первый блок)

**Exit:**

- target: +30% или первый устойчивый откат (2-3 красных свечи)
- stop: -10% от entry
- timeout: 5 минут


### 4.3. Сигнал S2: volume spike

**Гипотеза:** резкий рост объёма без движения цены -> загрузка перед импульсом.

**Условия входа:**

- volume_last_10s > 5 * volume_mean_60s (объём x5)
- abs(price_change_10s) < 2% (цена ещё не двинулась)
- buy_volume > 2 * sell_volume (перевес покупок)
- liquidity_usd >= 20000
- spread < 100 bps (нормальный bid-ask)

**Exit:**

- target: +20% или при развороте buy/sell ratio
- stop: -8%
- timeout: 3 минуты (если импульс не случился)

### 4.4. Сигнал S3: new-pool momentum

**Гипотеза:** первые 5 минут после graduation на Raydium - максимальная волатильность.

**Условия входа:**

- pool_age < 300 секунд (менее 5 минут)
- liquidity_usd >= 30000 (graduate threshold)
- tx_count_last_60s >= 30 (реальный интерес)
- unique_buyers_last_60s >= 20 (не бот-памп)
- dev_hold_percent < 10% (dev не держит большую долю)

**Exit:**

- target: +50% или trailing stop 15%
- stop: -15%
- timeout: 5 минут

**Особый риск:** rug pull. Проверки выше - только половина дела. См. раздел Risk.


### 4.5. Multi-signal ranking

Если S1+S2+S3 сработали одновременно на разных токенах - нужен ranking. Простая score:

    score = 0.4 * normalized_volume_ratio
          + 0.3 * normalized_liquidity
          + 0.2 * normalized_tx_count
          - 0.1 * spread_bps / 100

Открываем **1 позицию за раз** (не больше) для F3.0. Cap: 10% капитала на позицию.

### 4.6. Лог schema (paper_momentum_signals.jsonl)

    {
      "ts": 1791400000.123,
      "signal": "S1_breakout",
      "mint": "...",
      "pool": "...",
      "venue": "raydium",
      "price_at_signal": 0.000123,
      "liquidity_usd": 45000,
      "volume_ratio": 3.7,
      "holders": 120,
      "pool_age_sec": 240,
      "score": 0.82,
      "action": "open" | "reject",
      "reject_reason": null | "liquidity_too_low" | "holders_too_low" | ...
    }

### 4.7. Лог закрытий (paper_momentum_trades.jsonl)

    {
      "ts_entry": 1791400000.0,
      "ts_exit": 1791400123.4,
      "mint": "...",
      "venue": "raydium",
      "entry_price": 0.000123,
      "exit_price": 0.000158,
      "exit_reason": "target" | "stop" | "timeout",
      "gross_bps": 2845.5,
      "costs_bps": 215.0,
      "realized_bps": 2630.5,
      "cap_before": 100.0,
      "cap_after": 126.3
    }

Поля совместимы с corr_pairs-логгером (realized_bps, costs_bps, reason).


---

## 5. Costs model (F3)

### 5.1. AMM fees (swap fee на пуле)

| Venue | Тип | Fee |
|---|---|---|
| Raydium AMM v4 | CPMM | 25 bps |
| Raydium CLMM | Concentrated | 1-100 bps (динамически) |
| Meteora DLMM | Dynamic | 15-200 bps (по волатильности) |
| Orca Whirlpool | Concentrated | 1-100 bps |
| Jupiter (агрегатор) | Route fee | 0 bps (Jupiter не берет) + AMM fee |

Round-trip (вход+выход) = **2x fee**. Для F3.0 assume:

- Raydium AMM: 25 bps x 2 = 50 bps
- Meteora DLMM: 30 bps x 2 = 60 bps
- Итог: **AMM cost 50-60 bps round-trip**


### 5.2. Solana gas + priority fee

Solana tx fee: **5000 lamports = 0.000005 SOL** (базовая).

Priority fee (для скорости):

- Low congestion: 0 (1000 lamports -> ~$0.0002)
- Normal: 10000 lamports (0.00001 SOL -> ~$0.002)
- High (sniping): 100000+ lamports (0.0001 SOL -> ~$0.02)
- Extreme (MEV war): 1000000+ lamports (0.001 SOL -> $0.2)

При notional $10 и SOL = $200:

- Base tx: 0.000005 SOL = $0.001 = **0.1 bps**
- Normal priority: $0.002 = **0.2 bps**
- Sniping priority: $0.02 = **2 bps**
- Round-trip: 2x (вход+выход) = **0.4-4 bps**

Плюс: если выход через Jupiter - могут быть 2-3 tx (approve + swap), еще +0.2-0.6 bps.

Итог: **gas cost 0.6-5 bps round-trip** (зависит от congestion).


### 5.3. Slippage + MEV

Slippage зависит от:

- Размер позиции vs ликвидность пула
- Волатильность
- MEV-боты в мемпуле

Эмпирика для memecoins на Solana (notional $10-50):

| Ситуация | Slippage |
|---|---|
| Тихий пул, $100k+ ликвидность | 20-50 bps |
| Свежий пул, $30k ликвидность | 50-150 bps |
| Sniping (первые 30 сек) | 100-500 bps |
| MEV sandwich (без защиты) | 100-1000 bps |

**MEV защита:**

- Jito bundles (Solana) - приватный мемпул, отправка через bundle.
- Helius Sender - private RPC.
- Priority fee cap - не давать боту перекупить.

Для F3.0 assume **slippage 100 bps round-trip** (in+out, mid).

### 5.4. Итоговая cost model F3.0

| Компонент | Bps round-trip |
|---|---|
| AMM fees | 50-60 |
| Gas + priority | 0.6-5 |
| Slippage | 50-150 |
| MEV (при защите) | 0-20 |
| **ИТОГО** | **100-235 bps** |

**Сравнение с corr_pairs (baseline):** 12-21 bps. Momentum в **10-20x дороже**, но gross 200-3000 bps - **оправдывает**.

### 5.5. Правило break-even

Любой сигнал должен давать **net_bps > 100** после costs. Иначе reject.

    gross_bps - 200 (worst case costs) > 50 (min edge)
    gross_bps > 250
