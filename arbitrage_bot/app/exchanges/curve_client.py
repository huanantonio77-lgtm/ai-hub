"""Curve DEX client (AMM, read-only, phase 1, s201-p3).

Публичный REST: https://api.curve.finance/v1/getPools/ethereum/main
Один HTTP-вызов -> все pools -> synthetic orderbook per pair.

Символы (пары): DAI/USDC, USDC/USDT, DAI/USDT, ETH/stETH.
  Индексы i/j из curve_markets.MARKETS (позиция в pool's `coins`).

Synthetic book (s195-r0):
  bid = ask = spot_price = bal_quote_human / bal_base_human.
  AMM fee = 0 (s197-r1: уже внутри synthetic book).

Инварианты (s156-r0):
  R1 - ноль LLM-API.
  R2 - ноль ML в runtime (stdlib: urllib, json).
  R3 - детерминизм: HTTP-вызов инжектируется через http_call.
  R4 - сеть только к api.curve.finance / api.curve.fi.
  R5 - решения локально.

Phase 1 (s201): только get_orderbook. place_order/cancel_order - no-op.
"""

from __future__ import annotations

import json
import ssl
from typing import Callable, Optional

try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = ssl.create_default_context()

from urllib.request import Request, urlopen

from .base import ExchangeAdapter, OrderBook, OrderRequest, OrderResult
from .curve_markets import ALLOWED_HOSTS, API_URL, MARKETS


HttpCall = Callable[[str, str, dict, Optional[bytes]], tuple]


def _host_ok(url: str) -> bool:
    from urllib.parse import urlparse
    return urlparse(url).hostname in ALLOWED_HOSTS


def _default_http_call(method, url, headers, body):
    if not _host_ok(url):
        return 403, '{"error":"r4_whitelist"}'
    req = Request(url, data=body, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urlopen(req, timeout=10.0, context=_SSL_CTX) as resp:
        status = int(getattr(resp, "status", 200))
        text = resp.read().decode("utf-8")
    return status, text


def _norm(symbol: str) -> str:
    return symbol.upper().replace("-", "/")


def _stable_get_D(x, A):
    n = len(x)
    S = sum(x)
    if S <= 0:
        return 0.0
    D = S
    Ann = A * n
    for _ in range(255):
        D_P = D
        for _x in x:
            D_P = D_P * D / (_x * n)
        D_prev = D
        D = (Ann * S + D_P * n) * D / ((Ann - 1) * D + (n + 1) * D_P)
        if abs(D - D_prev) <= max(1e-9, D * 1e-12):
            return D
    return D


def _stable_get_y(i, j, x, D, A):
    n = len(x)
    Ann = A * n
    c = D
    S_ = 0.0
    for k in range(n):
        if k == i:
            _x = x[i]
        elif k == j:
            continue
        else:
            _x = x[k]
        S_ += _x
        c = c * D / (_x * n)
    c = c * D / (Ann * n)
    b = S_ + D / Ann
    y = D
    for _ in range(255):
        y_prev = y
        y = (y * y + c) / (2 * y + b - D)
        if abs(y - y_prev) <= max(1e-9, y * 1e-12):
            return y
    return y


def _stable_spot(x, i, j, A):
    """Marginal price of coin i in units of coin j (StableSwap)."""
    D = _stable_get_D(x, A)
    if D <= 0 or x[i] <= 0 or x[j] <= 0:
        return 0.0
    dx = x[i] * 1e-6
    x_new = list(x)
    x_new[i] = x[i] + dx
    y_new = _stable_get_y(i, j, x_new, D, A)
    dy = x[j] - y_new
    return dy / dx if dx > 0 else 0.0


class CurveClient(ExchangeAdapter):
    name = "curve"

    def __init__(
        self,
        base_url: str = API_URL,
        timeout: float = 10.0,
        http_call: Optional[HttpCall] = None,
    ):
        self.base_url = base_url
        self.timeout = float(timeout)
        self._http_call = http_call or _default_http_call

    def _headers(self) -> dict:
        return {"Accept": "application/json", "User-Agent": "ai-hub/1.0"}

    def _fetch_pools(self) -> dict:
        """One HTTP -> dict[addr_lower, pool]. Пусто при ошибке."""
        status, body = self._http_call("GET", self.base_url, self._headers(), None)
        if status != 200:
            return {}
        try:
            data = json.loads(body)
        except Exception:
            return {}
        pools = (data.get("data") or {}).get("poolData") or []
        return {str(p.get("address", "")).lower(): p for p in pools}

    def get_orderbook(self, symbol: str) -> OrderBook:
        book = OrderBook(symbol)
        meta = MARKETS.get(_norm(symbol))
        if not meta:
            return book
        pools = self._fetch_pools()
        pool = pools.get(meta["pool"].lower())
        if not pool:
            return book
        coins = pool.get("coins") or []
        i, j = meta["i"], meta["j"]
        try:
            x_human = []
            for c in coins:
                raw = int(c.get("poolBalance") or 0)
                dec = int(c.get("decimals") or 0)
                x_human.append(raw / (10 ** dec))
        except Exception:
            return book
        if i >= len(x_human) or j >= len(x_human):
            return book
        if x_human[i] <= 0 or x_human[j] <= 0:
            return book
        A = float(pool.get("amplificationCoefficient") or 0) or 100.0
        spot = _stable_spot(x_human, i, j, A)
        if spot <= 0:
            return book
        # AMM synthetic book (StableSwap, s201).
        # Deterministic micro-tick keeps OrderBook invariant bb < ba.
        tick = max(spot, 1.0) * 1e-6
        bid = spot - tick
        ask = spot + tick
        qty = x_human[i]
        book.apply_snapshot(bids=[(bid, qty)], asks=[(ask, qty)])
        return book

    def place_order(self, req: OrderRequest) -> OrderResult:
        return OrderResult(accepted=False, reason="read_only_phase1")

    def cancel_order(self, order_id: str) -> bool:
        return False
