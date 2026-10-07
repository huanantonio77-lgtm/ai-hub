"""Testnet-драйвер биржевого адаптера (ТЗ §14, stage 6, s163).

Реальный I/O к testnet-эндпоинту биржи. Инварианты (s156-r0):
  R1 — ноль LLM-API в коде.
  R2 — ноль ML в runtime (только stdlib: urllib, json, urllib.parse).
  R3 — детерминизм: HTTP-вызов инжектируется через `http_call`.
       В тестах — фейк, без сети. Один вход -> один выход.
  R4 — сеть только к testnet-хостам бирж (ALLOWED_HOSTS).
  R5 — решения о сделке локально.

Gate: Автономность >= 97% (s162: 97 — открыт).
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
    "testnet.binance.vision",
    "testnet.bybit.com",
    "api-testnet.bybit.com",
})

_SSL_CTX = ssl.create_default_context(cafile=certifi.where())

HttpCall = Callable[[str, str, dict, Optional[bytes]], "tuple[int, str]"]


def _track(status):
    try:
        import sys as _s, os as _os
        root = _os.path.dirname(_os.path.dirname(_os.path.dirname(
            _os.path.dirname(_os.path.abspath(__file__)))))
        if str(root) not in _s.path:
            _s.path.insert(0, str(root))
        import limits as _lim
        _lim.record_call("testnet", status)
    except Exception:
        pass


def _default_http_call(method, url, headers, body):
    try:
        result = _default_http_call_orig(method, url, headers, body)
        _track("ok")
        return result
    except Exception:
        _track("error")
        raise


def _default_http_call_orig(method, url, headers, body):
    """Реальный HTTP через urllib (stdlib). Только testnet-хосты (R4)."""
    req = Request(url=url, method=method, data=body)
    for k, v in headers.items():
        req.add_header(k, v)
    with urlopen(req, timeout=10.0, context=_SSL_CTX) as resp:
        status = int(getattr(resp, "status", 200))
        text = resp.read().decode("utf-8")
    return status, text


class TestnetAdapter(ExchangeAdapter):
    """Реальный testnet-драйвер. R4: только ALLOWED_HOSTS."""

    name = "testnet"

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        api_secret: str = "",
        timeout: float = 10.0,
        http_call: Optional[HttpCall] = None,
    ) -> None:
        host = urlparse(base_url).netloc
        if host not in ALLOWED_HOSTS:
            raise ValueError(
                "R4 violation: host " + repr(host) + " not in ALLOWED_HOSTS"
            )
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret
        self.timeout = float(timeout)
        self._http_call: HttpCall = http_call or _default_http_call

    def _headers(self) -> dict:
        return {
            "Accept": "application/json",
            "X-API-KEY": self.api_key,
        }

    def get_orderbook(self, symbol: str) -> OrderBook:
        url = self.base_url + "/api/v3/depth?symbol=" + symbol + "&limit=5"
        status, body = self._http_call("GET", url, self._headers(), None)
        book = OrderBook(symbol)
        if status != 200:
            return book
        data = json.loads(body)
        bids = [(float(p), float(s)) for p, s in data.get("bids", [])]
        asks = [(float(p), float(s)) for p, s in data.get("asks", [])]
        book.apply_snapshot(bids, asks)
        return book

    def place_order(self, req: OrderRequest) -> OrderResult:
        url = self.base_url + "/api/v3/order"
        payload = json.dumps({
            "symbol": req.symbol,
            "side": req.side.upper(),
            "type": "LIMIT",
            "price": str(req.price),
            "quantity": str(req.size),
            "newClientOrderId": req.client_id or "arb",
        }).encode("utf-8")
        headers = self._headers()
        headers["Content-Type"] = "application/json"
        status, body = self._http_call("POST", url, headers, payload)
        if status not in (200, 201):
            return OrderResult(accepted=False, reason="http_" + str(status))
        data = json.loads(body)
        return OrderResult(
            accepted=True,
            order_id=str(data.get("orderId", "")),
            reason="",
            filled_size=float(data.get("executedQty", 0.0)),
            avg_price=float(data.get("price", req.price)),
        )

    def cancel_order(self, order_id: str) -> bool:
        url = self.base_url + "/api/v3/order?orderId=" + order_id
        status, _ = self._http_call("DELETE", url, self._headers(), None)
        return status == 200
