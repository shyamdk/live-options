from __future__ import annotations

import copy
import time
from datetime import datetime
from typing import Any

from app.core.config import Settings, get_settings
from app.services.delta_exchange import DeltaExchangeService
from app.services.dhan import DhanService
from app.services.dhan_scrip_master import resolve_nearest_mcx_future, resolve_nifty_futures

MCX_SEGMENT = "MCX_COMM"
FNO_SEGMENT = "NSE_FNO"
# (display label, SM_SYMBOL_NAME in Dhan's scrip master). MCX has no
# tradable spot instrument -- nearest-expiry future is the standard proxy.
# Domestic INR futures, not international spot/Brent.
MCX_COMMODITIES = (("Gold (MCX)", "GOLD"), ("Silver (MCX)", "SILVER"), ("Crude Oil (MCX)", "CRUDEOIL"))
NIFTY_FUTURES_COUNT = 2

_MARKET_CACHE: tuple[float, dict[str, Any]] | None = None
_COMMODITY_CACHE: tuple[float, dict[str, Any]] | None = None


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
        securities = [
            self.settings.dhan_nifty_security_id,
            self.settings.dhan_banknifty_security_id,
            self.settings.dhan_sensex_security_id,
        ]
        if india_vix_security_id:
            securities.append(india_vix_security_id)

        quotes = await DhanService(self.settings).market_quotes_by_segment({"IDX_I": securities})
        data = quotes.get("IDX_I", {})
        payload = {
            "source": "dhan",
            "updatedAt": int(time.time()),
            "indices": [
                self._index("Nifty 50", data.get(str(self.settings.dhan_nifty_security_id), {})),
                self._index("Bank Nifty", data.get(str(self.settings.dhan_banknifty_security_id), {})),
                self._index("Sensex", data.get(str(self.settings.dhan_sensex_security_id), {})),
                self._index("India VIX", data.get(str(india_vix_security_id), {})),
                *(await self._crypto_indices()),
            ],
        }
        return payload

    async def commodities(self) -> dict[str, Any]:
        """Gold/Silver/Crude Oil via Dhan's MCX segment (domestic INR
        futures, nearest expiry, no spot instrument exists) plus the
        current/next-month NIFTY index futures. A separate panel/cache from
        indices() since it's materially slower (a scrip-master lookup per
        instrument) and doesn't need the same freshness as NIFTY/SENSEX.
        """
        global _COMMODITY_CACHE
        now = time.monotonic()
        if _COMMODITY_CACHE and now - _COMMODITY_CACHE[0] < self.settings.dhan_market_quote_cache_seconds:
            return copy.deepcopy(_COMMODITY_CACHE[1])

        results = await self._commodity_and_futures_indices()
        payload = {"source": "dhan-mcx", "updatedAt": int(time.time()), "indices": results}
        _COMMODITY_CACHE = (now, copy.deepcopy(payload))
        return payload

    async def _commodity_and_futures_indices(self) -> list[dict[str, Any]]:
        # One batched quote call across both segments (same pattern _quote()
        # uses for NIFTY/BANKNIFTY/SENSEX/VIX) -- separate calls in quick
        # succession is exactly the shape that trips Dhan's own rate
        # limiter (seen for real once already in this codebase's history).
        dhan = DhanService(self.settings)
        mcx_futures: dict[str, dict[str, Any]] = {}
        for label, symbol_name in MCX_COMMODITIES:
            try:
                future = await resolve_nearest_mcx_future(symbol_name)
            except Exception:
                future = None
            if future:
                mcx_futures[label] = future

        try:
            nifty_contracts = await resolve_nifty_futures(NIFTY_FUTURES_COUNT)
        except Exception:
            nifty_contracts = []
        nifty_futures = {_nifty_future_label(contract): contract for contract in nifty_contracts}

        segments: dict[str, list[int]] = {}
        if mcx_futures:
            segments[MCX_SEGMENT] = [f["securityId"] for f in mcx_futures.values()]
        if nifty_futures:
            segments[FNO_SEGMENT] = [f["securityId"] for f in nifty_futures.values()]

        quotes_by_segment: dict[str, Any] = {}
        if segments:
            try:
                quotes_by_segment = await dhan.market_quotes_by_segment(segments)
            except Exception:
                quotes_by_segment = {}

        mcx_quotes = quotes_by_segment.get(MCX_SEGMENT) or {}
        fno_quotes = quotes_by_segment.get(FNO_SEGMENT) or {}

        results: list[dict[str, Any]] = []
        for label, _symbol_name in MCX_COMMODITIES:
            future = mcx_futures.get(label)
            quote = mcx_quotes.get(str(future["securityId"]), {}) if future else {}
            results.append(self._index(label, quote))
        for label, future in nifty_futures.items():
            quote = fno_quotes.get(str(future["securityId"]), {})
            results.append(self._index(label, quote))
        return results

    async def _crypto_indices(self) -> list[dict[str, Any]]:
        # Best-effort -- a Delta Exchange hiccup shouldn't take down the
        # NIFTY/SENSEX strip, which is the primary thing this panel is for.
        delta = DeltaExchangeService(self.settings)
        results = []
        for label, symbol in (("BTC/USD", "BTCUSD"), ("ETH/USD", "ETHUSD")):
            try:
                ticker = await delta.get_ticker(symbol)
                results.append(self._crypto_index(label, ticker))
            except Exception:
                results.append({"name": label, "lastPrice": None, "change": None, "percentChange": None})
        return results

    def _crypto_index(self, name: str, ticker: dict[str, Any]) -> dict[str, Any]:
        last_price = _number(ticker.get("close"))
        open_price = _number(ticker.get("open"))
        change = (last_price - open_price) if last_price is not None and open_price else None
        percent_change = _number(ticker.get("ltp_change_24h"))
        if percent_change is None and change is not None and open_price:
            percent_change = change / open_price * 100
        return {
            "name": name,
            "lastPrice": last_price,
            "change": round(change, 2) if change is not None else None,
            "percentChange": round(percent_change, 2) if percent_change is not None else None,
        }

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


def _nifty_future_label(contract: dict[str, Any]) -> str:
    expiry = str(contract.get("expiry") or "")
    try:
        month = datetime.strptime(expiry[:10], "%Y-%m-%d").strftime("%b")
    except ValueError:
        return "Nifty Fut"
    return f"Nifty Fut ({month})"


def _number(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _has_index_price(payload: dict[str, Any]) -> bool:
    return any(_number(index.get("lastPrice")) is not None for index in payload.get("indices") or [])
