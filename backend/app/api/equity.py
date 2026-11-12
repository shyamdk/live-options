from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.config import get_settings
from app.db.sqlite import (
    delete_equity_cache,
    get_equity_cache,
    list_equity_cache_by_category,
    list_equity_options_transactions,
    list_equity_transactions_cache,
    upsert_equity_cache,
    upsert_equity_transactions,
)
from app.services.app_auth import require_auth
from app.services.dhan_equity import DhanEquityService, normalize_historical_candles
from app.services.equity_entry import build_entry_signal, last_buys, rsi14, summarize as summarize_entries
from app.services.equity_recommendations import build_recommendation
from app.services.openai_news import OpenAINewsService
from app.services.screener import ScreenerService

router = APIRouter(prefix="/equity", tags=["equity"])

LOWEST_PRICE_OVERRIDE_CATEGORY = "lowest_price_override"
TRANSACTION_OVERLAP_DAYS = 2
TRANSACTION_SYNC_CATEGORY = "transactions_sync"
DHAN_TRADE_HISTORY_DAYS = 100  # Dhan serves only ~3 months; older trades come from the CSV import


class EquityRefreshIn(BaseModel):
    scope: Literal["portfolio", "transactions", "news", "all"] = "all"
    fromDate: str | None = None
    toDate: str | None = None


class LowestPriceOverrideIn(BaseModel):
    price: float | None = None


@router.get("/lowest-price-overrides", dependencies=[Depends(require_auth)])
async def list_lowest_price_overrides() -> dict[str, float]:
    """Manual lowest-buy-price entries, keyed by security id -- for holdings
    Dhan's trade-history API can't cover (confirmed it doesn't serve trade
    records older than roughly the last 2-3 months, regardless of the date
    range requested; not documented, found by testing)."""
    entries = list_equity_cache_by_category(LOWEST_PRICE_OVERRIDE_CATEGORY)
    return {security_id: entry["payload"]["price"] for security_id, entry in entries.items()}


@router.put("/lowest-price-overrides/{security_id}", dependencies=[Depends(require_auth)])
async def set_lowest_price_override(security_id: str, body: LowestPriceOverrideIn) -> dict[str, Any]:
    if body.price is None:
        delete_equity_cache(LOWEST_PRICE_OVERRIDE_CATEGORY, security_id)
        return {"securityId": security_id, "price": None}
    upsert_equity_cache(LOWEST_PRICE_OVERRIDE_CATEGORY, security_id, {"price": body.price})
    return {"securityId": security_id, "price": body.price}


@router.get("/portfolio", dependencies=[Depends(require_auth)])
async def equity_portfolio(refresh: bool = False) -> dict[str, Any]:
    return await _portfolio(refresh=refresh)


@router.get("/transactions", dependencies=[Depends(require_auth)])
async def equity_transactions(fromDate: str | None = None, toDate: str | None = None, refresh: bool = False, full: bool = False) -> dict[str, Any]:
    return await _transactions(from_date=fromDate, to_date=toDate, refresh=refresh, full=full)


@router.get("/news", dependencies=[Depends(require_auth)])
async def equity_news(refresh: bool = False) -> dict[str, Any]:
    settings = get_settings()
    warning = None
    try:
        holdings = await DhanEquityService(settings).holdings()
        upsert_equity_cache("holdings", "portfolio", {"data": holdings})
    except Exception as exc:
        cached_holdings = get_equity_cache("holdings", "portfolio")
        holdings = (cached_holdings or {}).get("data") or []
        warning = f"Holdings: showing cached data ({exc})" if holdings else f"Holdings: {exc}"

    if refresh:
        limiter = asyncio.Semaphore(3)

        async def fetch_live_news(holding: dict[str, Any]) -> dict[str, Any]:
            async with limiter:
                return await _news_for_holding(holding, refresh=True)

        rows = list(await asyncio.gather(*(fetch_live_news(holding) for holding in holdings)))
    else:
        rows = [await _news_for_holding(holding, refresh=False) for holding in holdings]
    return {
        "source": "openai_web_search",
        "warning": warning,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "count": len(rows),
        "data": rows,
    }


@router.get("/options-report", dependencies=[Depends(require_auth)])
async def equity_options_report() -> dict[str, Any]:
    """Month/financial-year-wise options P&L, built from leg-days backfilled
    by scripts/import_dhan_csv.py -- Dhan's live API has no per-leg options
    trade-history endpoint, so this data only exists via the CSV import."""
    rows = list_equity_options_transactions()
    return _options_report(rows)


def _financial_year_label(trade_date: str) -> str:
    year, month = int(trade_date[:4]), int(trade_date[5:7])
    start_year = year if month >= 4 else year - 1
    return f"FY{start_year}-{str(start_year + 1)[-2:]}"


def _options_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def _empty_bucket() -> dict[str, Any]:
        return {"trades": 0, "buyValue": 0.0, "sellValue": 0.0, "charges": 0.0, "grossPnl": 0.0}

    def _add(bucket: dict[str, Any], row: dict[str, Any]) -> None:
        bucket["trades"] += 1
        bucket["buyValue"] += row.get("buy_value") or 0
        bucket["sellValue"] += row.get("sell_value") or 0
        bucket["charges"] += sum(
            row.get(key) or 0
            for key in ("brokerage", "gst", "stt", "sebi_fees", "stamp_duty", "txn_charges", "oth_charges")
        )
        bucket["grossPnl"] += row.get("gross_amount") or 0

    monthly: dict[str, dict[str, Any]] = {}
    yearly: dict[str, dict[str, Any]] = {}
    totals = _empty_bucket()

    for row in rows:
        trade_date = str(row.get("trade_date") or "")
        if not trade_date:
            continue
        month_key = trade_date[:7]
        year_key = _financial_year_label(trade_date)
        underlying = str(row.get("underlying") or "UNKNOWN")

        month_bucket = monthly.setdefault(month_key, {"period": month_key, "total": _empty_bucket(), "byUnderlying": {}})
        _add(month_bucket["total"], row)
        _add(month_bucket["byUnderlying"].setdefault(underlying, _empty_bucket()), row)

        year_bucket = yearly.setdefault(year_key, {"period": year_key, "total": _empty_bucket(), "byUnderlying": {}})
        _add(year_bucket["total"], row)
        _add(year_bucket["byUnderlying"].setdefault(underlying, _empty_bucket()), row)

        _add(totals, row)

    def _round_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
        return {
            "trades": bucket["trades"],
            "buyValue": round(bucket["buyValue"], 2),
            "sellValue": round(bucket["sellValue"], 2),
            "charges": round(bucket["charges"], 2),
            "grossPnl": round(bucket["grossPnl"], 2),
        }

    def _finalize(buckets: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "period": entry["period"],
                **_round_bucket(entry["total"]),
                "byUnderlying": {name: _round_bucket(sub) for name, sub in entry["byUnderlying"].items()},
            }
            for entry in sorted(buckets.values(), key=lambda item: item["period"])
        ]

    return {
        "monthly": _finalize(monthly),
        "yearly": _finalize(yearly),
        "totals": _round_bucket(totals),
        "count": len(rows),
    }


@router.post("/refresh", dependencies=[Depends(require_auth)])
async def refresh_equity(payload: EquityRefreshIn) -> dict[str, Any]:
    result: dict[str, Any] = {"scope": payload.scope, "updatedAt": datetime.now(timezone.utc).isoformat()}
    if payload.scope in {"portfolio", "all"}:
        result["portfolio"] = await _portfolio(refresh=True)
    if payload.scope in {"transactions", "all"}:
        result["transactions"] = await _transactions(from_date=payload.fromDate, to_date=payload.toDate, refresh=True)
    if payload.scope in {"news", "all"}:
        result["news"] = await equity_news(refresh=True)
    return result


async def _portfolio(*, refresh: bool) -> dict[str, Any]:
    settings = get_settings()
    service = DhanEquityService(settings)
    warning_parts: list[str] = []
    try:
        holdings = await service.holdings()
        upsert_equity_cache("holdings", "portfolio", {"data": holdings})
    except Exception as exc:
        cached_holdings = get_equity_cache("holdings", "portfolio")
        holdings = (cached_holdings or {}).get("data") or []
        warning_parts.append(f"Holdings: showing cached data ({exc})" if holdings else f"Holdings: {exc}")

    quotes = {} if refresh else _cached_quotes_for_holdings(holdings, max_age_seconds=settings.equity_quote_cache_seconds)
    if refresh or not quotes:
        try:
            quotes = await service.market_quotes(holdings)
            _cache_quotes(holdings, quotes)
        except Exception as exc:
            cached_quotes = _cached_quotes_for_holdings(holdings)
            if cached_quotes:
                quotes = cached_quotes
            else:
                warning_parts.append(f"Quotes: {exc}")

    fundamentals_by_symbol = await _fundamentals_for_holdings(holdings, refresh=refresh)
    enriched = []
    for holding in holdings:
        holding = dict(holding)
        _apply_quote(holding, quotes)
        try:
            holding["technicals"] = await _technicals_for_holding(service, holding, refresh=refresh)
        except Exception as exc:
            holding["technicals"] = _empty_technicals(str(exc))
        _apply_ltp_fallback(holding)
        holding["fundamentals"] = fundamentals_by_symbol.get(_holding_symbol(holding)) or _empty_fundamentals("Missing symbol.")
        holding["news"] = _cached_news_for_holding(holding)
        holding["recommendation"] = build_recommendation(
            holding=holding,
            fundamentals=holding.get("fundamentals"),
            technicals=holding.get("technicals"),
            news=holding.get("news"),
        )
        enriched.append(holding)

    total_market_value = sum(_number(row.get("marketValue")) or 0 for row in enriched)
    total_invested = sum(_number(row.get("investedValue")) or 0 for row in enriched)
    for holding in enriched:
        market_value = _number(holding.get("marketValue"))
        holding["exposurePercent"] = round((market_value / total_market_value) * 100, 2) if market_value and total_market_value else None
    filters = _portfolio_filters(enriched)
    latest_buys = last_buys(list_equity_transactions_cache(security_ids=filters["securityIds"], isins=filters["isins"]))
    for holding in enriched:
        try:
            holding["entrySignal"] = build_entry_signal(
                holding=holding, fundamentals=holding.get("fundamentals"), technicals=holding.get("technicals"),
                news=holding.get("news"), last_buy=latest_buys.get(str(holding.get("securityId") or "")),
            )
        except Exception as exc:  # never let the timing overlay break the portfolio view
            holding["entrySignal"] = {"state": "NO_DATA", "label": "No data", "reasons": [f"Entry signal failed: {exc}"], "blocks": []}

    total_pnl = round(total_market_value - total_invested, 2)
    return {
        "source": "dhan",
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "warning": " | ".join(warning_parts) if warning_parts else None,
        "count": len(enriched),
        "summary": {
            "totalInvested": round(total_invested, 2),
            "marketValue": round(total_market_value, 2),
            "pnl": total_pnl,
            "pnlPercent": round((total_pnl / total_invested) * 100, 2) if total_invested else None,
            "potentialBuyCount": sum(1 for row in enriched if "Buy" in str((row.get("recommendation") or {}).get("action") or "")),
            "reviewCount": sum(1 for row in enriched if str((row.get("recommendation") or {}).get("action") or "") in {"Review", "Avoid / Reduce"}),
            "entrySignals": summarize_entries(enriched),
        },
        "data": sorted(enriched, key=lambda row: _number(row.get("marketValue")) or 0, reverse=True),
    }


async def _transactions(*, from_date: str | None, to_date: str | None, refresh: bool, full: bool = False) -> dict[str, Any]:
    settings = get_settings()
    end = _date_or_default(to_date, date.today())
    start = _date_or_default(from_date, end - timedelta(days=settings.equity_transactions_lookback_days))
    # Every fetched trade is stored, so only ask Dhan for the days since the
    # last complete sync (Dhan's list also carries every F&O trade, ~1 page a
    # day), with a short overlap for late fills; `full` re-fetches the range.
    fetch_start = start
    synced = None if full else (get_equity_cache(TRANSACTION_SYNC_CATEGORY, "through") or {}).get("payload", {}).get("date")
    if synced:
        fetch_start = max(start, min(end, date.fromisoformat(synced) - timedelta(days=TRANSACTION_OVERLAP_DAYS)))
    elif not full:
        fetch_start = max(start, end - timedelta(days=DHAN_TRADE_HISTORY_DAYS))
    range_key = f"{fetch_start.isoformat()}:{end.isoformat()}"
    warning = None
    try:
        holdings = await DhanEquityService(settings).holdings()
        upsert_equity_cache("holdings", "portfolio", {"data": holdings})
    except Exception as exc:
        cached_holdings = get_equity_cache("holdings", "portfolio")
        holdings = (cached_holdings or {}).get("data") or []
        warning = f"Holdings: showing cached data ({exc})" if holdings else f"Holdings: {exc}"
    filters = _portfolio_filters(holdings)
    max_age = 30 * 60
    cached = None if refresh else get_equity_cache("transactions_range", range_key, max_age)
    if cached:
        rows = cached["payload"].get("data") or []
    else:
        service = DhanEquityService(settings)
        try:
            rows = await service.trade_history(fetch_start.isoformat(), end.isoformat())
            upsert_equity_transactions(rows)
            if service.last_warning:
                warning = " | ".join(part for part in [warning, service.last_warning] if part)
            else:
                upsert_equity_cache("transactions_range", range_key, {"data": rows})
                upsert_equity_cache(TRANSACTION_SYNC_CATEGORY, "through", {"date": end.isoformat()})
        except Exception as exc:
            warning = " | ".join(part for part in [warning, str(exc)] if part)
            rows = []

    # Merge in whatever's cached for these holdings -- this includes both
    # rows the live API already fetched AND any older history backfilled via
    # scripts/import_dhan_csv.py (Dhan's live trade-history API doesn't serve
    # records older than ~2.5-3 months regardless of the date range requested).
    cached_rows = list_equity_transactions_cache(security_ids=filters["securityIds"], isins=filters["isins"])
    merged_by_id: dict[str, dict[str, Any]] = {str(row.get("id")): row for row in cached_rows}
    merged_by_id.update({str(row.get("id")): row for row in rows})
    rows = list(merged_by_id.values())

    filtered = [row for row in rows if _transaction_in_portfolio(row, filters)]
    filtered.sort(key=lambda row: str(row.get("exchangeTime") or ""), reverse=True)
    return {
        "source": "dhan" if not warning else "cache",
        "warning": warning,
        "fromDate": start.isoformat(),
        "toDate": end.isoformat(),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "count": len(filtered),
        "summary": _transaction_summary(filtered),
        "data": filtered,
    }


async def _fundamentals_for_holding(holding: dict[str, Any], *, refresh: bool) -> dict[str, Any]:
    rows = await _fundamentals_for_holdings([holding], refresh=refresh)
    return rows.get(_holding_symbol(holding)) or _empty_fundamentals("Missing symbol.")


async def _fundamentals_for_holdings(holdings: list[dict[str, Any]], *, refresh: bool) -> dict[str, dict[str, Any]]:
    settings = get_settings()
    max_age = settings.equity_fundamentals_cache_hours * 3600
    symbols = sorted({_holding_symbol(holding) for holding in holdings if _holding_symbol(holding)})
    service = ScreenerService(settings)
    results: dict[str, dict[str, Any]] = {}
    pending: list[str] = []
    existing_by_symbol: dict[str, dict[str, Any] | None] = {}
    url_overrides: dict[str, str] = {}

    for symbol in symbols:
        default_url = service.company_url(symbol)
        url_cache = get_equity_cache("screener_url", symbol)
        if url_cache and url_cache["payload"].get("url"):
            url_overrides[symbol] = str(url_cache["payload"]["url"])
        else:
            url_overrides[symbol] = default_url
            upsert_equity_cache("screener_url", symbol, {"symbol": symbol, "url": default_url})

        cached = None if refresh else get_equity_cache("fundamentals", symbol, max_age)
        if cached and _fundamentals_cache_has_current_fields(cached["payload"]):
            payload = dict(cached["payload"])
            payload["cachedAt"] = cached["updatedAt"]
            results[symbol] = payload
            continue

        existing_by_symbol[symbol] = get_equity_cache("fundamentals", symbol)
        pending.append(symbol)

    if not pending:
        return results

    screener = ScreenerService(settings, url_overrides=url_overrides)
    fetched = await screener.fundamentals_many(pending)
    for symbol in pending:
        fundamentals = fetched.get(symbol) or _empty_fundamentals(symbol, "Missing Screener result.")
        existing = existing_by_symbol.get(symbol)
        if existing and not _fundamentals_has_values(fundamentals):
            payload = dict(existing["payload"])
            if fundamentals.get("warning"):
                payload["warning"] = f"Refresh failed: {fundamentals['warning']}"
            payload["cachedAt"] = existing["updatedAt"]
            results[symbol] = payload
            continue
        upsert_equity_cache("fundamentals", symbol, fundamentals)
        if fundamentals.get("url"):
            upsert_equity_cache("screener_url", symbol, {"symbol": symbol, "url": fundamentals["url"]})
        results[symbol] = fundamentals
    return results


def _fundamentals_cache_has_current_fields(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("parserVersion") != 2:
        return False
    return not (payload.get("pe") is not None and payload.get("medianPe") is None)


def _fundamentals_has_values(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    keys = ("pe", "medianPe", "industryPe", "roce", "roe", "debtToEquity")
    return any(payload.get(key) is not None for key in keys)


async def _technicals_for_holding(service: DhanEquityService, holding: dict[str, Any], *, refresh: bool) -> dict[str, Any]:
    settings = get_settings()
    security_id = str(holding.get("securityId") or "")
    if not security_id:
        return _empty_technicals("Missing Dhan security id.")
    max_age = settings.equity_price_cache_minutes * 60
    cached = None if refresh else get_equity_cache("technicals", security_id, max_age)
    if cached and "rsi14" not in (cached.get("payload") or {}):
        cached = None  # saved before RSI / SMA200 slope were added
    if cached:
        payload = dict(cached["payload"])
        payload["cachedAt"] = cached["updatedAt"]
        return payload
    try:
        payload = None
        for attempt in range(3):  # 30+ holdings back to back trip Dhan's rate limit
            await asyncio.sleep(0.35 + attempt * 1.5)
            try:
                payload = await service.historical_daily_data(
                    security_id=security_id,
                    exchange_segment=str(holding.get("exchangeSegment") or "NSE_EQ"),
                )
                break
            except Exception as exc:
                if "Rate_Limit" not in str(exc) or attempt == 2:
                    raise
        candles = normalize_historical_candles(payload)
        technicals = _technicals(candles)
        upsert_equity_cache("technicals", security_id, technicals)
        return technicals
    except Exception as exc:
        stale = get_equity_cache("technicals", security_id)
        if stale:
            payload = dict(stale["payload"])
            payload["cachedAt"] = stale["updatedAt"]
            payload["warning"] = f"Using cached historical data; refresh failed: {exc}"
            return payload
        return _empty_technicals(str(exc))


async def _news_for_holding(holding: dict[str, Any], *, refresh: bool) -> dict[str, Any]:
    settings = get_settings()
    symbol = str(holding.get("symbol") or holding.get("tradingSymbol") or "").upper()
    max_age = settings.equity_news_cache_hours * 3600
    cached = None if refresh else get_equity_cache("news", symbol, max_age)
    if cached:
        payload = dict(cached["payload"])
        payload["cachedAt"] = cached["updatedAt"]
        return payload
    if not refresh:
        return _cached_news_for_holding(holding)
    news = await OpenAINewsService(settings).stock_news(symbol=symbol, company_name=holding.get("tradingSymbol"))
    if (not news.get("warning") or settings.resolved_openai_api_key) and "credit overuse" not in str(news.get("warning") or ""):
        upsert_equity_cache("news", symbol, news)
    return news


def _cached_news_for_holding(holding: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    symbol = str(holding.get("symbol") or holding.get("tradingSymbol") or "").upper()
    cached = get_equity_cache("news", symbol, settings.equity_news_cache_hours * 3600)
    if cached:
        payload = dict(cached["payload"])
        payload["cachedAt"] = cached["updatedAt"]
        return payload
    return {
        "symbol": symbol,
        "source": "openai_web_search",
        "sentiment": "neutral",
        "summary": "No cached news yet.",
        "headlines": [],
        "risks": [],
        "sources": [],
        "warning": "Use Refresh News to fetch the latest web summary.",
    }


def _apply_quote(holding: dict[str, Any], quotes: dict[str, Any]) -> None:
    segment = str(holding.get("exchangeSegment") or "NSE_EQ")
    security_id = str(holding.get("securityId") or "")
    quote = (quotes.get(segment) or {}).get(security_id) or quotes.get(security_id) or {}
    ltp = _number(quote.get("last_price") or quote.get("lastPrice") or quote.get("ltp"))
    avg_cost = _number(holding.get("avgCostPrice"))
    total_qty = _number(holding.get("totalQty")) or 0
    holding["ltp"] = ltp
    holding["marketValue"] = round(total_qty * ltp, 2) if ltp is not None else None
    holding["pnl"] = round(total_qty * (ltp - avg_cost), 2) if ltp is not None and avg_cost is not None else None
    holding["pnlPercent"] = round(((ltp - avg_cost) / avg_cost) * 100, 2) if ltp is not None and avg_cost else None
    holding["quote"] = quote


def _cache_quotes(holdings: list[dict[str, Any]], quotes: dict[str, Any]) -> None:
    for holding in holdings:
        segment = str(holding.get("exchangeSegment") or "NSE_EQ")
        security_id = str(holding.get("securityId") or "")
        if not security_id:
            continue
        quote = (quotes.get(segment) or {}).get(security_id) or quotes.get(security_id) or {}
        if _number(quote.get("last_price") or quote.get("lastPrice") or quote.get("ltp")) is None:
            continue
        upsert_equity_cache(
            "quote",
            security_id,
            {
                "segment": segment,
                "securityId": security_id,
                "quote": quote,
            },
        )


def _cached_quotes_for_holdings(holdings: list[dict[str, Any]], max_age_seconds: int | None = None) -> dict[str, Any]:
    quotes: dict[str, Any] = {}
    for holding in holdings:
        segment = str(holding.get("exchangeSegment") or "NSE_EQ")
        security_id = str(holding.get("securityId") or "")
        if not security_id:
            continue
        cached = get_equity_cache("quote", security_id, max_age_seconds)
        if not cached:
            continue
        quote = (cached["payload"] or {}).get("quote") or {}
        if not quote:
            continue
        quotes.setdefault(segment, {})[security_id] = quote
    return quotes


def _apply_ltp_fallback(holding: dict[str, Any]) -> None:
    if _number(holding.get("ltp")) is not None:
        holding["quoteSource"] = "dhan_quote"
        return
    close = _number((holding.get("technicals") or {}).get("close"))
    if close is None:
        return
    avg_cost = _number(holding.get("avgCostPrice"))
    total_qty = _number(holding.get("totalQty")) or 0
    holding["ltp"] = close
    holding["marketValue"] = round(total_qty * close, 2)
    holding["pnl"] = round(total_qty * (close - avg_cost), 2) if avg_cost is not None else None
    holding["pnlPercent"] = round(((close - avg_cost) / avg_cost) * 100, 2) if avg_cost else None
    holding["quoteSource"] = "technical_close"


def _technicals(candles: list[dict[str, Any]]) -> dict[str, Any]:
    closes = [_number(candle.get("close")) for candle in candles]
    closes = [value for value in closes if value is not None]
    highs = [_number(candle.get("high")) for candle in candles]
    highs = [value for value in highs if value is not None]
    lows = [_number(candle.get("low")) for candle in candles]
    lows = [value for value in lows if value is not None]
    close = closes[-1] if closes else None
    return {
        "source": "dhan_historical",
        "close": close,
        "sma20": _sma(closes, 20),
        "sma50": _sma(closes, 50),
        "sma200": _sma(closes, 200),
        "sma200Rising": (_sma(closes, 200) > _sma(closes[:-20], 200)) if len(closes) >= 220 else None,
        "rsi14": rsi14(closes),
        "fiftyTwoWeekHigh": max(highs[-260:]) if highs else None,
        "fiftyTwoWeekLow": min(lows[-260:]) if lows else None,
        "candleCount": len(candles),
        "warning": None if candles else "No historical candles returned.",
    }


def _empty_technicals(warning: str) -> dict[str, Any]:
    return {
        "source": "dhan_historical",
        "close": None,
        "sma20": None,
        "sma50": None,
        "sma200": None,
        "fiftyTwoWeekHigh": None,
        "fiftyTwoWeekLow": None,
        "candleCount": 0,
        "warning": warning,
    }


def _empty_fundamentals(warning: str) -> dict[str, Any]:
    return {
        "source": "screener",
        "parserVersion": 2,
        "warning": warning,
        "pe": None,
        "medianPe": None,
        "industryPe": None,
        "roce": None,
        "roe": None,
        "debtToEquity": None,
    }


def _holding_symbol(holding: dict[str, Any]) -> str:
    return str(holding.get("symbol") or holding.get("tradingSymbol") or "").upper()


def _portfolio_filters(holdings: list[dict[str, Any]]) -> dict[str, set[str]]:
    return {
        "securityIds": {str(row.get("securityId")) for row in holdings if row.get("securityId")},
        "isins": {str(row.get("isin")) for row in holdings if row.get("isin")},
        "symbols": {str(row.get("symbol") or row.get("tradingSymbol") or "").upper() for row in holdings},
    }


def _transaction_in_portfolio(row: dict[str, Any], filters: dict[str, set[str]]) -> bool:
    return bool(
        str(row.get("securityId") or "") in filters["securityIds"]
        or str(row.get("isin") or "") in filters["isins"]
        or str(row.get("symbol") or row.get("tradingSymbol") or "").upper() in filters["symbols"]
    )


def _transaction_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    buy_value = sum(_number(row.get("value")) or 0 for row in rows if row.get("transactionType") == "BUY")
    sell_value = sum(_number(row.get("value")) or 0 for row in rows if row.get("transactionType") == "SELL")
    charges = sum(_number(row.get("charges")) or 0 for row in rows)
    return {
        "buyValue": round(buy_value, 2),
        "sellValue": round(sell_value, 2),
        "netCashFlow": round(sell_value - buy_value - charges, 2),
        "charges": round(charges, 2),
        "buyCount": sum(1 for row in rows if row.get("transactionType") == "BUY"),
        "sellCount": sum(1 for row in rows if row.get("transactionType") == "SELL"),
    }


def _sma(values: list[float], length: int) -> float | None:
    if len(values) < length:
        return None
    return round(sum(values[-length:]) / length, 2)


def _date_or_default(value: str | None, fallback: date) -> date:
    if not value:
        return fallback
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return fallback


def _number(value: Any) -> float | None:
    if value in (None, "", "NA", "NaN"):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
