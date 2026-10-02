"""Resolves a Dhan security_id for a plain NSE equity/ETF trading symbol
(e.g. "NIFTYBEES") from Dhan's public instrument scrip-master CSV.

Unlike NIFTY/SENSEX (index security IDs are just hardcoded in config.py --
they never change) and options (resolved live via the option-chain
endpoints, see ema5_instruments.py), there's no Dhan REST endpoint to look
up a single equity's security_id by symbol -- Dhan's own docs point
integrators at this CSV instead. Parsed once per process and cached in
memory: it's a large (~10-20MB), slowly-changing file, not worth
re-fetching per request.
"""

from __future__ import annotations

import csv
import io
import time
from typing import Any

import httpx

SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
_CACHE_TTL_SECONDS = 24 * 3600

_cache: dict[str, Any] = {"rows": None, "fetched_at": 0.0}


class ScripMasterError(RuntimeError):
    pass


async def resolve_equity_security_id(trading_symbol: str, *, exchange: str = "NSE") -> int:
    """Returns the Dhan security_id for a cash-market equity/ETF trading
    symbol on the given exchange. Raises ScripMasterError (rather than
    guessing or returning None) if the symbol can't be found -- a wrong or
    missing security_id would silently fetch candles for the wrong
    instrument, which is worse than a loud failure.
    """
    rows = await _get_rows()
    target = trading_symbol.strip().upper()
    for row in rows:
        if row["symbol"].strip().upper() != target:
            continue
        if row["exchange"].strip().upper() != exchange.upper():
            continue
        if row["segment"] and row["segment"].strip().upper() not in ("E", "EQ", "EQUITY"):
            continue
        try:
            return int(row["security_id"])
        except (TypeError, ValueError):
            continue
    raise ScripMasterError(
        f"Could not resolve a Dhan security_id for {trading_symbol!r} on {exchange} from the scrip master "
        f"({len(rows)} rows scanned) -- the CSV's column names or the symbol itself may have changed."
    )


async def resolve_nearest_mcx_future(symbol_name: str) -> dict[str, Any] | None:
    """Nearest-expiry MCX commodity future's security_id for a given
    SM_SYMBOL_NAME (e.g. "GOLD", "SILVER", "CRUDEOIL"). MCX commodities have
    no spot-tradable instrument, so the nearest-expiry future is the
    standard proxy for "current price" -- same convention brokers'
    commodity tickers use. Returns None (not an exception) rather than
    raising, since this only ever backs a best-effort display panel, not an
    order -- a missing/renamed commodity shouldn't take the whole panel
    down (see market.py's _commodity_indices, same reasoning as its
    existing _crypto_indices).
    """
    rows = await _get_rows()
    target = symbol_name.strip().upper()
    candidates = [
        row
        for row in rows
        if row.get("exchange", "").strip().upper() == "MCX"
        and row.get("instrument", "").strip().upper() == "FUTCOM"
        and row.get("symbol_name", "").strip().upper() == target
        and row.get("expiry_date", "").strip()
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda row: row["expiry_date"])
    row = candidates[0]
    try:
        security_id = int(row["security_id"])
    except (TypeError, ValueError):
        return None
    return {"securityId": security_id, "expiry": row["expiry_date"]}


async def resolve_nifty_futures(count: int = 2) -> list[dict[str, Any]]:
    """Nearest `count` NIFTY index-future contracts (current month, next
    month, ...) by expiry, for the market-strip's futures panel. Same
    resolve-then-quote pattern as resolve_nearest_mcx_future -- NIFTY
    futures have no SM_SYMBOL_NAME set in the scrip master, so contracts are
    matched on SEM_TRADING_SYMBOL's "NIFTY-<Mon><Year>-FUT" convention
    instead (confirmed against a live download of the CSV; excludes
    NIFTYNXT50/NIFTYFPI/BANKNIFTY, which use different prefixes).
    """
    rows = await _get_rows()
    candidates = [
        row
        for row in rows
        if row.get("exchange", "").strip().upper() == "NSE"
        and row.get("instrument", "").strip().upper() == "FUTIDX"
        and row.get("symbol", "").strip().upper().startswith("NIFTY-")
        and row.get("expiry_date", "").strip()
    ]
    candidates.sort(key=lambda row: row["expiry_date"])
    results = []
    for row in candidates[:count]:
        try:
            security_id = int(row["security_id"])
        except (TypeError, ValueError):
            continue
        results.append({"securityId": security_id, "expiry": row["expiry_date"], "tradingSymbol": row["symbol"]})
    return results


async def resolve_lot_size_by_security_id(security_id: int | str) -> int:
    """Current lot size for an option/futures contract, straight from the
    instrument master (SEM_LOT_UNITS) -- spec requirement: "Load current lot
    size from the instrument master; never hard-code a permanent lot size."
    Raises ScripMasterError if the contract can't be found, same reasoning
    as resolve_equity_security_id: a wrong/missing lot size silently
    mis-sizes a real order, worse than a loud failure.
    """
    rows = await _get_rows()
    target = str(security_id)
    for row in rows:
        if row["security_id"].strip() == target:
            try:
                return int(float(row["lot_units"]))
            except (TypeError, ValueError):
                continue
    raise ScripMasterError(f"Could not resolve lot size for security_id {security_id!r} from the scrip master.")


async def _get_rows() -> list[dict[str, str]]:
    now = time.monotonic()
    if _cache["rows"] is not None and now - _cache["fetched_at"] < _CACHE_TTL_SECONDS:
        return _cache["rows"]

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(SCRIP_MASTER_URL)
    if response.status_code >= 400:
        raise ScripMasterError(f"Failed to download Dhan scrip master ({response.status_code})")

    reader = csv.DictReader(io.StringIO(response.text))
    if not reader.fieldnames:
        raise ScripMasterError("Dhan scrip master CSV had no header row")

    symbol_col = _find_column(reader.fieldnames, "TRADING_SYMBOL")
    security_id_col = _find_column(reader.fieldnames, "SECURITY_ID")
    exchange_col = _find_column(reader.fieldnames, "EXCH_ID") or _find_column(reader.fieldnames, "EXCHANGE")
    segment_col = _find_column(reader.fieldnames, "SEGMENT")
    lot_units_col = _find_column(reader.fieldnames, "LOT_UNITS")
    instrument_col = _find_column(reader.fieldnames, "INSTRUMENT_NAME")
    symbol_name_col = _find_column(reader.fieldnames, "SYMBOL_NAME")
    expiry_date_col = _find_column(reader.fieldnames, "EXPIRY_DATE")
    if not symbol_col or not security_id_col or not exchange_col:
        raise ScripMasterError(
            f"Dhan scrip master CSV columns didn't match expectations: {reader.fieldnames[:15]}"
        )

    rows = [
        {
            "symbol": row.get(symbol_col, ""),
            "security_id": row.get(security_id_col, ""),
            "exchange": row.get(exchange_col, ""),
            "segment": row.get(segment_col, "") if segment_col else "",
            "lot_units": row.get(lot_units_col, "") if lot_units_col else "",
            "instrument": row.get(instrument_col, "") if instrument_col else "",
            "symbol_name": row.get(symbol_name_col, "") if symbol_name_col else "",
            "expiry_date": row.get(expiry_date_col, "") if expiry_date_col else "",
        }
        for row in reader
    ]
    _cache["rows"] = rows
    _cache["fetched_at"] = now
    return rows


def _find_column(fieldnames: list[str], needle: str) -> str | None:
    for name in fieldnames:
        if needle.upper() in name.upper():
            return name
    return None
