from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import get_settings


_DB_LOCK = threading.Lock()


def _db_path() -> Path:
    return Path(get_settings().database_file)


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trade_levels (
                trade_id TEXT PRIMARY KEY,
                symbol TEXT,
                expiry TEXT,
                strike_price REAL,
                option_side TEXT,
                stop_loss REAL,
                target REAL,
                notes TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trade_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id TEXT NOT NULL,
                action TEXT NOT NULL,
                status TEXT NOT NULL,
                request_json TEXT,
                response_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trade_journals (
                trade_date TEXT PRIMARY KEY,
                strategy_details TEXT NOT NULL DEFAULT '',
                lessons_learnt TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alert_events (
                alert_key TEXT PRIMARY KEY,
                payload_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def get_trade_levels(trade_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not trade_ids:
        return {}
    placeholders = ",".join("?" for _ in trade_ids)
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(f"SELECT * FROM trade_levels WHERE trade_id IN ({placeholders})", trade_ids).fetchall()
    return {str(row["trade_id"]): _level_from_row(row) for row in rows}


def has_configured_trade_levels() -> bool:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM trade_levels
            WHERE stop_loss IS NOT NULL OR target IS NOT NULL
            LIMIT 1
            """
        ).fetchone()
    return row is not None


def upsert_trade_levels(trade_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    normalized = {
        "trade_id": trade_id,
        "symbol": payload.get("symbol"),
        "expiry": payload.get("expiry"),
        "strike_price": _number(payload.get("strikePrice")),
        "option_side": payload.get("optionSide"),
        "stop_loss": _number(payload.get("stopLoss")),
        "target": _number(payload.get("target")),
        "notes": payload.get("notes") or "",
        "updated_at": now,
    }
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO trade_levels (
                trade_id, symbol, expiry, strike_price, option_side, stop_loss, target, notes, updated_at
            ) VALUES (
                :trade_id, :symbol, :expiry, :strike_price, :option_side, :stop_loss, :target, :notes, :updated_at
            )
            ON CONFLICT(trade_id) DO UPDATE SET
                symbol = excluded.symbol,
                expiry = excluded.expiry,
                strike_price = excluded.strike_price,
                option_side = excluded.option_side,
                stop_loss = excluded.stop_loss,
                target = excluded.target,
                notes = excluded.notes,
                updated_at = excluded.updated_at
            """,
            normalized,
        )
        conn.commit()
    return _level_from_mapping(normalized)


def record_trade_action(
    trade_id: str,
    action: str,
    status: str,
    request_payload: dict[str, Any] | None,
    response_payload: dict[str, Any] | None,
) -> None:
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO trade_actions (trade_id, action, status, request_json, response_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                trade_id,
                action,
                status,
                json.dumps(request_payload or {}, default=str),
                json.dumps(response_payload or {}, default=str),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()


def get_trade_actions(
    trade_ids: list[str],
    *,
    action_prefix: str | None = None,
    limit_per_trade: int = 20,
) -> dict[str, list[dict[str, Any]]]:
    if not trade_ids:
        return {}
    placeholders = ",".join("?" for _ in trade_ids)
    params: list[Any] = [*trade_ids]
    action_clause = ""
    if action_prefix:
        action_clause = " AND action LIKE ?"
        params.append(f"{action_prefix}%")
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM trade_actions
            WHERE trade_id IN ({placeholders}){action_clause}
            ORDER BY trade_id, created_at DESC, id DESC
            """,
            params,
        ).fetchall()

    actions_by_trade: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        trade_id = str(row["trade_id"])
        bucket = actions_by_trade.setdefault(trade_id, [])
        if len(bucket) < limit_per_trade:
            bucket.append(_action_from_row(row))
    return actions_by_trade


def get_journal(trade_date: str) -> dict[str, Any]:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM trade_journals WHERE trade_date = ?", (trade_date,)).fetchone()
    if not row:
        now = datetime.now().isoformat(timespec="seconds")
        return {
            "tradeDate": trade_date,
            "strategyDetails": "",
            "lessonsLearnt": "",
            "createdAt": now,
            "updatedAt": now,
        }
    return {
        "tradeDate": row["trade_date"],
        "strategyDetails": row["strategy_details"],
        "lessonsLearnt": row["lessons_learnt"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def save_journal(trade_date: str, strategy_details: str, lessons_learnt: str) -> dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    existing = get_journal(trade_date)
    created_at = existing.get("createdAt") or now
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO trade_journals (trade_date, strategy_details, lessons_learnt, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(trade_date) DO UPDATE SET
                strategy_details = excluded.strategy_details,
                lessons_learnt = excluded.lessons_learnt,
                updated_at = excluded.updated_at
            """,
            (trade_date, strategy_details, lessons_learnt, created_at, now),
        )
        conn.commit()
    return get_journal(trade_date)


def record_alert_once(alert_key: str, payload: dict[str, Any] | None = None) -> bool:
    try:
        with _DB_LOCK, _connect() as conn:
            conn.execute(
                "INSERT INTO alert_events (alert_key, payload_json, created_at) VALUES (?, ?, ?)",
                (
                    alert_key,
                    json.dumps(payload or {}, default=str),
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def _level_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return _level_from_mapping(dict(row))


def _level_from_mapping(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "tradeId": row.get("trade_id"),
        "symbol": row.get("symbol"),
        "expiry": row.get("expiry"),
        "strikePrice": row.get("strike_price"),
        "optionSide": row.get("option_side"),
        "stopLoss": row.get("stop_loss"),
        "target": row.get("target"),
        "notes": row.get("notes") or "",
        "updatedAt": row.get("updated_at"),
    }


def _action_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "tradeId": row["trade_id"],
        "action": row["action"],
        "status": row["status"],
        "request": _json(row["request_json"]),
        "response": _json(row["response_json"]),
        "createdAt": row["created_at"],
    }


def _json(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float | None:
    if value in (None, "", "NA", "NaN"):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
