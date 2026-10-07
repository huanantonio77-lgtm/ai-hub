"""Hyperliquid DEX client (read-only, phase 1, s192).

Публичный API: https://api.hyperliquid.xyz/info (POST, без ключей).
Инварианты (s156-r0):
  R1 - ноль LLM-API.
  R2 - ноль ML в runtime (stdlib: urllib, json).
  R3 - детерминизм: HTTP-вызов инжектируется через http_call.
  R4 - сеть только к api.hyperliquid.xyz (ALLOWED_HOSTS).
  R5 - решения локально.

Phase 1 (s192): только get_orderbook. place_order/cancel_order - no-op.
"""

from __future__ import annotations

import json
import ssl
import certifi
from typing import Callable, Optional
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from arbitrage_bot.app.exchanges.base import (
    ExchangeAdapter,
    OrderRequest,
    OrderResult,
)
from arbitrage_bot.app.market_data.orderbook import OrderBook


ALLOWED_HOSTS = frozenset({
    "api.hyperliquid.xyz",
})

_SSL_CTX = ssl.create_default_context(cafile=certifi.where())

HttpCall = Callable[[str, str, dict, Optional[bytes]], tuple]


def _track(status):
    try:
        import limits as _lim
        _lim.record_call("hyperliquid", status)
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


class HyperliquidClient(ExchangeAdapter):
    """Read-only клиент Hyperliquid DEX. R4: только ALLOWED_HOSTS."""

    name = "hyperliquid"

    def __init__(
        self,
        base_url: str = "https://api.hyperliquid.xyz",
        timeout: float = 10.0,
        http_call: Optional[HttpCall] = None,
    ) -> None:
        host = urlparse(base_url).netloc
        if host not in ALLOWED_HOSTS:
            raise ValueError(
                "R4 violation: host " + repr(host) + " not in ALLOWED_HOSTS"
            )
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        self._http_call: HttpCall = http_call or _default_http_call

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def get_orderbook(self, symbol: str) -> OrderBook:
        url = self.base_url + "/info"
        payload = json.dumps({"type": "l2Book", "coin": symbol}).encode("utf-8")
        status, body = self._http_call("POST", url, self._headers(), payload)
        book = OrderBook(symbol)
        if status != 200:
            return book
        try:
            data = json.loads(body)
        except Exception:
            return book
        levels = data.get("levels") or []
        if len(levels) < 2:
            return book
        raw_bids, raw_asks = levels[0], levels[1]
        bids = [(float(l["px"]), float(l["sz"])) for l in raw_bids]
        asks = [(float(l["px"]), float(l["sz"])) for l in raw_asks]
        book.apply_snapshot(bids, asks)
        return book

    def place_order(self, req: OrderRequest) -> OrderResult:
        return OrderResult(
            accepted=False,
            reason="read_only_phase1",
            order_id="",
            filled_size=0.0,
            avg_price=0.0,
        )

    def cancel_order(self, order_id: str) -> bool:
        return False
