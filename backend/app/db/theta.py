"""Theta Book persistence: sessions (one per trading day, tracks day-type
per underlying and the daily halt/realized-P&L state), positions (one row
per open/closed strike, aggregated across all its tranches with a running
weighted-average entry premium), tranches (append-only audit log of each
individual sell fill on a position), signals (pending ENTRY/ADD/EXIT
proposals awaiting approval), events (audit trail), and settings (runtime-
editable key-value overrides for the THETA_* config defaults).

Mirrors app/db/animesh.py's shape, adapted for Theta Book's aggregate
multi-tranche positions instead of animesh's fixed 3-lot trades.
"""

from __future__ import annotations

import json
from typing import Any

from app.core.timeutil import now_ist
from app.db.sqlite import _DB_LOCK, _connect


def upsert_session(
    session_id: str,
    *,
    session_date: str,
    mode: str,
    status: str,
    nifty_day_type: str | None = None,
    sensex_day_type: str | None = None,
) -> None:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        existing = conn.execute("SELECT id FROM theta_sessions WHERE id = ?", (session_id,)).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE theta_sessions
                SET mode = ?, status = ?,
                    nifty_day_type = COALESCE(?, nifty_day_type),
                    sensex_day_type = COALESCE(?, sensex_day_type),
                    updated_at = ?
                WHERE id = ?
                """,
                (mode, status, nifty_day_type, sensex_day_type, now, session_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO theta_sessions (
                    id, session_date, mode, status, nifty_day_type, sensex_day_type,
                    realized_pnl, halted, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
                """,
                (session_id, session_date, mode, status, nifty_day_type, sensex_day_type, now, now),
            )
        conn.commit()


def get_session(session_id: str) -> dict[str, Any] | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM theta_sessions WHERE id = ?", (session_id,)).fetchone()
    return _session_from_row(row) if row else None


def list_sessions(limit: int = 30) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute("SELECT * FROM theta_sessions ORDER BY session_date DESC LIMIT ?", (limit,)).fetchall()
    return [_session_from_row(row) for row in rows]


def record_daily_pnl(session_id: str, realized_delta: float) -> None:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            "UPDATE theta_sessions SET realized_pnl = realized_pnl + ?, updated_at = ? WHERE id = ?",
            (realized_delta, now, session_id),
        )
        conn.commit()


def set_day_halted(session_id: str, halted: bool) -> None:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            "UPDATE theta_sessions SET halted = ?, updated_at = ? WHERE id = ?",
            (1 if halted else 0, now, session_id),
        )
        conn.commit()


def record_signal(
    session_id: str,
    *,
    kind: str,
    status: str,
    underlying: str,
    side: str,
    strike: float | None = None,
    expiry: str | None = None,
    position_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> int:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO theta_signals (
                session_id, kind, status, underlying, side, strike, expiry,
                position_id, payload_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, kind, status, underlying, side, strike, expiry, position_id, json.dumps(payload or {}, default=str), now, now),
        )
        conn.commit()
        return int(cursor.lastrowid)


def update_signal_status(signal_id: int, status: str, *, position_id: str | None = None) -> None:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        if position_id is not None:
            conn.execute(
                "UPDATE theta_signals SET status = ?, position_id = ?, updated_at = ? WHERE id = ?",
                (status, position_id, now, signal_id),
            )
        else:
            conn.execute("UPDATE theta_signals SET status = ?, updated_at = ? WHERE id = ?", (status, now, signal_id))
        conn.commit()


def get_signal(signal_id: int) -> dict[str, Any] | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM theta_signals WHERE id = ?", (signal_id,)).fetchone()
    return _signal_from_row(row) if row else None


def get_signals_for_session(session_id: str) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute("SELECT * FROM theta_signals WHERE session_id = ? ORDER BY created_at, id", (session_id,)).fetchall()
    return [_signal_from_row(row) for row in rows]


def get_pending_signals(session_id: str) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM theta_signals WHERE session_id = ? AND status = 'PENDING' ORDER BY created_at, id", (session_id,)
        ).fetchall()
    return [_signal_from_row(row) for row in rows]


def insert_position(
    position_id: str,
    *,
    session_id: str,
    underlying: str,
    side: str,
    strike: float,
    expiry: str,
    security_id: str | None,
    exchange_segment: str | None,
    mode: str,
    day_type: str | None,
    entry_spot: float | None,
) -> None:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO theta_positions (
                id, session_id, underlying, side, strike, expiry, security_id, exchange_segment,
                mode, status, day_type, tranche_count, total_qty, avg_entry_premium, entry_spot,
                estimated_margin, realized_pnl, close_reason, created_at, updated_at, closed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, 0, 0, NULL, ?, NULL, NULL, NULL, ?, ?, NULL)
            """,
            (position_id, session_id, underlying, side, strike, expiry, security_id, exchange_segment, mode, day_type, entry_spot, now, now),
        )
        conn.commit()


def add_tranche(
    position_id: str, *, qty: int, premium: float, spot_at_entry: float | None, distance_pct_at_entry: float | None, day_type: str | None
) -> None:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO theta_tranches (position_id, qty, premium, spot_at_entry, distance_pct_at_entry, day_type, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (position_id, qty, premium, spot_at_entry, distance_pct_at_entry, day_type, now),
        )
        row = conn.execute("SELECT total_qty, avg_entry_premium, estimated_margin FROM theta_positions WHERE id = ?", (position_id,)).fetchone()
        existing_qty = row["total_qty"] if row else 0
        existing_avg = row["avg_entry_premium"] if row else None
        new_qty = existing_qty + qty
        new_avg = premium if not existing_qty or existing_avg is None else ((existing_avg * existing_qty) + (premium * qty)) / new_qty
        conn.execute(
            """
            UPDATE theta_positions
            SET tranche_count = tranche_count + 1, total_qty = ?, avg_entry_premium = ?, updated_at = ?
            WHERE id = ?
            """,
            (new_qty, new_avg, now, position_id),
        )
        conn.commit()


def set_position_margin(position_id: str, estimated_margin: float) -> None:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            "UPDATE theta_positions SET estimated_margin = ?, updated_at = ? WHERE id = ?",
            (estimated_margin, now, position_id),
        )
        conn.commit()


def close_position(position_id: str, *, realized_pnl: float, close_reason: str) -> None:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            UPDATE theta_positions
            SET status = 'CLOSED', realized_pnl = ?, close_reason = ?, updated_at = ?, closed_at = ?
            WHERE id = ?
            """,
            (realized_pnl, close_reason, now, now, position_id),
        )
        conn.commit()


def get_position(position_id: str) -> dict[str, Any] | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM theta_positions WHERE id = ?", (position_id,)).fetchone()
    return _position_from_row(row) if row else None


def get_open_positions(session_id: str, underlying: str | None = None) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        if underlying:
            rows = conn.execute(
                "SELECT * FROM theta_positions WHERE session_id = ? AND status = 'OPEN' AND underlying = ? ORDER BY created_at",
                (session_id, underlying),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM theta_positions WHERE session_id = ? AND status = 'OPEN' ORDER BY created_at", (session_id,)
            ).fetchall()
    return [_position_from_row(row) for row in rows]


def get_positions_for_session(session_id: str) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute("SELECT * FROM theta_positions WHERE session_id = ? ORDER BY created_at", (session_id,)).fetchall()
    return [_position_from_row(row) for row in rows]


def get_tranches_for_position(position_id: str) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute("SELECT * FROM theta_tranches WHERE position_id = ? ORDER BY created_at, id", (position_id,)).fetchall()
    return [_tranche_from_row(row) for row in rows]


def get_tranches_for_positions(position_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not position_ids:
        return {}
    placeholders = ",".join("?" for _ in position_ids)
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM theta_tranches WHERE position_id IN ({placeholders}) ORDER BY position_id, created_at, id", position_ids
        ).fetchall()
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        result.setdefault(row["position_id"], []).append(_tranche_from_row(row))
    return result


def record_event(session_id: str, event_type: str, message: str, payload: dict[str, Any] | None = None) -> None:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            "INSERT INTO theta_events (session_id, event_type, message, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, event_type, message, json.dumps(payload or {}, default=str), now),
        )
        conn.commit()


def get_events_for_session(session_id: str, limit: int = 200) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM theta_events WHERE session_id = ? ORDER BY created_at DESC, id DESC LIMIT ?", (session_id, limit)
        ).fetchall()
    events = [_event_from_row(row) for row in rows]
    events.reverse()
    return events


def get_setting(key: str) -> str | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT value FROM theta_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO theta_settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, now),
        )
        conn.commit()


def _session_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "sessionDate": row["session_date"],
        "mode": row["mode"],
        "status": row["status"],
        "niftyDayType": row["nifty_day_type"],
        "sensexDayType": row["sensex_day_type"],
        "realizedPnl": row["realized_pnl"],
        "halted": bool(row["halted"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _signal_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "sessionId": row["session_id"],
        "kind": row["kind"],
        "status": row["status"],
        "underlying": row["underlying"],
        "side": row["side"],
        "strike": row["strike"],
        "expiry": row["expiry"],
        "positionId": row["position_id"],
        "payload": _json(row["payload_json"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _position_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "sessionId": row["session_id"],
        "underlying": row["underlying"],
        "side": row["side"],
        "strike": row["strike"],
        "expiry": row["expiry"],
        "securityId": row["security_id"],
        "exchangeSegment": row["exchange_segment"],
        "mode": row["mode"],
        "status": row["status"],
        "dayType": row["day_type"],
        "trancheCount": row["tranche_count"],
        "totalQty": row["total_qty"],
        "avgEntryPremium": row["avg_entry_premium"],
        "entrySpot": row["entry_spot"],
        "estimatedMargin": row["estimated_margin"],
        "realizedPnl": row["realized_pnl"],
        "closeReason": row["close_reason"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "closedAt": row["closed_at"],
    }


def _tranche_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "positionId": row["position_id"],
        "qty": row["qty"],
        "premium": row["premium"],
        "spotAtEntry": row["spot_at_entry"],
        "distancePctAtEntry": row["distance_pct_at_entry"],
        "dayType": row["day_type"],
        "createdAt": row["created_at"],
    }


def _event_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "sessionId": row["session_id"],
        "eventType": row["event_type"],
        "message": row["message"],
        "payload": _json(row["payload_json"]),
        "createdAt": row["created_at"],
    }


def _json(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None
