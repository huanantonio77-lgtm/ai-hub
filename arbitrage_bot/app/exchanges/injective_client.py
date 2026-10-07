"""Injective DEX client (read-only, phase 1, s199-p2).

Публичный LCD: https://sentry.lcd.injective.network
  GET /injective/exchange/v1beta1/derivative/orderbook/{market_id}

Символы: BTC, ETH, SOL (мапятся в market_id через injective_markets).

Формат ответа: {"buys_price_level":[{"p":"...","q":"..."}], "sells_price_level":[...]}
  p - целое, scale 1e6 (см. injective_markets.PRICE_SCALE).
  q - десятичная строка, уже в базовых единицах.

Инварианты (s156-r0):
  R1 - ноль LLM-API.
  R2 - ноль ML в runtime (stdlib: urllib, json).
  R3 - детерминизм: HTTP-вызов инжектируется через http_call.
  R4 - сеть только к sentry.lcd.injective.network.
  R5 - решения локально.

Phase 1 (s199): только get_orderbook. place_order/cancel_order - no-op.
"""

from __future__ import annotations

import json
import ssl
from typing import Callable, Optional
from urllib.request import Request, urlopen

import certifi

from arbitrage_bot.app.exchanges.base import (
    ExchangeAdapter,
    OrderRequest,
    OrderResult,
)
from arbitrage_bot.app.exchanges.injective_markets import MARKETS, PRICE_SCALE
from arbitrage_bot.app.market_data.orderbook import OrderBook


ALLOWED_HOSTS = frozenset({
    "sentry.lcd.injective.network",
})

_SSL_CTX = ssl.create_default_context(cafile=certifi.where())

HttpCall = Callable[[str, str, dict, Optional[bytes]], tuple]

DEFAULT_BASE_URL = "https://sentry.lcd.injective.network"


def _track(status):
    try:
        import limits as _lim
        _lim.record_call("injective", status)
    except Exception:
        pass


def _default_http_call(method, url, headers, body):
    req = Request(url=url, method=method, data=body)
    for k, v in headers.items():
        req.add_header(k, v)
    with urlopen(req, timeout=10.0, context=_SSL_CTX) as resp:
        status = int(getattr(resp, "status", 200))
        text = resp.read().decode("utf-8")
    return status, text


def _norm(symbol: str) -> str:
    return symbol.upper().split("-")[0].split("/")[0]


class InjectiveClient(ExchangeAdapter):
    name = "injective"

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 10.0,
        http_call: Optional[HttpCall] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        self._http_call = http_call or _default_http_call

    def _headers(self) -> dict:
        return {"Accept": "application/json", "User-Agent": "ai-hub/1.0"}

    def get_orderbook(self, symbol: str) -> OrderBook:
        book = OrderBook(symbol)
        meta = MARKETS.get(_norm(symbol))
        if not meta:
            return book
        url = (self.base_url
               + "/injective/exchange/v1beta1/derivative/orderbook/"
               + meta["market_id"])
        status, body = self._http_call("GET", url, self._headers(), None)
        _track(status)
        if status != 200:
            return book
        try:
            data = json.loads(body)
        except Exception:
            return book
        raw_bids = data.get("buys_price_level") or []
        raw_asks = data.get("sells_price_level") or []
        bids = [(float(b["p"]) / PRICE_SCALE, float(b["q"]))
                for b in raw_bids if "p" in b and "q" in b]
        asks = [(float(a["p"]) / PRICE_SCALE, float(a["q"]))
                for a in raw_asks if "p" in a and "q" in a]
        book.apply_snapshot(bids, asks)
        return book

    def place_order(self, req: OrderRequest) -> OrderResult:
        return OrderResult(accepted=False, reason="read_only_phase1")

    def cancel_order(self, order_id: str) -> bool:
        return False
