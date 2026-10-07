"""Orca DEX client (read-only, phase 1, s195).

Orca = AMM (whirlpools on Solana). No CLOB. We synthesize a 1-level
book from the pool price (bid = price - fee/2, ask = price + fee/2).

API: https://api.orca.so/v2/solana/pools?size=N
GET, no auth, requires User-Agent (s194-r3).
Pool: {address, tokenA:{symbol}, tokenB:{symbol}, price, feeRate, tvlUsdc}

Invariants (s156-r0):
  R1 - no LLM. R2 - no ML. R3 - http_call injectable.
  R4 - only api.orca.so. R5 - local decisions.
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


ALLOWED_HOSTS = frozenset({"api.orca.so"})
_SSL_CTX = ssl.create_default_context(cafile=certifi.where())
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"

HttpCall = Callable[[str, str, dict, Optional[bytes]], tuple]


def _track(status):
    try:
        import limits as _lim
        _lim.record_call("orca", status)
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


class OrcaClient(ExchangeAdapter):
    """Read-only Orca client (AMM -> synthesized 1-level book)."""

    name = "orca"
    DEFAULT_FEE_BPS = 30

    def __init__(
        self,
        base_url: str = "https://api.orca.so",
        timeout: float = 10.0,
        http_call: Optional[HttpCall] = None,
        pool_size: int = 200,
        fee_bps: int = DEFAULT_FEE_BPS,
    ) -> None:
        host = urlparse(base_url).netloc
        if host not in ALLOWED_HOSTS:
            raise ValueError(
                "R4 violation: host " + repr(host) + " not in ALLOWED_HOSTS"
            )
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        self.pool_size = int(pool_size)
        self.fee_bps = int(fee_bps)
        self._http_call: HttpCall = http_call or _default_http_call

    def _headers(self) -> dict:
        return {"Accept": "application/json", "User-Agent": _UA}

    def _find_pool(self, symbol: str):
        if "/" not in symbol:
            return None
        base, quote = [s.strip().upper() for s in symbol.split("/", 1)]
        url = self.base_url + "/v2/solana/pools?size=" + str(self.pool_size)
        status, body = self._http_call("GET", url, self._headers(), None)
        if status != 200:
            return None
        try:
            data = json.loads(body)
        except Exception:
            return None
        best = None
        best_tvl = -1.0
        for p in data.get("data", []):
            a = ((p.get("tokenA") or {}).get("symbol") or "").upper()
            b = ((p.get("tokenB") or {}).get("symbol") or "").upper()
            if a == base and b == quote:
                try:
                    tvl = float(p.get("tvlUsdc") or 0)
                except Exception:
                    tvl = 0.0
                if tvl > best_tvl:
                    best = p
                    best_tvl = tvl
        return best

    def get_orderbook(self, symbol: str) -> OrderBook:
        book = OrderBook(symbol)
        pool = self._find_pool(symbol)
        if not pool:
            return book
        try:
            price = float(pool.get("price") or 0)
        except Exception:
            return book
        if price <= 0:
            return book
        half = price * (self.fee_bps / 2.0) / 10000.0
        bid = price - half
        ask = price + half
        book.apply_snapshot([(bid, 1.0)], [(ask, 1.0)])
        return book

    def place_order(self, req: OrderRequest) -> OrderResult:
        return OrderResult(accepted=False, reason="read_only_phase1")

    def cancel_order(self, order_id: str) -> bool:
        return False
