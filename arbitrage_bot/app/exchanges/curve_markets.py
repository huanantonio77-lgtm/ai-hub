"""Curve pools (s201-p3, Ethereum main, read-only phase 1).

Источник: https://api.curve.finance/v1/getPools/ethereum/main
  3pool (DAI/USDC/USDT) — $160M TVL.
  stETH (ETH/stETH)     — $100M TVL.

Формат ответа API: {"success": true, "data": {"poolData": [...]}}
  coin.poolBalance — целое (raw units), coin.decimals — строка.

AMM synthetic book (s195-r0):
  price(in→out) = bal_out_human / bal_in_human.
  fee = 0 (s197-r1: уже внутри synthetic book).
"""

API_URL = "https://api.curve.finance/v1/getPools/ethereum/main"
ALLOWED_HOSTS = {"api.curve.finance", "api.curve.fi"}

# Pool addresses (main Ethereum)
POOL_3POOL = "0xbEbc44782C7dB0a1A60Cb6fe97d0b483032FF1C7"
POOL_STETH = "0xDC24316b9AE028F1497c275EB9192a3Ea0f67022"

# Pair -> pool + coin indices.
# Coin index i = base, j = quote inside pool's `coins` array.
# Expected coin symbols (for runtime validation).
MARKETS = {
    "DAI/USDC": {
        "pool": POOL_3POOL, "i": 0, "j": 1,
        "base": "DAI",  "quote": "USDC",
        "pool_tokens": ["DAI", "USDC", "USDT"],
    },
    "USDC/USDT": {
        "pool": POOL_3POOL, "i": 1, "j": 2,
        "base": "USDC", "quote": "USDT",
        "pool_tokens": ["DAI", "USDC", "USDT"],
    },
    "DAI/USDT": {
        "pool": POOL_3POOL, "i": 0, "j": 2,
        "base": "DAI",  "quote": "USDT",
        "pool_tokens": ["DAI", "USDC", "USDT"],
    },
    "ETH/STETH": {
        "pool": POOL_STETH, "i": 0, "j": 1,
        "base": "ETH",  "quote": "stETH",
        "pool_tokens": ["ETH", "stETH"],
    },
}
