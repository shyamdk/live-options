"""Fetches NIFTY index candles for the ema5 strategy via Dhan's REST
/charts/intraday endpoint (confirmed live: securityId=13, exchangeSegment=
IDX_I, instrument=INDEX, interval in {5, 15}). Polled by the orchestrator
only once per candle-close boundary (every 5 or 15 minutes), never
continuously — live SL/target monitoring uses the WebSocket feed instead
(see dhan_ws.py), this module is purely for candle-close pattern detection.
"""

from __future__ import annotations

from app.core.timeutil import now_ist
from app.services.dhan import DhanService
from app.services.ema5_engine import Candle

INDEX_SEGMENT = "IDX_I"
INDEX_INSTRUMENT = "INDEX"


async def fetch_today_candles(
    dhan: DhanService, security_id: str, interval: str, session_start_time: str
) -> list[Candle]:
    now = now_ist()
    today = now.date().isoformat()
    from_date = f"{today} {session_start_time}:00"
    to_date = now.strftime("%Y-%m-%d %H:%M:%S")
    raw = await dhan.intraday_candles(
        security_id=security_id,
        exchange_segment=INDEX_SEGMENT,
        instrument=INDEX_INSTRUMENT,
        interval=interval,
        from_date=from_date,
        to_date=to_date,
    )
    return [Candle(time=int(c["time"]), open=c["open"], high=c["high"], low=c["low"], close=c["close"]) for c in raw]
