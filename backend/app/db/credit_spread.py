from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.core.timeutil import now_ist
from app.db.sqlite import _DB_LOCK, _connect


def insert_position(
    position_id: str,
    *,
    expiry: str,
    mode: str,
    qty: int,
    sell_strike: float,
    sell_security_id: str,
    sell_entry_price: float,
    hedge_strike: float | None,
    hedge_security_id: str | None,
    hedge_entry_price: float | None,
    net_credit: float,
    entry_spot: float | None,
    entry_synthetic_future: float | None,
    entry_vix: float | None,
    planned_exit_date: str | None,
    entry_signal_id: int | None,
    payload: dict[str, Any] | None = None,
) -> None:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO credit_spread_positions (
                id, expiry, mode, status, qty,
                sell_strike, sell_security_id, sell_entry_price,
                hedge_strike, hedge_security_id, hedge_entry_price,
                net_credit, entry_spot, entry_synthetic_future, entry_vix,
                planned_exit_date, entry_signal_id, entry_at, payload_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, 'OPEN', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                position_id,
                expiry,
                mode,
                qty,
                sell_strike,
                sell_security_id,
                sell_entry_price,
                hedge_strike,
                hedge_security_id,
                hedge_entry_price,
                net_credit,
                entry_spot,
                entry_synthetic_future,
                entry_vix,
                planned_exit_date,
                entry_signal_id,
                now,
                json.dumps(payload or {}, default=str),
                now,
                now,
            ),
        )
        conn.commit()


def close_position(
    position_id: str,
    *,
    sell_exit_price: float,
    hedge_exit_price: float | None,
    exit_reason: str,
    realized_pnl: float,
) -> None:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            UPDATE credit_spread_positions
            SET status = 'CLOSED', sell_exit_price = ?, hedge_exit_price = ?,
                exit_reason = ?, realized_pnl = ?, exit_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (sell_exit_price, hedge_exit_price, exit_reason, realized_pnl, now, now, position_id),
        )
        conn.commit()


def get_position(position_id: str) -> dict[str, Any] | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM credit_spread_positions WHERE id = ?", (position_id,)).fetchone()
    return _position_from_row(row) if row else None


def get_open_position() -> dict[str, Any] | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM credit_spread_positions WHERE status = 'OPEN' ORDER BY entry_at DESC LIMIT 1"
        ).fetchone()
    return _position_from_row(row) if row else None


def get_position_for_expiry(expiry: str) -> dict[str, Any] | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM credit_spread_positions WHERE expiry = ? ORDER BY entry_at DESC LIMIT 1", (expiry,)
        ).fetchone()
    return _position_from_row(row) if row else None


def list_positions(limit: int = 60) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM credit_spread_positions ORDER BY entry_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_position_from_row(row) for row in rows]


def record_signal(*, kind: str, status: str, position_id: str | None = None, payload: dict[str, Any] | None = None) -> int:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO credit_spread_signals (kind, status, position_id, payload_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (kind, status, position_id, json.dumps(payload or {}, default=str), now, now),
        )
        conn.commit()
        return int(cursor.lastrowid)


def update_signal_status(signal_id: int, status: str, *, position_id: str | None = None) -> None:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        if position_id is not None:
            conn.execute(
                "UPDATE credit_spread_signals SET status = ?, position_id = ?, updated_at = ? WHERE id = ?",
                (status, position_id, now, signal_id),
            )
        else:
            conn.execute(
                "UPDATE credit_spread_signals SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, signal_id),
            )
        conn.commit()


def get_signal(signal_id: int) -> dict[str, Any] | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM credit_spread_signals WHERE id = ?", (signal_id,)).fetchone()
    return _signal_from_row(row) if row else None


def get_pending_signals() -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM credit_spread_signals WHERE status = 'PENDING' ORDER BY id"
        ).fetchall()
    return [_signal_from_row(row) for row in rows]


def list_signals(limit: int = 100) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute("SELECT * FROM credit_spread_signals ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [_signal_from_row(row) for row in rows]


def record_event(event_type: str, message: str, *, position_id: str | None = None, payload: dict[str, Any] | None = None) -> None:
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO credit_spread_events (event_type, message, position_id, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                event_type,
                message,
                position_id,
                json.dumps(payload or {}, default=str),
                now_ist().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()


def list_events(limit: int = 120) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute("SELECT * FROM credit_spread_events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [
        {
            "id": row["id"],
            "eventType": row["event_type"],
            "message": row["message"],
            "positionId": row["position_id"],
            "payload": _json(row["payload_json"]),
            "createdAt": row["created_at"],
        }
        for row in rows
    ]


def get_meta(key: str) -> str | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT value FROM credit_spread_meta WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row else None


def set_meta(key: str, value: str) -> None:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO credit_spread_meta (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, now),
        )
        conn.commit()


def _position_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "expiry": row["expiry"],
        "mode": row["mode"],
        "status": row["status"],
        "qty": row["qty"],
        "sellStrike": row["sell_strike"],
        "sellSecurityId": row["sell_security_id"],
        "sellEntryPrice": row["sell_entry_price"],
        "hedgeStrike": row["hedge_strike"],
        "hedgeSecurityId": row["hedge_security_id"],
        "hedgeEntryPrice": row["hedge_entry_price"],
        "netCredit": row["net_credit"],
        "entrySpot": row["entry_spot"],
        "entrySyntheticFuture": row["entry_synthetic_future"],
        "entryVix": row["entry_vix"],
        "plannedExitDate": row["planned_exit_date"],
        "entrySignalId": row["entry_signal_id"],
        "entryAt": row["entry_at"],
        "sellExitPrice": row["sell_exit_price"],
        "hedgeExitPrice": row["hedge_exit_price"],
        "exitReason": row["exit_reason"],
        "realizedPnl": row["realized_pnl"],
        "exitAt": row["exit_at"],
        "payload": _json(row["payload_json"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _signal_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "status": row["status"],
        "positionId": row["position_id"],
        "payload": _json(row["payload_json"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _json(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None
