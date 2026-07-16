"""Asyncio-native Dhan v2 WebSocket market feed client.

Binary protocol confirmed against Dhan's official docs (feed request codes,
feed response codes, Full-packet byte layout) and cross-checked against the
working Ticker/Quote parser in strangle/dhan_ws.py. Full mode (RequestCode 21,
response code 8) carries LTP + Open Interest in a single packet — no separate
REST poll needed for OI once subscribed to option contracts this way.

Indices (segment IDX_I, e.g. NIFTY/SENSEX spot) are a documented exception:
confirmed by direct testing against the live feed that Dhan sends *zero*
packets for an index subscribed in Full mode (indices have no OI/depth to
report), but responds immediately with Quote-mode (RequestCode 17, response
code 4) packets. So index instruments must be subscribed separately in Quote
mode; option contracts stay on Full mode for OI.

Rate-limit note: Dhan documents no explicit cap on WS message volume once
connected (unlike the REST option-chain endpoints), but connection setup competes
for the same access token as everything else in this app — get_dhan_access_token()
is called fresh on every (re)connect so this automatically benefits from the
DHAN_TOKEN_REFRESH_MIN_INTERVAL_SECONDS gate in dhan_auth.py.

Originally built as a Gamma-Blast-only module with module-level global state;
generalized into this instance-based client so any strategy (Gamma Blast,
ema5, ...) can hold its own independent connection/state without fighting
over shared globals. Each instance is its own WS connection — Dhan allows up
to 5 concurrent connections per user, comfortably enough for a few strategies.
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
QUOTE_MODE_REQUEST_CODE = 17
FEED_RESPONSE_TICKER = 2
FEED_RESPONSE_QUOTE = 4
FEED_RESPONSE_OI = 5
FEED_RESPONSE_FULL = 8
FEED_RESPONSE_DISCONNECT = 50


class DhanWsClient:
    def __init__(self) -> None:
        self._live_state: dict[str, dict[str, Any]] = {}
        self._connected = False
        self._last_tick_at: float = 0.0
        self._task: asyncio.Task | None = None

    def get_state(self, security_id: str) -> dict[str, Any] | None:
        return self._live_state.get(str(security_id))

    def get_all_state(self) -> dict[str, dict[str, Any]]:
        return dict(self._live_state)

    def is_connected(self) -> bool:
        return self._connected

    def seconds_since_last_tick(self) -> float | None:
        if self._last_tick_at == 0.0:
            return None
        return time.monotonic() - self._last_tick_at

    def start(
        self,
        settings: Settings,
        full_mode_instruments: list[tuple[str, str]],
        quote_mode_instruments: list[tuple[str, str]] | None = None,
    ) -> asyncio.Task:
        self._task = asyncio.create_task(self._run_feed(settings, full_mode_instruments, quote_mode_instruments or []))
        return self._task

    async def stop(self) -> None:
        self._connected = False
        task, self._task = self._task, None
        if not task:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return

    async def _run_feed(
        self, settings: Settings, full_mode_instruments: list[tuple[str, str]], quote_mode_instruments: list[tuple[str, str]]
    ) -> None:
        import websockets

        attempt = 0
        while True:
            try:
                token = await get_dhan_access_token(settings, force_refresh=attempt > 0)
                client_id = settings.resolved_dhan_client_id
                url = f"{WSS_URL}?version=2&token={token}&clientId={client_id}&authType=2"
                async with websockets.connect(url, ping_interval=20, ping_timeout=10, close_timeout=5) as ws:
                    self._connected = True
                    attempt = 0
                    await self._subscribe(ws, full_mode_instruments, FULL_MODE_REQUEST_CODE)
                    await self._subscribe(ws, quote_mode_instruments, QUOTE_MODE_REQUEST_CODE)
                    async for message in ws:
                        if isinstance(message, bytes):
                            self._handle_packet(message)
            except asyncio.CancelledError:
                self._connected = False
                raise
            except Exception:
                self._connected = False
                attempt += 1
                await asyncio.sleep(min(2**attempt, 30))
            else:
                self._connected = False

    async def _subscribe(self, ws: Any, instruments: list[tuple[str, str]], request_code: int) -> None:
        for i in range(0, len(instruments), 100):
            batch = instruments[i : i + 100]
            message = {
                "RequestCode": request_code,
                "InstrumentCount": len(batch),
                "InstrumentList": [{"ExchangeSegment": seg, "SecurityId": sid} for seg, sid in batch],
            }
            await ws.send(json.dumps(message))

    def _handle_packet(self, data: bytes) -> None:
        if len(data) < 8:
            return
        response_code, _msg_len, _exch_seg, security_id = struct.unpack("<BHBI", data[0:8])
        key = str(security_id)

        if response_code == FEED_RESPONSE_FULL and len(data) >= 46:
            ltp, _ltq, _ltt, _atp, _volume, _sell, _buy, oi = struct.unpack("<fHIfIIII", data[8:38])
            self._live_state[key] = {"ltp": round(ltp, 2), "oi": float(oi), "updatedAt": time.monotonic()}
            self._last_tick_at = time.monotonic()
        elif response_code == FEED_RESPONSE_QUOTE and len(data) >= 12:
            (ltp,) = struct.unpack("<f", data[8:12])
            entry = self._live_state.setdefault(key, {"ltp": None, "oi": None, "updatedAt": 0.0})
            entry["ltp"] = round(ltp, 2)
            entry["updatedAt"] = time.monotonic()
            self._last_tick_at = time.monotonic()
        elif response_code == FEED_RESPONSE_OI and len(data) >= 12:
            (oi,) = struct.unpack("<I", data[8:12])
            entry = self._live_state.setdefault(key, {"ltp": None, "oi": None, "updatedAt": 0.0})
            entry["oi"] = float(oi)
            entry["updatedAt"] = time.monotonic()
            self._last_tick_at = time.monotonic()
        elif response_code == FEED_RESPONSE_TICKER and len(data) >= 16:
            ltp, _ltt = struct.unpack("<fI", data[8:16])
            entry = self._live_state.setdefault(key, {"ltp": None, "oi": None, "updatedAt": 0.0})
            entry["ltp"] = round(ltp, 2)
            entry["updatedAt"] = time.monotonic()
            self._last_tick_at = time.monotonic()
        # FEED_RESPONSE_DISCONNECT and anything else: ignored, the reconnect loop handles drops.
