"""Asyncio-native Dhan v2 WebSocket market feed client for Gamma Blast.

Binary protocol confirmed against Dhan's official docs (feed request codes,
feed response codes, Full-packet byte layout) and cross-checked against the
working Ticker/Quote parser in strangle/dhan_ws.py. Full mode (RequestCode 21,
response code 8) carries LTP + Open Interest in a single packet — no separate
REST poll needed for OI once subscribed.

Rate-limit note: Dhan documents no explicit cap on WS message volume once
connected (unlike the REST option-chain endpoints), but connection setup competes
for the same access token as everything else in this app — get_dhan_access_token()
is called fresh on every (re)connect so this automatically benefits from the
DHAN_TOKEN_REFRESH_MIN_INTERVAL_SECONDS gate in dhan_auth.py.
"""

from __future__ import annotations

import asyncio
import json
import struct
import time
from typing import Any

from app.core.config import Settings
from app.services.dhan_auth import get_dhan_access_token

WSS_URL = "wss://api-feed.dhan.co"
FULL_MODE_REQUEST_CODE = 21
FEED_RESPONSE_TICKER = 2
FEED_RESPONSE_OI = 5
FEED_RESPONSE_FULL = 8
FEED_RESPONSE_DISCONNECT = 50

_LIVE_STATE: dict[str, dict[str, Any]] = {}
_CONNECTED = False
_last_tick_at: float = 0.0


def get_state(security_id: str) -> dict[str, Any] | None:
    return _LIVE_STATE.get(str(security_id))


def get_all_state() -> dict[str, dict[str, Any]]:
    return dict(_LIVE_STATE)


def is_connected() -> bool:
    return _CONNECTED


def seconds_since_last_tick() -> float | None:
    if _last_tick_at == 0.0:
        return None
    return time.monotonic() - _last_tick_at


def start_feed_task(settings: Settings, instruments: list[tuple[str, str]]) -> asyncio.Task:
    return asyncio.create_task(_run_feed(settings, instruments))


async def stop_feed_task(task: asyncio.Task | None) -> None:
    global _CONNECTED
    _CONNECTED = False
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return


async def _run_feed(settings: Settings, instruments: list[tuple[str, str]]) -> None:
    global _CONNECTED
    import websockets

    attempt = 0
    while True:
        try:
            token = await get_dhan_access_token(settings, force_refresh=attempt > 0)
            client_id = settings.resolved_dhan_client_id
            url = f"{WSS_URL}?version=2&token={token}&clientId={client_id}&authType=2"
            async with websockets.connect(url, ping_interval=20, ping_timeout=10, close_timeout=5) as ws:
                _CONNECTED = True
                attempt = 0
                await _subscribe_all(ws, instruments)
                async for message in ws:
                    if isinstance(message, bytes):
                        _handle_packet(message)
        except asyncio.CancelledError:
            _CONNECTED = False
            raise
        except Exception:
            _CONNECTED = False
            attempt += 1
            await asyncio.sleep(min(2**attempt, 30))
        else:
            _CONNECTED = False


async def _subscribe_all(ws: Any, instruments: list[tuple[str, str]]) -> None:
    for i in range(0, len(instruments), 100):
        batch = instruments[i : i + 100]
        message = {
            "RequestCode": FULL_MODE_REQUEST_CODE,
            "InstrumentCount": len(batch),
            "InstrumentList": [{"ExchangeSegment": seg, "SecurityId": sid} for seg, sid in batch],
        }
        await ws.send(json.dumps(message))


def _handle_packet(data: bytes) -> None:
    global _last_tick_at
    if len(data) < 8:
        return
    response_code, _msg_len, _exch_seg, security_id = struct.unpack("<BHBI", data[0:8])
    key = str(security_id)

    if response_code == FEED_RESPONSE_FULL and len(data) >= 46:
        ltp, _ltq, _ltt, _atp, _volume, _sell, _buy, oi = struct.unpack("<fHIfIIII", data[8:38])
        _LIVE_STATE[key] = {"ltp": round(ltp, 2), "oi": float(oi), "updatedAt": time.monotonic()}
        _last_tick_at = time.monotonic()
    elif response_code == FEED_RESPONSE_OI and len(data) >= 12:
        (oi,) = struct.unpack("<I", data[8:12])
        entry = _LIVE_STATE.setdefault(key, {"ltp": None, "oi": None, "updatedAt": 0.0})
        entry["oi"] = float(oi)
        entry["updatedAt"] = time.monotonic()
        _last_tick_at = time.monotonic()
    elif response_code == FEED_RESPONSE_TICKER and len(data) >= 16:
        ltp, _ltt = struct.unpack("<fI", data[8:16])
        entry = _LIVE_STATE.setdefault(key, {"ltp": None, "oi": None, "updatedAt": 0.0})
        entry["ltp"] = round(ltp, 2)
        entry["updatedAt"] = time.monotonic()
        _last_tick_at = time.monotonic()
    # FEED_RESPONSE_DISCONNECT and anything else: ignored, the reconnect loop handles drops.
