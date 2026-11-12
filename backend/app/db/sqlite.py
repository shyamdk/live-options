from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
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
        # % target of the leg's premium; target_auto=1 closes that leg automatically when hit
        _add_column_if_missing(conn, "trade_levels", "target_percent", "REAL")
        _add_column_if_missing(conn, "trade_levels", "target_auto", "INTEGER NOT NULL DEFAULT 0")
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
        # Bid/ask for the ATM strike -- needed by PE-CE Crossover's spread
        # gate (pe_ce_filters.py); Dhan's option chain already returns these
        # per-strike (top_bid_price/top_ask_price), just wasn't captured here.
        _add_column_if_missing(conn, "pcr_oi_snapshots", "ce_bid", "REAL")
        _add_column_if_missing(conn, "pcr_oi_snapshots", "ce_ask", "REAL")
        _add_column_if_missing(conn, "pcr_oi_snapshots", "pe_bid", "REAL")
        _add_column_if_missing(conn, "pcr_oi_snapshots", "pe_ask", "REAL")
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
            CREATE TABLE IF NOT EXISTS pstrategy_nifty_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                resolution TEXT NOT NULL,
                side TEXT NOT NULL,
                strike REAL NOT NULL,
                expiry TEXT NOT NULL,
                security_id TEXT NOT NULL,
                exchange_segment TEXT NOT NULL,
                lots INTEGER NOT NULL,
                lot_size INTEGER NOT NULL,
                entry_time INTEGER NOT NULL,
                entry_premium REAL NOT NULL,
                entry_underlying_price REAL NOT NULL,
                stop_loss_percent REAL NOT NULL,
                peak_premium REAL,
                best_underlying_close REAL NOT NULL,
                trail_stop_underlying REAL,
                status TEXT NOT NULL DEFAULT 'open',
                exit_time INTEGER,
                exit_premium REAL,
                exit_reason TEXT,
                realized_pnl REAL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        # Entry-time invalidation level (the opposite boundary of the box the
        # breakout came from) -- active from the first tick, unlike the ATR
        # trail which only arms once favorable. Added after a real XAUTUSD
        # short lost -11.66% net with no price-based protection at all
        # before the trail armed; see check_ema_trail_exit's docstring.
        _add_column_if_missing(conn, "pstrategy_nifty_trades", "hard_stop_underlying", "REAL")
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pe_ce_crossover_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                underlying TEXT NOT NULL,
                side TEXT NOT NULL,
                strike REAL NOT NULL,
                expiry TEXT NOT NULL,
                dte INTEGER,
                security_id TEXT NOT NULL,
                exchange_segment TEXT NOT NULL,
                lots INTEGER NOT NULL,
                lot_size INTEGER NOT NULL,
                entry_time INTEGER NOT NULL,
                entry_premium REAL NOT NULL,
                stop_loss_percent REAL NOT NULL,
                target_percent REAL NOT NULL,
                peak_premium REAL,
                trail_stop_premium REAL,
                status TEXT NOT NULL DEFAULT 'open',
                exit_time INTEGER,
                exit_premium REAL,
                exit_reason TEXT,
                realized_pnl REAL,
                charges REAL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        # Phase 2 broker integration: mode distinguishes paper (Phase 1,
        # default for every pre-existing row)/shadow/live trades so guardrail
        # accounting and reporting can be scoped per mode. order_id/note carry
        # the Dhan order reference or a shadow "would have..." note.
        _add_column_if_missing(conn, "pe_ce_crossover_trades", "mode", "TEXT NOT NULL DEFAULT 'paper'")
        _add_column_if_missing(conn, "pe_ce_crossover_trades", "entry_order_id", "TEXT")
        _add_column_if_missing(conn, "pe_ce_crossover_trades", "exit_order_id", "TEXT")
        _add_column_if_missing(conn, "pe_ce_crossover_trades", "note", "TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pe_ce_crossover_signal_log (
                -- rsi/adx (informational only, not a gating filter) added
                -- via _add_column_if_missing below
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_date TEXT NOT NULL,
                epoch INTEGER NOT NULL,
                underlying TEXT NOT NULL,
                side TEXT NOT NULL,
                state TEXT NOT NULL,
                blocked_reason TEXT,
                ema_fast REAL,
                ema_slow REAL,
                premium REAL,
                premium_expansion_percent REAL,
                spread_percent REAL,
                created_at TEXT NOT NULL,
                UNIQUE(session_date, epoch, underlying, side)
            )
            """
        )
        _add_column_if_missing(conn, "pe_ce_crossover_signal_log", "rsi", "REAL")
        _add_column_if_missing(conn, "pe_ce_crossover_signal_log", "adx", "REAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pe_ce_crossover_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS simple_crossover_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                underlying TEXT NOT NULL,
                side TEXT NOT NULL,
                strike REAL NOT NULL,
                expiry TEXT NOT NULL,
                security_id TEXT NOT NULL,
                exchange_segment TEXT NOT NULL,
                lots INTEGER NOT NULL,
                lot_size INTEGER NOT NULL,
                entry_time INTEGER NOT NULL,
                entry_premium REAL NOT NULL,
                entry_ema_gap REAL,
                entry_pcr REAL,
                entry_ce_oi_change INTEGER,
                entry_pe_oi_change INTEGER,
                day_direction TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                current_premium REAL,
                remaining_lots INTEGER NOT NULL DEFAULT 0,
                target1_hit INTEGER NOT NULL DEFAULT 0,
                target2_hit INTEGER NOT NULL DEFAULT 0,
                peak_premium REAL,
                trailing_stop_price REAL,
                exit_time INTEGER,
                exit_premium REAL,
                exit_reason TEXT,
                realized_pnl REAL,
                comment TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        _add_column_if_missing(conn, "simple_crossover_trades", "remaining_lots", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "simple_crossover_trades", "target1_hit", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "simple_crossover_trades", "target2_hit", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "simple_crossover_trades", "peak_premium", "REAL")
        _add_column_if_missing(conn, "simple_crossover_trades", "trailing_stop_price", "REAL")
        _add_column_if_missing(conn, "simple_crossover_trades", "timeframe_minutes", "INTEGER NOT NULL DEFAULT 1")
        # The crossover candle that triggered the entry: its start time, close,
        # and whether that close came from Dhan's candle or the live price.
        _add_column_if_missing(conn, "simple_crossover_trades", "signal_time", "INTEGER")
        _add_column_if_missing(conn, "simple_crossover_trades", "signal_close", "REAL")
        _add_column_if_missing(conn, "simple_crossover_trades", "signal_source", "TEXT")
        # Plain cross over: entry on the cross-over, exit only on the
        # cross-under (or the 15:30 square-off) -- no stop or targets.
        _add_column_if_missing(conn, "simple_crossover_trades", "plain_crossover", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "simple_crossover_trades", "plain_target_percent", "REAL")
        # Minimum EMA gap (% of premium) a cross needed when the trade entered.
        _add_column_if_missing(conn, "simple_crossover_trades", "min_gap_percent", "REAL")
        conn.execute(
            "UPDATE simple_crossover_trades SET remaining_lots = lots WHERE status = 'open' AND remaining_lots = 0"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS simple_crossover_exit_legs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER NOT NULL,
                lots INTEGER NOT NULL,
                exit_time INTEGER NOT NULL,
                exit_premium REAL NOT NULL,
                exit_reason TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(trade_id, exit_reason)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS simple_crossover_xaut_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                entry_time INTEGER NOT NULL,
                entry_price REAL NOT NULL,
                entry_ema_gap REAL,
                day_direction TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                current_price REAL,
                exit_time INTEGER,
                exit_price REAL,
                exit_reason TEXT,
                realized_pnl REAL,
                comment TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        # Margin/leverage sizing: snapshotted per trade at entry time so a
        # later change to the margin/leverage settings doesn't retroactively
        # change an already-open or closed trade's % P&L.
        _add_column_if_missing(conn, "simple_crossover_xaut_trades", "margin", "REAL")
        _add_column_if_missing(conn, "simple_crossover_xaut_trades", "leverage", "REAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS simple_crossover_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS simple_crossover_xaut_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS btc_calm_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                expiry_code TEXT NOT NULL,
                settlement INTEGER NOT NULL,
                mode TEXT NOT NULL,
                trigger TEXT NOT NULL,
                entry_time INTEGER NOT NULL,
                entry_spot REAL NOT NULL,
                straddle REAL NOT NULL,
                calm_range REAL,
                atm_strike REAL NOT NULL,
                ce_strike REAL NOT NULL,
                pe_strike REAL NOT NULL,
                ce_symbol TEXT NOT NULL,
                pe_symbol TEXT NOT NULL,
                ce_product_id INTEGER NOT NULL,
                pe_product_id INTEGER NOT NULL,
                contracts INTEGER NOT NULL,
                entry_ce REAL NOT NULL,
                entry_pe REAL NOT NULL,
                credit REAL NOT NULL,
                entry_quotes TEXT,
                stop_low REAL NOT NULL,
                stop_high REAL NOT NULL,
                backstop REAL NOT NULL,
                early_target REAL,
                exit_by INTEGER NOT NULL,
                status TEXT NOT NULL,
                exit_time INTEGER,
                exit_reason TEXT,
                exit_ce REAL,
                exit_pe REAL,
                exit_spot REAL,
                exit_quotes TEXT,
                fees REAL NOT NULL DEFAULT 0,
                last_ce REAL,
                last_pe REAL,
                last_spot REAL,
                last_update INTEGER,
                best REAL,
                worst REAL,
                order_ids TEXT,
                notes TEXT
            )
            """
        )
        _add_column_if_missing(conn, "btc_calm_trades", "book", "TEXT NOT NULL DEFAULT 'standard'")
        conn.execute("CREATE TABLE IF NOT EXISTS btc_calm_events (id INTEGER PRIMARY KEY AUTOINCREMENT, expiry_code TEXT, trade_id INTEGER, time INTEGER NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS btc_calm_marks (trade_id INTEGER NOT NULL, time INTEGER NOT NULL, combined REAL NOT NULL, spot REAL, PRIMARY KEY (trade_id, time))")
        conn.execute("CREATE TABLE IF NOT EXISTS btc_calm_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS calm_strangle_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT NOT NULL,
                expiry TEXT NOT NULL,
                dte INTEGER NOT NULL,
                mode TEXT NOT NULL,
                trigger TEXT NOT NULL,
                entry_time INTEGER NOT NULL,
                entry_spot REAL NOT NULL,
                straddle REAL NOT NULL,
                calm_range REAL,
                atm_strike REAL NOT NULL,
                ce_strike REAL NOT NULL,
                pe_strike REAL NOT NULL,
                ce_security_id TEXT NOT NULL,
                pe_security_id TEXT NOT NULL,
                lots INTEGER NOT NULL,
                lot_size INTEGER NOT NULL,
                entry_ce REAL NOT NULL,
                entry_pe REAL NOT NULL,
                credit REAL NOT NULL,
                entry_quotes TEXT,
                stop_low REAL NOT NULL,
                stop_high REAL NOT NULL,
                backstop REAL NOT NULL,
                status TEXT NOT NULL,
                exit_time INTEGER,
                exit_reason TEXT,
                exit_ce REAL,
                exit_pe REAL,
                exit_spot REAL,
                exit_quotes TEXT,
                charges REAL NOT NULL DEFAULT 0,
                last_ce REAL,
                last_pe REAL,
                last_spot REAL,
                last_update INTEGER,
                best REAL,
                worst REAL,
                order_ids TEXT,
                notes TEXT
            )
            """
        )
        _add_column_if_missing(conn, "calm_strangle_trades", "early_target", "REAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS calm_strangle_marks (
                trade_id INTEGER NOT NULL,
                time INTEGER NOT NULL,
                combined REAL NOT NULL,
                spot REAL,
                PRIMARY KEY (trade_id, time)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS calm_strangle_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT NOT NULL,
                trade_id INTEGER,
                time INTEGER NOT NULL,
                kind TEXT NOT NULL,
                text TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS equity_swing_bars (security_id TEXT NOT NULL, ts INTEGER NOT NULL, open REAL, high REAL, low REAL, close REAL, volume REAL, PRIMARY KEY (security_id, ts))
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS equity_swing_trades (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, security_id TEXT NOT NULL, industry TEXT, mode TEXT NOT NULL, status TEXT NOT NULL, qty INTEGER NOT NULL, planned_at INTEGER, entry_time INTEGER, entry_price REAL, entry_charges REAL, entry_reason TEXT, entry_rank INTEGER, entry_score REAL, exit_time INTEGER, exit_price REAL, exit_charges REAL, exit_reason TEXT, pnl REAL, last_price REAL, last_rank INTEGER, last_update INTEGER, entry_order_id TEXT, exit_order_id TEXT, note TEXT)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS equity_swing_events (id INTEGER PRIMARY KEY AUTOINCREMENT, time INTEGER NOT NULL, kind TEXT NOT NULL, symbol TEXT, text TEXT NOT NULL)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS equity_swing_equity (day TEXT PRIMARY KEY, cash REAL NOT NULL, holdings REAL NOT NULL, equity REAL NOT NULL, nifty REAL, positions INTEGER)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS equity_swing_rankings (week TEXT PRIMARY KEY, created_at INTEGER NOT NULL, payload TEXT NOT NULL)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS equity_swing_retros (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at INTEGER NOT NULL, trigger TEXT NOT NULL, payload TEXT NOT NULL)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS equity_swing_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                symbol TEXT,
                security_id TEXT,
                segment TEXT,
                direction TEXT,
                price REAL,
                remind_at INTEGER,
                note TEXT,
                source TEXT NOT NULL DEFAULT 'manual',
                status TEXT NOT NULL DEFAULT 'active',
                created_at INTEGER NOT NULL,
                triggered_at INTEGER,
                trigger_price REAL,
                telegram_sent INTEGER,
                acknowledged_at INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS manage_trades_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS calm_strangle_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        # Calm Strangle - OR (opening-range filter): same tables under its own prefix
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS calm_or_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT NOT NULL,
                expiry TEXT NOT NULL,
                dte INTEGER NOT NULL,
                mode TEXT NOT NULL,
                trigger TEXT NOT NULL,
                entry_time INTEGER NOT NULL,
                entry_spot REAL NOT NULL,
                straddle REAL NOT NULL,
                calm_range REAL,
                atm_strike REAL NOT NULL,
                ce_strike REAL NOT NULL,
                pe_strike REAL NOT NULL,
                ce_security_id TEXT NOT NULL,
                pe_security_id TEXT NOT NULL,
                lots INTEGER NOT NULL,
                lot_size INTEGER NOT NULL,
                entry_ce REAL NOT NULL,
                entry_pe REAL NOT NULL,
                credit REAL NOT NULL,
                entry_quotes TEXT,
                stop_low REAL NOT NULL,
                stop_high REAL NOT NULL,
                backstop REAL NOT NULL,
                status TEXT NOT NULL,
                exit_time INTEGER,
                exit_reason TEXT,
                exit_ce REAL,
                exit_pe REAL,
                exit_spot REAL,
                exit_quotes TEXT,
                charges REAL NOT NULL DEFAULT 0,
                last_ce REAL,
                last_pe REAL,
                last_spot REAL,
                last_update INTEGER,
                best REAL,
                worst REAL,
                order_ids TEXT,
                notes TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS calm_or_marks (
                trade_id INTEGER NOT NULL,
                time INTEGER NOT NULL,
                combined REAL NOT NULL,
                spot REAL,
                PRIMARY KEY (trade_id, time)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS calm_or_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT NOT NULL,
                trade_id INTEGER,
                time INTEGER NOT NULL,
                kind TEXT NOT NULL,
                text TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS calm_or_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        _add_column_if_missing(conn, "calm_or_trades", "early_target", "REAL")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS nifty_strangle_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mode TEXT NOT NULL,
                trigger TEXT NOT NULL,
                entry_date TEXT NOT NULL,
                expiry TEXT NOT NULL,
                entry_time INTEGER NOT NULL,
                spot REAL NOT NULL,
                atm_strike REAL NOT NULL,
                straddle REAL NOT NULL,
                multiplier REAL NOT NULL,
                distance REAL NOT NULL,
                stop_loss_percent REAL NOT NULL,
                lots INTEGER NOT NULL,
                lot_size INTEGER NOT NULL,
                status TEXT NOT NULL,
                notes TEXT,
                closed_at INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS nifty_strangle_legs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER NOT NULL,
                option_type TEXT NOT NULL,
                strike REAL NOT NULL,
                security_id TEXT NOT NULL,
                formula_strike REAL,
                quantity INTEGER NOT NULL,
                entry_price REAL,
                entry_bid REAL,
                entry_ask REAL,
                sl_price REAL,
                status TEXT NOT NULL,
                exit_price REAL,
                exit_time INTEGER,
                exit_reason TEXT,
                entry_order_id TEXT,
                exit_order_id TEXT,
                entry_charges REAL NOT NULL DEFAULT 0,
                exit_charges REAL NOT NULL DEFAULT 0,
                last_ltp REAL,
                last_bid REAL,
                last_ask REAL,
                last_update INTEGER,
                error TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS nifty_strangle_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        # two paper books side by side: "plain" (naked strangle) and "hedged" (with bought wings)
        _add_column_if_missing(conn, "nifty_strangle_trades", "book", "TEXT NOT NULL DEFAULT 'plain'")
        _add_column_if_missing(conn, "nifty_strangle_trades", "broker", "TEXT")
        _add_column_if_missing(conn, "nifty_strangle_legs", "role", "TEXT NOT NULL DEFAULT 'short'")
        _add_column_if_missing(conn, "nifty_strangle_legs", "symbol", "TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS market_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT NOT NULL,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                source TEXT NOT NULL,
                note TEXT,
                created_at INTEGER NOT NULL,
                UNIQUE (day, kind)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kite_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS melting_days (
                day TEXT PRIMARY KEY,
                index_name TEXT NOT NULL,
                expiry TEXT NOT NULL,
                dte INTEGER NOT NULL,
                spot_open REAL NOT NULL,
                atm REAL NOT NULL,
                straddles TEXT NOT NULL,
                lot_size INTEGER NOT NULL,
                exchange_segment TEXT NOT NULL,
                stops INTEGER NOT NULL DEFAULT 0,
                braked_at INTEGER,
                brake_reason TEXT,
                created_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS melting_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT NOT NULL,
                index_name TEXT NOT NULL,
                expiry TEXT NOT NULL,
                dte INTEGER NOT NULL,
                tag TEXT NOT NULL,
                strike REAL NOT NULL,
                ce_security_id TEXT NOT NULL,
                pe_security_id TEXT NOT NULL,
                exchange_segment TEXT NOT NULL,
                mode TEXT NOT NULL,
                trigger TEXT NOT NULL,
                signal TEXT NOT NULL,
                signal_time INTEGER NOT NULL,
                signal_price REAL NOT NULL,
                signal_vwap REAL NOT NULL,
                lot_size INTEGER NOT NULL,
                lots INTEGER NOT NULL,
                lots_open INTEGER NOT NULL,
                entry_time INTEGER NOT NULL,
                entry_ce REAL NOT NULL,
                entry_pe REAL NOT NULL,
                entry_price REAL NOT NULL,
                initial_sl REAL NOT NULL,
                sl REAL NOT NULL,
                step REAL NOT NULL,
                hits INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                exit_time INTEGER,
                exit_reason TEXT,
                booked_points REAL NOT NULL DEFAULT 0,
                charges REAL NOT NULL DEFAULT 0,
                last_ce REAL,
                last_pe REAL,
                last_price REAL,
                last_vwap REAL,
                last_update INTEGER,
                best_price REAL,
                worst_price REAL,
                needs_attention TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_melting_trades_day ON melting_trades(day)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS melting_fills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER NOT NULL,
                time INTEGER NOT NULL,
                action TEXT NOT NULL,
                side TEXT NOT NULL,
                lots INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                ce_price REAL NOT NULL,
                pe_price REAL NOT NULL,
                combined REAL NOT NULL,
                ce_bid REAL, ce_ask REAL, ce_ltp REAL,
                pe_bid REAL, pe_ask REAL, pe_ltp REAL,
                reference_price REAL,
                slippage REAL,
                points REAL,
                pnl REAL,
                charges REAL NOT NULL,
                reason TEXT NOT NULL,
                mode TEXT NOT NULL,
                ce_order_id TEXT,
                pe_order_id TEXT,
                order_status TEXT,
                note TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_melting_fills_trade ON melting_fills(trade_id)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS melting_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT NOT NULL,
                trade_id INTEGER,
                time INTEGER NOT NULL,
                kind TEXT NOT NULL,
                text TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_melting_events_day ON melting_events(day)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS melting_minutes (
                day TEXT NOT NULL,
                tag TEXT NOT NULL,
                time INTEGER NOT NULL,
                ce REAL NOT NULL,
                pe REAL NOT NULL,
                combined REAL NOT NULL,
                vwap REAL,
                PRIMARY KEY (day, tag, time)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS melting_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        # Melting Straddles - Gap: same tables under its own prefix
        # (the gap version also records the opening gap)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS melting_gap_days (
                day TEXT PRIMARY KEY,
                index_name TEXT NOT NULL,
                expiry TEXT NOT NULL,
                dte INTEGER NOT NULL,
                spot_open REAL NOT NULL,
                atm REAL NOT NULL,
                straddles TEXT NOT NULL,
                lot_size INTEGER NOT NULL,
                exchange_segment TEXT NOT NULL,
                stops INTEGER NOT NULL DEFAULT 0,
                braked_at INTEGER,
                brake_reason TEXT,
                created_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS melting_gap_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT NOT NULL,
                index_name TEXT NOT NULL,
                expiry TEXT NOT NULL,
                dte INTEGER NOT NULL,
                tag TEXT NOT NULL,
                strike REAL NOT NULL,
                ce_security_id TEXT NOT NULL,
                pe_security_id TEXT NOT NULL,
                exchange_segment TEXT NOT NULL,
                mode TEXT NOT NULL,
                trigger TEXT NOT NULL,
                signal TEXT NOT NULL,
                signal_time INTEGER NOT NULL,
                signal_price REAL NOT NULL,
                signal_vwap REAL NOT NULL,
                lot_size INTEGER NOT NULL,
                lots INTEGER NOT NULL,
                lots_open INTEGER NOT NULL,
                entry_time INTEGER NOT NULL,
                entry_ce REAL NOT NULL,
                entry_pe REAL NOT NULL,
                entry_price REAL NOT NULL,
                initial_sl REAL NOT NULL,
                sl REAL NOT NULL,
                step REAL NOT NULL,
                hits INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                exit_time INTEGER,
                exit_reason TEXT,
                booked_points REAL NOT NULL DEFAULT 0,
                charges REAL NOT NULL DEFAULT 0,
                last_ce REAL,
                last_pe REAL,
                last_price REAL,
                last_vwap REAL,
                last_update INTEGER,
                best_price REAL,
                worst_price REAL,
                needs_attention TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS melting_gap_fills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER NOT NULL,
                time INTEGER NOT NULL,
                action TEXT NOT NULL,
                side TEXT NOT NULL,
                lots INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                ce_price REAL NOT NULL,
                pe_price REAL NOT NULL,
                combined REAL NOT NULL,
                ce_bid REAL, ce_ask REAL, ce_ltp REAL,
                pe_bid REAL, pe_ask REAL, pe_ltp REAL,
                reference_price REAL,
                slippage REAL,
                points REAL,
                pnl REAL,
                charges REAL NOT NULL,
                reason TEXT NOT NULL,
                mode TEXT NOT NULL,
                ce_order_id TEXT,
                pe_order_id TEXT,
                order_status TEXT,
                note TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS melting_gap_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT NOT NULL,
                trade_id INTEGER,
                time INTEGER NOT NULL,
                kind TEXT NOT NULL,
                text TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS melting_gap_minutes (
                day TEXT NOT NULL,
                tag TEXT NOT NULL,
                time INTEGER NOT NULL,
                ce REAL NOT NULL,
                pe REAL NOT NULL,
                combined REAL NOT NULL,
                vwap REAL,
                PRIMARY KEY (day, tag, time)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS melting_gap_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        _add_column_if_missing(conn, "melting_gap_days", "gap_percent", "REAL")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mantra_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mode TEXT NOT NULL,
                trigger TEXT NOT NULL,
                status TEXT NOT NULL,
                state TEXT NOT NULL,
                expiry TEXT NOT NULL,
                entry_time INTEGER NOT NULL,
                spot REAL NOT NULL,
                lots INTEGER NOT NULL,
                lot_size INTEGER NOT NULL,
                credit_points REAL NOT NULL,
                booked REAL NOT NULL DEFAULT 0,
                charges REAL NOT NULL DEFAULT 0,
                rolls INTEGER NOT NULL DEFAULT 0,
                exit_time INTEGER,
                exit_reason TEXT,
                gross REAL,
                last_mtm REAL,
                last_spot REAL,
                last_update INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mantra_legs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER NOT NULL,
                option_type TEXT NOT NULL,
                strike REAL NOT NULL,
                security_id TEXT,
                entry REAL NOT NULL,
                exit REAL,
                status TEXT NOT NULL,
                opened_at INTEGER NOT NULL,
                closed_at INTEGER,
                roll_no INTEGER NOT NULL DEFAULT 0,
                last_ltp REAL,
                last_bid REAL,
                last_ask REAL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mantra_legs_trade ON mantra_legs (trade_id)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS mantra_events (trade_id INTEGER NOT NULL, time INTEGER NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL)"
        )
        conn.execute("CREATE TABLE IF NOT EXISTS mantra_mtm (trade_id INTEGER NOT NULL, time INTEGER NOT NULL, mtm REAL NOT NULL, spot REAL)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mantra_mtm_trade ON mantra_mtm (trade_id, time)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mantra_alarms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at INTEGER NOT NULL,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                trade_id INTEGER,
                acknowledged_at INTEGER
            )
            """
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS mantra_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS turtle_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT NOT NULL,
                trigger TEXT NOT NULL,
                signal_time INTEGER,
                signal_rsi REAL,
                entry_time INTEGER NOT NULL,
                expiry TEXT NOT NULL,
                spot REAL NOT NULL,
                lots INTEGER NOT NULL,
                lot_size INTEGER NOT NULL,
                short_strike REAL NOT NULL,
                long_strike REAL NOT NULL,
                short_security_id TEXT,
                long_security_id TEXT,
                short_entry REAL NOT NULL,
                long_entry REAL NOT NULL,
                credit_points REAL NOT NULL,
                short_exit REAL,
                long_exit REAL,
                exit_time INTEGER,
                exit_reason TEXT,
                realized_pnl REAL,
                charges REAL,
                last_cost REAL,
                last_decay REAL,
                last_rsi REAL,
                last_update INTEGER
            )
            """
        )
        # Order-flow recorder: 1-min aggregates of Dhan's live feed (research data)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orderflow_minutes (
                day TEXT NOT NULL,
                security_id TEXT NOT NULL,
                label TEXT,
                kind TEXT,
                minute_ts INTEGER NOT NULL,
                open REAL, high REAL, low REAL, close REAL,
                volume REAL, buy_vol REAL, sell_vol REAL,
                book_buy REAL, book_sell REAL, bid_qty REAL, ask_qty REAL, spread REAL, oi REAL,
                packets INTEGER,
                footprint TEXT,
                PRIMARY KEY (security_id, minute_ts)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_orderflow_day ON orderflow_minutes(day)")
        # 1-Min CHoCH paper trades (NIFTY futures points)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS choch_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT NOT NULL,
                side INTEGER NOT NULL,
                status TEXT NOT NULL,
                entry_time INTEGER NOT NULL,
                entry REAL NOT NULL,
                stop REAL NOT NULL,
                target REAL NOT NULL,
                exit_time INTEGER,
                exit REAL,
                exit_reason TEXT,
                points REAL,
                lots INTEGER NOT NULL,
                lot_size INTEGER NOT NULL,
                cost_points REAL NOT NULL,
                params TEXT NOT NULL,
                last_price REAL,
                UNIQUE (day, entry_time)
            )
            """
        )
        conn.execute("CREATE TABLE IF NOT EXISTS choch_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)")
        # P&F Lab: daily closes per market + paper books (market x horizon x system)
        conn.execute("CREATE TABLE IF NOT EXISTS pf_lab_bars (market TEXT NOT NULL, time INTEGER NOT NULL, close REAL NOT NULL, PRIMARY KEY (market, time))")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pf_lab_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market TEXT NOT NULL,
                horizon TEXT NOT NULL,
                system TEXT NOT NULL,
                position_id INTEGER,
                side INTEGER NOT NULL,
                status TEXT NOT NULL,
                trigger TEXT NOT NULL,
                opened_at INTEGER NOT NULL,
                closed_at INTEGER,
                exit_reason TEXT,
                underlying_entry REAL NOT NULL,
                underlying_exit REAL,
                instrument TEXT NOT NULL,
                qty REAL NOT NULL,
                entry_price REAL,
                exit_price REAL,
                expiry TEXT,
                short_strike REAL,
                long_strike REAL,
                short_security_id TEXT,
                long_security_id TEXT,
                short_entry REAL,
                long_entry REAL,
                short_exit REAL,
                long_exit REAL,
                realized REAL,
                charges REAL,
                last_value REAL,
                last_pnl REAL,
                last_update INTEGER
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pf_lab_trades_book ON pf_lab_trades(market, horizon, status)")
        conn.execute("CREATE TABLE IF NOT EXISTS pf_lab_events (id INTEGER PRIMARY KEY AUTOINCREMENT, time INTEGER NOT NULL, market TEXT NOT NULL, horizon TEXT, system TEXT, kind TEXT NOT NULL, text TEXT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS pf_lab_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)")
        # Notes page: free-form learnings by date + a cached AI summary
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_day ON notes(day)")
        conn.execute("CREATE TABLE IF NOT EXISTS notes_summary (id INTEGER PRIMARY KEY CHECK (id = 1), payload TEXT NOT NULL, generated_at INTEGER NOT NULL)")
        # Define Turtle A1 (paper + live on Angel One): same tables under its own prefix
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS turtle_a1_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT NOT NULL,
                trigger TEXT NOT NULL,
                signal_time INTEGER,
                signal_rsi REAL,
                entry_time INTEGER NOT NULL,
                expiry TEXT NOT NULL,
                spot REAL NOT NULL,
                lots INTEGER NOT NULL,
                lot_size INTEGER NOT NULL,
                short_strike REAL NOT NULL,
                long_strike REAL NOT NULL,
                short_security_id TEXT,
                long_security_id TEXT,
                short_entry REAL NOT NULL,
                long_entry REAL NOT NULL,
                credit_points REAL NOT NULL,
                short_exit REAL,
                long_exit REAL,
                exit_time INTEGER,
                exit_reason TEXT,
                realized_pnl REAL,
                charges REAL,
                last_cost REAL,
                last_decay REAL,
                last_rsi REAL,
                last_update INTEGER
            )
            """
        )
        conn.execute("CREATE TABLE IF NOT EXISTS turtle_a1_alarms (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at INTEGER NOT NULL, kind TEXT NOT NULL, "
                     "title TEXT NOT NULL, message TEXT NOT NULL, trade_id INTEGER, acknowledged_at INTEGER)")
        conn.execute("CREATE TABLE IF NOT EXISTS turtle_a1_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)")
        for table in ("turtle_trades", "turtle_a1_trades"):
            _add_column_if_missing(conn, table, "mode", "TEXT NOT NULL DEFAULT 'paper'")
            for column in ("short_order_id", "long_order_id", "short_exit_order_id", "long_exit_order_id", "needs_attention", "broker"):
                _add_column_if_missing(conn, table, column, "TEXT")  # live: each trade keeps its own mode and broker
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS turtle_alarms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at INTEGER NOT NULL,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                trade_id INTEGER,
                acknowledged_at INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS turtle_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS batman_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mode TEXT NOT NULL,
                session_date TEXT NOT NULL,
                trigger TEXT NOT NULL,
                expiry TEXT NOT NULL,
                entry_time INTEGER NOT NULL,
                spot REAL NOT NULL,
                capital REAL NOT NULL,
                lot_size INTEGER NOT NULL,
                base_lots INTEGER NOT NULL,
                buy_offset REAL NOT NULL,
                sell_gap REAL NOT NULL,
                hedge_gap REAL NOT NULL,
                extra_call_lots INTEGER NOT NULL,
                credit REAL NOT NULL,
                credit_percent REAL NOT NULL,
                target_percent REAL NOT NULL,
                stop_percent REAL NOT NULL,
                exit_by INTEGER NOT NULL,
                status TEXT NOT NULL,
                exit_time INTEGER,
                exit_reason TEXT,
                realized_pnl REAL,
                charges REAL,
                last_mtm REAL,
                last_update INTEGER,
                plan_json TEXT,
                notes TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS batman_legs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                option_type TEXT NOT NULL,
                role TEXT NOT NULL,
                strike REAL NOT NULL,
                lots INTEGER NOT NULL,
                security_id TEXT,
                entry_price REAL NOT NULL,
                iv REAL,
                exit_price REAL,
                last_ltp REAL,
                last_bid REAL,
                last_ask REAL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_batman_legs_trade ON batman_legs (trade_id)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS batman_mtm (
                trade_id INTEGER NOT NULL,
                time INTEGER NOT NULL,
                mtm REAL NOT NULL,
                spot REAL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_batman_mtm_trade ON batman_mtm (trade_id, time)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS batman_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS btc_strangle_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mode TEXT NOT NULL,
                session_date TEXT NOT NULL,
                expiry_code TEXT NOT NULL,
                settlement_time INTEGER NOT NULL,
                entry_time INTEGER NOT NULL,
                spot REAL NOT NULL,
                atm_strike REAL,
                straddle REAL NOT NULL,
                multiplier REAL NOT NULL,
                distance REAL NOT NULL,
                stop_loss_percent REAL NOT NULL,
                contracts INTEGER NOT NULL,
                status TEXT NOT NULL,
                trigger TEXT NOT NULL,
                notes TEXT,
                closed_at INTEGER,
                created_at TEXT NOT NULL
            )
            """
        )
        _add_column_if_missing(conn, "btc_strangle_trades", "variant", "TEXT NOT NULL DEFAULT 'strangle'")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS btc_strangle_legs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER NOT NULL,
                option_type TEXT NOT NULL,
                symbol TEXT NOT NULL,
                product_id INTEGER NOT NULL,
                strike REAL NOT NULL,
                requested_contracts INTEGER NOT NULL,
                contracts INTEGER NOT NULL,
                entry_price REAL,
                sl_price REAL,
                status TEXT NOT NULL,
                exit_price REAL,
                exit_time INTEGER,
                exit_reason TEXT,
                entry_order_id TEXT,
                sl_order_id TEXT,
                exit_order_id TEXT,
                entry_fee REAL NOT NULL DEFAULT 0,
                exit_fee REAL NOT NULL DEFAULT 0,
                last_mark REAL,
                last_bid REAL,
                last_ask REAL,
                last_update INTEGER,
                error TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_btc_strangle_legs_trade ON btc_strangle_legs (trade_id)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS btc_strangle_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tag_levels (
                session_date TEXT NOT NULL,
                tag TEXT NOT NULL,
                target_net REAL,
                stop_loss_net REAL,
                status TEXT NOT NULL,
                trigger_kind TEXT,
                trigger_net REAL,
                triggered_at TEXT,
                result_json TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (session_date, tag)
            )
            """
        )
        for column in ("target_percent", "stop_percent", "premium_base"):
            _add_column_if_missing(conn, "tag_levels", column, "REAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS varaha_paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rec_id INTEGER,
                session_date TEXT NOT NULL,
                mode TEXT NOT NULL,
                trigger TEXT NOT NULL,
                structure TEXT NOT NULL,
                structure_label TEXT NOT NULL,
                variant_label TEXT,
                candidate_id TEXT,
                direction TEXT NOT NULL,
                move_class TEXT,
                decision TEXT,
                expiry TEXT NOT NULL,
                exit_by INTEGER NOT NULL,
                entry_time INTEGER NOT NULL,
                entry_spot REAL NOT NULL,
                lots INTEGER NOT NULL,
                lot_size INTEGER NOT NULL,
                entry_value REAL NOT NULL,
                max_profit_points REAL,
                max_loss_points REAL,
                breakevens TEXT,
                target_points REAL NOT NULL,
                stop_points REAL NOT NULL,
                status TEXT NOT NULL,
                exit_time INTEGER,
                exit_reason TEXT,
                exit_value REAL,
                exit_spot REAL,
                charges REAL NOT NULL DEFAULT 0,
                last_value REAL,
                last_spot REAL,
                last_update INTEGER,
                best_points REAL,
                worst_points REAL,
                needs_attention TEXT,
                notes TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS varaha_paper_legs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                option_type TEXT NOT NULL,
                strike REAL NOT NULL,
                ratio INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                security_id TEXT NOT NULL,
                entry_price REAL,
                entry_bid REAL, entry_ask REAL, entry_ltp REAL,
                entry_order_id TEXT,
                exit_price REAL,
                exit_bid REAL, exit_ask REAL, exit_ltp REAL,
                exit_order_id TEXT,
                last_ltp REAL, last_bid REAL, last_ask REAL,
                iv REAL,
                delta REAL
            )
            """
        )
        conn.execute("CREATE TABLE IF NOT EXISTS varaha_paper_events (id INTEGER PRIMARY KEY AUTOINCREMENT, trade_id INTEGER, time INTEGER NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS varaha_paper_marks (trade_id INTEGER NOT NULL, time INTEGER NOT NULL, pnl_points REAL NOT NULL, spot REAL, PRIMARY KEY (trade_id, time))")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS varaha_recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_date TEXT NOT NULL,
                trigger TEXT NOT NULL,
                manual_override TEXT,
                snapshot_json TEXT NOT NULL,
                result_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_varaha_recommendations_date ON varaha_recommendations (session_date, id)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS varaha_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS crypto_swing_live_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                mode TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                entry_time INTEGER NOT NULL,
                entry_price REAL NOT NULL,
                size_contracts INTEGER NOT NULL,
                notional_usd REAL NOT NULL,
                stop_loss REAL,
                tranches INTEGER NOT NULL DEFAULT 1,
                exit_time INTEGER,
                exit_price REAL,
                exit_reason TEXT,
                pnl_usd REAL,
                order_id TEXT,
                note TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS nifty_swing_live_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                side TEXT NOT NULL,
                mode TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                entry_time INTEGER NOT NULL,
                entry_price REAL NOT NULL,
                quantity INTEGER NOT NULL,
                tranches INTEGER NOT NULL DEFAULT 1,
                stop_loss REAL,
                exit_time INTEGER,
                exit_price REAL,
                exit_reason TEXT,
                pnl_inr REAL,
                order_id TEXT,
                note TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        # Equity page (ported from options-dash): Dhan holdings/quotes/
        # transactions/candles + Screener fundamentals + OpenAI news, all
        # cached here to avoid re-scraping/re-fetching on every page load.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS equity_cache (
                category TEXT NOT NULL,
                cache_key TEXT NOT NULL,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (category, cache_key)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_equity_cache_category_updated ON equity_cache(category, updated_at DESC)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS equity_transactions_cache (
                transaction_key TEXT PRIMARY KEY,
                symbol TEXT,
                security_id TEXT,
                isin TEXT,
                exchange_time TEXT,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_equity_transactions_lookup ON equity_transactions_cache(security_id, isin, exchange_time DESC)"
        )
        # Options leg-days imported from user-provided Dhan "Global Transaction
        # Report" CSVs -- Dhan's live trade-history API has no per-leg options
        # granularity and only reaches back ~2.5-3 months, so this is populated
        # by a one-time/occasional import script, not the live API path.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS equity_options_transactions (
                id TEXT PRIMARY KEY,
                trade_date TEXT NOT NULL,
                underlying TEXT NOT NULL,
                expiry_date TEXT,
                strike REAL,
                option_type TEXT,
                exchange TEXT,
                bill_no TEXT,
                buy_qty REAL,
                buy_value REAL,
                sell_qty REAL,
                sell_value REAL,
                brokerage REAL,
                gst REAL,
                stt REAL,
                sebi_fees REAL,
                stamp_duty REAL,
                txn_charges REAL,
                oth_charges REAL,
                gross_amount REAL,
                source TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_equity_options_txn_date ON equity_options_transactions(trade_date)"
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
            WHERE stop_loss IS NOT NULL OR target IS NOT NULL OR target_percent IS NOT NULL
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
        "target_percent": _number(payload.get("targetPercent")),
        "target_auto": 1 if payload.get("targetAuto") else 0,
        "notes": payload.get("notes") or "",
        "tag": (payload.get("tag") or "").strip() or None,
        "updated_at": now,
    }
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO trade_levels (
                trade_id, symbol, expiry, strike_price, option_side, stop_loss, target, target_percent, target_auto, notes, tag, updated_at
            ) VALUES (
                :trade_id, :symbol, :expiry, :strike_price, :option_side, :stop_loss, :target, :target_percent, :target_auto, :notes, :tag, :updated_at
            )
            ON CONFLICT(trade_id) DO UPDATE SET
                symbol = excluded.symbol,
                expiry = excluded.expiry,
                strike_price = excluded.strike_price,
                option_side = excluded.option_side,
                stop_loss = excluded.stop_loss,
                target = excluded.target,
                target_percent = excluded.target_percent,
                target_auto = excluded.target_auto,
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
    ce_bid: float | None = None,
    ce_ask: float | None = None,
    pe_bid: float | None = None,
    pe_ask: float | None = None,
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO pcr_oi_snapshots (
                session_date, underlying, epoch, captured_at, spot, pcr, ce_oi, pe_oi, ce_oi_change, pe_oi_change,
                atm_strike, ce_premium, ce_iv, ce_delta, ce_vega, pe_premium, pe_iv, pe_delta, pe_vega, india_vix,
                ce_bid, ce_ask, pe_bid, pe_ask
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_date, underlying, epoch, now, spot, pcr, ce_oi, pe_oi, ce_oi_change, pe_oi_change,
                atm_strike, ce_premium, ce_iv, ce_delta, ce_vega, pe_premium, pe_iv, pe_delta, pe_vega, india_vix,
                ce_bid, ce_ask, pe_bid, pe_ask,
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
                "ceBid": row["ce_bid"],
                "ceAsk": row["ce_ask"],
                "peBid": row["pe_bid"],
                "peAsk": row["pe_ask"],
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
        "targetPercent": row.get("target_percent"),
        "targetAuto": bool(row.get("target_auto")),
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


def last_paper_trade_close(underlying: str, signal_type: str) -> int | None:
    """Epoch when the latest closed paper trade of this (underlying, signal) closed."""
    with _DB_LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT MAX(closed_at) FROM paper_trades WHERE underlying = ? AND signal_type = ? AND status = 'closed'",
            (underlying, signal_type),
        ).fetchone()
    return int(row[0]) if row and row[0] else None


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


# pStrategy-Nifty: deliberately its own table, not a reuse of paper_trades --
# that table's schema (target1/target2/phase) is tightly coupled to
# paper_trading_engine.py's 3-lot staged-exit state machine, and its
# background loop (paper_trading.py's _manage_open_trades) manages every
# row in paper_trades regardless of signal_type. Sharing it would mean that
# loop tries to manage pStrategy-Nifty's trades with the wrong exit logic.
# One open trade per resolution ("1m"/"3m") at a time, same no-pyramiding
# rule as pStrategy itself.


def create_pstrategy_nifty_trade(
    *,
    resolution: str,
    side: str,
    strike: float,
    expiry: str,
    security_id: str,
    exchange_segment: str,
    lots: int,
    lot_size: int,
    entry_time: int,
    entry_premium: float,
    entry_underlying_price: float,
    stop_loss_percent: float,
    hard_stop_underlying: float | None = None,
) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO pstrategy_nifty_trades (
                resolution, side, strike, expiry, security_id, exchange_segment,
                lots, lot_size, entry_time, entry_premium, entry_underlying_price,
                stop_loss_percent, peak_premium, best_underlying_close, trail_stop_underlying,
                status, created_at, updated_at, hard_stop_underlying
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, 'open', ?, ?, ?)
            """,
            (
                resolution,
                side,
                strike,
                expiry,
                security_id,
                exchange_segment,
                lots,
                lot_size,
                entry_time,
                entry_premium,
                entry_underlying_price,
                stop_loss_percent,
                entry_underlying_price,
                now,
                now,
                hard_stop_underlying,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def get_open_pstrategy_nifty_trade(resolution: str) -> dict[str, Any] | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM pstrategy_nifty_trades WHERE resolution = ? AND status = 'open' ORDER BY id DESC LIMIT 1",
            (resolution,),
        ).fetchone()
    return _pstrategy_nifty_trade_from_row(row) if row else None


def list_open_pstrategy_nifty_trades() -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute("SELECT * FROM pstrategy_nifty_trades WHERE status = 'open'").fetchall()
    return [_pstrategy_nifty_trade_from_row(row) for row in rows]


def update_pstrategy_nifty_trade_progress(
    trade_id: int, *, peak_premium: float | None, best_underlying_close: float, trail_stop_underlying: float | None
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            UPDATE pstrategy_nifty_trades
            SET peak_premium = ?, best_underlying_close = ?, trail_stop_underlying = ?, updated_at = ?
            WHERE id = ?
            """,
            (peak_premium, best_underlying_close, trail_stop_underlying, now, trade_id),
        )
        conn.commit()


def close_pstrategy_nifty_trade(
    trade_id: int, *, exit_time: int, exit_premium: float, exit_reason: str, realized_pnl: float
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            UPDATE pstrategy_nifty_trades
            SET status = 'closed', exit_time = ?, exit_premium = ?, exit_reason = ?, realized_pnl = ?, updated_at = ?
            WHERE id = ?
            """,
            (exit_time, exit_premium, exit_reason, realized_pnl, now, trade_id),
        )
        conn.commit()


def list_pstrategy_nifty_trades(resolution: str | None = None) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        if resolution:
            rows = conn.execute(
                "SELECT * FROM pstrategy_nifty_trades WHERE resolution = ? ORDER BY entry_time DESC", (resolution,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM pstrategy_nifty_trades ORDER BY entry_time DESC").fetchall()
    return [_pstrategy_nifty_trade_from_row(row) for row in rows]


def _pstrategy_nifty_trade_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "resolution": row["resolution"],
        "side": row["side"],
        "strike": row["strike"],
        "expiry": row["expiry"],
        "securityId": row["security_id"],
        "exchangeSegment": row["exchange_segment"],
        "lots": row["lots"],
        "lotSize": row["lot_size"],
        "entryTime": row["entry_time"],
        "entryPremium": row["entry_premium"],
        "entryUnderlyingPrice": row["entry_underlying_price"],
        "stopLossPercent": row["stop_loss_percent"],
        "peakPremium": row["peak_premium"],
        "bestUnderlyingClose": row["best_underlying_close"],
        "trailStopUnderlying": row["trail_stop_underlying"],
        "hardStopUnderlying": row["hard_stop_underlying"],
        "status": row["status"],
        "exitTime": row["exit_time"],
        "exitPremium": row["exit_premium"],
        "exitReason": row["exit_reason"],
        "realizedPnl": row["realized_pnl"],
        "createdAt": row["created_at"],
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


def create_pe_ce_crossover_trade(
    *,
    underlying: str,
    side: str,
    strike: float,
    expiry: str,
    dte: int | None,
    security_id: str,
    exchange_segment: str,
    lots: int,
    lot_size: int,
    entry_time: int,
    entry_premium: float,
    stop_loss_percent: float,
    target_percent: float,
    mode: str = "paper",
    entry_order_id: str | None = None,
    note: str | None = None,
) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO pe_ce_crossover_trades (
                underlying, side, strike, expiry, dte, security_id, exchange_segment,
                lots, lot_size, entry_time, entry_premium, stop_loss_percent, target_percent,
                peak_premium, trail_stop_premium, status, mode, entry_order_id, note, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'open', ?, ?, ?, ?, ?)
            """,
            (
                underlying,
                side,
                strike,
                expiry,
                dte,
                security_id,
                exchange_segment,
                lots,
                lot_size,
                entry_time,
                entry_premium,
                stop_loss_percent,
                target_percent,
                entry_premium,
                mode,
                entry_order_id,
                note,
                now,
                now,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def get_open_pe_ce_crossover_trade(underlying: str, side: str) -> dict[str, Any] | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM pe_ce_crossover_trades WHERE underlying = ? AND side = ? AND status = 'open' ORDER BY id DESC LIMIT 1",
            (underlying, side),
        ).fetchone()
    return _pe_ce_crossover_trade_from_row(row) if row else None


def list_open_pe_ce_crossover_trades(mode: str | None = None) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        if mode:
            rows = conn.execute(
                "SELECT * FROM pe_ce_crossover_trades WHERE status = 'open' AND mode = ?", (mode,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM pe_ce_crossover_trades WHERE status = 'open'").fetchall()
    return [_pe_ce_crossover_trade_from_row(row) for row in rows]


def update_pe_ce_crossover_trade_progress(
    trade_id: int, *, peak_premium: float | None, trail_stop_premium: float | None
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            "UPDATE pe_ce_crossover_trades SET peak_premium = ?, trail_stop_premium = ?, updated_at = ? WHERE id = ?",
            (peak_premium, trail_stop_premium, now, trade_id),
        )
        conn.commit()


def close_pe_ce_crossover_trade(
    trade_id: int,
    *,
    exit_time: int,
    exit_premium: float,
    exit_reason: str,
    realized_pnl: float,
    charges: float,
    exit_order_id: str | None = None,
    exit_note: str | None = None,
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            UPDATE pe_ce_crossover_trades
            SET status = 'closed', exit_time = ?, exit_premium = ?, exit_reason = ?, realized_pnl = ?, charges = ?,
                exit_order_id = ?, note = CASE WHEN ? IS NULL THEN note
                                              WHEN note IS NULL THEN ?
                                              ELSE note || ' | ' || ? END,
                updated_at = ?
            WHERE id = ?
            """,
            (exit_time, exit_premium, exit_reason, realized_pnl, charges, exit_order_id, exit_note, exit_note, exit_note, now, trade_id),
        )
        conn.commit()


def list_pe_ce_crossover_trades(underlying: str | None = None) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        if underlying:
            rows = conn.execute(
                "SELECT * FROM pe_ce_crossover_trades WHERE underlying = ? ORDER BY entry_time DESC", (underlying,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM pe_ce_crossover_trades ORDER BY entry_time DESC").fetchall()
    return [_pe_ce_crossover_trade_from_row(row) for row in rows]


def list_pe_ce_crossover_trades_for_report(mode: str, from_epoch: int, to_epoch: int) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM pe_ce_crossover_trades
            WHERE mode = ? AND status = 'closed' AND exit_time >= ? AND exit_time <= ?
            ORDER BY exit_time ASC
            """,
            (mode, from_epoch, to_epoch),
        ).fetchall()
    return [_pe_ce_crossover_trade_from_row(row) for row in rows]


def count_pe_ce_crossover_trades_today(underlying: str, side: str, start_of_day_epoch: int, mode: str) -> int:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM pe_ce_crossover_trades WHERE underlying = ? AND side = ? AND entry_time >= ? AND mode = ?",
            (underlying, side, start_of_day_epoch, mode),
        ).fetchone()
    return int(row["n"]) if row else 0


def get_last_pe_ce_crossover_exit_time(underlying: str, side: str, mode: str) -> int | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute(
            """
            SELECT exit_time FROM pe_ce_crossover_trades
            WHERE underlying = ? AND side = ? AND status = 'closed' AND exit_time IS NOT NULL AND mode = ?
            ORDER BY exit_time DESC LIMIT 1
            """,
            (underlying, side, mode),
        ).fetchone()
    return int(row["exit_time"]) if row and row["exit_time"] is not None else None


def get_today_realized_pnl_pe_ce_crossover(start_of_day_epoch: int, mode: str) -> float:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(realized_pnl), 0) AS total
            FROM pe_ce_crossover_trades
            WHERE status = 'closed' AND exit_time >= ? AND mode = ?
            """,
            (start_of_day_epoch, mode),
        ).fetchone()
    return float(row["total"]) if row else 0.0


def _pe_ce_crossover_trade_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "underlying": row["underlying"],
        "side": row["side"],
        "strike": row["strike"],
        "expiry": row["expiry"],
        "dte": row["dte"],
        "securityId": row["security_id"],
        "exchangeSegment": row["exchange_segment"],
        "lots": row["lots"],
        "lotSize": row["lot_size"],
        "entryTime": row["entry_time"],
        "entryPremium": row["entry_premium"],
        "stopLossPercent": row["stop_loss_percent"],
        "targetPercent": row["target_percent"],
        "peakPremium": row["peak_premium"],
        "trailStopPremium": row["trail_stop_premium"],
        "status": row["status"],
        "exitTime": row["exit_time"],
        "exitPremium": row["exit_premium"],
        "exitReason": row["exit_reason"],
        "realizedPnl": row["realized_pnl"],
        "charges": row["charges"],
        "mode": row["mode"] if "mode" in row.keys() else "paper",
        "entryOrderId": row["entry_order_id"] if "entry_order_id" in row.keys() else None,
        "exitOrderId": row["exit_order_id"] if "exit_order_id" in row.keys() else None,
        "note": row["note"] if "note" in row.keys() else None,
        "createdAt": row["created_at"],
    }


def record_pe_ce_crossover_signal(
    *,
    session_date: str,
    epoch: int,
    underlying: str,
    side: str,
    state: str,
    blocked_reason: str | None,
    ema_fast: float | None,
    ema_slow: float | None,
    premium: float | None,
    premium_expansion_percent: float | None,
    spread_percent: float | None,
    rsi: float | None = None,
    adx: float | None = None,
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO pe_ce_crossover_signal_log (
                session_date, epoch, underlying, side, state, blocked_reason,
                ema_fast, ema_slow, premium, premium_expansion_percent, spread_percent, rsi, adx, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_date,
                epoch,
                underlying,
                side,
                state,
                blocked_reason,
                ema_fast,
                ema_slow,
                premium,
                premium_expansion_percent,
                spread_percent,
                rsi,
                adx,
                now,
            ),
        )
        conn.commit()


def list_pe_ce_crossover_signal_log(session_date: str, underlying: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        if underlying:
            rows = conn.execute(
                """
                SELECT * FROM pe_ce_crossover_signal_log WHERE session_date = ? AND underlying = ?
                ORDER BY epoch DESC LIMIT ?
                """,
                (session_date, underlying, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM pe_ce_crossover_signal_log WHERE session_date = ? ORDER BY epoch DESC LIMIT ?",
                (session_date, limit),
            ).fetchall()
    return [
        {
            "time": row["epoch"],
            "underlying": row["underlying"],
            "side": row["side"],
            "state": row["state"],
            "blockedReason": row["blocked_reason"],
            "emaFast": row["ema_fast"],
            "emaSlow": row["ema_slow"],
            "premium": row["premium"],
            "premiumExpansionPercent": row["premium_expansion_percent"],
            "spreadPercent": row["spread_percent"],
            "rsi": row["rsi"] if "rsi" in row.keys() else None,
            "adx": row["adx"] if "adx" in row.keys() else None,
        }
        for row in rows
    ]


def get_pe_ce_crossover_setting(key: str) -> str | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT value FROM pe_ce_crossover_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_pe_ce_crossover_setting(key: str, value: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO pe_ce_crossover_settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, now),
        )
        conn.commit()


def create_simple_crossover_trade(
    *,
    underlying: str,
    side: str,
    strike: float,
    expiry: str,
    security_id: str,
    exchange_segment: str,
    lots: int,
    lot_size: int,
    entry_time: int,
    entry_premium: float,
    entry_ema_gap: float | None,
    entry_pcr: float | None,
    entry_ce_oi_change: int | None,
    entry_pe_oi_change: int | None,
    day_direction: str | None,
    timeframe_minutes: int = 1,
    signal_time: int | None = None,
    signal_close: float | None = None,
    signal_source: str | None = None,
    plain_crossover: bool = False,
    plain_target_percent: float | None = None,
    min_gap_percent: float | None = None,
    comment: str | None = None,
) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO simple_crossover_trades (
                underlying, side, strike, expiry, security_id, exchange_segment, lots, lot_size,
                entry_time, entry_premium, entry_ema_gap, entry_pcr, entry_ce_oi_change, entry_pe_oi_change,
                day_direction, status, current_premium, remaining_lots, peak_premium, created_at, updated_at,
                timeframe_minutes, signal_time, signal_close, signal_source, plain_crossover, comment, plain_target_percent,
                min_gap_percent
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                underlying, side, strike, expiry, security_id, exchange_segment, lots, lot_size,
                entry_time, entry_premium, entry_ema_gap, entry_pcr, entry_ce_oi_change, entry_pe_oi_change,
                day_direction, entry_premium, lots, entry_premium, now, now, timeframe_minutes,
                signal_time, signal_close, signal_source, 1 if plain_crossover else 0,
                comment or ("Plain cross over" if plain_crossover else None),
                plain_target_percent,
                min_gap_percent,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def get_open_simple_crossover_trade(side: str) -> dict[str, Any] | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM simple_crossover_trades WHERE side = ? AND status = 'open' ORDER BY id DESC LIMIT 1", (side,)
        ).fetchone()
    return _simple_crossover_trade_from_row(row) if row else None


def list_open_simple_crossover_trades() -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute("SELECT * FROM simple_crossover_trades WHERE status = 'open'").fetchall()
    return [_simple_crossover_trade_from_row(row) for row in rows]


def update_simple_crossover_trade_progress(
    trade_id: int, *, current_premium: float, peak_premium: float, trailing_stop_price: float | None
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            UPDATE simple_crossover_trades
            SET current_premium = ?, peak_premium = ?, trailing_stop_price = ?, updated_at = ?
            WHERE id = ? AND status = 'open'
            """,
            (current_premium, peak_premium, trailing_stop_price, now, trade_id),
        )
        conn.commit()


def record_simple_crossover_exit_leg(
    trade_id: int, *, lots: int, exit_time: int, exit_premium: float, exit_reason: str
) -> bool:
    if lots <= 0:
        return False
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM simple_crossover_trades WHERE id = ? AND status = 'open'", (trade_id,)
        ).fetchone()
        if not row or int(row["remaining_lots"] or 0) < lots:
            return False
        try:
            conn.execute(
                """
                INSERT INTO simple_crossover_exit_legs (trade_id, lots, exit_time, exit_premium, exit_reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (trade_id, lots, exit_time, exit_premium, exit_reason, now),
            )
        except sqlite3.IntegrityError:
            return False

        remaining_lots = int(row["remaining_lots"]) - lots
        realized_pnl = float(row["realized_pnl"] or 0) + (
            exit_premium - float(row["entry_premium"])
        ) * int(row["lot_size"]) * lots
        target1_hit = bool(row["target1_hit"]) or exit_reason == "target_5"
        target2_hit = bool(row["target2_hit"]) or exit_reason == "target_10"
        trailing_stop_price = row["trailing_stop_price"]
        if exit_reason == "target_10":
            trailing_stop_price = float(row["entry_premium"]) * 1.05

        status = "closed" if remaining_lots == 0 else "open"
        exit_at = exit_time if remaining_lots == 0 else None
        exit_average = None
        final_reason = None
        if remaining_lots == 0:
            exits = conn.execute(
                "SELECT lots, exit_premium, exit_reason FROM simple_crossover_exit_legs WHERE trade_id = ?",
                (trade_id,),
            ).fetchall()
            exited_lots = sum(int(item["lots"]) for item in exits)
            exit_average = (
                sum(int(item["lots"]) * float(item["exit_premium"]) for item in exits) / exited_lots
                if exited_lots
                else exit_premium
            )
            final_reason = exit_reason
        conn.execute(
            """
            UPDATE simple_crossover_trades
            SET status = ?, remaining_lots = ?, target1_hit = ?, target2_hit = ?, peak_premium = MAX(COALESCE(peak_premium, entry_premium), ?),
                trailing_stop_price = ?, exit_time = ?, exit_premium = ?, exit_reason = ?, realized_pnl = ?,
                current_premium = ?, updated_at = ?
            WHERE id = ? AND status = 'open'
            """,
            (
                status, remaining_lots, int(target1_hit), int(target2_hit), exit_premium,
                trailing_stop_price, exit_at, exit_average, final_reason, realized_pnl,
                exit_premium, now, trade_id,
            ),
        )
        conn.commit()
        return True


def list_simple_crossover_trades() -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute("SELECT * FROM simple_crossover_trades ORDER BY entry_time DESC").fetchall()
        exit_rows = conn.execute(
            "SELECT * FROM simple_crossover_exit_legs ORDER BY exit_time, id"
        ).fetchall()
    legs_by_trade: dict[int, list[dict[str, Any]]] = {}
    for leg in exit_rows:
        legs_by_trade.setdefault(int(leg["trade_id"]), []).append(
            {
                "lots": int(leg["lots"]),
                "exitTime": int(leg["exit_time"]),
                "exitPremium": float(leg["exit_premium"]),
                "exitReason": leg["exit_reason"],
            }
        )
    return [_simple_crossover_trade_from_row(row, legs_by_trade.get(int(row["id"]), [])) for row in rows]


def update_simple_crossover_trade_comment(trade_id: int, comment: str) -> dict[str, Any] | None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            "UPDATE simple_crossover_trades SET comment = ?, updated_at = ? WHERE id = ?", (comment, now, trade_id)
        )
        conn.commit()
        row = conn.execute("SELECT * FROM simple_crossover_trades WHERE id = ?", (trade_id,)).fetchone()
    return _simple_crossover_trade_from_row(row) if row else None


def _simple_crossover_trade_from_row(row: sqlite3.Row, exit_legs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "id": row["id"],
        "underlying": row["underlying"],
        "side": row["side"],
        "strike": row["strike"],
        "expiry": row["expiry"],
        "securityId": row["security_id"],
        "exchangeSegment": row["exchange_segment"],
        "lots": row["lots"],
        "lotSize": row["lot_size"],
        "entryTime": row["entry_time"],
        "entryPremium": row["entry_premium"],
        "entryEmaGap": row["entry_ema_gap"],
        "entryPcr": row["entry_pcr"],
        "entryCeOiChange": row["entry_ce_oi_change"],
        "entryPeOiChange": row["entry_pe_oi_change"],
        "dayDirection": row["day_direction"],
        "timeframeMinutes": row["timeframe_minutes"],
        "signalTime": row["signal_time"],
        "signalClose": row["signal_close"],
        "signalSource": row["signal_source"],
        "plainCrossover": bool(row["plain_crossover"]),
        "plainTargetPercent": row["plain_target_percent"] if "plain_target_percent" in row.keys() else None,
        "minGapPercent": row["min_gap_percent"] if "min_gap_percent" in row.keys() else None,
        "status": row["status"],
        "currentPremium": row["current_premium"],
        "remainingLots": row["remaining_lots"],
        "target1Hit": bool(row["target1_hit"]),
        "target2Hit": bool(row["target2_hit"]),
        "peakPremium": row["peak_premium"],
        "trailingStopPrice": row["trailing_stop_price"],
        "exitTime": row["exit_time"],
        "exitPremium": row["exit_premium"],
        "exitReason": row["exit_reason"],
        "realizedPnl": row["realized_pnl"],
        "exitLegs": exit_legs or [],
        "comment": row["comment"],
        "createdAt": row["created_at"],
    }


def create_simple_crossover_xaut_trade(
    *,
    side: str,
    quantity: float,
    entry_time: int,
    entry_price: float,
    entry_ema_gap: float | None,
    day_direction: str | None,
    margin: float,
    leverage: float,
) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO simple_crossover_xaut_trades (
                side, quantity, entry_time, entry_price, entry_ema_gap, day_direction,
                margin, leverage, status, current_price, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)
            """,
            (side, quantity, entry_time, entry_price, entry_ema_gap, day_direction, margin, leverage, entry_price, now, now),
        )
        conn.commit()
        return int(cur.lastrowid)


def get_open_simple_crossover_xaut_trade(side: str) -> dict[str, Any] | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM simple_crossover_xaut_trades WHERE side = ? AND status = 'open' ORDER BY id DESC LIMIT 1",
            (side,),
        ).fetchone()
    return _simple_crossover_xaut_trade_from_row(row) if row else None


def list_open_simple_crossover_xaut_trades() -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute("SELECT * FROM simple_crossover_xaut_trades WHERE status = 'open'").fetchall()
    return [_simple_crossover_xaut_trade_from_row(row) for row in rows]


def update_simple_crossover_xaut_trade_progress(trade_id: int, *, current_price: float) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            "UPDATE simple_crossover_xaut_trades SET current_price = ?, updated_at = ? WHERE id = ?",
            (current_price, now, trade_id),
        )
        conn.commit()


def close_simple_crossover_xaut_trade(
    trade_id: int, *, exit_time: int, exit_price: float, exit_reason: str, realized_pnl: float
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            UPDATE simple_crossover_xaut_trades
            SET status = 'closed', exit_time = ?, exit_price = ?, exit_reason = ?, realized_pnl = ?,
                current_price = ?, updated_at = ?
            WHERE id = ?
            """,
            (exit_time, exit_price, exit_reason, realized_pnl, exit_price, now, trade_id),
        )
        conn.commit()


def list_simple_crossover_xaut_trades() -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute("SELECT * FROM simple_crossover_xaut_trades ORDER BY entry_time DESC").fetchall()
    return [_simple_crossover_xaut_trade_from_row(row) for row in rows]


def update_simple_crossover_xaut_trade_comment(trade_id: int, comment: str) -> dict[str, Any] | None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            "UPDATE simple_crossover_xaut_trades SET comment = ?, updated_at = ? WHERE id = ?", (comment, now, trade_id)
        )
        conn.commit()
        row = conn.execute("SELECT * FROM simple_crossover_xaut_trades WHERE id = ?", (trade_id,)).fetchone()
    return _simple_crossover_xaut_trade_from_row(row) if row else None


def _simple_crossover_xaut_trade_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "side": row["side"],
        "quantity": row["quantity"],
        "entryTime": row["entry_time"],
        "entryPrice": row["entry_price"],
        "entryEmaGap": row["entry_ema_gap"],
        "dayDirection": row["day_direction"],
        "margin": row["margin"],
        "leverage": row["leverage"],
        "status": row["status"],
        "currentPrice": row["current_price"],
        "exitTime": row["exit_time"],
        "exitPrice": row["exit_price"],
        "exitReason": row["exit_reason"],
        "realizedPnl": row["realized_pnl"],
        "comment": row["comment"],
        "createdAt": row["created_at"],
    }


def get_simple_crossover_setting(key: str) -> str | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT value FROM simple_crossover_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_simple_crossover_setting(key: str, value: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO simple_crossover_settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, now),
        )
        conn.commit()


def get_simple_crossover_xaut_setting(key: str) -> str | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT value FROM simple_crossover_xaut_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_simple_crossover_xaut_setting(key: str, value: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO simple_crossover_xaut_settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, now),
        )
        conn.commit()


def create_crypto_swing_live_trade(
    *,
    symbol: str,
    side: str,
    mode: str,
    entry_time: int,
    entry_price: float,
    size_contracts: int,
    notional_usd: float,
    stop_loss: float | None,
    order_id: str | None = None,
    note: str | None = None,
) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO crypto_swing_live_trades (
                symbol, side, mode, status, entry_time, entry_price, size_contracts,
                notional_usd, stop_loss, tranches, order_id, note, created_at, updated_at
            ) VALUES (?, ?, ?, 'open', ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
            """,
            (symbol, side, mode, entry_time, entry_price, size_contracts, notional_usd, stop_loss, order_id, note, now, now),
        )
        conn.commit()
        return int(cur.lastrowid)


def get_open_crypto_swing_live_trade(symbol: str, mode: str) -> dict[str, Any] | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM crypto_swing_live_trades WHERE symbol = ? AND mode = ? AND status = 'open' ORDER BY id DESC LIMIT 1",
            (symbol, mode),
        ).fetchone()
    return _crypto_swing_live_trade_from_row(row) if row else None


def count_open_crypto_swing_live_trades(mode: str) -> int:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM crypto_swing_live_trades WHERE mode = ? AND status = 'open'", (mode,)
        ).fetchone()
    return int(row["n"]) if row else 0


def add_crypto_swing_live_tranche(trade_id: int, *, size_contracts: int, notional_usd: float) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            UPDATE crypto_swing_live_trades
            SET size_contracts = size_contracts + ?, notional_usd = notional_usd + ?, tranches = tranches + 1, updated_at = ?
            WHERE id = ?
            """,
            (size_contracts, notional_usd, now, trade_id),
        )
        conn.commit()


def close_crypto_swing_live_trade(
    trade_id: int, *, exit_time: int, exit_price: float, exit_reason: str, pnl_usd: float
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            UPDATE crypto_swing_live_trades
            SET status = 'closed', exit_time = ?, exit_price = ?, exit_reason = ?, pnl_usd = ?, updated_at = ?
            WHERE id = ?
            """,
            (exit_time, exit_price, exit_reason, pnl_usd, now, trade_id),
        )
        conn.commit()


def list_crypto_swing_live_trades(limit: int = 200) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM crypto_swing_live_trades ORDER BY entry_time DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_crypto_swing_live_trade_from_row(row) for row in rows]


def get_today_realized_pnl_usd(mode: str, start_of_day_epoch: int) -> float:
    """Sum of pnl_usd for trades closed today (IST) in this mode -- the
    daily-loss-cap guardrail's running total. `start_of_day_epoch` is
    computed by the caller (which owns the IST timezone logic) rather than
    this module reaching for a timezone itself.
    """
    with _DB_LOCK, _connect() as conn:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(pnl_usd), 0) AS total
            FROM crypto_swing_live_trades
            WHERE mode = ? AND status = 'closed' AND exit_time >= ?
            """,
            (mode, start_of_day_epoch),
        ).fetchone()
    return float(row["total"]) if row else 0.0


def _crypto_swing_live_trade_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "symbol": row["symbol"],
        "side": row["side"],
        "mode": row["mode"],
        "status": row["status"],
        "entryTime": row["entry_time"],
        "entryPrice": row["entry_price"],
        "sizeContracts": row["size_contracts"],
        "notionalUsd": row["notional_usd"],
        "stopLoss": row["stop_loss"],
        "tranches": row["tranches"],
        "exitTime": row["exit_time"],
        "exitPrice": row["exit_price"],
        "exitReason": row["exit_reason"],
        "pnlUsd": row["pnl_usd"],
        "orderId": row["order_id"],
        "note": row["note"],
    }


# Nifty-Swing live/shadow trades -- same shape/purpose as
# crypto_swing_live_trades above, just rupee/share-quantity denominated
# (no leverage, no per-symbol dimension since Nifty-Swing trades one
# instrument).


def create_nifty_swing_live_trade(
    *,
    side: str,
    mode: str,
    entry_time: int,
    entry_price: float,
    quantity: int,
    stop_loss: float | None,
    order_id: str | None = None,
    note: str | None = None,
) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO nifty_swing_live_trades (
                side, mode, status, entry_time, entry_price, quantity,
                tranches, stop_loss, order_id, note, created_at, updated_at
            ) VALUES (?, ?, 'open', ?, ?, ?, 1, ?, ?, ?, ?, ?)
            """,
            (side, mode, entry_time, entry_price, quantity, stop_loss, order_id, note, now, now),
        )
        conn.commit()
        return int(cur.lastrowid)


def get_open_nifty_swing_live_trade(mode: str) -> dict[str, Any] | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM nifty_swing_live_trades WHERE mode = ? AND status = 'open' ORDER BY id DESC LIMIT 1",
            (mode,),
        ).fetchone()
    return _nifty_swing_live_trade_from_row(row) if row else None


def count_open_nifty_swing_live_trades(mode: str) -> int:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM nifty_swing_live_trades WHERE mode = ? AND status = 'open'", (mode,)
        ).fetchone()
    return int(row["n"]) if row else 0


def add_nifty_swing_live_tranche(trade_id: int, *, quantity: int) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            UPDATE nifty_swing_live_trades
            SET quantity = quantity + ?, tranches = tranches + 1, updated_at = ?
            WHERE id = ?
            """,
            (quantity, now, trade_id),
        )
        conn.commit()


def close_nifty_swing_live_trade(
    trade_id: int, *, exit_time: int, exit_price: float, exit_reason: str, pnl_inr: float
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            UPDATE nifty_swing_live_trades
            SET status = 'closed', exit_time = ?, exit_price = ?, exit_reason = ?, pnl_inr = ?, updated_at = ?
            WHERE id = ?
            """,
            (exit_time, exit_price, exit_reason, pnl_inr, now, trade_id),
        )
        conn.commit()


def list_nifty_swing_live_trades(limit: int = 200) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM nifty_swing_live_trades ORDER BY entry_time DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_nifty_swing_live_trade_from_row(row) for row in rows]


def get_today_realized_pnl_inr(mode: str, start_of_day_epoch: int) -> float:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(pnl_inr), 0) AS total
            FROM nifty_swing_live_trades
            WHERE mode = ? AND status = 'closed' AND exit_time >= ?
            """,
            (mode, start_of_day_epoch),
        ).fetchone()
    return float(row["total"]) if row else 0.0


def _nifty_swing_live_trade_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "side": row["side"],
        "mode": row["mode"],
        "status": row["status"],
        "entryTime": row["entry_time"],
        "entryPrice": row["entry_price"],
        "quantity": row["quantity"],
        "tranches": row["tranches"],
        "stopLoss": row["stop_loss"],
        "exitTime": row["exit_time"],
        "exitPrice": row["exit_price"],
        "exitReason": row["exit_reason"],
        "pnlInr": row["pnl_inr"],
        "orderId": row["order_id"],
        "note": row["note"],
    }


def get_equity_cache(category: str, cache_key: str, max_age_seconds: int | float | None = None) -> dict[str, Any] | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT category, cache_key, payload, updated_at FROM equity_cache WHERE category = ? AND cache_key = ?",
            (category, cache_key),
        ).fetchone()
    if not row:
        return None
    updated_at = _parse_sqlite_timestamp(row["updated_at"])
    if max_age_seconds is not None and updated_at is not None:
        age = (datetime.now(timezone.utc) - updated_at).total_seconds()
        if age > max_age_seconds:
            return None
    return {
        "category": row["category"],
        "cacheKey": row["cache_key"],
        "payload": json.loads(row["payload"]),
        "updatedAt": row["updated_at"],
    }


def list_equity_cache_by_category(category: str) -> dict[str, dict[str, Any]]:
    """All entries in a category, keyed by cache_key -- e.g. every manual
    lowest-price override, keyed by security id."""
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT cache_key, payload, updated_at FROM equity_cache WHERE category = ?", (category,)
        ).fetchall()
    return {row["cache_key"]: {"payload": json.loads(row["payload"]), "updatedAt": row["updated_at"]} for row in rows}


def delete_equity_cache(category: str, cache_key: str) -> None:
    with _DB_LOCK, _connect() as conn:
        conn.execute("DELETE FROM equity_cache WHERE category = ? AND cache_key = ?", (category, cache_key))
        conn.commit()


def upsert_equity_cache(category: str, cache_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO equity_cache(category, cache_key, payload, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(category, cache_key) DO UPDATE SET
                payload = excluded.payload,
                updated_at = CURRENT_TIMESTAMP
            """,
            (category, cache_key, json.dumps(payload)),
        )
        conn.commit()
    return payload


def upsert_equity_transactions(transactions: list[dict[str, Any]]) -> None:
    if not transactions:
        return
    with _DB_LOCK, _connect() as conn:
        conn.executemany(
            """
            INSERT INTO equity_transactions_cache(transaction_key, symbol, security_id, isin, exchange_time, payload, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(transaction_key) DO UPDATE SET
                symbol = excluded.symbol,
                security_id = excluded.security_id,
                isin = excluded.isin,
                exchange_time = excluded.exchange_time,
                payload = excluded.payload,
                updated_at = CURRENT_TIMESTAMP
            """,
            [
                (
                    str(row.get("id") or row.get("transactionKey") or ""),
                    row.get("symbol"),
                    str(row.get("securityId") or "") or None,
                    row.get("isin"),
                    row.get("exchangeTime"),
                    json.dumps(row),
                )
                for row in transactions
                if row.get("id") or row.get("transactionKey")
            ],
        )
        conn.commit()


def list_equity_transactions_cache(
    *, security_ids: set[str] | None = None, isins: set[str] | None = None, limit: int = 5000
) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if security_ids:
        placeholders = ",".join("?" for _ in security_ids)
        clauses.append(f"security_id IN ({placeholders})")
        params.extend(sorted(security_ids))
    if isins:
        placeholders = ",".join("?" for _ in isins)
        clauses.append(f"isin IN ({placeholders})")
        params.extend(sorted(isins))
    query = "SELECT payload FROM equity_transactions_cache"
    if clauses:
        query += " WHERE " + " OR ".join(clauses)
    query += " ORDER BY exchange_time DESC LIMIT ?"
    params.append(limit)
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [json.loads(row["payload"]) for row in rows]


def upsert_equity_options_transactions(rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    with _DB_LOCK, _connect() as conn:
        conn.executemany(
            """
            INSERT INTO equity_options_transactions(
                id, trade_date, underlying, expiry_date, strike, option_type, exchange, bill_no,
                buy_qty, buy_value, sell_qty, sell_value,
                brokerage, gst, stt, sebi_fees, stamp_duty, txn_charges, oth_charges,
                gross_amount, source, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                trade_date = excluded.trade_date,
                underlying = excluded.underlying,
                expiry_date = excluded.expiry_date,
                strike = excluded.strike,
                option_type = excluded.option_type,
                exchange = excluded.exchange,
                bill_no = excluded.bill_no,
                buy_qty = excluded.buy_qty,
                buy_value = excluded.buy_value,
                sell_qty = excluded.sell_qty,
                sell_value = excluded.sell_value,
                brokerage = excluded.brokerage,
                gst = excluded.gst,
                stt = excluded.stt,
                sebi_fees = excluded.sebi_fees,
                stamp_duty = excluded.stamp_duty,
                txn_charges = excluded.txn_charges,
                oth_charges = excluded.oth_charges,
                gross_amount = excluded.gross_amount,
                source = excluded.source,
                updated_at = CURRENT_TIMESTAMP
            """,
            [
                (
                    row["id"],
                    row["tradeDate"],
                    row["underlying"],
                    row.get("expiryDate"),
                    row.get("strike"),
                    row.get("optionType"),
                    row.get("exchange"),
                    row.get("billNo"),
                    row.get("buyQty"),
                    row.get("buyValue"),
                    row.get("sellQty"),
                    row.get("sellValue"),
                    row.get("brokerage"),
                    row.get("gst"),
                    row.get("stt"),
                    row.get("sebiFees"),
                    row.get("stampDuty"),
                    row.get("txnCharges"),
                    row.get("othCharges"),
                    row.get("grossAmount"),
                    row.get("source"),
                )
                for row in rows
            ],
        )
        conn.commit()
    return len(rows)


def list_equity_options_transactions(
    *, from_date: str | None = None, to_date: str | None = None
) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if from_date:
        clauses.append("trade_date >= ?")
        params.append(from_date)
    if to_date:
        clauses.append("trade_date <= ?")
        params.append(to_date)
    query = "SELECT * FROM equity_options_transactions"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY trade_date ASC"
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def _parse_sqlite_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            parsed = datetime.strptime(value, fmt)
        except ValueError:
            continue
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def save_varaha_recommendation(
    *, session_date: str, trigger: str, manual_override: str | None, snapshot: dict[str, Any], result: dict[str, Any]
) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO varaha_recommendations (session_date, trigger, manual_override, snapshot_json, result_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_date, trigger, manual_override, json.dumps(snapshot), json.dumps(result), now),
        )
        conn.commit()
        return int(cursor.lastrowid)


def _varaha_row(row: sqlite3.Row, *, include_snapshot: bool) -> dict[str, Any]:
    item = {
        "id": row["id"],
        "sessionDate": row["session_date"],
        "trigger": row["trigger"],
        "manualOverride": row["manual_override"],
        "createdAt": row["created_at"],
        "result": _json(row["result_json"]) or {},
    }
    if include_snapshot:
        item["snapshot"] = _json(row["snapshot_json"]) or {}
    return item


def get_latest_varaha_recommendation(session_date: str | None = None, *, include_snapshot: bool = False) -> dict[str, Any] | None:
    with _DB_LOCK, _connect() as conn:
        if session_date:
            row = conn.execute(
                "SELECT * FROM varaha_recommendations WHERE session_date = ? ORDER BY id DESC LIMIT 1", (session_date,)
            ).fetchone()
        else:
            row = conn.execute("SELECT * FROM varaha_recommendations ORDER BY id DESC LIMIT 1").fetchone()
    return _varaha_row(row, include_snapshot=include_snapshot) if row else None


def has_varaha_scheduled_run(session_date: str) -> bool:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM varaha_recommendations WHERE session_date = ? AND trigger = 'scheduled' LIMIT 1", (session_date,)
        ).fetchone()
    return row is not None


def list_varaha_daily_history(limit: int = 20) -> list[dict[str, Any]]:
    """Latest recommendation per session date, newest first (no snapshots)."""
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            """
            SELECT r.* FROM varaha_recommendations r
            JOIN (SELECT session_date, MAX(id) AS max_id FROM varaha_recommendations GROUP BY session_date) latest
              ON latest.max_id = r.id
            ORDER BY r.session_date DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_varaha_row(row, include_snapshot=False) for row in rows]


def get_varaha_setting(key: str) -> str | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT value FROM varaha_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_varaha_setting(key: str, value: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO varaha_settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, now),
        )
        conn.commit()


# Tag-level Net P&L target / stop loss for Manage Trades. Scoped to one
# session_date so a level set on a reused tag ("nifty") never carries over to
# the next day's new positions. status: NONE | ARMED | TRIGGERING | DONE |
# PARTIAL | FAILED -- anything past ARMED means the automatic exit has
# already fired for that tag today and must not fire again.


def _tag_level_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "tag": row["tag"],
        "sessionDate": row["session_date"],
        "target": row["target_net"],
        "stopLoss": row["stop_loss_net"],
        "targetPercent": row["target_percent"] if "target_percent" in row.keys() else None,
        "stopPercent": row["stop_percent"] if "stop_percent" in row.keys() else None,
        "premiumBase": row["premium_base"] if "premium_base" in row.keys() else None,
        "status": row["status"],
        "triggerKind": row["trigger_kind"],
        "triggerNet": row["trigger_net"],
        "triggeredAt": row["triggered_at"],
        "result": _json(row["result_json"]),
        "updatedAt": row["updated_at"],
    }


def get_tag_levels(session_date: str) -> dict[str, dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute("SELECT * FROM tag_levels WHERE session_date = ?", (session_date,)).fetchall()
    return {row["tag"]: _tag_level_row(row) for row in rows}


def upsert_tag_levels(session_date: str, tag: str, *, target: float | None, stop_loss: float | None,
                      target_percent: float | None = None, stop_percent: float | None = None,
                      premium_base: float | None = None) -> dict[str, Any]:
    """Saving levels (re-)arms the tag and clears any earlier trigger. The % fields
    record how the rupee levels were derived (a % of the tag's combined premium)."""
    now = datetime.now().isoformat(timespec="seconds")
    status = "ARMED" if target is not None or stop_loss is not None else "NONE"
    with _DB_LOCK, _connect() as conn:
        _add_column_if_missing(conn, "tag_levels", "target_percent", "REAL")
        _add_column_if_missing(conn, "tag_levels", "stop_percent", "REAL")
        _add_column_if_missing(conn, "tag_levels", "premium_base", "REAL")
        conn.execute(
            """
            INSERT INTO tag_levels (session_date, tag, target_net, stop_loss_net, target_percent, stop_percent, premium_base, status, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_date, tag) DO UPDATE SET
                target_net = excluded.target_net,
                stop_loss_net = excluded.stop_loss_net,
                target_percent = excluded.target_percent,
                stop_percent = excluded.stop_percent,
                premium_base = excluded.premium_base,
                status = excluded.status,
                trigger_kind = NULL,
                trigger_net = NULL,
                triggered_at = NULL,
                result_json = NULL,
                updated_at = excluded.updated_at
            """,
            (session_date, tag, target, stop_loss, target_percent, stop_percent, premium_base, status, now),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM tag_levels WHERE session_date = ? AND tag = ?", (session_date, tag)
        ).fetchone()
    return _tag_level_row(row)


def has_armed_tag_levels(session_date: str) -> bool:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM tag_levels WHERE session_date = ? AND status = 'ARMED' LIMIT 1", (session_date,)
        ).fetchone()
    return row is not None


def claim_tag_trigger(session_date: str, tag: str, *, kind: str, net: float) -> bool:
    """Atomically moves ARMED -> TRIGGERING. Only the caller that gets True
    may place exit orders, so a tag can never be squared off twice."""
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        cursor = conn.execute(
            """
            UPDATE tag_levels
            SET status = 'TRIGGERING', trigger_kind = ?, trigger_net = ?, triggered_at = ?, updated_at = ?
            WHERE session_date = ? AND tag = ? AND status = 'ARMED'
            """,
            (kind, net, now, now, session_date, tag),
        )
        conn.commit()
        return cursor.rowcount == 1


def finish_tag_trigger(session_date: str, tag: str, *, status: str, result: dict[str, Any]) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            "UPDATE tag_levels SET status = ?, result_json = ?, updated_at = ? WHERE session_date = ? AND tag = ?",
            (status, json.dumps(result, default=str), now, session_date, tag),
        )
        conn.commit()


# ---------------------------------------------------------------- BTC Strangle

_BTC_TRADE_FIELDS = {
    "id": "id", "mode": "mode", "session_date": "sessionDate", "expiry_code": "expiryCode",
    "settlement_time": "settlementTime", "entry_time": "entryTime", "spot": "spot", "atm_strike": "atmStrike",
    "straddle": "straddle", "multiplier": "multiplier", "distance": "distance",
    "stop_loss_percent": "stopLossPercent", "contracts": "contracts", "status": "status", "trigger": "trigger",
    "notes": "notes", "closed_at": "closedAt", "created_at": "createdAt", "variant": "variant",
}
_BTC_LEG_FIELDS = {
    "id": "id", "trade_id": "tradeId", "option_type": "optionType", "symbol": "symbol", "product_id": "productId",
    "strike": "strike", "requested_contracts": "requestedContracts", "contracts": "contracts",
    "entry_price": "entryPrice", "sl_price": "slPrice", "status": "status", "exit_price": "exitPrice",
    "exit_time": "exitTime", "exit_reason": "exitReason", "entry_order_id": "entryOrderId",
    "sl_order_id": "slOrderId", "exit_order_id": "exitOrderId", "entry_fee": "entryFee", "exit_fee": "exitFee",
    "last_mark": "lastMark", "last_bid": "lastBid", "last_ask": "lastAsk", "last_update": "lastUpdate", "error": "error",
}


def _btc_row(row: sqlite3.Row, fields: dict[str, str]) -> dict[str, Any]:
    return {camel: row[col] for col, camel in fields.items()}


def create_btc_strangle_trade(**values: Any) -> int:
    values = {**values, "created_at": datetime.now().isoformat(timespec="seconds")}
    cols = ", ".join(values)
    marks = ", ".join(f":{k}" for k in values)
    with _DB_LOCK, _connect() as conn:
        cursor = conn.execute(f"INSERT INTO btc_strangle_trades ({cols}) VALUES ({marks})", values)
        conn.commit()
        return int(cursor.lastrowid)


def create_btc_strangle_leg(**values: Any) -> int:
    cols = ", ".join(values)
    marks = ", ".join(f":{k}" for k in values)
    with _DB_LOCK, _connect() as conn:
        cursor = conn.execute(f"INSERT INTO btc_strangle_legs ({cols}) VALUES ({marks})", values)
        conn.commit()
        return int(cursor.lastrowid)


def update_btc_strangle_leg(leg_id: int, **values: Any) -> None:
    if not values:
        return
    sets = ", ".join(f"{k} = :{k}" for k in values)
    with _DB_LOCK, _connect() as conn:
        conn.execute(f"UPDATE btc_strangle_legs SET {sets} WHERE id = :leg_id", {**values, "leg_id": leg_id})
        conn.commit()


def update_btc_strangle_trade(trade_id: int, **values: Any) -> None:
    if not values:
        return
    sets = ", ".join(f"{k} = :{k}" for k in values)
    with _DB_LOCK, _connect() as conn:
        conn.execute(f"UPDATE btc_strangle_trades SET {sets} WHERE id = :trade_id", {**values, "trade_id": trade_id})
        conn.commit()


def list_btc_strangle_trades(*, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM btc_strangle_trades WHERE status = ? ORDER BY entry_time DESC LIMIT ?", (status, limit)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM btc_strangle_trades ORDER BY entry_time DESC LIMIT ?", (limit,)).fetchall()
        trades = [_btc_row(row, _BTC_TRADE_FIELDS) for row in rows]
        ids = [t["id"] for t in trades]
        legs_by_trade: dict[int, list[dict[str, Any]]] = {i: [] for i in ids}
        if ids:
            marks = ",".join("?" for _ in ids)
            for row in conn.execute(f"SELECT * FROM btc_strangle_legs WHERE trade_id IN ({marks}) ORDER BY id", ids):
                legs_by_trade[row["trade_id"]].append(_btc_row(row, _BTC_LEG_FIELDS))
    for trade in trades:
        trade["legs"] = legs_by_trade.get(trade["id"], [])
    return trades


def get_btc_strangle_trade(trade_id: int) -> dict[str, Any] | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM btc_strangle_trades WHERE id = ?", (trade_id,)).fetchone()
        if not row:
            return None
        trade = _btc_row(row, _BTC_TRADE_FIELDS)
        trade["legs"] = [
            _btc_row(leg, _BTC_LEG_FIELDS)
            for leg in conn.execute("SELECT * FROM btc_strangle_legs WHERE trade_id = ? ORDER BY id", (trade_id,))
        ]
    return trade


def has_btc_strangle_trade_for_session(session_date: str, mode: str) -> bool:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM btc_strangle_trades WHERE session_date = ? AND mode = ? AND trigger = 'scheduled' LIMIT 1",
            (session_date, mode),
        ).fetchone()
    return row is not None


def get_btc_strangle_setting(key: str) -> str | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT value FROM btc_strangle_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_btc_strangle_setting(key: str, value: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO btc_strangle_settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, now),
        )
        conn.commit()


# ---------------------------------------------------------------- Batman

_BATMAN_TRADE_FIELDS = {
    "id": "id", "mode": "mode", "session_date": "sessionDate", "trigger": "trigger", "expiry": "expiry",
    "entry_time": "entryTime", "spot": "spot", "capital": "capital", "lot_size": "lotSize", "base_lots": "baseLots",
    "buy_offset": "buyOffset", "sell_gap": "sellGap", "hedge_gap": "hedgeGap", "extra_call_lots": "extraCallLots",
    "credit": "credit", "credit_percent": "creditPercent", "target_percent": "targetPercent",
    "stop_percent": "stopPercent", "exit_by": "exitBy", "status": "status", "exit_time": "exitTime",
    "exit_reason": "exitReason", "realized_pnl": "realizedPnl", "charges": "charges", "last_mtm": "lastMtm",
    "last_update": "lastUpdate", "notes": "notes",
}
_BATMAN_LEG_FIELDS = {
    "id": "id", "trade_id": "tradeId", "action": "action", "option_type": "optionType", "role": "role",
    "strike": "strike", "lots": "lots", "security_id": "securityId", "entry_price": "entryPrice", "iv": "iv",
    "exit_price": "exitPrice", "last_ltp": "lastLtp", "last_bid": "lastBid", "last_ask": "lastAsk",
}


def create_batman_trade(legs: list[dict[str, Any]], **values: Any) -> int:
    cols = ", ".join(values)
    marks = ", ".join(f":{k}" for k in values)
    with _DB_LOCK, _connect() as conn:
        trade_id = int(conn.execute(f"INSERT INTO batman_trades ({cols}) VALUES ({marks})", values).lastrowid)
        for leg in legs:
            conn.execute(
                """
                INSERT INTO batman_legs (trade_id, action, option_type, role, strike, lots, security_id, entry_price, iv,
                                         last_ltp, last_bid, last_ask)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (trade_id, leg["action"], leg["optionType"], leg["role"], leg["strike"], leg["qty"], leg.get("securityId"),
                 leg["price"], leg.get("iv"), leg.get("ltp"), leg.get("bid"), leg.get("ask")),
            )
        conn.commit()
    return trade_id


def update_batman_trade(trade_id: int, **values: Any) -> None:
    if not values:
        return
    sets = ", ".join(f"{k} = :{k}" for k in values)
    with _DB_LOCK, _connect() as conn:
        conn.execute(f"UPDATE batman_trades SET {sets} WHERE id = :trade_id", {**values, "trade_id": trade_id})
        conn.commit()


def update_batman_leg(leg_id: int, **values: Any) -> None:
    if not values:
        return
    sets = ", ".join(f"{k} = :{k}" for k in values)
    with _DB_LOCK, _connect() as conn:
        conn.execute(f"UPDATE batman_legs SET {sets} WHERE id = :leg_id", {**values, "leg_id": leg_id})
        conn.commit()


def list_batman_trades(*, mode: str | None = None, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    clauses, params = [], []
    if mode:
        clauses.append("mode = ?")
        params.append(mode)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(f"SELECT * FROM batman_trades {where} ORDER BY entry_time DESC LIMIT ?", (*params, limit)).fetchall()
        trades = [{camel: row[col] for col, camel in _BATMAN_TRADE_FIELDS.items()} for row in rows]
        for trade in trades:
            trade["legs"] = [
                {camel: leg[col] for col, camel in _BATMAN_LEG_FIELDS.items()}
                for leg in conn.execute("SELECT * FROM batman_legs WHERE trade_id = ? ORDER BY id", (trade["id"],))
            ]
    return trades


def has_batman_trade_for_session(mode: str, session_date: str) -> bool:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM batman_trades WHERE mode = ? AND session_date = ? AND trigger = 'scheduled' LIMIT 1",
            (mode, session_date),
        ).fetchone()
    return row is not None


def record_batman_mtm(trade_id: int, time_epoch: int, mtm: float, spot: float | None) -> None:
    with _DB_LOCK, _connect() as conn:
        conn.execute("INSERT INTO batman_mtm (trade_id, time, mtm, spot) VALUES (?, ?, ?, ?)", (trade_id, time_epoch, mtm, spot))
        conn.commit()


def list_batman_mtm(trade_id: int) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute("SELECT time, mtm, spot FROM batman_mtm WHERE trade_id = ? ORDER BY time", (trade_id,)).fetchall()
    return [{"time": r["time"], "mtm": r["mtm"], "spot": r["spot"]} for r in rows]


def get_batman_setting(key: str) -> str | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT value FROM batman_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_batman_setting(key: str, value: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO batman_settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, now),
        )
        conn.commit()


# ---------------------------------------------------------------- Define Turtle

_TURTLE_TRADE_FIELDS = {
    "id": "id", "status": "status", "trigger": "trigger", "signal_time": "signalTime", "signal_rsi": "signalRsi",
    "entry_time": "entryTime", "expiry": "expiry", "spot": "spot", "lots": "lots", "lot_size": "lotSize",
    "short_strike": "shortStrike", "long_strike": "longStrike", "short_security_id": "shortSecurityId",
    "long_security_id": "longSecurityId", "short_entry": "shortEntry", "long_entry": "longEntry",
    "credit_points": "creditPoints", "short_exit": "shortExit", "long_exit": "longExit", "exit_time": "exitTime",
    "exit_reason": "exitReason", "realized_pnl": "realizedPnl", "charges": "charges", "last_cost": "lastCost",
    "last_decay": "lastDecay", "last_rsi": "lastRsi", "last_update": "lastUpdate", "mode": "mode",
    "short_order_id": "shortOrderId", "long_order_id": "longOrderId", "short_exit_order_id": "shortExitOrderId",
    "long_exit_order_id": "longExitOrderId", "needs_attention": "needsAttention", "broker": "broker",
}


def create_turtle_trade(prefix: str = "turtle", **values: Any) -> int:
    cols = ", ".join(values)
    marks = ", ".join(f":{k}" for k in values)
    with _DB_LOCK, _connect() as conn:
        cursor = conn.execute(f"INSERT INTO {prefix}_trades ({cols}) VALUES ({marks})", values)
        conn.commit()
        return int(cursor.lastrowid)


def update_turtle_trade(trade_id: int, prefix: str = "turtle", **values: Any) -> None:
    if not values:
        return
    sets = ", ".join(f"{k} = :{k}" for k in values)
    with _DB_LOCK, _connect() as conn:
        conn.execute(f"UPDATE {prefix}_trades SET {sets} WHERE id = :trade_id", {**values, "trade_id": trade_id})
        conn.commit()


def list_turtle_trades(*, status: str | None = None, limit: int = 300, prefix: str = "turtle") -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        if status:
            rows = conn.execute(f"SELECT * FROM {prefix}_trades WHERE status = ? ORDER BY entry_time DESC LIMIT ?", (status, limit)).fetchall()
        else:
            rows = conn.execute(f"SELECT * FROM {prefix}_trades ORDER BY entry_time DESC LIMIT ?", (limit,)).fetchall()
    return [{camel: row[col] for col, camel in _TURTLE_TRADE_FIELDS.items()} for row in rows]


def create_turtle_alarm(*, kind: str, title: str, message: str, trade_id: int | None, prefix: str = "turtle") -> int:
    with _DB_LOCK, _connect() as conn:
        cursor = conn.execute(
            f"INSERT INTO {prefix}_alarms (created_at, kind, title, message, trade_id) VALUES (?, ?, ?, ?, ?)",
            (int(datetime.now().timestamp()), kind, title, message, trade_id),
        )
        conn.commit()
        return int(cursor.lastrowid)


def list_turtle_alarms(*, unacknowledged_only: bool = False, limit: int = 50, prefix: str = "turtle") -> list[dict[str, Any]]:
    where = "WHERE acknowledged_at IS NULL" if unacknowledged_only else ""
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(f"SELECT * FROM {prefix}_alarms {where} ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [
        {"id": r["id"], "createdAt": r["created_at"], "kind": r["kind"], "title": r["title"], "message": r["message"],
         "tradeId": r["trade_id"], "acknowledgedAt": r["acknowledged_at"]}
        for r in rows
    ]


def acknowledge_turtle_alarm(alarm_id: int, prefix: str = "turtle") -> bool:
    with _DB_LOCK, _connect() as conn:
        cursor = conn.execute(
            f"UPDATE {prefix}_alarms SET acknowledged_at = ? WHERE id = ? AND acknowledged_at IS NULL",
            (int(datetime.now().timestamp()), alarm_id),
        )
        conn.commit()
        return cursor.rowcount == 1


def get_turtle_setting(key: str, prefix: str = "turtle") -> str | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute(f"SELECT value FROM {prefix}_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_turtle_setting(key: str, value: str, prefix: str = "turtle") -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            f"""
            INSERT INTO {prefix}_settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, now),
        )
        conn.commit()


# ---------------------------------------------------------------- Mantra

_MANTRA_TRADE_FIELDS = {
    "id": "id", "mode": "mode", "trigger": "trigger", "status": "status", "state": "state", "expiry": "expiry",
    "entry_time": "entryTime", "spot": "spot", "lots": "lots", "lot_size": "lotSize", "credit_points": "creditPoints",
    "booked": "booked", "charges": "charges", "rolls": "rolls", "exit_time": "exitTime", "exit_reason": "exitReason",
    "gross": "gross", "last_mtm": "lastMtm", "last_spot": "lastSpot", "last_update": "lastUpdate",
}
_MANTRA_LEG_FIELDS = {
    "id": "id", "trade_id": "tradeId", "option_type": "optionType", "strike": "strike", "security_id": "securityId",
    "entry": "entry", "exit": "exit", "status": "status", "opened_at": "openedAt", "closed_at": "closedAt",
    "roll_no": "rollNo", "last_ltp": "lastLtp", "last_bid": "lastBid", "last_ask": "lastAsk",
}


def _mantra_insert(table: str, values: dict[str, Any]) -> int:
    cols = ", ".join(values)
    marks = ", ".join(f":{k}" for k in values)
    with _DB_LOCK, _connect() as conn:
        cursor = conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", values)
        conn.commit()
        return int(cursor.lastrowid)


def _mantra_update(table: str, row_id: int, values: dict[str, Any]) -> None:
    if not values:
        return
    sets = ", ".join(f"{k} = :{k}" for k in values)
    with _DB_LOCK, _connect() as conn:
        conn.execute(f"UPDATE {table} SET {sets} WHERE id = :row_id", {**values, "row_id": row_id})
        conn.commit()


def create_mantra_trade(**values: Any) -> int:
    return _mantra_insert("mantra_trades", values)


def update_mantra_trade(trade_id: int, **values: Any) -> None:
    _mantra_update("mantra_trades", trade_id, values)


def create_mantra_leg(**values: Any) -> int:
    return _mantra_insert("mantra_legs", values)


def update_mantra_leg(leg_id: int, **values: Any) -> None:
    _mantra_update("mantra_legs", leg_id, values)


def list_mantra_trades(*, mode: str | None = None, status: str | None = None, limit: int = 300) -> list[dict[str, Any]]:
    clauses, params = [], []
    if mode:
        clauses.append("mode = ?"); params.append(mode)
    if status:
        clauses.append("status = ?"); params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(f"SELECT * FROM mantra_trades {where} ORDER BY entry_time DESC, id DESC LIMIT ?", (*params, limit)).fetchall()
        trades = [{camel: r[col] for col, camel in _MANTRA_TRADE_FIELDS.items()} for r in rows]
        for trade in trades:
            trade["legs"] = [
                {camel: leg[col] for col, camel in _MANTRA_LEG_FIELDS.items()}
                for leg in conn.execute("SELECT * FROM mantra_legs WHERE trade_id = ? ORDER BY id", (trade["id"],))
            ]
            trade["events"] = [
                {"time": e["time"], "kind": e["kind"], "text": e["text"]}
                for e in conn.execute("SELECT * FROM mantra_events WHERE trade_id = ? ORDER BY time", (trade["id"],))
            ]
    return trades


def add_mantra_event(trade_id: int, time_epoch: int, kind: str, text: str) -> None:
    with _DB_LOCK, _connect() as conn:
        conn.execute("INSERT INTO mantra_events (trade_id, time, kind, text) VALUES (?, ?, ?, ?)", (trade_id, time_epoch, kind, text))
        conn.commit()


def record_mantra_mtm(trade_id: int, time_epoch: int, mtm: float, spot: float | None) -> None:
    with _DB_LOCK, _connect() as conn:
        conn.execute("INSERT INTO mantra_mtm (trade_id, time, mtm, spot) VALUES (?, ?, ?, ?)", (trade_id, time_epoch, mtm, spot))
        conn.commit()


def list_mantra_mtm(trade_id: int) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute("SELECT time, mtm, spot FROM mantra_mtm WHERE trade_id = ? ORDER BY time", (trade_id,)).fetchall()
    return [{"time": r["time"], "mtm": r["mtm"], "spot": r["spot"]} for r in rows]


def create_mantra_alarm(*, kind: str, title: str, message: str, trade_id: int | None) -> int:
    return _mantra_insert("mantra_alarms", {
        "created_at": int(datetime.now().timestamp()), "kind": kind, "title": title, "message": message, "trade_id": trade_id,
    })


def list_mantra_alarms(*, unacknowledged_only: bool = False, limit: int = 50) -> list[dict[str, Any]]:
    where = "WHERE acknowledged_at IS NULL" if unacknowledged_only else ""
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(f"SELECT * FROM mantra_alarms {where} ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [
        {"id": r["id"], "createdAt": r["created_at"], "kind": r["kind"], "title": r["title"], "message": r["message"],
         "tradeId": r["trade_id"], "acknowledgedAt": r["acknowledged_at"]}
        for r in rows
    ]


def acknowledge_mantra_alarm(alarm_id: int) -> bool:
    with _DB_LOCK, _connect() as conn:
        cursor = conn.execute(
            "UPDATE mantra_alarms SET acknowledged_at = ? WHERE id = ? AND acknowledged_at IS NULL",
            (int(datetime.now().timestamp()), alarm_id),
        )
        conn.commit()
        return cursor.rowcount == 1


def get_mantra_setting(key: str) -> str | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT value FROM mantra_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_mantra_setting(key: str, value: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO mantra_settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, now),
        )
        conn.commit()


# ---------------------------------------------------------------- Melting Straddles (docs/strategies/melting-straddles.md)


def _melting_rows(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def melting_insert(table: str, values: dict[str, Any]) -> int:
    return _mantra_insert(table, values)


def melting_update_trade(trade_id: int, prefix: str = "melting", **values: Any) -> None:
    _mantra_update(f"{prefix}_trades", trade_id, values)


def get_melting_day(day: str, prefix: str = "melting") -> dict[str, Any] | None:
    rows = _melting_rows(f"SELECT * FROM {prefix}_days WHERE day = ?", (day,))
    return rows[0] if rows else None


def list_melting_days(limit: int = 120, prefix: str = "melting") -> list[dict[str, Any]]:
    return _melting_rows(f"SELECT * FROM {prefix}_days ORDER BY day DESC LIMIT ?", (limit,))


def upsert_melting_day(values: dict[str, Any], prefix: str = "melting") -> None:
    cols = ", ".join(values)
    marks = ", ".join(f":{k}" for k in values)
    updates = ", ".join(f"{k} = excluded.{k}" for k in values if k != "day")
    with _DB_LOCK, _connect() as conn:
        conn.execute(f"INSERT INTO {prefix}_days ({cols}) VALUES ({marks}) ON CONFLICT(day) DO UPDATE SET {updates}", values)
        conn.commit()


def update_melting_day(day: str, prefix: str = "melting", **values: Any) -> None:
    sets = ", ".join(f"{k} = :{k}" for k in values)
    with _DB_LOCK, _connect() as conn:
        conn.execute(f"UPDATE {prefix}_days SET {sets} WHERE day = :day", {**values, "day": day})
        conn.commit()


def list_melting_trades(*, day: str | None = None, status: str | None = None, limit: int = 500, prefix: str = "melting") -> list[dict[str, Any]]:
    clauses, params = [], []
    if day:
        clauses.append("day = ?"); params.append(day)
    if status:
        clauses.append("status = ?"); params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return _melting_rows(f"SELECT * FROM {prefix}_trades {where} ORDER BY entry_time DESC, id DESC LIMIT ?", (*params, limit))


def get_melting_trade(trade_id: int, prefix: str = "melting") -> dict[str, Any] | None:
    rows = _melting_rows(f"SELECT * FROM {prefix}_trades WHERE id = ?", (trade_id,))
    return rows[0] if rows else None


def list_melting_fills(trade_ids: list[int], prefix: str = "melting") -> list[dict[str, Any]]:
    if not trade_ids:
        return []
    marks = ", ".join("?" for _ in trade_ids)
    return _melting_rows(f"SELECT * FROM {prefix}_fills WHERE trade_id IN ({marks}) ORDER BY time, id", tuple(trade_ids))


def list_melting_events(*, day: str | None = None, trade_id: int | None = None, limit: int = 500, prefix: str = "melting") -> list[dict[str, Any]]:
    if trade_id is not None:
        return _melting_rows(f"SELECT * FROM {prefix}_events WHERE trade_id = ? ORDER BY time, id", (trade_id,))
    return _melting_rows(f"SELECT * FROM {prefix}_events WHERE day = ? ORDER BY time DESC, id DESC LIMIT ?", (day, limit))


def save_melting_minutes(rows: list[dict[str, Any]], prefix: str = "melting") -> None:
    if not rows:
        return
    with _DB_LOCK, _connect() as conn:
        conn.executemany(
            f"INSERT OR REPLACE INTO {prefix}_minutes (day, tag, time, ce, pe, combined, vwap) VALUES (:day, :tag, :time, :ce, :pe, :combined, :vwap)",
            rows,
        )
        conn.commit()


def list_melting_minutes(day: str, prefix: str = "melting") -> list[dict[str, Any]]:
    return _melting_rows(f"SELECT * FROM {prefix}_minutes WHERE day = ? ORDER BY tag, time", (day,))


def get_melting_setting(key: str, prefix: str = "melting") -> str | None:
    rows = _melting_rows(f"SELECT value FROM {prefix}_settings WHERE key = ?", (key,))
    return rows[0]["value"] if rows else None


def set_melting_setting(key: str, value: str, prefix: str = "melting") -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            f"""
            INSERT INTO {prefix}_settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, now),
        )
        conn.commit()


# ---------------------------------------------------------------- NIFTY Strangle


def nifty_strangle_insert(table: str, values: dict[str, Any]) -> int:
    return _mantra_insert(table, values)


def nifty_strangle_update(table: str, row_id: int, **values: Any) -> None:
    _mantra_update(table, row_id, values)


def list_nifty_strangle_trades(*, status: str | None = None, limit: int = 300, book: str | None = None) -> list[dict[str, Any]]:
    clauses, args = [], []
    if status:
        clauses.append("status = ?"); args.append(status)
    if book:
        clauses.append("book = ?"); args.append(book)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params: tuple = (*args, limit)
    with _DB_LOCK, _connect() as conn:
        trades = [dict(r) for r in conn.execute(
            f"SELECT * FROM nifty_strangle_trades {where} ORDER BY entry_time DESC, id DESC LIMIT ?", params
        ).fetchall()]
        for trade in trades:
            trade["legs"] = [dict(r) for r in conn.execute(
                "SELECT * FROM nifty_strangle_legs WHERE trade_id = ? ORDER BY id", (trade["id"],)
            ).fetchall()]
    return trades


def has_nifty_strangle_trade(entry_date: str, mode: str, book: str = "plain") -> bool:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM nifty_strangle_trades WHERE entry_date = ? AND mode = ? AND book = ? AND trigger IN ('scheduled', 'skipped') LIMIT 1",
            (entry_date, mode, book),
        ).fetchone()
    return row is not None


def get_nifty_strangle_setting(key: str) -> str | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT value FROM nifty_strangle_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_nifty_strangle_setting(key: str, value: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO nifty_strangle_settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, now),
        )
        conn.commit()


# ---------------------------------------------------------------- Calm Strangle (docs/strategies/calm-strangle.md)


def calm_insert(table: str, values: dict[str, Any]) -> int:
    return _mantra_insert(table, values)


def calm_update_trade(trade_id: int, prefix: str = "calm_strangle", **values: Any) -> None:
    _mantra_update(f"{prefix}_trades", trade_id, values)


def list_calm_trades(*, day: str | None = None, status: str | None = None, limit: int = 1000, prefix: str = "calm_strangle") -> list[dict[str, Any]]:
    clauses, params = [], []
    if day:
        clauses.append("day = ?"); params.append(day)
    if status:
        clauses.append("status = ?"); params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return _melting_rows(f"SELECT * FROM {prefix}_trades {where} ORDER BY entry_time DESC, id DESC LIMIT ?", (*params, limit))


def list_calm_events(day: str, limit: int = 300, prefix: str = "calm_strangle") -> list[dict[str, Any]]:
    return _melting_rows(f"SELECT * FROM {prefix}_events WHERE day = ? ORDER BY time DESC, id DESC LIMIT ?", (day, limit))


def swing_insert(table: str, values: dict[str, Any]) -> int:
    return _mantra_insert(table, values)


def swing_update(table: str, row_id: int, values: dict[str, Any]) -> None:
    _mantra_update(table, row_id, values)


def swing_rows(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    return _melting_rows(sql, params)


def swing_execute_many(sql: str, rows: list[tuple]) -> None:
    with _DB_LOCK, _connect() as conn:
        conn.executemany(sql, rows)
        conn.commit()


def get_swing_setting(key: str) -> str | None:
    rows = _melting_rows("SELECT value FROM equity_swing_settings WHERE key = ?", (key,))
    return rows[0]["value"] if rows else None


def set_swing_setting(key: str, value: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            "INSERT INTO equity_swing_settings (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, value, now),
        )
        conn.commit()


def create_alert(**values: Any) -> int:
    return _mantra_insert("alerts", values)


def update_alert(alert_id: int, **values: Any) -> None:
    _mantra_update("alerts", alert_id, values)


def list_alerts(status: str | None = None, limit: int = 300) -> list[dict[str, Any]]:
    if status:
        return _melting_rows("SELECT * FROM alerts WHERE status = ? ORDER BY id DESC LIMIT ?", (status, limit))
    return _melting_rows("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,))


def delete_alert(alert_id: int) -> None:
    with _DB_LOCK, _connect() as conn:
        conn.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
        conn.commit()


def get_manage_setting(key: str) -> str | None:
    rows = _melting_rows("SELECT value FROM manage_trades_settings WHERE key = ?", (key,))
    return rows[0]["value"] if rows else None


def set_manage_setting(key: str, value: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO manage_trades_settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, now),
        )
        conn.commit()


def get_calm_setting(key: str, prefix: str = "calm_strangle") -> str | None:
    rows = _melting_rows(f"SELECT value FROM {prefix}_settings WHERE key = ?", (key,))
    return rows[0]["value"] if rows else None


def set_calm_setting(key: str, value: str, prefix: str = "calm_strangle") -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            f"""
            INSERT INTO {prefix}_settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, now),
        )
        conn.commit()


def add_calm_mark(trade_id: int, time_epoch: int, combined: float, spot: float | None, prefix: str = "calm_strangle") -> None:
    with _DB_LOCK, _connect() as conn:
        conn.execute(f"INSERT OR REPLACE INTO {prefix}_marks (trade_id, time, combined, spot) VALUES (?, ?, ?, ?)",
                     (trade_id, time_epoch, combined, spot))
        conn.commit()


def list_calm_marks(trade_id: int, prefix: str = "calm_strangle") -> list[dict[str, Any]]:
    return _melting_rows(f"SELECT time, combined, spot FROM {prefix}_marks WHERE trade_id = ? ORDER BY time", (trade_id,))


def get_calm_trade(trade_id: int, prefix: str = "calm_strangle") -> dict[str, Any] | None:
    rows = _melting_rows(f"SELECT * FROM {prefix}_trades WHERE id = ?", (trade_id,))
    return rows[0] if rows else None


# ---------------------------------------------------------------- BTC Calm Strangle


def btc_calm_insert(table: str, values: dict[str, Any]) -> int:
    return _mantra_insert(table, values)


def btc_calm_update_trade(trade_id: int, **values: Any) -> None:
    _mantra_update("btc_calm_trades", trade_id, values)


def list_btc_calm_trades(*, status: str | None = None, expiry_code: str | None = None, book: str | None = None,
                         limit: int = 1000) -> list[dict[str, Any]]:
    clauses, params = [], []
    if book:
        clauses.append("book = ?"); params.append(book)
    if status:
        clauses.append("status = ?"); params.append(status)
    if expiry_code:
        clauses.append("expiry_code = ?"); params.append(expiry_code)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return _melting_rows(f"SELECT * FROM btc_calm_trades {where} ORDER BY entry_time DESC, id DESC LIMIT ?", (*params, limit))


def get_btc_calm_trade(trade_id: int) -> dict[str, Any] | None:
    rows = _melting_rows("SELECT * FROM btc_calm_trades WHERE id = ?", (trade_id,))
    return rows[0] if rows else None


def add_btc_calm_mark(trade_id: int, time_epoch: int, combined: float, spot: float | None) -> None:
    with _DB_LOCK, _connect() as conn:
        conn.execute("INSERT OR REPLACE INTO btc_calm_marks (trade_id, time, combined, spot) VALUES (?, ?, ?, ?)",
                     (trade_id, time_epoch, combined, spot))
        conn.commit()


def list_btc_calm_marks(trade_id: int) -> list[dict[str, Any]]:
    return _melting_rows("SELECT time, combined, spot FROM btc_calm_marks WHERE trade_id = ? ORDER BY time", (trade_id,))


def list_btc_calm_events(limit: int = 300) -> list[dict[str, Any]]:
    return _melting_rows("SELECT * FROM btc_calm_events ORDER BY time DESC, id DESC LIMIT ?", (limit,))


def get_btc_calm_setting(key: str) -> str | None:
    rows = _melting_rows("SELECT value FROM btc_calm_settings WHERE key = ?", (key,))
    return rows[0]["value"] if rows else None


def set_btc_calm_setting(key: str, value: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO btc_calm_settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, now),
        )
        conn.commit()


# ---------------------------------------------------------------- Varaha paper trading


def varaha_paper_insert(table: str, values: dict[str, Any]) -> int:
    return _mantra_insert(table, values)


def varaha_paper_update(table: str, row_id: int, **values: Any) -> None:
    _mantra_update(table, row_id, values)


def list_varaha_paper_trades(*, status: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    where = "WHERE status = ?" if status else ""
    params: tuple = (status, limit) if status else (limit,)
    with _DB_LOCK, _connect() as conn:
        trades = [dict(r) for r in conn.execute(
            f"SELECT * FROM varaha_paper_trades {where} ORDER BY entry_time DESC, id DESC LIMIT ?", params).fetchall()]
        for t in trades:
            t["legs"] = [dict(r) for r in conn.execute("SELECT * FROM varaha_paper_legs WHERE trade_id = ? ORDER BY id", (t["id"],))]
    return trades


def list_varaha_paper_events(trade_id: int | None = None, limit: int = 300) -> list[dict[str, Any]]:
    if trade_id is not None:
        return _melting_rows("SELECT * FROM varaha_paper_events WHERE trade_id = ? ORDER BY time, id", (trade_id,))
    return _melting_rows("SELECT * FROM varaha_paper_events ORDER BY time DESC, id DESC LIMIT ?", (limit,))


def add_varaha_paper_mark(trade_id: int, time_epoch: int, pnl_points: float, spot: float | None) -> None:
    with _DB_LOCK, _connect() as conn:
        conn.execute("INSERT OR REPLACE INTO varaha_paper_marks (trade_id, time, pnl_points, spot) VALUES (?, ?, ?, ?)",
                     (trade_id, time_epoch, pnl_points, spot))
        conn.commit()


def list_varaha_paper_marks(trade_id: int) -> list[dict[str, Any]]:
    return _melting_rows("SELECT time, pnl_points, spot FROM varaha_paper_marks WHERE trade_id = ? ORDER BY time", (trade_id,))


def get_varaha_recommendation(rec_id: int, *, include_snapshot: bool = False) -> dict[str, Any] | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM varaha_recommendations WHERE id = ?", (rec_id,)).fetchone()
    return _varaha_row(row, include_snapshot=include_snapshot) if row else None


# ---------------------------------------------------------------- notes


def _note_row(r: sqlite3.Row) -> dict[str, Any]:
    return {"id": r["id"], "day": r["day"], "title": r["title"], "body": r["body"],
            "tags": [t for t in (r["tags"] or "").split(",") if t], "createdAt": r["created_at"], "updatedAt": r["updated_at"]}


def list_notes() -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute("SELECT * FROM notes ORDER BY day DESC, created_at DESC").fetchall()
    return [_note_row(r) for r in rows]


def create_note(*, day: str, title: str, body: str, tags: list[str]) -> dict[str, Any]:
    now = int(datetime.now().timestamp())
    with _DB_LOCK, _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO notes (day, title, body, tags, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (day, title, body, ",".join(tags), now, now),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM notes WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _note_row(row)


def update_note(note_id: int, *, day: str, title: str, body: str, tags: list[str]) -> dict[str, Any] | None:
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            "UPDATE notes SET day = ?, title = ?, body = ?, tags = ?, updated_at = ? WHERE id = ?",
            (day, title, body, ",".join(tags), int(datetime.now().timestamp()), note_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    return _note_row(row) if row else None


def delete_note(note_id: int) -> bool:
    with _DB_LOCK, _connect() as conn:
        cursor = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        conn.commit()
        return cursor.rowcount == 1


def get_notes_summary() -> dict[str, Any] | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT payload, generated_at FROM notes_summary WHERE id = 1").fetchone()
    if not row:
        return None
    return {**json.loads(row["payload"]), "generatedAt": row["generated_at"]}


def save_notes_summary(payload: dict[str, Any]) -> None:
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            "INSERT INTO notes_summary (id, payload, generated_at) VALUES (1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload, generated_at = excluded.generated_at",
            (json.dumps(payload), int(datetime.now().timestamp())),
        )
        conn.commit()


# ---------------------------------------------------------------- P&F Lab


def pf_save_bars(market: str, bars: list[tuple[int, float]]) -> None:
    with _DB_LOCK, _connect() as conn:
        conn.executemany("INSERT OR REPLACE INTO pf_lab_bars (market, time, close) VALUES (?, ?, ?)", [(market, int(t), float(c)) for t, c in bars])
        conn.commit()


def pf_list_bars(market: str) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute("SELECT time, close FROM pf_lab_bars WHERE market = ? ORDER BY time", (market,)).fetchall()
    return [{"time": r["time"], "close": r["close"]} for r in rows]


def pf_insert_trade(values: dict[str, Any]) -> int:
    cols = ", ".join(values)
    marks = ", ".join(f":{k}" for k in values)
    with _DB_LOCK, _connect() as conn:
        cursor = conn.execute(f"INSERT INTO pf_lab_trades ({cols}) VALUES ({marks})", values)
        conn.commit()
        return int(cursor.lastrowid)


def pf_update_trade(trade_id: int, **values: Any) -> None:
    sets = ", ".join(f"{k} = :{k}" for k in values)
    with _DB_LOCK, _connect() as conn:
        conn.execute(f"UPDATE pf_lab_trades SET {sets} WHERE id = :id", {**values, "id": trade_id})
        conn.commit()


def pf_list_trades(*, market: str | None = None, horizon: str | None = None, status: str | None = None, limit: int = 2000) -> list[dict[str, Any]]:
    clauses, params = [], []
    for col, val in (("market", market), ("horizon", horizon), ("status", status)):
        if val:
            clauses.append(f"{col} = ?")
            params.append(val)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(f"SELECT * FROM pf_lab_trades {where} ORDER BY opened_at DESC, id DESC LIMIT ?", (*params, limit)).fetchall()
    return [dict(r) for r in rows]


def pf_add_event(market: str, horizon: str | None, system: str | None, kind: str, text: str) -> None:
    with _DB_LOCK, _connect() as conn:
        conn.execute("INSERT INTO pf_lab_events (time, market, horizon, system, kind, text) VALUES (?, ?, ?, ?, ?, ?)",
                     (int(datetime.now().timestamp()), market, horizon, system, kind, text))
        conn.commit()


def pf_list_events(market: str, horizon: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute("SELECT * FROM pf_lab_events WHERE market = ? AND (horizon = ? OR horizon IS NULL OR ? IS NULL) ORDER BY id DESC LIMIT ?",
                            (market, horizon, horizon, limit)).fetchall()
    return [dict(r) for r in rows]


def pf_get_setting(key: str) -> str | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT value FROM pf_lab_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def pf_set_setting(key: str, value: str) -> None:
    with _DB_LOCK, _connect() as conn:
        conn.execute("INSERT INTO pf_lab_settings (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                     (key, value, datetime.now().isoformat(timespec="seconds")))
        conn.commit()


# ---------------------------------------------------------------- 1-Min CHoCH


def choch_insert_trade(values: dict[str, Any]) -> int | None:
    cols = ", ".join(values)
    marks = ", ".join(f":{k}" for k in values)
    with _DB_LOCK, _connect() as conn:
        cursor = conn.execute(f"INSERT OR IGNORE INTO choch_trades ({cols}) VALUES ({marks})", values)
        conn.commit()
        return int(cursor.lastrowid) if cursor.rowcount else None


def choch_update_trade(trade_id: int, **values: Any) -> None:
    sets = ", ".join(f"{k} = :{k}" for k in values)
    with _DB_LOCK, _connect() as conn:
        conn.execute(f"UPDATE choch_trades SET {sets} WHERE id = :id", {**values, "id": trade_id})
        conn.commit()


def choch_list_trades(*, day: str | None = None, status: str | None = None, limit: int = 2000) -> list[dict[str, Any]]:
    clauses, params = [], []
    if day:
        clauses.append("day = ?"); params.append(day)
    if status:
        clauses.append("status = ?"); params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(f"SELECT * FROM choch_trades {where} ORDER BY entry_time DESC LIMIT ?", (*params, limit)).fetchall()
    return [dict(r) for r in rows]


def choch_get_setting(key: str) -> str | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT value FROM choch_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def choch_set_setting(key: str, value: str) -> None:
    with _DB_LOCK, _connect() as conn:
        conn.execute("INSERT INTO choch_settings (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                     (key, value, datetime.now().isoformat(timespec="seconds")))
        conn.commit()


# ---------------------------------------------------------------- order-flow recorder


def orderflow_save_minute(values: dict[str, Any]) -> None:
    cols = ", ".join(values)
    marks = ", ".join(f":{k}" for k in values)
    with _DB_LOCK, _connect() as conn:
        conn.execute(f"INSERT OR REPLACE INTO orderflow_minutes ({cols}) VALUES ({marks})", values)
        conn.commit()


def orderflow_minutes(*, day: str, security_id: str | None = None) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        if security_id:
            rows = conn.execute("SELECT * FROM orderflow_minutes WHERE day = ? AND security_id = ? ORDER BY minute_ts", (day, security_id)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM orderflow_minutes WHERE day = ? ORDER BY minute_ts", (day,)).fetchall()
    return [dict(r) for r in rows]


def orderflow_days() -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute("SELECT day, COUNT(*) AS minutes, COUNT(DISTINCT security_id) AS instruments, SUM(volume) AS volume "
                            "FROM orderflow_minutes GROUP BY day ORDER BY day DESC LIMIT 120").fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- market events (event-week rider)


def list_market_events(start: str | None = None, end: str | None = None) -> list[dict[str, Any]]:
    clauses, args = [], []
    if start:
        clauses.append("day >= ?"); args.append(start)
    if end:
        clauses.append("day <= ?"); args.append(end)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with _DB_LOCK, _connect() as conn:
        return [dict(r) for r in conn.execute(f"SELECT * FROM market_events {where} ORDER BY day, id", tuple(args)).fetchall()]


def upsert_market_event(day: str, name: str, kind: str, source: str, note: str | None = None) -> None:
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO market_events (day, name, kind, source, note, created_at) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(day, kind) DO UPDATE SET name = excluded.name, note = COALESCE(excluded.note, market_events.note)
            """,
            (day, name, kind, source, note, int(datetime.now().timestamp())),
        )
        conn.commit()


def delete_market_event(event_id: int) -> None:
    with _DB_LOCK, _connect() as conn:
        conn.execute("DELETE FROM market_events WHERE id = ?", (event_id,))
        conn.commit()


# ---------------------------------------------------------------- Kite (Zerodha) session


def get_kite_setting(key: str) -> str | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT value FROM kite_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_kite_setting(key: str, value: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO kite_settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, now),
        )
        conn.commit()
