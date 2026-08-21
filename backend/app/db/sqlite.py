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


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


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
        _add_column_if_missing(conn, "trade_levels", "tag", "TEXT")
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
        _add_column_if_missing(conn, "trade_journals", "how_i_felt", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, "trade_journals", "what_happened", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, "trade_journals", "comments", "TEXT NOT NULL DEFAULT ''")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_trade_summary (
                trade_date TEXT PRIMARY KEY,
                trades_count INTEGER NOT NULL DEFAULT 0,
                day_pnl REAL,
                net_pnl REAL,
                realized_pnl REAL,
                charges REAL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS journal_insights (
                id TEXT PRIMARY KEY,
                bullets_json TEXT NOT NULL,
                generated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS market_news (
                id TEXT PRIMARY KEY,
                items_json TEXT NOT NULL,
                generated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS market_calendar (
                id TEXT PRIMARY KEY,
                items_json TEXT NOT NULL,
                generated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pcr_oi_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_date TEXT NOT NULL,
                underlying TEXT NOT NULL,
                epoch INTEGER NOT NULL,
                captured_at TEXT NOT NULL,
                spot REAL,
                pcr REAL,
                ce_oi INTEGER,
                pe_oi INTEGER,
                ce_oi_change INTEGER,
                pe_oi_change INTEGER
            )
            """
        )
        _add_column_if_missing(conn, "pcr_oi_snapshots", "atm_strike", "REAL")
        _add_column_if_missing(conn, "pcr_oi_snapshots", "ce_premium", "REAL")
        _add_column_if_missing(conn, "pcr_oi_snapshots", "ce_iv", "REAL")
        _add_column_if_missing(conn, "pcr_oi_snapshots", "ce_delta", "REAL")
        _add_column_if_missing(conn, "pcr_oi_snapshots", "ce_vega", "REAL")
        _add_column_if_missing(conn, "pcr_oi_snapshots", "pe_premium", "REAL")
        _add_column_if_missing(conn, "pcr_oi_snapshots", "pe_iv", "REAL")
        _add_column_if_missing(conn, "pcr_oi_snapshots", "pe_delta", "REAL")
        _add_column_if_missing(conn, "pcr_oi_snapshots", "pe_vega", "REAL")
        _add_column_if_missing(conn, "pcr_oi_snapshots", "india_vix", "REAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alert_events (
                alert_key TEXT PRIMARY KEY,
                payload_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS gamma_blast_sessions (
                id TEXT PRIMARY KEY,
                session_date TEXT NOT NULL,
                index_symbol TEXT NOT NULL,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                spot_open REAL,
                payload_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS gamma_blast_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                index_symbol TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                strike REAL,
                option_side TEXT,
                trigger_price REAL,
                level REAL,
                trade_id TEXT,
                payload_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS gamma_blast_trades (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                index_symbol TEXT NOT NULL,
                strike REAL,
                option_side TEXT,
                security_id TEXT,
                exchange_segment TEXT,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                entry_signal_id INTEGER,
                entry_price REAL,
                entry_qty INTEGER,
                entry_at TEXT,
                exit_price REAL,
                exit_qty INTEGER,
                exit_at TEXT,
                exit_reason TEXT,
                realized_pnl REAL,
                payload_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS gamma_blast_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                payload_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS gamma_blast_retrospectives (
                session_id TEXT PRIMARY KEY,
                session_date TEXT NOT NULL,
                summary TEXT,
                payload_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ema5_sessions (
                id TEXT PRIMARY KEY,
                session_date TEXT NOT NULL,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                pe_trades_count INTEGER NOT NULL DEFAULT 0,
                pe_consecutive_sl INTEGER NOT NULL DEFAULT 0,
                pe_halted INTEGER NOT NULL DEFAULT 0,
                ce_trades_count INTEGER NOT NULL DEFAULT 0,
                ce_consecutive_sl INTEGER NOT NULL DEFAULT 0,
                ce_halted INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ema5_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                side TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                strike REAL,
                index_level REAL,
                trade_id TEXT,
                payload_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ema5_trades (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                side TEXT NOT NULL,
                strike REAL,
                security_id TEXT,
                exchange_segment TEXT,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                entry_signal_id INTEGER,
                entry_index_level REAL,
                entry_premium REAL,
                entry_qty INTEGER,
                entry_at TEXT,
                initial_sl REAL,
                target1 REAL,
                target2 REAL,
                target3 REAL,
                phase TEXT NOT NULL DEFAULT 'OPEN_ALL',
                lot3_trail_sl REAL,
                realized_pnl REAL,
                payload_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ema5_trade_legs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id TEXT NOT NULL,
                lot_number INTEGER NOT NULL,
                qty INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'OPEN',
                exit_index_level REAL,
                exit_premium REAL,
                exit_at TEXT,
                exit_reason TEXT,
                realized_pnl REAL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ema5_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                payload_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ema5_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS animesh_sessions (
                id TEXT PRIMARY KEY,
                session_date TEXT NOT NULL,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                daily_bias TEXT,
                pe_trades_count INTEGER NOT NULL DEFAULT 0,
                pe_consecutive_sl INTEGER NOT NULL DEFAULT 0,
                pe_halted INTEGER NOT NULL DEFAULT 0,
                ce_trades_count INTEGER NOT NULL DEFAULT 0,
                ce_consecutive_sl INTEGER NOT NULL DEFAULT 0,
                ce_halted INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS animesh_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                side TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                strike REAL,
                index_level REAL,
                trade_id TEXT,
                payload_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS animesh_trades (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                side TEXT NOT NULL,
                strike REAL,
                security_id TEXT,
                exchange_segment TEXT,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                entry_signal_id INTEGER,
                entry_index_level REAL,
                entry_premium REAL,
                entry_qty INTEGER,
                entry_at TEXT,
                initial_sl REAL,
                target1 REAL,
                target2 REAL,
                phase TEXT NOT NULL DEFAULT 'OPEN_ALL',
                lot3_trail_sl REAL,
                realized_pnl REAL,
                payload_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS animesh_trade_legs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id TEXT NOT NULL,
                lot_number INTEGER NOT NULL,
                qty INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'OPEN',
                exit_index_level REAL,
                exit_premium REAL,
                exit_at TEXT,
                exit_reason TEXT,
                realized_pnl REAL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS animesh_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                payload_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS theta_sessions (
                id TEXT PRIMARY KEY,
                session_date TEXT NOT NULL,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                nifty_day_type TEXT,
                sensex_day_type TEXT,
                realized_pnl REAL NOT NULL DEFAULT 0,
                halted INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS theta_positions (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                underlying TEXT NOT NULL,
                side TEXT NOT NULL,
                strike REAL NOT NULL,
                expiry TEXT NOT NULL,
                security_id TEXT,
                exchange_segment TEXT,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                day_type TEXT,
                tranche_count INTEGER NOT NULL DEFAULT 0,
                total_qty INTEGER NOT NULL DEFAULT 0,
                avg_entry_premium REAL,
                entry_spot REAL,
                estimated_margin REAL,
                realized_pnl REAL,
                close_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                closed_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS theta_tranches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                position_id TEXT NOT NULL,
                qty INTEGER NOT NULL,
                premium REAL NOT NULL,
                spot_at_entry REAL,
                distance_pct_at_entry REAL,
                day_type TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS theta_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                underlying TEXT NOT NULL,
                side TEXT NOT NULL,
                strike REAL,
                expiry TEXT,
                position_id TEXT,
                payload_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS theta_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                payload_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS theta_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS credit_spread_positions (
                id TEXT PRIMARY KEY,
                expiry TEXT NOT NULL,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                qty INTEGER NOT NULL,
                sell_strike REAL NOT NULL,
                sell_security_id TEXT NOT NULL,
                sell_entry_price REAL NOT NULL,
                hedge_strike REAL,
                hedge_security_id TEXT,
                hedge_entry_price REAL,
                net_credit REAL NOT NULL,
                entry_spot REAL,
                entry_synthetic_future REAL,
                entry_vix REAL,
                planned_exit_date TEXT,
                entry_signal_id INTEGER,
                entry_at TEXT NOT NULL,
                sell_exit_price REAL,
                hedge_exit_price REAL,
                exit_reason TEXT,
                realized_pnl REAL,
                exit_at TEXT,
                payload_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS credit_spread_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                position_id TEXT,
                payload_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS credit_spread_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                position_id TEXT,
                payload_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS credit_spread_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                underlying TEXT NOT NULL,
                side TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                strike REAL,
                expiry TEXT,
                security_id TEXT,
                exchange_segment TEXT,
                entry_time INTEGER NOT NULL,
                entry_premium REAL NOT NULL,
                lots INTEGER NOT NULL,
                lot_size INTEGER NOT NULL,
                stop_loss_percent REAL NOT NULL,
                target1_percent REAL NOT NULL,
                target2_percent REAL NOT NULL,
                trail_percent REAL NOT NULL,
                stop_loss_price REAL NOT NULL,
                target1_price REAL NOT NULL,
                target2_price REAL NOT NULL,
                phase TEXT NOT NULL DEFAULT 'OPEN_ALL',
                peak_premium REAL,
                remaining_lots INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                realized_pnl REAL NOT NULL DEFAULT 0,
                closed_at INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_trade_legs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER NOT NULL,
                lot_number INTEGER NOT NULL,
                qty INTEGER NOT NULL,
                exit_time INTEGER NOT NULL,
                exit_premium REAL NOT NULL,
                exit_reason TEXT NOT NULL,
                pnl_points REAL NOT NULL,
                pnl_amount REAL NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_trading_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS oi_upgraded_signal_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_date TEXT NOT NULL,
                epoch INTEGER NOT NULL,
                state TEXT NOT NULL,
                signal TEXT NOT NULL,
                regime TEXT NOT NULL,
                pcr REAL,
                ce_score INTEGER NOT NULL,
                pe_score INTEGER NOT NULL,
                persistence INTEGER NOT NULL,
                nifty_price REAL,
                vwap REAL,
                ce_premium REAL,
                pe_premium REAL,
                created_at TEXT NOT NULL,
                UNIQUE(session_date, epoch)
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
        "tag": (payload.get("tag") or "").strip() or None,
        "updated_at": now,
    }
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO trade_levels (
                trade_id, symbol, expiry, strike_price, option_side, stop_loss, target, notes, tag, updated_at
            ) VALUES (
                :trade_id, :symbol, :expiry, :strike_price, :option_side, :stop_loss, :target, :notes, :tag, :updated_at
            )
            ON CONFLICT(trade_id) DO UPDATE SET
                symbol = excluded.symbol,
                expiry = excluded.expiry,
                strike_price = excluded.strike_price,
                option_side = excluded.option_side,
                stop_loss = excluded.stop_loss,
                target = excluded.target,
                notes = excluded.notes,
                tag = excluded.tag,
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
            "howIFelt": "",
            "whatHappened": "",
            "lessonsLearnt": "",
            "comments": "",
            "createdAt": now,
            "updatedAt": now,
        }
    return _journal_from_row(row)


def save_journal(
    trade_date: str,
    *,
    strategy_details: str,
    how_i_felt: str,
    what_happened: str,
    lessons_learnt: str,
    comments: str,
) -> dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    existing = get_journal(trade_date)
    created_at = existing.get("createdAt") or now
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO trade_journals (
                trade_date, strategy_details, how_i_felt, what_happened, lessons_learnt, comments, created_at, updated_at
            ) VALUES (:trade_date, :strategy_details, :how_i_felt, :what_happened, :lessons_learnt, :comments, :created_at, :now)
            ON CONFLICT(trade_date) DO UPDATE SET
                strategy_details = excluded.strategy_details,
                how_i_felt = excluded.how_i_felt,
                what_happened = excluded.what_happened,
                lessons_learnt = excluded.lessons_learnt,
                comments = excluded.comments,
                updated_at = excluded.updated_at
            """,
            {
                "trade_date": trade_date,
                "strategy_details": strategy_details,
                "how_i_felt": how_i_felt,
                "what_happened": what_happened,
                "lessons_learnt": lessons_learnt,
                "comments": comments,
                "created_at": created_at,
                "now": now,
            },
        )
        conn.commit()
    return get_journal(trade_date)


def get_journals_for_dates(trade_dates: list[str]) -> dict[str, dict[str, Any]]:
    if not trade_dates:
        return {}
    placeholders = ",".join("?" for _ in trade_dates)
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(f"SELECT * FROM trade_journals WHERE trade_date IN ({placeholders})", trade_dates).fetchall()
    return {row["trade_date"]: _journal_from_row(row) for row in rows}


def get_journals_with_content(limit: int = 200) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM trade_journals
            WHERE strategy_details != '' OR how_i_felt != '' OR what_happened != '' OR lessons_learnt != '' OR comments != ''
            ORDER BY trade_date DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_journal_from_row(row) for row in rows]


def _journal_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "tradeDate": row["trade_date"],
        "strategyDetails": row["strategy_details"],
        "howIFelt": row["how_i_felt"],
        "whatHappened": row["what_happened"],
        "lessonsLearnt": row["lessons_learnt"],
        "comments": row["comments"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def record_daily_trade_summary(
    trade_date: str, *, trades_count: int, day_pnl: float | None, net_pnl: float | None, realized_pnl: float | None, charges: float | None
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO daily_trade_summary (
                trade_date, trades_count, day_pnl, net_pnl, realized_pnl, charges, created_at, updated_at
            ) VALUES (:trade_date, :trades_count, :day_pnl, :net_pnl, :realized_pnl, :charges, :now, :now)
            ON CONFLICT(trade_date) DO UPDATE SET
                trades_count = excluded.trades_count,
                day_pnl = excluded.day_pnl,
                net_pnl = excluded.net_pnl,
                realized_pnl = excluded.realized_pnl,
                charges = excluded.charges,
                updated_at = excluded.updated_at
            """,
            {
                "trade_date": trade_date,
                "trades_count": trades_count,
                "day_pnl": day_pnl,
                "net_pnl": net_pnl,
                "realized_pnl": realized_pnl,
                "charges": charges,
                "now": now,
            },
        )
        conn.commit()


def get_daily_trade_summaries(trade_dates: list[str]) -> dict[str, dict[str, Any]]:
    if not trade_dates:
        return {}
    placeholders = ",".join("?" for _ in trade_dates)
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM daily_trade_summary WHERE trade_date IN ({placeholders})", trade_dates
        ).fetchall()
    return {
        row["trade_date"]: {
            "tradeDate": row["trade_date"],
            "tradesCount": row["trades_count"],
            "dayPnl": row["day_pnl"],
            "netPnl": row["net_pnl"],
            "realizedPnl": row["realized_pnl"],
            "charges": row["charges"],
            "updatedAt": row["updated_at"],
        }
        for row in rows
    }


def save_journal_insights(bullets: list[str]) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO journal_insights (id, bullets_json, generated_at)
            VALUES ('latest', :bullets_json, :now)
            ON CONFLICT(id) DO UPDATE SET
                bullets_json = excluded.bullets_json,
                generated_at = excluded.generated_at
            """,
            {"bullets_json": json.dumps(bullets), "now": now},
        )
        conn.commit()


def get_journal_insights() -> dict[str, Any] | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM journal_insights WHERE id = 'latest'").fetchone()
    if not row:
        return None
    return {"bullets": _json(row["bullets_json"]) or [], "generatedAt": row["generated_at"]}


def save_market_news(items: list[dict[str, Any]]) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO market_news (id, items_json, generated_at)
            VALUES ('latest', :items_json, :now)
            ON CONFLICT(id) DO UPDATE SET
                items_json = excluded.items_json,
                generated_at = excluded.generated_at
            """,
            {"items_json": json.dumps(items), "now": now},
        )
        conn.commit()


def get_market_news() -> dict[str, Any] | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM market_news WHERE id = 'latest'").fetchone()
    if not row:
        return None
    return {"items": _json(row["items_json"]) or [], "generatedAt": row["generated_at"]}


def save_market_calendar(items: list[dict[str, Any]]) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO market_calendar (id, items_json, generated_at)
            VALUES ('latest', :items_json, :now)
            ON CONFLICT(id) DO UPDATE SET
                items_json = excluded.items_json,
                generated_at = excluded.generated_at
            """,
            {"items_json": json.dumps(items), "now": now},
        )
        conn.commit()


def get_market_calendar() -> dict[str, Any] | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM market_calendar WHERE id = 'latest'").fetchone()
    if not row:
        return None
    return {"items": _json(row["items_json"]) or [], "generatedAt": row["generated_at"]}


def record_pcr_oi_snapshot(
    *,
    session_date: str,
    underlying: str,
    epoch: int,
    spot: float | None,
    pcr: float | None,
    ce_oi: int | None,
    pe_oi: int | None,
    ce_oi_change: int | None,
    pe_oi_change: int | None,
    atm_strike: float | None = None,
    ce_premium: float | None = None,
    ce_iv: float | None = None,
    ce_delta: float | None = None,
    ce_vega: float | None = None,
    pe_premium: float | None = None,
    pe_iv: float | None = None,
    pe_delta: float | None = None,
    pe_vega: float | None = None,
    india_vix: float | None = None,
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO pcr_oi_snapshots (
                session_date, underlying, epoch, captured_at, spot, pcr, ce_oi, pe_oi, ce_oi_change, pe_oi_change,
                atm_strike, ce_premium, ce_iv, ce_delta, ce_vega, pe_premium, pe_iv, pe_delta, pe_vega, india_vix
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_date, underlying, epoch, now, spot, pcr, ce_oi, pe_oi, ce_oi_change, pe_oi_change,
                atm_strike, ce_premium, ce_iv, ce_delta, ce_vega, pe_premium, pe_iv, pe_delta, pe_vega, india_vix,
            ),
        )
        conn.commit()


def get_pcr_oi_session_dates() -> list[str]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT session_date FROM pcr_oi_snapshots ORDER BY session_date DESC"
        ).fetchall()
    return [row["session_date"] for row in rows]


def get_pcr_oi_snapshots(session_date: str) -> dict[str, list[dict[str, Any]]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM pcr_oi_snapshots WHERE session_date = ? ORDER BY underlying, epoch", (session_date,)
        ).fetchall()
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        result.setdefault(row["underlying"], []).append(
            {
                "time": row["epoch"],
                "spot": row["spot"],
                "pcr": row["pcr"],
                "ceOi": row["ce_oi"],
                "peOi": row["pe_oi"],
                "ceOiChange": row["ce_oi_change"],
                "peOiChange": row["pe_oi_change"],
                "atmStrike": row["atm_strike"],
                "cePremium": row["ce_premium"],
                "ceIv": row["ce_iv"],
                "ceDelta": row["ce_delta"],
                "ceVega": row["ce_vega"],
                "pePremium": row["pe_premium"],
                "peIv": row["pe_iv"],
                "peDelta": row["pe_delta"],
                "peVega": row["pe_vega"],
                "indiaVix": row["india_vix"],
            }
        )
    return result


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
        "tag": row.get("tag"),
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


PAPER_TRADING_SETTINGS_DEFAULTS: dict[str, str] = {
    "stopLossPercent": "15",
    "target1Percent": "10",
    "target2Percent": "20",
    "trailPercent": "5",
    "niftyLots": "3",
    "niftyLotSize": "65",
    "sensexLots": "3",
    "sensexLotSize": "20",
}


def get_paper_trading_settings() -> dict[str, float]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute("SELECT key, value FROM paper_trading_settings").fetchall()
    stored = {row["key"]: row["value"] for row in rows}
    merged = {**PAPER_TRADING_SETTINGS_DEFAULTS, **stored}
    return {key: float(value) for key, value in merged.items()}


def save_paper_trading_settings(values: dict[str, Any]) -> dict[str, float]:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        for key, value in values.items():
            if key not in PAPER_TRADING_SETTINGS_DEFAULTS or value is None:
                continue
            conn.execute(
                """
                INSERT INTO paper_trading_settings (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, str(value), now),
            )
        conn.commit()
    return get_paper_trading_settings()


def create_paper_trade(
    *,
    underlying: str,
    side: str,
    signal_type: str,
    strike: float | None,
    expiry: str | None,
    security_id: str | None,
    exchange_segment: str | None,
    entry_time: int,
    entry_premium: float,
    lots: int,
    lot_size: int,
    stop_loss_percent: float,
    target1_percent: float,
    target2_percent: float,
    trail_percent: float,
    stop_loss_price: float,
    target1_price: float,
    target2_price: float,
) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO paper_trades (
                underlying, side, signal_type, strike, expiry, security_id, exchange_segment,
                entry_time, entry_premium, lots, lot_size,
                stop_loss_percent, target1_percent, target2_percent, trail_percent,
                stop_loss_price, target1_price, target2_price,
                phase, peak_premium, remaining_lots, status, realized_pnl,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN_ALL', NULL, ?, 'open', 0, ?, ?)
            """,
            (
                underlying,
                side,
                signal_type,
                strike,
                expiry,
                security_id,
                exchange_segment,
                entry_time,
                entry_premium,
                lots,
                lot_size,
                stop_loss_percent,
                target1_percent,
                target2_percent,
                trail_percent,
                stop_loss_price,
                target1_price,
                target2_price,
                lots,
                now,
                now,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def get_open_paper_trade(underlying: str, signal_type: str) -> dict[str, Any] | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM paper_trades WHERE underlying = ? AND signal_type = ? AND status = 'open' ORDER BY id DESC LIMIT 1",
            (underlying, signal_type),
        ).fetchone()
    return _paper_trade_from_row(row) if row else None


def list_open_paper_trades() -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute("SELECT * FROM paper_trades WHERE status = 'open'").fetchall()
    return [_paper_trade_from_row(row) for row in rows]


def update_paper_trade_progress(trade_id: int, *, phase: str, peak_premium: float | None, remaining_lots: int) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            "UPDATE paper_trades SET phase = ?, peak_premium = ?, remaining_lots = ?, updated_at = ? WHERE id = ?",
            (phase, peak_premium, remaining_lots, now, trade_id),
        )
        conn.commit()


def add_paper_trade_leg(
    trade_id: int,
    *,
    lot_number: int,
    qty: int,
    exit_time: int,
    exit_premium: float,
    exit_reason: str,
    pnl_points: float,
    pnl_amount: float,
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO paper_trade_legs
                (trade_id, lot_number, qty, exit_time, exit_premium, exit_reason, pnl_points, pnl_amount, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (trade_id, lot_number, qty, exit_time, exit_premium, exit_reason, pnl_points, pnl_amount, now),
        )
        conn.commit()


def close_paper_trade(trade_id: int, *, closed_at: int, realized_pnl: float) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            "UPDATE paper_trades SET status = 'closed', closed_at = ?, realized_pnl = ?, remaining_lots = 0, updated_at = ? WHERE id = ?",
            (closed_at, realized_pnl, now, trade_id),
        )
        conn.commit()


def get_paper_trade_legs(trade_id: int) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM paper_trade_legs WHERE trade_id = ? ORDER BY exit_time ASC", (trade_id,)
        ).fetchall()
    return [_paper_trade_leg_from_row(row) for row in rows]


def list_paper_trades() -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        trade_rows = conn.execute("SELECT * FROM paper_trades ORDER BY entry_time DESC").fetchall()
        trades = [_paper_trade_from_row(row) for row in trade_rows]
        if not trades:
            return trades
        ids = [t["id"] for t in trades]
        placeholders = ",".join("?" for _ in ids)
        leg_rows = conn.execute(
            f"SELECT * FROM paper_trade_legs WHERE trade_id IN ({placeholders}) ORDER BY exit_time ASC", ids
        ).fetchall()
    legs_by_trade: dict[int, list[dict[str, Any]]] = {}
    for row in leg_rows:
        legs_by_trade.setdefault(row["trade_id"], []).append(_paper_trade_leg_from_row(row))
    for trade in trades:
        trade["legs"] = legs_by_trade.get(trade["id"], [])
    return trades


def _paper_trade_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "underlying": row["underlying"],
        "side": row["side"],
        "signalType": row["signal_type"],
        "strike": row["strike"],
        "expiry": row["expiry"],
        "securityId": row["security_id"],
        "exchangeSegment": row["exchange_segment"],
        "entryTime": row["entry_time"],
        "entryPremium": row["entry_premium"],
        "lots": row["lots"],
        "lotSize": row["lot_size"],
        "stopLossPercent": row["stop_loss_percent"],
        "target1Percent": row["target1_percent"],
        "target2Percent": row["target2_percent"],
        "trailPercent": row["trail_percent"],
        "stopLossPrice": row["stop_loss_price"],
        "target1Price": row["target1_price"],
        "target2Price": row["target2_price"],
        "phase": row["phase"],
        "peakPremium": row["peak_premium"],
        "remainingLots": row["remaining_lots"],
        "status": row["status"],
        "realizedPnl": row["realized_pnl"],
        "closedAt": row["closed_at"],
        "createdAt": row["created_at"],
    }


def _paper_trade_leg_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "tradeId": row["trade_id"],
        "lotNumber": row["lot_number"],
        "qty": row["qty"],
        "exitTime": row["exit_time"],
        "exitPremium": row["exit_premium"],
        "exitReason": row["exit_reason"],
        "pnlPoints": row["pnl_points"],
        "pnlAmount": row["pnl_amount"],
    }


def record_oi_upgraded_signal(
    *,
    session_date: str,
    epoch: int,
    state: str,
    signal: str,
    regime: str,
    pcr: float | None,
    ce_score: int,
    pe_score: int,
    persistence: int,
    nifty_price: float | None,
    vwap: float | None,
    ce_premium: float | None,
    pe_premium: float | None,
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO oi_upgraded_signal_log (
                session_date, epoch, state, signal, regime, pcr, ce_score, pe_score,
                persistence, nifty_price, vwap, ce_premium, pe_premium, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_date, epoch, state, signal, regime, pcr, ce_score, pe_score, persistence, nifty_price, vwap, ce_premium, pe_premium, now),
        )
        conn.commit()


def get_oi_upgraded_signal_log(session_date: str) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM oi_upgraded_signal_log WHERE session_date = ? ORDER BY epoch", (session_date,)
        ).fetchall()
    return [
        {
            "time": row["epoch"],
            "state": row["state"],
            "signal": row["signal"],
            "regime": row["regime"],
            "pcr": row["pcr"],
            "ceScore": row["ce_score"],
            "peScore": row["pe_score"],
            "persistence": row["persistence"],
            "niftyPrice": row["nifty_price"],
            "vwap": row["vwap"],
            "cePremium": row["ce_premium"],
            "pePremium": row["pe_premium"],
        }
        for row in rows
    ]
