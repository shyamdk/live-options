"""Fetches NIFTY index candles for the animesh-scalping strategy via Dhan's
REST /charts/intraday endpoint. Reuses ema5_candles.fetch_today_candles
directly for the 1-minute execution-timeframe candles (it's already
generic over security id / interval / session start time — nothing
ema5-specific about it).

Dhan's /charts/intraday has no daily/"D" interval, so the previous trading
day's Heikin Ashi color (and the day's opening gap vs previous close) is
derived by fetching ~20 calendar days of 60-minute candles and aggregating
them into daily OHLC bars here, rather than adding a new Dhan endpoint.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.timeutil import now_ist
from app.services.dhan import DhanService
from app.services.ema5_candles import INDEX_INSTRUMENT, INDEX_SEGMENT, fetch_today_candles
from app.services.ema5_engine import Candle

_IST = ZoneInfo("Asia/Kolkata")

__all__ = ["fetch_today_candles", "fetch_daily_bias_candles"]


async def fetch_daily_bias_candles(dhan: DhanService, security_id: str, lookback_days: int = 20) -> list[Candle]:
    """Returns daily OHLC bars for the last `lookback_days` calendar days,
    strictly EXCLUDING today (today's daily bar is still forming). Oldest
    first; the last element is yesterday's (most recent complete trading
    day's) daily candle.
    """
    now = now_ist()
    from_date = f"{(now.date() - timedelta(days=lookback_days)).isoformat()} 09:15:00"
    to_date = now.strftime("%Y-%m-%d %H:%M:%S")
    raw = await dhan.intraday_candles(
        security_id=security_id,
        exchange_segment=INDEX_SEGMENT,
        instrument=INDEX_INSTRUMENT,
        interval="60",
        from_date=from_date,
        to_date=to_date,
    )
    hourly = [Candle(time=int(c["time"]), open=c["open"], high=c["high"], low=c["low"], close=c["close"]) for c in raw]

    today = now.date().isoformat()
    by_date: dict[str, list[Candle]] = {}
    for candle in hourly:
        date_key = _epoch_to_ist_date(candle.time)
        if date_key == today:
            continue
        by_date.setdefault(date_key, []).append(candle)

    daily: list[Candle] = []
    for date_key in sorted(by_date.keys()):
        bars = by_date[date_key]
        daily.append(
            Candle(
                time=bars[0].time,
                open=bars[0].open,
                high=max(b.high for b in bars),
                low=min(b.low for b in bars),
                close=bars[-1].close,
            )
        )
    return daily


def _epoch_to_ist_date(epoch_seconds: int) -> str:
    return datetime.fromtimestamp(epoch_seconds, tz=_IST).date().isoformat()
