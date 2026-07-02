from __future__ import annotations

import copy
import time
from typing import Any

from app.core.config import Settings, get_settings
from app.services.dhan import DhanService


_MARKET_CACHE: tuple[float, dict[str, Any]] | None = None


class MarketService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def indices(self) -> dict[str, Any]:
        global _MARKET_CACHE
        now = time.monotonic()
        if _MARKET_CACHE and now - _MARKET_CACHE[0] < self.settings.dhan_market_quote_cache_seconds:
            return copy.deepcopy(_MARKET_CACHE[1])

        try:
            payload = await self._quote()
        except Exception as exc:
            stale_payload = self._stale_payload(str(exc))
            if stale_payload:
                return stale_payload
            raise

        if not _has_index_price(payload):
            stale_payload = self._stale_payload("Market quote response did not include index prices.")
            if stale_payload:
                return stale_payload

        _MARKET_CACHE = (time.monotonic(), copy.deepcopy(payload))
        return payload

    async def _quote(self) -> dict[str, Any]:
        india_vix_security_id = self._india_vix_security_id()
        securities = [self.settings.dhan_nifty_security_id, self.settings.dhan_sensex_security_id]
        if india_vix_security_id:
            securities.append(india_vix_security_id)

        quotes = await DhanService(self.settings).market_quotes_by_segment({"IDX_I": securities})
        data = quotes.get("IDX_I", {})
        payload = {
            "source": "dhan",
            "updatedAt": int(time.time()),
            "indices": [
                self._index("Nifty 50", data.get(str(self.settings.dhan_nifty_security_id), {})),
                self._index("Sensex", data.get(str(self.settings.dhan_sensex_security_id), {})),
                self._index("India VIX", data.get(str(india_vix_security_id), {})),
            ],
        }
        return payload

    def _stale_payload(self, warning: str) -> dict[str, Any] | None:
        if not _MARKET_CACHE:
            return None
        payload = copy.deepcopy(_MARKET_CACHE[1])
        payload["source"] = "stale-cache"
        payload["warning"] = warning
        payload["stale"] = True
        return payload

    def _india_vix_security_id(self) -> int:
        return 21 if self.settings.dhan_india_vix_security_id in {None, 13} else int(self.settings.dhan_india_vix_security_id)

    def _index(self, name: str, quote: dict[str, Any]) -> dict[str, Any]:
        last_price = _number(quote.get("last_price"))
        net_change = _number(quote.get("net_change"))
        close = _number((quote.get("ohlc") or {}).get("close"))
        if net_change is None and last_price is not None and close:
            net_change = last_price - close
        percent_change = (net_change / close * 100) if net_change is not None and close else None
        return {
            "name": name,
            "lastPrice": last_price,
            "change": round(net_change, 2) if net_change is not None else None,
            "percentChange": round(percent_change, 2) if percent_change is not None else None,
        }


def _number(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _has_index_price(payload: dict[str, Any]) -> bool:
    return any(_number(index.get("lastPrice")) is not None for index in payload.get("indices") or [])
