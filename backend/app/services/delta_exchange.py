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

    async def _request(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        api_key = self._settings.delta_exchange_api_key
        api_secret = self._settings.delta_exchange_api_secret
        if not api_key or not api_secret:
            raise DeltaExchangeError("DELTA_EXCHANGE_API_KEY / DELTA_EXCHANGE_API_SECRET not configured")

        query = ""
        if params:
            query = "?" + "&".join(f"{k}={v}" for k, v in params.items())
        timestamp = str(int(time.time()))
        signature = self._sign(method, path, query, "", timestamp)

        headers = {
            "api-key": api_key,
            "signature": signature,
            "timestamp": timestamp,
            "User-Agent": "live-options-delta-check/1.0",
            "Content-Type": "application/json",
        }
        url = f"{self._settings.delta_exchange_base_url}{path}{query}"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.request(method, url, headers=headers)
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
