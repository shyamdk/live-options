"""I/O orchestration for the upgraded signal engine (oi_signal_engine.py):
fetches the already-collected PCR/OI snapshots plus fresh 1-minute index
candles, and returns the enriched series. NIFTY only for this iteration --
see upgrade.md's own "we will do NIFTY only for now" scoping.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.core.timeutil import now_ist
from app.db.sqlite import get_pcr_oi_snapshots
from app.services.dhan import DhanService
from app.services.oi_signal_engine import enrich_with_upgraded_signal

INDEX_SEGMENT = "IDX_I"


async def get_upgraded_nifty_signal(session_date: str | None = None) -> list[dict]:
    settings = get_settings()
    now = now_ist()
    today = now.date().isoformat()
    resolved_date = session_date or today
    points = get_pcr_oi_snapshots(resolved_date).get("NIFTY", [])
    if not points:
        return []

    dhan = DhanService(settings)
    from_date = f"{resolved_date} 09:15:00"
    to_date = now.strftime("%Y-%m-%d %H:%M:%S") if resolved_date == today else f"{resolved_date} 15:30:00"
    try:
        candles = await dhan.intraday_candles(
            security_id=settings.dhan_nifty_security_id,
            exchange_segment=INDEX_SEGMENT,
            instrument="INDEX",
            interval="1",
            from_date=from_date,
            to_date=to_date,
        )
    except Exception:
        candles = []

    return enrich_with_upgraded_signal(points, candles)
