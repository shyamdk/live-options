"""Angel One SmartAPI client -- only what Equity-Swing needs for live orders:
login (client id + PIN + TOTP), CNC market orders, order status, funds and
holdings. Paper trading never calls this.

NSE equity symbol tokens are NSE's own tokens, the same ids Dhan uses as
security ids (RELIANCE = 2885 on both).
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.core.config import Settings, get_settings

BASE = "https://apiconnect.angelone.in"
_session: dict[str, Any] = {"jwt": None, "at": 0.0}


class AngelError(RuntimeError):
    pass


def _totp(secret: str) -> str:
    import pyotp

    return pyotp.TOTP(secret).now()


class AngelBroker:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        missing = [k for k in ("angel_api_key", "angel_client_id", "angel_pin", "angel_totp_secret") if not getattr(self.settings, k)]
        if missing:
            raise AngelError(f"Angel One credentials missing on this server: {', '.join(m.upper() for m in missing)}")

    def _headers(self, jwt: str | None = None) -> dict[str, str]:
        h = {
            "Content-Type": "application/json", "Accept": "application/json", "X-UserType": "USER", "X-SourceID": "WEB",
            "X-ClientLocalIP": "127.0.0.1", "X-ClientPublicIP": "127.0.0.1", "X-MACAddress": "00:00:00:00:00:00",
            "X-PrivateKey": str(self.settings.angel_api_key),
        }
        if jwt:
            h["Authorization"] = f"Bearer {jwt}"
        return h

    async def _jwt(self, client: httpx.AsyncClient) -> str:
        if _session["jwt"] and time.time() - _session["at"] < 6 * 3600:
            return _session["jwt"]
        r = await client.post(f"{BASE}/rest/auth/angelbroking/user/v1/loginByPassword", headers=self._headers(), json={
            "clientcode": self.settings.angel_client_id, "password": self.settings.angel_pin, "totp": _totp(str(self.settings.angel_totp_secret)),
        })
        data = r.json()
        if not data.get("status"):
            raise AngelError(f"Angel login failed: {data.get('message')} ({data.get('errorcode')})")
        _session.update(jwt=data["data"]["jwtToken"], at=time.time())
        return _session["jwt"]

    async def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        async with httpx.AsyncClient(timeout=20) as client:
            jwt = await self._jwt(client)
            r = await client.request(method, f"{BASE}{path}", headers=self._headers(jwt), json=body)
            data = r.json()
            if not data.get("status"):
                if data.get("errorcode") in ("AG8001", "AG8002", "AG8003"):  # token expired / invalid: log in again once
                    _session.update(jwt=None)
                    jwt = await self._jwt(client)
                    data = (await client.request(method, f"{BASE}{path}", headers=self._headers(jwt), json=body)).json()
                if not data.get("status"):
                    raise AngelError(f"Angel {path} failed: {data.get('message')} ({data.get('errorcode')})")
            return data.get("data")

    async def place_market_order(self, *, symbol: str, token: str, side: str, qty: int, tag: str) -> str:
        data = await self._call("POST", "/rest/secure/angelbroking/order/v1/placeOrder", {
            "variety": "NORMAL", "tradingsymbol": f"{symbol}-EQ", "symboltoken": str(token), "transactiontype": side,
            "exchange": "NSE", "ordertype": "MARKET", "producttype": "DELIVERY", "duration": "DAY", "quantity": str(int(qty)),
            "ordertag": tag[:20],
        })
        return str(data["orderid"])

    async def order_fill(self, order_id: str) -> dict[str, Any] | None:
        """{status, avgPrice, filledQty} for an order id, from the order book."""
        for row in await self._call("GET", "/rest/secure/angelbroking/order/v1/getOrderBook") or []:
            if str(row.get("orderid")) == str(order_id):
                return {"status": row.get("orderstatus"), "avgPrice": float(row.get("averageprice") or 0) or None,
                        "filledQty": int(float(row.get("filledshares") or 0)), "text": row.get("text")}
        return None

    async def funds(self) -> dict[str, Any]:
        return await self._call("GET", "/rest/secure/angelbroking/user/v1/getRMS") or {}

    async def holdings(self) -> list[dict[str, Any]]:
        return await self._call("GET", "/rest/secure/angelbroking/portfolio/v1/getHolding") or []
