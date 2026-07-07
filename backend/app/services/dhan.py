from __future__ import annotations

import copy
import time
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.services.dhan_auth import DhanAuthError, get_dhan_access_token


class DhanClientError(RuntimeError):
    pass


class DhanApiError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


_QUOTE_CACHE: dict[tuple[tuple[str, tuple[int, ...]], ...], tuple[float, dict[str, Any]]] = {}
_QUOTE_BACKOFF_UNTIL: dict[tuple[tuple[str, tuple[int, ...]], ...], float] = {}


class DhanService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def profile(self, *, force_refresh: bool = False) -> dict[str, Any]:
        payload = await self._request("GET", "/profile", require_client_id=False, force_refresh=force_refresh)
        return payload if isinstance(payload, dict) else {"data": payload}

    async def positions(self) -> list[dict[str, Any]]:
        payload = await self._request("GET", "/positions", require_client_id=False)
        rows = payload if isinstance(payload, list) else payload.get("data", [])
        return [row for row in rows if isinstance(row, dict)]

    async def holdings(self) -> list[dict[str, Any]]:
        payload = await self._request("GET", "/holdings", require_client_id=False)
        rows = payload if isinstance(payload, list) else payload.get("data", [])
        return [row for row in rows if isinstance(row, dict)]

    async def trade_book(self) -> list[dict[str, Any]]:
        payload = await self._request("GET", "/trades", require_client_id=False)
        rows = payload if isinstance(payload, list) else payload.get("data", [])
        return [row for row in rows if isinstance(row, dict)]

    async def market_quotes_by_segment(self, securities_by_segment: dict[str, list[int]]) -> dict[str, Any]:
        body = {segment: sorted(set(ids)) for segment, ids in securities_by_segment.items() if ids}
        if not body:
            return {}
        cache_key = _quote_cache_key(body)
        now = time.monotonic()
        cached = _QUOTE_CACHE.get(cache_key)
        backoff_until = _QUOTE_BACKOFF_UNTIL.get(cache_key, 0)
        if cached and now - cached[0] < self.settings.dhan_market_quote_cache_seconds:
            return copy.deepcopy(cached[1])
        if now < backoff_until:
            if cached:
                return copy.deepcopy(cached[1])
            raise DhanApiError("Dhan market quote backoff is active after rate limiting.", 429)

        try:
            payload = await self._request("POST", "/marketfeed/quote", require_client_id=True, json_body=body)
        except DhanApiError as exc:
            if exc.status_code == 429:
                _QUOTE_BACKOFF_UNTIL[cache_key] = now + self.settings.dhan_market_quote_backoff_seconds
            if cached and exc.status_code == 429:
                return copy.deepcopy(cached[1])
            raise
        data = payload.get("data") or {}
        _QUOTE_CACHE[cache_key] = (time.monotonic(), copy.deepcopy(data))
        _QUOTE_BACKOFF_UNTIL.pop(cache_key, None)
        return data

    async def _request(
        self,
        method: str,
        path: str,
        *,
        require_client_id: bool,
        json_body: dict[str, Any] | None = None,
        force_refresh: bool = False,
    ) -> Any:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.request(
                method,
                f"{self.settings.dhan_base_url}{path}",
                headers=await self._headers(require_client_id=require_client_id, force_refresh=force_refresh),
                json=json_body,
            )
            if not force_refresh and self._is_invalid_token_response(response):
                response = await client.request(
                    method,
                    f"{self.settings.dhan_base_url}{path}",
                    headers=await self._headers(require_client_id=require_client_id, force_refresh=True),
                    json=json_body,
                )
        if response.is_error:
            raise self._api_error(response, f"Dhan {method} {path} failed")
        payload = _response_json(response)
        self._raise_status_failure(payload, f"Dhan {method} {path} failed")
        return payload

    async def _headers(self, *, require_client_id: bool, force_refresh: bool = False) -> dict[str, str]:
        try:
            token = await get_dhan_access_token(self.settings, force_refresh=force_refresh)
        except DhanAuthError as exc:
            raise DhanClientError(str(exc)) from exc
        headers = {"Accept": "application/json", "Content-Type": "application/json", "access-token": token}
        if require_client_id:
            client_id = self.settings.resolved_dhan_client_id
            if not client_id:
                raise DhanClientError("Missing DHAN_CLIENT_ID in .env.")
            headers["client-id"] = client_id
        return headers

    def _is_invalid_token_response(self, response: httpx.Response) -> bool:
        if response.status_code == 401:
            return True
        return _looks_like_invalid_token(_response_json(response))

    def _api_error(self, response: httpx.Response, context: str) -> DhanApiError:
        try:
            payload = response.json()
            detail = payload.get("message") or payload.get("remarks") or payload.get("error") or str(payload)
        except ValueError:
            detail = response.text[:220]
        if response.status_code == 401:
            detail = "401 Unauthorized from Dhan. Check DHAN_ACCESS_TOKEN and DHAN_CLIENT_ID."
        return DhanApiError(f"{context}: {detail}", response.status_code)

    def _raise_status_failure(self, payload: Any, context: str) -> None:
        if isinstance(payload, dict) and payload.get("status") == "failed":
            raise DhanApiError(f"{context}: {payload.get('data') or payload.get('message') or payload}", 429)


def _looks_like_invalid_token(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    text = " ".join(
        str(payload.get(key) or "") for key in ("errorMessage", "message", "remarks", "error")
    ).lower()
    return "token" in text or "invalid access" in text


def _response_json(response: httpx.Response) -> Any:
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text}


def _quote_cache_key(body: dict[str, list[int]]) -> tuple[tuple[str, tuple[int, ...]], ...]:
    return tuple((str(segment), tuple(ids)) for segment, ids in sorted(body.items()))
