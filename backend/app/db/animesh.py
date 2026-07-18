from __future__ import annotations

import json
from typing import Any

from app.core.timeutil import now_ist
from app.db.sqlite import _DB_LOCK, _connect


def upsert_session(session_id: str, *, session_date: str, mode: str, status: str, daily_bias: str | None = None) -> None:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        if daily_bias is not None:
            conn.execute(
                """
                INSERT INTO animesh_sessions (id, session_date, mode, status, daily_bias, created_at, updated_at)
                VALUES (:id, :session_date, :mode, :status, :daily_bias, :now, :now)
                ON CONFLICT(id) DO UPDATE SET
                    mode = excluded.mode,
                    status = excluded.status,
                    daily_bias = excluded.daily_bias,
                    updated_at = excluded.updated_at
                """,
                {"id": session_id, "session_date": session_date, "mode": mode, "status": status, "daily_bias": daily_bias, "now": now},
            )
        else:
            conn.execute(
                """
                INSERT INTO animesh_sessions (id, session_date, mode, status, created_at, updated_at)
                VALUES (:id, :session_date, :mode, :status, :now, :now)
                ON CONFLICT(id) DO UPDATE SET
                    mode = excluded.mode,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                {"id": session_id, "session_date": session_date, "mode": mode, "status": status, "now": now},
            )
        conn.commit()


def get_session(session_id: str) -> dict[str, Any] | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM animesh_sessions WHERE id = ?", (session_id,)).fetchone()
    return _session_from_row(row) if row else None


def list_sessions(limit: int = 30) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute("SELECT * FROM animesh_sessions ORDER BY session_date DESC LIMIT ?", (limit,)).fetchall()
    return [_session_from_row(row) for row in rows]


def record_trade_entry(session_id: str, side: str) -> None:
    """Increments the day's entry count for this side."""
    now = now_ist().isoformat(timespec="seconds")
    column = "pe_trades_count" if side == "PE" else "ce_trades_count"
    with _DB_LOCK, _connect() as conn:
        conn.execute(f"UPDATE animesh_sessions SET {column} = {column} + 1, updated_at = ? WHERE id = ?", (now, session_id))
        conn.commit()


def record_trade_result(session_id: str, side: str, *, was_sl: bool) -> None:
    """Updates the consecutive-SL streak for this side: increments on a stop
    loss, resets to 0 on any non-SL exit. Halts the side once the streak hits
    the configured max (checked by the caller, this just records the count).
    """
    now = now_ist().isoformat(timespec="seconds")
    streak_column = "pe_consecutive_sl" if side == "PE" else "ce_consecutive_sl"
    with _DB_LOCK, _connect() as conn:
        if was_sl:
            conn.execute(f"UPDATE animesh_sessions SET {streak_column} = {streak_column} + 1, updated_at = ? WHERE id = ?", (now, session_id))
        else:
            conn.execute(f"UPDATE animesh_sessions SET {streak_column} = 0, updated_at = ? WHERE id = ?", (now, session_id))
        conn.commit()


def set_side_halted(session_id: str, side: str, halted: bool) -> None:
    now = now_ist().isoformat(timespec="seconds")
    column = "pe_halted" if side == "PE" else "ce_halted"
    with _DB_LOCK, _connect() as conn:
        conn.execute(f"UPDATE animesh_sessions SET {column} = ?, updated_at = ? WHERE id = ?", (1 if halted else 0, now, session_id))
        conn.commit()


def record_signal(
    session_id: str,
    *,
    side: str,
    kind: str,
    status: str,
    strike: float | None = None,
    index_level: float | None = None,
    payload: dict[str, Any] | None = None,
) -> int:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO animesh_signals (session_id, side, kind, status, strike, index_level, payload_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, side, kind, status, strike, index_level, json.dumps(payload or {}, default=str), now, now),
        )
        conn.commit()
        return int(cursor.lastrowid)


def update_signal_status(signal_id: int, status: str, *, trade_id: str | None = None) -> None:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        if trade_id is not None:
            conn.execute(
                "UPDATE animesh_signals SET status = ?, trade_id = ?, updated_at = ? WHERE id = ?",
                (status, trade_id, now, signal_id),
            )
        else:
            conn.execute("UPDATE animesh_signals SET status = ?, updated_at = ? WHERE id = ?", (status, now, signal_id))
        conn.commit()


def get_signal(signal_id: int) -> dict[str, Any] | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM animesh_signals WHERE id = ?", (signal_id,)).fetchone()
    return _signal_from_row(row) if row else None


def get_signals_for_session(session_id: str) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute("SELECT * FROM animesh_signals WHERE session_id = ? ORDER BY created_at, id", (session_id,)).fetchall()
    return [_signal_from_row(row) for row in rows]


def get_pending_signals(session_id: str) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM animesh_signals WHERE session_id = ? AND status = 'PENDING' ORDER BY created_at, id", (session_id,)
        ).fetchall()
    return [_signal_from_row(row) for row in rows]


def insert_trade(
    trade_id: str,
    *,
    session_id: str,
    side: str,
    strike: float | None,
    security_id: str | None,
    exchange_segment: str | None,
    mode: str,
    entry_signal_id: int | None,
    entry_index_level: float,
    initial_sl: float,
    target1: float,
    target2: float,
    payload: dict[str, Any] | None = None,
) -> None:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO animesh_trades (
                id, session_id, side, strike, security_id, exchange_segment, mode, status,
                entry_signal_id, entry_index_level, initial_sl, target1, target2,
                phase, payload_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?, ?, ?, 'OPEN_ALL', ?, ?, ?)
            """,
            (
                trade_id, session_id, side, strike, security_id, exchange_segment, mode,
                entry_signal_id, entry_index_level, initial_sl, target1, target2,
                json.dumps(payload or {}, default=str), now, now,
            ),
        )
        conn.commit()


def record_entry_fill(trade_id: str, *, entry_premium: float, entry_qty: int) -> None:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            "UPDATE animesh_trades SET entry_premium = ?, entry_qty = ?, entry_at = ?, updated_at = ? WHERE id = ?",
            (entry_premium, entry_qty, now, now, trade_id),
        )
        conn.commit()


def update_trade_phase(trade_id: str, phase: str, *, lot3_trail_sl: float | None = None) -> None:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        if lot3_trail_sl is not None:
            conn.execute(
                "UPDATE animesh_trades SET phase = ?, lot3_trail_sl = ?, updated_at = ? WHERE id = ?",
                (phase, lot3_trail_sl, now, trade_id),
            )
        else:
            conn.execute("UPDATE animesh_trades SET phase = ?, updated_at = ? WHERE id = ?", (phase, now, trade_id))
        conn.commit()


def close_trade(trade_id: str, *, realized_pnl: float) -> None:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            "UPDATE animesh_trades SET status = 'CLOSED', realized_pnl = ?, updated_at = ? WHERE id = ?",
            (realized_pnl, now, trade_id),
        )
        conn.commit()


def get_trade(trade_id: str) -> dict[str, Any] | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM animesh_trades WHERE id = ?", (trade_id,)).fetchone()
    return _trade_from_row(row) if row else None


def get_open_trades(session_id: str) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute("SELECT * FROM animesh_trades WHERE session_id = ? AND status = 'OPEN' ORDER BY created_at", (session_id,)).fetchall()
    return [_trade_from_row(row) for row in rows]


def get_trades_for_session(session_id: str) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute("SELECT * FROM animesh_trades WHERE session_id = ? ORDER BY created_at", (session_id,)).fetchall()
    return [_trade_from_row(row) for row in rows]


def insert_trade_legs(trade_id: str, *, lot_count: int, qty_per_lot: int) -> None:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        for lot_number in range(1, lot_count + 1):
            conn.execute(
                """
                INSERT INTO animesh_trade_legs (trade_id, lot_number, qty, status, created_at, updated_at)
                VALUES (?, ?, ?, 'OPEN', ?, ?)
                """,
                (trade_id, lot_number, qty_per_lot, now, now),
            )
        conn.commit()


def close_trade_leg(trade_id: str, lot_number: int, *, exit_index_level: float, exit_premium: float, exit_reason: str, realized_pnl: float) -> None:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            UPDATE animesh_trade_legs
            SET status = 'CLOSED', exit_index_level = ?, exit_premium = ?, exit_at = ?, exit_reason = ?, realized_pnl = ?, updated_at = ?
            WHERE trade_id = ? AND lot_number = ?
            """,
            (exit_index_level, exit_premium, now, exit_reason, realized_pnl, now, trade_id, lot_number),
        )
        conn.commit()


def get_trade_legs(trade_id: str) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute("SELECT * FROM animesh_trade_legs WHERE trade_id = ? ORDER BY lot_number", (trade_id,)).fetchall()
    return [_leg_from_row(row) for row in rows]


def get_legs_for_trades(trade_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not trade_ids:
        return {}
    placeholders = ",".join("?" for _ in trade_ids)
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(f"SELECT * FROM animesh_trade_legs WHERE trade_id IN ({placeholders}) ORDER BY trade_id, lot_number", trade_ids).fetchall()
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        result.setdefault(row["trade_id"], []).append(_leg_from_row(row))
    return result


def record_event(session_id: str, event_type: str, message: str, payload: dict[str, Any] | None = None) -> None:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            "INSERT INTO animesh_events (session_id, event_type, message, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, event_type, message, json.dumps(payload or {}, default=str), now),
        )
        conn.commit()


def get_events_for_session(session_id: str, limit: int = 200) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM animesh_events WHERE session_id = ? ORDER BY created_at DESC, id DESC LIMIT ?", (session_id, limit)
        ).fetchall()
    events = [_event_from_row(row) for row in rows]
    events.reverse()
    return events


def _session_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "sessionDate": row["session_date"],
        "mode": row["mode"],
        "status": row["status"],
        "dailyBias": row["daily_bias"],
        "peTradesCount": row["pe_trades_count"],
        "peConsecutiveSl": row["pe_consecutive_sl"],
        "peHalted": bool(row["pe_halted"]),
        "ceTradesCount": row["ce_trades_count"],
        "ceConsecutiveSl": row["ce_consecutive_sl"],
        "ceHalted": bool(row["ce_halted"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _signal_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "sessionId": row["session_id"],
        "side": row["side"],
        "kind": row["kind"],
        "status": row["status"],
        "strike": row["strike"],
        "indexLevel": row["index_level"],
        "tradeId": row["trade_id"],
        "payload": _json(row["payload_json"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _trade_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "sessionId": row["session_id"],
        "side": row["side"],
        "strike": row["strike"],
        "securityId": row["security_id"],
        "exchangeSegment": row["exchange_segment"],
        "mode": row["mode"],
        "status": row["status"],
        "entrySignalId": row["entry_signal_id"],
        "entryIndexLevel": row["entry_index_level"],
        "entryPremium": row["entry_premium"],
        "entryQty": row["entry_qty"],
        "entryAt": row["entry_at"],
        "initialSl": row["initial_sl"],
        "target1": row["target1"],
        "target2": row["target2"],
        "phase": row["phase"],
        "lot3TrailSl": row["lot3_trail_sl"],
        "realizedPnl": row["realized_pnl"],
        "payload": _json(row["payload_json"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _leg_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "tradeId": row["trade_id"],
        "lotNumber": row["lot_number"],
        "qty": row["qty"],
        "status": row["status"],
        "exitIndexLevel": row["exit_index_level"],
        "exitPremium": row["exit_premium"],
        "exitAt": row["exit_at"],
        "exitReason": row["exit_reason"],
        "realizedPnl": row["realized_pnl"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
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
