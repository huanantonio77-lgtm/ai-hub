"""Injective derivative market IDs (s199-p2).

Источник: https://sentry.lcd.injective.network/injective/exchange/v1beta1/derivative/markets
Все три рынка: Active, USDC quote, on-chain taker/maker = 0.000001.
"""

MARKETS = {
    "BTC": {
        "market_id": "0x0ee7ca44147bab6ec81ac293b5fe7915488e612af59964b2d663d6008d861dee",
        "ticker": "BTC/USDC PERP",
    },
    "ETH": {
        "market_id": "0xe9c90a90ec75194ba9693f12b58a88a06937599e00c2adbc565a7b1a6ffbe4ed",
        "ticker": "ETH/USDC PERP",
    },
    "SOL": {
        "market_id": "0x291f404810c663e5fdd68b50454c1014760227842d420a2315f88311efe6ec41",
        "ticker": "SOL/USDC PERP",
    },
}

# Orderbook price - целое, scale = 10^6 (USDC quote_decimals=6).
# Пример: p="83802000000" -> 83802.00 USDC.
PRICE_SCALE = 10 ** 6
