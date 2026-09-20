"""Delta Exchange India REST client -- key+secret HMAC-signed requests, no
browser session or 2FA involved (2FA only gates their web UI login, which
this never automates; API access is fully stateless per-request signing).

Run directly for a connectivity check:

    cd backend && ../.venv/bin/python -m app.services.delta_exchange

Auth scheme (per docs.delta.exchange): sign method + timestamp + path +
query string + body with HMAC-SHA256(api_secret), hex-encoded, sent as the
`signature` header alongside `api-key` and `timestamp`. Timestamps more
than 5 seconds old are rejected, so this signs fresh on every call rather
than caching anything.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import httpx

from app.core.config import Settings, get_settings


class DeltaExchangeError(Exception):
    pass


class DeltaExchangeService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def _sign(self, method: str, path: str, query: str, body: str, timestamp: str) -> str:
        secret = self._settings.delta_exchange_api_secret or ""
        prehash = f"{method}{timestamp}{path}{query}{body}"
        return hmac.new(secret.encode(), prehash.encode(), hashlib.sha256).hexdigest()

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        api_key = self._settings.delta_exchange_api_key
        api_secret = self._settings.delta_exchange_api_secret
        if not api_key or not api_secret:
            raise DeltaExchangeError("DELTA_EXCHANGE_API_KEY / DELTA_EXCHANGE_API_SECRET not configured")

        query = ""
        if params:
            query = "?" + "&".join(f"{k}={v}" for k, v in params.items())
        # Compact, deterministic serialization -- the signature covers the
        # exact bytes sent, so this same string is what's transmitted below
        # rather than letting httpx re-serialize (which could reorder/
        # respace and invalidate the signature).
        body_str = json.dumps(json_body, separators=(",", ":")) if json_body is not None else ""
        timestamp = str(int(time.time()))
        signature = self._sign(method, path, query, body_str, timestamp)

        headers = {
            "api-key": api_key,
            "signature": signature,
            "timestamp": timestamp,
            "User-Agent": "live-options-delta-check/1.0",
            "Content-Type": "application/json",
        }
        url = f"{self._settings.delta_exchange_base_url}{path}{query}"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.request(method, url, headers=headers, content=body_str.encode() if body_str else None)
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text}
        if response.status_code >= 400 or (isinstance(payload, dict) and payload.get("success") is False):
            raise DeltaExchangeError(f"Delta Exchange API error ({response.status_code}): {payload}")
        return payload.get("result") if isinstance(payload, dict) else payload

    async def get_wallet_balances(self) -> list[dict[str, Any]]:
        result = await self._request("GET", "/v2/wallet/balances")
        return result if isinstance(result, list) else []

    async def get_candles(self, symbol: str, resolution: str, start: int, end: int) -> list[dict[str, Any]]:
        """Public OHLCV history (no signing needed). `resolution` is Delta's
        own string format ("30m", "1h", "1d", ...); start/end are unix
        seconds. Returns newest-first per Delta's API -- callers that need
        chronological order should reverse it.
        """
        params = {"resolution": resolution, "symbol": symbol, "start": start, "end": end}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f"{self._settings.delta_exchange_base_url}/v2/history/candles", params=params)
        payload = response.json()
        if response.status_code >= 400 or not payload.get("success"):
            raise DeltaExchangeError(f"Delta Exchange candles error ({response.status_code}): {payload}")
        return payload.get("result") or []

    async def get_ticker(self, symbol: str) -> dict[str, Any]:
        """Public market data (no signing needed) -- symbol is a Delta
        perpetual-futures product like "BTCUSD" / "ETHUSD".
        """
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f"{self._settings.delta_exchange_base_url}/v2/tickers/{symbol}")
        payload = response.json()
        if response.status_code >= 400 or not payload.get("success"):
            raise DeltaExchangeError(f"Delta Exchange ticker error ({response.status_code}): {payload}")
        return payload.get("result") or {}

    # -- Trading (real capital -- everything below actually moves money
    # once called with live_enabled + shadow_mode off; see
    # crypto_swing_live.py, which is the only caller). --

    async def get_product(self, symbol: str) -> dict[str, Any]:
        """Contract spec (product_id, contract_value, tick_size) needed to
        convert a desired notional into an integer number of contracts.
        """
        result = await self._request("GET", f"/v2/products/{symbol}")
        return result if isinstance(result, dict) else {}

    async def get_positions(self, product_id: int | None = None) -> list[dict[str, Any]]:
        params = {"product_id": product_id} if product_id is not None else None
        result = await self._request("GET", "/v2/positions", params=params)
        if isinstance(result, list):
            return result
        return [result] if isinstance(result, dict) else []

    async def set_leverage(self, product_id: int, leverage: str) -> dict[str, Any]:
        result = await self._request("POST", f"/v2/products/{product_id}/orders/leverage", json_body={"leverage": leverage})
        return result if isinstance(result, dict) else {}

    async def place_order(
        self,
        product_id: int,
        size: int,
        side: str,
        order_type: str = "market_order",
        limit_price: str | None = None,
        time_in_force: str = "gtc",
        reduce_only: bool = False,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        """Places a REAL order -- size is in contracts (Delta's own unit,
        via product.contract_value), not underlying quantity or USD. Only
        ever called from crypto_swing_live.py, and only when both
        crypto_swing_live_enabled and NOT crypto_swing_shadow_mode.
        """
        body: dict[str, Any] = {
            "product_id": product_id,
            "size": size,
            "side": side,
            "order_type": order_type,
            "time_in_force": time_in_force,
            "reduce_only": reduce_only,
        }
        if limit_price is not None:
            body["limit_price"] = limit_price
        if client_order_id is not None:
            body["client_order_id"] = client_order_id
        result = await self._request("POST", "/v2/orders", json_body=body)
        return result if isinstance(result, dict) else {}


async def _check_connection() -> None:
    service = DeltaExchangeService()
    try:
        balances = await service.get_wallet_balances()
    except DeltaExchangeError as exc:
        print(f"FAILED to connect to Delta Exchange: {exc}")
        return

    print(f"Connected to Delta Exchange. {len(balances)} wallet balance row(s):")
    for row in balances:
        asset = row.get("asset_symbol") or row.get("asset", {}).get("symbol") or "?"
        balance = row.get("balance")
        available = row.get("available_balance")
        print(f"  {asset}: balance={balance} available={available}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(_check_connection())
