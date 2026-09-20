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
