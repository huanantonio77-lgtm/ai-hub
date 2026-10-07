"""GMX DEX client (read-only, phase 1, s195).

GMX V2 = oracle-priced perp DEX on Arbitrum. No CLOB, no AMM.
Oracle tickers: min/max price per token in 10^(30 - decimals) units.

API: https://arbitrum-api.gmxinfra.io/prices/tickers
GET, no auth, requires User-Agent (s194-r3).

Price conversion: usd = raw / 10^(30 - token_decimals)

Synthesize 1-level book from oracle mid:
  mid = (min + max) / 2 (converted)
  bid = mid * (1 - fee/2), ask = mid * (1 + fee/2)

Invariants (s156-r0):
  R1 - no LLM. R2 - no ML. R3 - http_call injectable.
  R4 - only arbitrum-api.gmxinfra.io. R5 - local decisions.
"""

from __future__ import annotations

import json
import ssl
from typing import Callable, Optional
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import certifi

from arbitrage_bot.app.exchanges.base import (
    ExchangeAdapter,
    OrderRequest,
    OrderResult,
)
from arbitrage_bot.app.market_data.orderbook import OrderBook


ALLOWED_HOSTS = frozenset({"arbitrum-api.gmxinfra.io"})
_SSL_CTX = ssl.create_default_context(cafile=certifi.where())
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"

# GMX oracle scale: raw = usd * 10^(30 - token_decimals)
_ORACLE_EXP = 30

_DECIMALS = {
    "BTC": 8, "WBTC": 8,
    "ETH": 18, "WETH": 18,
    "SOL": 9, "WSOL": 9,
    "USDC": 6, "USDT": 6, "DAI": 6,
    "ARB": 18, "LINK": 18, "UNI": 18, "OP": 18,
    "AVAX": 18, "BNB": 18, "MATIC": 18, "ATOM": 6,
    "DOGE": 8, "LTC": 8, "XRP": 6,
}
_FALLBACK_DEC = 18

HttpCall = Callable[[str, str, dict, Optional[bytes]], tuple]


def _track(status):
    try:
        import limits as _lim
        _lim.record_call("gmx", status)
    except Exception:
        pass


def _default_http_call_orig(method, url, headers, body):
    req = Request(url=url, method=method, data=body)
    for k, v in headers.items():
        req.add_header(k, v)
    with urlopen(req, timeout=10.0, context=_SSL_CTX) as resp:
        status = int(getattr(resp, "status", 200))
        text = resp.read().decode("utf-8")
    return status, text


def _default_http_call(method, url, headers, body):
    try:
        result = _default_http_call_orig(method, url, headers, body)
        _track("ok")
        return result
    except Exception:
        _track("error")
        raise


class GmxClient(ExchangeAdapter):
    """Read-only GMX client (oracle -> synthesized 1-level book)."""

    name = "gmx"
    DEFAULT_FEE_BPS = 20

    def __init__(
        self,
        base_url: str = "https://arbitrum-api.gmxinfra.io",
        timeout: float = 10.0,
        http_call: Optional[HttpCall] = None,
        fee_bps: int = DEFAULT_FEE_BPS,
    ) -> None:
        host = urlparse(base_url).netloc
        if host not in ALLOWED_HOSTS:
            raise ValueError(
                "R4 violation: host " + repr(host) + " not in ALLOWED_HOSTS"
            )
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        self.fee_bps = int(fee_bps)
        self._http_call: HttpCall = http_call or _default_http_call

    def _headers(self) -> dict:
        return {"Accept": "application/json", "User-Agent": _UA}

    @staticmethod
    def _scale(token_symbol: str) -> float:
        dec = _DECIMALS.get(token_symbol.upper(), _FALLBACK_DEC)
        return float(10 ** (_ORACLE_EXP - dec))

    def _find_ticker(self, token_symbol: str):
        url = self.base_url + "/prices/tickers"
        status, body = self._http_call("GET", url, self._headers(), None)
        if status != 200:
            return None
        try:
            rows = json.loads(body)
        except Exception:
            return None
        if not isinstance(rows, list):
            return None
        for t in rows:
            sym = (t.get("tokenSymbol") or "").upper()
            if sym == token_symbol.upper():
                return t
        return None

    def get_orderbook(self, symbol: str) -> OrderBook:
        book = OrderBook(symbol)
        if "/" not in symbol:
            return book
        base = symbol.split("/", 1)[0].strip().upper()
        ticker = self._find_ticker(base)
        if not ticker:
            return book
        scale = self._scale(base)
        try:
            lo = float(ticker.get("minPrice") or 0) / scale
            hi = float(ticker.get("maxPrice") or 0) / scale
        except Exception:
            return book
        if lo <= 0 or hi <= 0:
            return book
        mid = (lo + hi) / 2.0
        half = mid * (self.fee_bps / 2.0) / 10000.0
        book.apply_snapshot([(mid - half, 1.0)], [(mid + half, 1.0)])
        return book

    def place_order(self, req: OrderRequest) -> OrderResult:
        return OrderResult(accepted=False, reason="read_only_phase1")

    def cancel_order(self, order_id: str) -> bool:
        return False
