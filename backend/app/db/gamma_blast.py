from __future__ import annotations

import json
from typing import Any

from app.db.sqlite import _DB_LOCK, _connect
from app.services.gamma_blast_engine import now_ist


def upsert_session(
    session_id: str,
    *,
    session_date: str,
    index_symbol: str,
    mode: str,
    status: str,
    spot_open: float | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO gamma_blast_sessions (
                id, session_date, index_symbol, mode, status, spot_open, payload_json, created_at, updated_at
            ) VALUES (:id, :session_date, :index_symbol, :mode, :status, :spot_open, :payload_json, :now, :now)
            ON CONFLICT(id) DO UPDATE SET
                mode = excluded.mode,
                status = excluded.status,
                spot_open = COALESCE(excluded.spot_open, gamma_blast_sessions.spot_open),
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """,
            {
                "id": session_id,
                "session_date": session_date,
                "index_symbol": index_symbol,
                "mode": mode,
                "status": status,
                "spot_open": spot_open,
                "payload_json": json.dumps(payload or {}, default=str),
                "now": now,
            },
        )
        conn.commit()


def get_session(session_id: str) -> dict[str, Any] | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM gamma_blast_sessions WHERE id = ?", (session_id,)).fetchone()
    return _session_from_row(row) if row else None


def list_sessions(limit: int = 30) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM gamma_blast_sessions ORDER BY session_date DESC, index_symbol LIMIT ?", (limit,)
        ).fetchall()
    return [_session_from_row(row) for row in rows]


def record_signal(
    session_id: str,
    *,
    index_symbol: str,
    kind: str,
    status: str,
    strike: float | None = None,
    option_side: str | None = None,
    trigger_price: float | None = None,
    level: float | None = None,
    payload: dict[str, Any] | None = None,
) -> int:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO gamma_blast_signals (
                session_id, index_symbol, kind, status, strike, option_side,
                trigger_price, level, payload_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                index_symbol,
                kind,
                status,
                strike,
                option_side,
                trigger_price,
                level,
                json.dumps(payload or {}, default=str),
                now,
                now,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)


def update_signal_status(signal_id: int, status: str, *, trade_id: str | None = None) -> None:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        if trade_id is not None:
            conn.execute(
                "UPDATE gamma_blast_signals SET status = ?, trade_id = ?, updated_at = ? WHERE id = ?",
                (status, trade_id, now, signal_id),
            )
        else:
            conn.execute(
                "UPDATE gamma_blast_signals SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, signal_id),
            )
        conn.commit()


def get_signal(signal_id: int) -> dict[str, Any] | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM gamma_blast_signals WHERE id = ?", (signal_id,)).fetchone()
    return _signal_from_row(row) if row else None


def get_signals_for_session(session_id: str) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM gamma_blast_signals WHERE session_id = ? ORDER BY created_at, id", (session_id,)
        ).fetchall()
    return [_signal_from_row(row) for row in rows]


def get_pending_signals(session_id: str) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM gamma_blast_signals WHERE session_id = ? AND status = 'PENDING' ORDER BY created_at, id",
            (session_id,),
        ).fetchall()
    return [_signal_from_row(row) for row in rows]


def insert_trade(
    trade_id: str,
    *,
    session_id: str,
    index_symbol: str,
    strike: float | None,
    option_side: str | None,
    security_id: str | None,
    exchange_segment: str | None,
    mode: str,
    entry_signal_id: int | None,
    payload: dict[str, Any] | None = None,
) -> None:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO gamma_blast_trades (
                id, session_id, index_symbol, strike, option_side, security_id, exchange_segment,
                mode, status, entry_signal_id, payload_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?, ?)
            """,
            (
                trade_id,
                session_id,
                index_symbol,
                strike,
                option_side,
                security_id,
                exchange_segment,
                mode,
                entry_signal_id,
                json.dumps(payload or {}, default=str),
                now,
                now,
            ),
        )
        conn.commit()


def record_entry_fill(trade_id: str, *, entry_price: float, entry_qty: int) -> None:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            "UPDATE gamma_blast_trades SET entry_price = ?, entry_qty = ?, entry_at = ?, updated_at = ? WHERE id = ?",
            (entry_price, entry_qty, now, now, trade_id),
        )
        conn.commit()


def record_exit_fill(
    trade_id: str, *, exit_price: float, exit_qty: int, exit_reason: str, realized_pnl: float
) -> None:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            UPDATE gamma_blast_trades
            SET exit_price = ?, exit_qty = ?, exit_at = ?, exit_reason = ?, realized_pnl = ?,
                status = 'CLOSED', updated_at = ?
            WHERE id = ?
            """,
            (exit_price, exit_qty, now, exit_reason, realized_pnl, now, trade_id),
        )
        conn.commit()


def get_trade(trade_id: str) -> dict[str, Any] | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM gamma_blast_trades WHERE id = ?", (trade_id,)).fetchone()
    return _trade_from_row(row) if row else None


def get_open_trades(session_id: str) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM gamma_blast_trades WHERE session_id = ? AND status = 'OPEN' ORDER BY created_at",
            (session_id,),
        ).fetchall()
    return [_trade_from_row(row) for row in rows]


def get_trades_for_session(session_id: str) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM gamma_blast_trades WHERE session_id = ? ORDER BY created_at", (session_id,)
        ).fetchall()
    return [_trade_from_row(row) for row in rows]


def record_event(session_id: str, event_type: str, message: str, payload: dict[str, Any] | None = None) -> None:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO gamma_blast_events (session_id, event_type, message, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, event_type, message, json.dumps(payload or {}, default=str), now),
        )
        conn.commit()


def get_events_for_session(session_id: str, limit: int = 200) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM gamma_blast_events WHERE session_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    events = [_event_from_row(row) for row in rows]
    events.reverse()
    return events


def save_retrospective(session_id: str, session_date: str, summary: str, payload: dict[str, Any] | None = None) -> None:
    now = now_ist().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO gamma_blast_retrospectives (session_id, session_date, summary, payload_json, created_at)
            VALUES (:session_id, :session_date, :summary, :payload_json, :now)
            ON CONFLICT(session_id) DO UPDATE SET
                summary = excluded.summary,
                payload_json = excluded.payload_json,
                created_at = excluded.created_at
            """,
            {
                "session_id": session_id,
                "session_date": session_date,
                "summary": summary,
                "payload_json": json.dumps(payload or {}, default=str),
                "now": now,
            },
        )
        conn.commit()


def get_retrospective(session_id: str) -> dict[str, Any] | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM gamma_blast_retrospectives WHERE session_id = ?", (session_id,)
        ).fetchone()
    if not row:
        return None
    return {
        "sessionId": row["session_id"],
        "sessionDate": row["session_date"],
        "summary": row["summary"],
        "payload": _json(row["payload_json"]),
        "createdAt": row["created_at"],
    }


def _session_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "sessionDate": row["session_date"],
        "indexSymbol": row["index_symbol"],
        "mode": row["mode"],
        "status": row["status"],
        "spotOpen": row["spot_open"],
        "payload": _json(row["payload_json"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _signal_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "sessionId": row["session_id"],
        "indexSymbol": row["index_symbol"],
        "kind": row["kind"],
        "status": row["status"],
        "strike": row["strike"],
        "optionSide": row["option_side"],
        "triggerPrice": row["trigger_price"],
        "level": row["level"],
        "tradeId": row["trade_id"],
        "payload": _json(row["payload_json"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _trade_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "sessionId": row["session_id"],
        "indexSymbol": row["index_symbol"],
        "strike": row["strike"],
        "optionSide": row["option_side"],
        "securityId": row["security_id"],
        "exchangeSegment": row["exchange_segment"],
        "mode": row["mode"],
        "status": row["status"],
        "entrySignalId": row["entry_signal_id"],
        "entryPrice": row["entry_price"],
        "entryQty": row["entry_qty"],
        "entryAt": row["entry_at"],
        "exitPrice": row["exit_price"],
        "exitQty": row["exit_qty"],
        "exitAt": row["exit_at"],
        "exitReason": row["exit_reason"],
        "realizedPnl": row["realized_pnl"],
        "payload": _json(row["payload_json"]),
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
