# Architecture — ai-hub

High-level overview of how the agent works. Code-level details live in `security/`, `scripts/`, `arbitrage_bot/`.

## 4 self-axes

| Axis | % | What it does |
|---|---|---|
| Autonomy | 100 | self_daemon runs 24/7, scans 7 DEX, extracts lessons, runs research |
| Self-service | 100 | 27 healers, lessons hygiene, disk janitor, CORE re-sign |
| Self-learning | 100 | 9000+ lessons, autonomous lesson extraction, daily trading research, rolling 30-day stats |
| Self-diagnostics | 100 | blindness audit, sign 14/14, healthcheck 7/7, sysmon, coverage audit |

## R1-R5 rules

- **R1 — no LLM API in runtime.** Ollama local only, no cloud keys.
- **R2 — stdlib only.** No pip deps for runtime code (dev tooling may differ).
- **R3 — read-only trading.** `place_order` is a no-op in phase 1.
- **R4 — network only to public endpoints.** No private accounts, no keys.
- **R5 — CORE must stay signed.** After any CORE patch, `sign_core()` immediately.

## CORE sign

CORE = the small set of files whose integrity is verified at every daemon cycle.
Currently 14 files signed; `verify_core()` returns `{'valid': True, 'checked': 14}`.
If a CORE file is patched by hand and not re-signed → daemon refuses to run.

## Daemon loop

`scripts/research/self_daemon.py` runs forever. Each cycle:

1. **arbitrage_scan --apply --write-stats** (every cycle, ~2 h) — scans all 7 DEX, writes rows to `self/curator/ARBITRAGE_STATS.jsonl`.
2. **trading_research_daily** (once/day, marker `.trading_research_last`) — pulls papers and articles, writes `RESEARCH_TRADING.jsonl`.
3. **arbitrage_stats_daily** (once/day, marker `.stats_last`) — rolls 30-day window, appends to `SELF_TRADING.md`, extracts rules into `ARBITRAGE_RULES.md`.

Marker guards keep each daily task idempotent — restarting the daemon does not double-run.

## Healers

27 healers auto-detect and repair common issues:

- `verify_core` — CORE signature check (14 files).
- `lessons_hygiene` — dedup, format fixes, garbage removal ([ERROR]/[FABRICATION]/[REVIEW]). Whitelists `sN-rM`, dated `YYYY-MM-DD` and `legacy-NNN` ids by design.
- `disk_janitor` — old temp files, log rotation.
- `blindness_audit` — dead sensors, missing counters.
- `sysmon` — CPU/mem sanity.
- `coverage_audit` — feature / check coverage.

If a healer cannot fix it, the issue is written to `self/curator/UNRESOLVED.jsonl`.

## DEX layer

7 exchanges live, read-only, phase 1:

| # | DEX | Kind | Endpoint |
|---|---|---|---|
| 1 | Hyperliquid | CLOB | api.hyperliquid.xyz |
| 2 | dYdX v4 | CLOB | indexer.dydx.trade |
| 3 | Paradex | CLOB | api.prod.paradex.trade |
| 4 | Orca | AMM (Solana) | api.orca.so |
| 5 | Raydium | AMM (Solana) | api-v3.raydium.io |
| 6 | GMX | Perp oracle | arbitrum-api.gmxinfra.io |
| 7 | Injective | CLOB (LCD) | sentry.lcd.injective.network |

## Lesson extraction

Lessons are how the agent remembers. Flow:

    DEX probe -> 404/403/error -> emit_event -> EVENTS.jsonl
       -> session_lesson_extract (daemon + close) -> draft
       -> Curator approves -> lessons.md -> agent remembers

Currently 9292 lessons, indexed (296) and embedded (297). Rebuild order:

Lesson id styles (all preserved by design):
- `sN-rM` — canonical session lessons (160).
- `YYYY-MM-DD` — dated legacy entries (117).
- `legacy-NNN` — pre-session entries (19).

`lesson_index.py --build` first, then `lesson_embed.py --build` (9-15 min).

## Arbitrage pipeline

    self_daemon (every cycle)
       |- arbitrage_scan --apply --write-stats -> ARBITRAGE_STATS.jsonl
       |- trading_research_daily (once/day)    -> RESEARCH_TRADING.jsonl
       |- arbitrage_stats_daily (once/day)     -> SELF_TRADING.md + ARBITRAGE_RULES.md

Rules extracted from real net-PnL data (commissions, slippage, safety buffer).
AMM fees are counted once (already inside synthetic book, s197-r1).

## Product roadmap

- s200 (current) — README, LICENSE, docs/QUICKSTART, ARCHITECTURE, DISCLAIMER.
- s201 — Dockerfile, screenshots.
- s202 — public GitHub + first post (HN / r/LocalLLaMA / r/algotrading).
- s203+ — community feedback -> prioritization -> roadmap v2.

Full roadmap and criteria: [PRODUCT.md](PRODUCT.md).

## Verdict

Reference implementation of a self-improving autonomous agent using:
- pure Python stdlib (no frameworks, no LangChain)
- local Ollama (no cloud keys)
- read-only DEX integration (no financial risk)
- self-healing loop (27 healers, CORE sign, lesson extraction)

Educational. Not production-ready. Not financial advice.
