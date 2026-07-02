from __future__ import annotations

import re
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.services.dhan_auth import get_dhan_access_token


class DhanOrderService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def place_market_order(
        self,
        *,
        transaction_type: str,
        exchange_segment: str,
        security_id: str | int,
        quantity: int,
        correlation_id: str,
        product_type: str | None = None,
    ) -> dict[str, Any]:
        request = self.build_market_order_request(
            transaction_type=transaction_type,
            exchange_segment=exchange_segment,
            security_id=security_id,
            quantity=quantity,
            correlation_id=correlation_id,
            product_type=product_type,
        )
        if not self.settings.live_order_enabled:
            return {
                "status": "blocked",
                "message": "LIVE_ORDER_ENABLED is false. Order payload was not sent to Dhan.",
                "request": request,
                "order": None,
            }

        body = request
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.post(
                f"{self.settings.dhan_base_url}/orders",
                headers=await self._headers(),
                json=body,
            )
            if response.status_code == 401:
                response = await client.post(
                    f"{self.settings.dhan_base_url}/orders",
                    headers=await self._headers(force_refresh=True),
                    json=body,
                )
        if response.is_error:
            return {"status": "failed", "message": f"Dhan order request failed: {response.text[:220]}", "request": body}
        return {"status": "sent", "request": body, "order": _response_json(response)}

    def build_market_order_request(
        self,
        *,
        transaction_type: str,
        exchange_segment: str,
        security_id: str | int,
        quantity: int,
        correlation_id: str,
        product_type: str | None = None,
    ) -> dict[str, Any]:
        return self._body(
            transaction_type=transaction_type,
            exchange_segment=exchange_segment,
            security_id=security_id,
            quantity=quantity,
            correlation_id=correlation_id,
            product_type=product_type,
        )

    async def _headers(self, *, force_refresh: bool = False) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "access-token": await get_dhan_access_token(self.settings, force_refresh=force_refresh),
        }
        if self.settings.resolved_dhan_client_id:
            headers["client-id"] = self.settings.resolved_dhan_client_id
        return headers

    def _body(
        self,
        *,
        transaction_type: str,
        exchange_segment: str,
        security_id: str | int,
        quantity: int,
        correlation_id: str,
        product_type: str | None,
    ) -> dict[str, Any]:
        client_id = self.settings.resolved_dhan_client_id
        if not client_id:
            raise RuntimeError("DHAN_CLIENT_ID is required for live order placement.")
        correlation = re.sub(r"[^A-Za-z0-9 -]", "-", correlation_id)[:30]
        return {
            "dhanClientId": str(client_id),
            "correlationId": correlation,
            "transactionType": transaction_type.upper(),
            "exchangeSegment": exchange_segment,
            "productType": product_type or self.settings.live_order_product_type,
            "orderType": self.settings.live_order_type,
            "validity": self.settings.live_order_validity,
            "securityId": str(security_id),
            "quantity": int(quantity),
            "disclosedQuantity": 0,
            "price": 0,
            "triggerPrice": 0,
            "afterMarketOrder": False,
        }


def _response_json(response: httpx.Response) -> Any:
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text}
