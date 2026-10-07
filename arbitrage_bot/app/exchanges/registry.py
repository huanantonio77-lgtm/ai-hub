"""Exchange registry (s193).

Единый список подключённых бирж. healthcheck читает отсюда.
Добавление новой биржи = одна запись здесь + клиент в app/exchanges/.

Поля:
  name     - короткое имя (используется в limits.record_call)
  class    - "module:ClassName" (importable)
  endpoint - базовый URL (публичный)
  symbols  - список символов для probe
  added    - сессия, в которой биржа подключена
  phase    - фаза интеграции (1=read-only, 2=adapter, 3=signing, 4=live)
  kind     - dex | cex
"""
from __future__ import annotations

REGISTRY = [
    {
        "name": "hyperliquid",
        "class": "arbitrage_bot.app.exchanges.hyperliquid_client:HyperliquidClient",
        "endpoint": "https://api.hyperliquid.xyz",
        "symbols": ["BTC", "ETH", "SOL"],
        "added": "s192",
        "phase": 1,
        "kind": "dex",
    },
    {
        "name": "dydx",
        "class": "arbitrage_bot.app.exchanges.dydx_client:DydxClient",
        "endpoint": "https://indexer.dydx.trade",
        "symbols": ["BTC-USD", "ETH-USD", "SOL-USD"],
        "added": "s193",
        "phase": 1,
        "kind": "dex",
    },
    {
        "name": "paradex",
        "class": "arbitrage_bot.app.exchanges.paradex_client:ParadexClient",
        "endpoint": "https://api.prod.paradex.trade",
        "symbols": ["BTC-USD-PERP", "ETH-USD-PERP", "SOL-USD-PERP"],
        "added": "s194",
        "phase": 1,
        "kind": "dex",
    },
    {
        "name": "orca",
        "class": "arbitrage_bot.app.exchanges.orca_client:OrcaClient",
        "endpoint": "https://api.orca.so",
        "symbols": ["SOL/USDC"],
        "added": "s195",
        "phase": 1,
        "kind": "dex",
    },
    {
        "name": "raydium",
        "class": "arbitrage_bot.app.exchanges.raydium_client:RaydiumClient",
        "endpoint": "https://api-v3.raydium.io",
        "symbols": ["SOL/USDC"],
        "added": "s195",
        "phase": 1,
        "kind": "dex",
    },
    {
        "name": "gmx",
        "class": "arbitrage_bot.app.exchanges.gmx_client:GmxClient",
        "endpoint": "https://arbitrum-api.gmxinfra.io",
        "symbols": ["SOL/USD"],
        "added": "s195",
        "phase": 1,
        "kind": "dex",
    },
    {
        "name": "injective",
        "class": "arbitrage_bot.app.exchanges.injective_client:InjectiveClient",
        "markets": "arbitrage_bot.app.exchanges.injective_markets:MARKETS",
        "endpoint": "https://sentry.lcd.injective.network",
        "symbols": ["BTC", "ETH", "SOL"],
        "added": "s199",
        "phase": 1,
        "kind": "dex",
    },
    {
        "name": "curve",
        "class": "arbitrage_bot.app.exchanges.curve_client:CurveClient",
        "markets": "arbitrage_bot.app.exchanges.curve_markets:MARKETS",
        "endpoint": "https://api.curve.finance/v1/getPools/ethereum/main",
        "symbols": ["DAI/USDC", "USDC/USDT", "DAI/USDT", "ETH/STETH"],
        "added": "s201",
        "phase": 1,
        "kind": "dex",
    },
]


def all_exchanges():
    return list(REGISTRY)
