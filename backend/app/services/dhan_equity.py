from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.services.dhan import DhanApiError, DhanClientError
from app.services.dhan_health import describe_401
from app.services.dhan_auth import DhanAuthError, get_dhan_access_token, is_invalid_token_response


TRADE_PAGE_GAP_SECONDS = 0.6  # Dhan's per-user limit trips on back-to-back pages
RATE_LIMIT_BACKOFF_SECONDS = (2.0, 4.0, 8.0)


def _rate_limited(exc: Exception) -> bool:
    text = str(exc)
    return getattr(exc, "status_code", None) == 429 or "DH-904" in text or "Rate_Limit" in text


class DhanEquityService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def holdings(self) -> list[dict[str, Any]]:
        payload = await self._get("/holdings", require_client_id=False)
        rows = payload if isinstance(payload, list) else payload.get("data", [])
        holdings = [self._holding(row) for row in rows if isinstance(row, dict)]
        return [holding for holding in holdings if (holding.get("totalQty") or 0) > 0]

    async def market_quotes(self, holdings: list[dict[str, Any]]) -> dict[str, Any]:
        securities_by_segment: dict[str, list[int]] = {}
        for holding in holdings:
            security_id = _int(holding.get("securityId"))
            if not security_id:
                continue
            segment = str(holding.get("exchangeSegment") or "NSE_EQ")
            securities_by_segment.setdefault(segment, []).append(security_id)
        body = {segment: sorted(set(ids)) for segment, ids in securities_by_segment.items() if ids}
        if not body:
            return {}
        payload = await self._post("/marketfeed/quote", body, require_client_id=True)
        return payload.get("data") or {}

    async def trade_history(self, from_date: str, to_date: str, max_pages: int | None = None) -> list[dict[str, Any]]:
        """All equity trades in the range, page by page. Pages are spaced out
        and a rate-limited page is retried with back-off; if a page still
        fails, the pages already fetched are kept and `last_warning` says so."""
        max_pages = max_pages or self.settings.equity_trade_history_max_pages
        self.last_warning = None
        trades: list[dict[str, Any]] = []
        for page in range(max_pages):
            if page:
                await asyncio.sleep(TRADE_PAGE_GAP_SECONDS)
            try:
                payload = await self._get_with_backoff(f"/trades/{from_date}/{to_date}/{page}")
            except DhanApiError as exc:
                if not trades:
                    raise
                self.last_warning = f"Trade history stopped at page {page} ({exc}); showing the {len(trades)} trades fetched plus saved history."
                break
            rows = payload if isinstance(payload, list) else payload.get("data", [])
            if not rows:
                break
            normalized = [self._transaction(row) for row in rows if isinstance(row, dict)]
            trades.extend([row for row in normalized if row.get("instrument") == "EQUITY"])
        else:
            self.last_warning = f"Trade history hit the {max_pages}-page limit; older trades in the range may be missing."
        return trades

    async def _get_with_backoff(self, path: str) -> Any:
        for wait in RATE_LIMIT_BACKOFF_SECONDS:
            try:
                return await self._get(path, require_client_id=False)
            except DhanApiError as exc:
                if not _rate_limited(exc):
                    raise
                await asyncio.sleep(wait)
        return await self._get(path, require_client_id=False)

    async def historical_daily_data(
        self,
        *,
        security_id: int | str,
        exchange_segment: str = "NSE_EQ",
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> dict[str, Any]:
        today = date.today()
        body = {
            "securityId": str(security_id),
            "exchangeSegment": exchange_segment,
            "instrument": "EQUITY",
            "expiryCode": 0,
            "oi": False,
            "fromDate": from_date or (today - timedelta(days=430)).isoformat(),
            "toDate": to_date or (today + timedelta(days=1)).isoformat(),
        }
        return await self._post("/charts/historical", body, require_client_id=False)

    async def _get(self, path: str, *, require_client_id: bool) -> Any:
        headers = await self._headers(require_client_id=require_client_id)
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f"{self.settings.dhan_base_url}{path}", headers=headers)
            if is_invalid_token_response(response):
                response = await client.get(
                    f"{self.settings.dhan_base_url}{path}",
                    headers=await self._headers(require_client_id=require_client_id, force_refresh=True),
                )
        if response.is_error:
            raise self._api_error(response, f"Dhan GET {path} failed")
        payload = response.json()
        self._raise_status_failure(payload, f"Dhan GET {path} failed")
        return payload

    async def _post(self, path: str, body: dict[str, Any], *, require_client_id: bool) -> dict[str, Any]:
        headers = await self._headers(require_client_id=require_client_id)
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(f"{self.settings.dhan_base_url}{path}", headers=headers, json=body)
            if is_invalid_token_response(response):
                response = await client.post(
                    f"{self.settings.dhan_base_url}{path}",
                    headers=await self._headers(require_client_id=require_client_id, force_refresh=True),
                    json=body,
                )
        if response.is_error:
            raise self._api_error(response, f"Dhan POST {path} failed")
        payload = response.json()
        self._raise_status_failure(payload, f"Dhan POST {path} failed")
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

    def _api_error(self, response: httpx.Response, context: str) -> DhanApiError:
        payload: Any = None
        try:
            payload = response.json()
            detail = payload.get("message") or payload.get("remarks") or payload.get("error") or str(payload)
        except (ValueError, AttributeError):
            detail = response.text[:220]
        if response.status_code == 401:
            detail = describe_401(payload)
        return DhanApiError(f"{context}: {detail}", response.status_code)

    def _raise_status_failure(self, payload: Any, context: str) -> None:
        if isinstance(payload, dict) and payload.get("status") == "failed":
            raise DhanApiError(f"{context}: {payload.get('data') or payload.get('message') or payload}", 429)

    def _holding(self, row: dict[str, Any]) -> dict[str, Any]:
        exchange = str(row.get("exchange") or "NSE").upper()
        exchange_segment = _exchange_segment(exchange)
        total_qty = _number(row.get("totalQty")) or 0
        avg_cost = _number(row.get("avgCostPrice"))
        return {
            "id": str(row.get("isin") or row.get("securityId") or row.get("tradingSymbol") or ""),
            "exchange": row.get("exchange"),
            "exchangeSegment": exchange_segment,
            "tradingSymbol": row.get("tradingSymbol"),
            "symbol": _symbol(row.get("tradingSymbol")),
            "securityId": str(row.get("securityId") or ""),
            "isin": row.get("isin"),
            "totalQty": int(total_qty),
            "dpQty": int(_number(row.get("dpQty")) or 0),
            "t1Qty": int(_number(row.get("t1Qty")) or 0),
            "availableQty": int(_number(row.get("availableQty")) or 0),
            "collateralQty": int(_number(row.get("collateralQty")) or 0),
            "avgCostPrice": avg_cost,
            "investedValue": round(total_qty * avg_cost, 2) if avg_cost is not None else None,
            "raw": row,
        }

    def _transaction(self, row: dict[str, Any]) -> dict[str, Any]:
        quantity = int(_number(row.get("tradedQuantity")) or 0)
        price = _number(row.get("tradedPrice"))
        symbol = row.get("tradingSymbol") or row.get("customSymbol")
        exchange_time = _clean_na(row.get("exchangeTime")) or _clean_na(row.get("updateTime")) or _clean_na(row.get("createTime"))
        charges = sum(
            _number(row.get(key)) or 0
            for key in ("sebiTax", "stt", "brokerageCharges", "serviceTax", "exchangeTransactionCharges", "stampDuty")
        )
        transaction_key = ":".join(
            str(part or "")
            for part in (
                row.get("exchangeTradeId"),
                row.get("orderId"),
                row.get("transactionType"),
                row.get("securityId"),
                exchange_time,
                quantity,
            )
        )
        return {
            "id": transaction_key,
            "orderId": row.get("orderId"),
            "exchangeOrderId": row.get("exchangeOrderId"),
            "exchangeTradeId": row.get("exchangeTradeId"),
            "transactionType": str(row.get("transactionType") or "").upper(),
            "exchangeSegment": row.get("exchangeSegment"),
            "productType": row.get("productType"),
            "orderType": row.get("orderType"),
            "tradingSymbol": row.get("tradingSymbol"),
            "customSymbol": row.get("customSymbol"),
            "symbol": _symbol(symbol),
            "securityId": str(row.get("securityId") or ""),
            "isin": row.get("isin"),
            "instrument": row.get("instrument"),
            "quantity": quantity,
            "price": price,
            "value": round(quantity * price, 2) if price is not None else None,
            "charges": round(charges, 4),
            "createTime": _clean_na(row.get("createTime")),
            "updateTime": _clean_na(row.get("updateTime")),
            "exchangeTime": exchange_time,
            "raw": row,
        }


def normalize_historical_candles(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data: Any = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload
    if not isinstance(data, dict):
        return []
    timestamps = data.get("timestamp") or data.get("timestamps") or data.get("time") or []
    opens = data.get("open") or []
    highs = data.get("high") or []
    lows = data.get("low") or []
    closes = data.get("close") or []
    volumes = data.get("volume") or []
    candles = []
    for index, close_value in enumerate(closes):
        close = _number(close_value)
        if close is None:
            continue
        candles.append(
            {
                "time": timestamps[index] if index < len(timestamps) else None,
                "open": _number(opens[index] if index < len(opens) else close) or close,
                "high": _number(highs[index] if index < len(highs) else close) or close,
                "low": _number(lows[index] if index < len(lows) else close) or close,
                "close": close,
                "volume": _number(volumes[index] if index < len(volumes) else None),
            }
        )
    return candles


def _exchange_segment(exchange: str) -> str:
    if "BSE" in exchange:
        return "BSE_EQ"
    return "NSE_EQ"


def _symbol(value: Any) -> str:
    text = str(value or "").upper().strip()
    return text.replace("-EQ", "").replace(" ", "")


def _clean_na(value: Any) -> str | None:
    text = str(value or "").strip()
    return None if not text or text.upper() == "NA" else text


def _number(value: Any) -> float | None:
    if value in (None, "", "NA", "NaN"):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None
