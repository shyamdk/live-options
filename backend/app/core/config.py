from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT_DIR / "backend" / "data"


class Settings(BaseSettings):
    app_name: str = "Live Options"
    api_prefix: str = "/api"
    app_timezone: str = "Asia/Kolkata"
    database_file: str = str(DATA_DIR / "live_options.sqlite3")
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001"
    auth_enabled: bool = True
    app_auth_username: str = "admin"
    app_auth_password: str | None = None
    app_auth_secret: str | None = None
    app_auth_session_hours: int = 12

    dhan_access_token: str | None = None
    dhan_client_id: str | None = None
    dhan_pin: str | None = None
    dhan_login_pin: str | None = None
    dhan_web_pin: str | None = None
    totp_secret: str | None = None
    dhan_totp_secret: str | None = None
    dhan_auth_base_url: str = "https://auth.dhan.co"
    dhan_base_url: str = "https://api.dhan.co/v2"
    dhan_token_refresh_min_interval_seconds: float = 120.0
    dhan_token_par_url: str | None = None
    dhan_market_quote_cache_seconds: float = 60.0
    dhan_market_quote_backoff_seconds: float = 120.0
    dhan_nifty_security_id: int = 13
    dhan_sensex_security_id: int = 51
    dhan_banknifty_security_id: int = 25
    dhan_india_vix_security_id: int | None = 21

    live_order_enabled: bool = False
    live_order_product_type: str = "MARGIN"
    live_order_type: str = "MARKET"
    live_order_validity: str = "DAY"
    option_brokerage_per_order: float = 20.0
    option_gst_percent: float = 18.0
    option_stt_sell_percent: float = 0.1
    option_stamp_buy_percent: float = 0.003
    option_sebi_turnover_percent: float = 0.0001
    option_ipft_percent: float = 0.0000001
    option_nse_transaction_percent: float = 0.03503
    option_bse_transaction_percent: float = 0.0325
    spot_distance_alert_enabled: bool = True
    spot_distance_alert_percent: float = 0.5
    spot_distance_monitor_enabled: bool = True
    spot_distance_monitor_interval_seconds: int = 120
    risk_order_monitor_enabled: bool = True
    risk_order_execution_enabled: bool = False
    risk_order_monitor_interval_seconds: int = 1
    dhan_trade_book_cache_seconds: float = 30.0
    risk_order_retry_seconds: int = 60
    risk_order_alert_repeat_seconds: int = 15
    risk_order_allow_stale_ltp: bool = False
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    telegram_bot_username: str | None = None

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o"
    # Used by the Equity page's News tab (Responses API + web_search tool),
    # separate from the chat-completions model above.
    openai_base_url: str = "https://api.openai.com/v1"
    openai_news_model: str = "gpt-5.4-mini"

    # Equity page: Dhan holdings/quotes/transactions/candles + Screener.in
    # fundamentals + OpenAI news, ported from options-dash (see that repo's
    # equity.md for the full design writeup).
    screener_url: str = "https://www.screener.in"
    screener_urls: str | None = None
    login_email: str | None = None
    login_password: str | None = None
    equity_transactions_lookback_days: int = 1825
    equity_trade_history_max_pages: int = 150
    equity_fundamentals_cache_hours: int = 24
    equity_quote_cache_seconds: int = 120
    equity_price_cache_minutes: int = 1440
    equity_news_cache_hours: int = 6

    # Delta Exchange India -- key+secret HMAC-signed REST API, no browser
    # session/2FA needed for programmatic access (2FA only gates their web
    # UI login, which this app never automates).
    delta_exchange_api_key: str | None = None
    delta_exchange_api_secret: str | None = None
    delta_exchange_base_url: str = "https://api.india.delta.exchange"

    # Crypto-Swing live trading -- off by default like every new monitor
    # in this codebase. shadow_mode logs the order that WOULD be placed
    # (symbol, side, size, guardrail checks) without ever calling Delta's
    # order endpoint; only flip it off, deliberately, once shadow output
    # has been watched and trusted. Both must be set for a real order to
    # ever be sent -- live_enabled alone still only shadows.
    crypto_swing_live_enabled: bool = False
    crypto_swing_shadow_mode: bool = True
    crypto_swing_leverage: str = "10"
    crypto_swing_risk_percent_per_trade: float = 1.0
    crypto_swing_max_daily_loss_percent: float = 5.0
    crypto_swing_max_concurrent_positions: int = 3
    crypto_swing_min_margin_buffer_percent: float = 20.0
    crypto_swing_live_poll_interval_seconds: int = 60

    # Nifty-Swing live/shadow trading -- same two-flag gating as Crypto-Swing
    # above (nifty_swing_live_enabled alone still only shadows; both it and
    # shadow_mode=false are required for a real order). Runs at a fixed
    # resolution regardless of whatever the paper-trading page currently has
    # selected. Sizing is a flat share quantity (no leverage here, unlike
    # crypto), guarded by a rupee capital cap and a rupee daily-loss cap
    # rather than percent-of-wallet, since there's no Dhan fund-limit lookup
    # wired into this codebase to take a percentage of.
    nifty_swing_live_enabled: bool = False
    nifty_swing_shadow_mode: bool = True
    nifty_swing_live_resolution: str = "30m"
    nifty_swing_live_poll_interval_seconds: int = 60
    nifty_swing_live_quantity_per_tranche: int = 50
    nifty_swing_live_max_capital_rupees: float = 50_000.0
    nifty_swing_live_max_daily_loss_rupees: float = 2_000.0
    nifty_swing_live_product_type: str = "CNC"
    # Live orders only fire within the actual trading session. No separate
    # opening-minutes entry delay setting here like pStrategy-Nifty's --
    # this strategy's 30m/1h candles already can't confirm a signal before
    # a candle closes (earliest possible: 9:45), well past the opening
    # volatility window on their own.
    nifty_swing_live_session_start_time: str = "09:15"
    nifty_swing_live_session_end_time: str = "15:30"

    journal_insights_monitor_enabled: bool = True
    journal_insights_refresh_time: str = "16:00"
    journal_insights_check_interval_seconds: int = 900

    market_news_monitor_enabled: bool = True
    market_news_check_interval_seconds: int = 1200
    market_news_feed_urls: str = (
        "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms,"
        "https://www.livemint.com/rss/markets"
    )
    market_news_lookback_hours: int = 6
    market_news_max_items: int = 3

    market_calendar_monitor_enabled: bool = True
    market_calendar_check_interval_seconds: int = 14400
    market_calendar_horizon_hours: int = 48
    market_calendar_max_items: int = 2

    pcr_oi_monitor_enabled: bool = True
    pcr_oi_poll_interval_seconds: int = 180
    pcr_oi_session_start_time: str = "09:15"
    pcr_oi_session_end_time: str = "15:30"

    # Paper-only: never places a real order. Off by default like every new
    # monitor in this codebase -- opt in explicitly once verified.
    paper_trading_monitor_enabled: bool = False
    paper_trading_poll_interval_seconds: int = 60
    paper_trading_session_start_time: str = "09:15"
    paper_trading_session_end_time: str = "15:30"
    # OI early-signal paper trades (29 Oct 2026 review): square off at 15:15
    # (the old 15:30 check could never fire, so trades were carried
    # overnight) and take no new entries after 14:30.
    paper_trading_square_off_time: str = "15:15"
    paper_trading_last_entry_time: str = "14:30"

    # pStrategy-Nifty: paper-only, buys ATM CE/PE on a pStrategy-style
    # momentum breakout in NIFTY spot at 1m/3m. Off by default like every
    # new monitor in this codebase. stop_loss_percent is the hard backstop
    # on the option premium itself (on top of the EMA/ATR exit mirrored
    # from pStrategy -- see check_ema_trail_exit in pstrategy.py).
    pstrategy_nifty_monitor_enabled: bool = False
    pstrategy_nifty_poll_interval_seconds: int = 30
    pstrategy_nifty_session_start_time: str = "09:15"
    pstrategy_nifty_session_end_time: str = "15:30"
    # The engine watches/manages positions across the full session above,
    # but new ENTRIES are held back until session_start + this many minutes
    # -- the opening minutes of NSE trading are known to whipsaw, and a 1m/
    # 3m breakout signal is exactly the kind of fast, noisy timeframe that's
    # most exposed to it.
    pstrategy_nifty_entry_delay_minutes: int = 15
    pstrategy_nifty_stop_loss_percent: float = 35.0
    pstrategy_nifty_lots: int = 1
    pstrategy_nifty_lot_size: int = 65
    # Book profit outright once NIFTY's own RSI(14) reaches a genuinely
    # overbought/oversold extreme -- same rule as pStrategy's, checked
    # ahead of the underlying EMA-hold/ATR-trail exit (see
    # check_ema_trail_exit in pstrategy.py).
    pstrategy_nifty_rsi_long_exit: float = 90.0
    pstrategy_nifty_rsi_short_exit: float = 20.0

    # PE-CE Crossover: paper-only, buys ATM CE/PE when EMA8 crosses EMA21 on
    # the OPTION'S OWN premium candles -- not the underlying, unlike every
    # other options strategy in this codebase (pStrategy-Nifty, ema5,
    # gamma_blast). CE and PE are independent signal streams; see
    # pe_ce_crossover.py. Off by default like every new monitor here.
    pe_ce_crossover_monitor_enabled: bool = False
    pe_ce_crossover_poll_interval_seconds: int = 30
    pe_ce_crossover_session_start_time: str = "09:15"
    pe_ce_crossover_session_end_time: str = "15:30"
    # Comma-separated; NIFTY only by default, BANKNIFTY/SENSEX selectable.
    pe_ce_crossover_underlyings: str = "NIFTY"
    pe_ce_crossover_lots: int = 1
    # Spec asks to "select one stop-loss mode explicitly" -- percentage of
    # entry premium is the mode implemented first; ATR-on-option-candles is
    # a later configurable mode, not built yet.
    pe_ce_crossover_stop_loss_percent: float = 30.0
    pe_ce_crossover_target_percent: float = 50.0
    pe_ce_crossover_trail_arm_percent: float = 20.0
    pe_ce_crossover_trail_percent: float = 10.0
    pe_ce_crossover_max_capital_rupees: float = 50_000.0
    pe_ce_crossover_max_daily_loss_rupees: float = 5_000.0
    pe_ce_crossover_max_trades_per_day: int = 6
    pe_ce_crossover_cooldown_minutes: int = 15
    # "total": at most one open position across both CE and PE combined.
    # "per_side": one CE and one PE can be open at the same time.
    pe_ce_crossover_position_mode: str = "total"
    # Premium expansion filter (spec Section 6): the closing premium must
    # have moved at least this percent over the lookback below before a
    # crossover is actionable -- rules out a crossover on a dead/flat premium.
    pe_ce_crossover_min_premium_expansion_percent: float = 5.0
    pe_ce_crossover_premium_expansion_lookback_bars: int = 3
    pe_ce_crossover_max_spread_percent: float = 3.0
    pe_ce_crossover_max_quote_age_seconds: int = 90
    # DTE 0/1 avoidance (spec Section 3): None means the automatic DTE-0/1
    # -> next-expiry policy in pe_ce_expiry.py; set to an explicit expiry
    # string to override it (logged when set).
    pe_ce_crossover_expiry_policy_override: str | None = None

    # Phase 2 broker integration -- two-flag gate mirrors
    # nifty_swing_live_enabled/nifty_swing_shadow_mode. While live_enabled is
    # false (default), every trade is mode="paper" and no order/reconciliation
    # code runs at all -- byte-identical to Phase 1. Once live_enabled=true,
    # shadow_mode (default true) decides whether the same decision path tags
    # trades "shadow" (no Dhan order call, just a note) or "live" (real
    # order). A real order additionally still requires the global
    # live_order_enabled kill switch to be true -- see orders.py.
    pe_ce_crossover_live_enabled: bool = False
    pe_ce_crossover_shadow_mode: bool = True
    # INTRADAY, not the global default MARGIN -- gives Dhan's own
    # auto-square-off as a second safety net behind this strategy's own
    # mandatory EOD close, since it never holds overnight.
    pe_ce_crossover_live_order_product_type: str = "INTRADAY"

    # Phase 3a: Telegram alerts on entry/exit/guardrail-blocked/live-order-
    # failure/reconciliation-mismatch only -- not on every routine tick.
    pe_ce_crossover_telegram_alerts_enabled: bool = True

    # Simple Cross Over: paper-only entries on the day-direction-matched
    # side's EMA8/EMA21 cross-over, with fixed stop, staged targets, and a
    # mandatory EOD close. Off by default.
    simple_crossover_monitor_enabled: bool = False
    simple_crossover_poll_interval_seconds: int = 30
    simple_crossover_session_start_time: str = "09:15"
    simple_crossover_session_end_time: str = "15:30"
    simple_crossover_stop_loss_percent: float = 8.0

    # Simple Cross Over - XAUT: same strategy applied to XAUTUSD on Delta
    # Exchange -- a single spot/perp instrument (no CE/PE pair), 24/7
    # market. Up day -> long on an up-crossover; Down day -> short on a
    # down-crossover (the mirror signal, since there's no separate
    # PE-equivalent instrument to buy). Exits mirror by side: long exits on
    # cross-under or RSI >= rsi_long_exit; short exits on cross-over or RSI
    # <= rsi_short_exit -- same two-threshold pattern pStrategy-Nifty
    # already uses for long/short RSI-extreme exits. No NSE session window
    # (polls continuously); "EOD" becomes a midnight-IST square-off instead.
    # Paper-only -- position size is modeled as margin x leverage (Delta
    # Exchange lets XAUTUSD perpetuals go up to 50x), same as the archived
    # pStrategy engine, so P&L/charges can be shown as a % of margin (the
    # number that actually reflects capital efficiency) as well as in $.
    simple_crossover_xaut_monitor_enabled: bool = False
    simple_crossover_xaut_poll_interval_seconds: int = 30
    # RSI-extreme exit thresholds -- bootstrap defaults only, overridden by
    # the DB-backed runtime config (simple_crossover_xaut_settings) once the
    # user edits them from the UI, same as the day-direction filter toggle.
    simple_crossover_xaut_rsi_long_exit: float = 92.0
    simple_crossover_xaut_rsi_short_exit: float = 8.0
    simple_crossover_xaut_max_gap_from_crossover_percent: float = 0.5
    # Bootstrap defaults only -- overridden by the DB-backed runtime config
    # once edited from the UI. quantity (XAUTUSD units) at entry = margin *
    # leverage / entry price.
    simple_crossover_xaut_margin_per_trade: float = 50.0
    simple_crossover_xaut_leverage: float = 50.0
    # Delta's published taker commission for the XAUTUSD perpetual --
    # confirmed live via GET /v2/products/XAUTUSD (taker_commission_rate:
    # 0.0001 = 0.01%; maker is the same), same verified rate the archived
    # pStrategy engine used. Charged on both the entry and exit legs'
    # notional (price * quantity), same as a real taker fill.
    simple_crossover_xaut_taker_fee_percent: float = 0.01
    # Entry EMA-gap filter bootstrap defaults -- see the
    # ENTRY_GAP_FILTER_SETTING_KEY comment in simple_crossover_xaut.py for
    # the analysis behind these numbers.
    simple_crossover_xaut_min_entry_gap: float = 0.06
    simple_crossover_xaut_max_entry_gap: float = 0.25

    # Mantra (docs/strategies/mantra.md): NIFTY naked short strangle with roll-in
    # adjustments, monthly + weekly. Paper only.
    mantra_monitor_enabled: bool = True

    # BTC Calm Strangle (docs/strategies/btc-calm-strangle.md): Calm Strangle's idea on Delta
    # BTC daily options, overnight IST only. Paper by default; live needs
    # btc_calm_live_order_enabled AND the page mode set to live.
    btc_calm_monitor_enabled: bool = True
    btc_calm_live_order_enabled: bool = False

    # Calm Strangle (docs/strategies/calm-strangle.md): intraday NIFTY short strangle sold
    # only after the market settles. Paper by default; live needs
    # calm_strangle_live_order_enabled AND page mode live (+ live_order_enabled).
    calm_strangle_monitor_enabled: bool = True
    calm_strangle_live_order_enabled: bool = False
    # Calm Strangle - OR (opening-range filter), paper only
    calm_or_monitor_enabled: bool = True

    # NIFTY Strangle: BTC Strangle's rules on NIFTY weekly options -- sell an
    # OTM CE + PE at spot +- multiplier x ATM straddle at 15:15 the trading
    # day before expiry, per-leg stop, buy back or let expire on expiry day.
    # Paper by default; real orders need nifty_strangle_live_order_enabled
    # AND the page's mode set to live (plus the global live_order_enabled).
    nifty_strangle_monitor_enabled: bool = True
    nifty_strangle_live_order_enabled: bool = False

    # Melting Straddles (docs/strategies/melting-straddles.md): intraday NIFTY (Fri/Mon/Tue)
    # / Sensex (Wed/Thu) straddle decay on P&F combined-premium + VWAP.
    # Paper by default; real Dhan orders need BOTH melting_live_order_enabled
    # (env kill switch) AND the page's mode set to live, plus the global
    # live_order_enabled switch (orders.py).
    melting_monitor_enabled: bool = True
    melting_live_order_enabled: bool = False
    melting_live_order_product_type: str = "INTRADAY"

    # Define Turtle (docs/strategies/define-turtle.md): NIFTY P&F RSI + Turtle Follow-Through
    # -> next-week put credit spread. Paper only.
    turtle_monitor_enabled: bool = True

    # Batman (docs/sources/batman-option-strategy-guide.pdf): NIFTY 1:3:2 double ratio
    # spread, monthly per the rulebook + a weekly variant. Paper only.
    batman_monitor_enabled: bool = True

    # BTC Strangle (docs/sources/bitcoin-strangle.pdf): sells an OTM BTC call + put on
    # Delta Exchange India every night, strikes at spot +- multiplier x ATM
    # straddle, per-leg stop loss. Paper by default; live orders need BOTH
    # btc_strangle_live_order_enabled (env kill switch) AND the page's mode
    # set to live. Every value below except the kill switch is only a
    # bootstrap default -- the page's settings (DB) override them.
    btc_strangle_monitor_enabled: bool = True
    btc_strangle_live_order_enabled: bool = False
    btc_strangle_poll_interval_seconds: int = 15
    btc_strangle_entry_time: str = "22:30"
    btc_strangle_entry_window_end: str = "22:45"
    btc_strangle_expiry_offset: int = 2
    btc_strangle_strike_multiplier: float = 1.8
    btc_strangle_stop_loss_percent: float = 100.0
    btc_strangle_contracts: int = 500
    btc_strangle_expiry_exit_time: str = "17:25"
    btc_strangle_expiry_buyback_threshold: float = 5.0
    btc_strangle_min_available_balance: float = 2000.0
    btc_strangle_entry_fill_timeout_seconds: int = 60
    # Delta options fee: min(taker rate x underlying notional, premium cap x
    # premium), plus 18% GST -- product values confirmed via /v2/products.
    btc_strangle_taker_fee_rate: float = 0.0001
    btc_strangle_premium_fee_cap: float = 0.035
    btc_strangle_gst_rate: float = 0.18

    # Varaha: NIFTY adaptive daily strategy -- recommendation only (no
    # orders, no paper trades). Takes one snapshot at the decision time,
    # stores it, and ranks candidate structures with OpenAI. All thresholds
    # are research starting points from the spec, not calibrated values.
    varaha_monitor_enabled: bool = True
    # Varaha paper trading: auto-trades each 15:00 decision (UP -> CE
    # butterfly, DOWN -> PE butterfly, flat -> defined-risk strangle).
    # Live orders need varaha_live_order_enabled AND the paper page's mode
    # set to live (plus the global live_order_enabled).
    varaha_paper_enabled: bool = True
    # Price alerts + date reminders (app/services/alerts.py): portal alarm + Telegram.
    alerts_monitor_enabled: bool = True
    # Daily Dhan Data API plan check + Telegram alerts on login/data failures.
    dhan_health_monitor_enabled: bool = True
    # Equity-Swing (app/services/equity_swing.py): weekly NIFTY 200 momentum
    # rotation. Paper by default; live orders go to Angel One only when the
    # page's mode is live AND both switches below are true.
    equity_swing_monitor_enabled: bool = True
    equity_swing_live_order_enabled: bool = False
    angel_api_key: str | None = None
    angel_client_id: str | None = None
    angel_pin: str | None = None
    angel_totp_secret: str | None = None
    varaha_live_order_enabled: bool = False
    varaha_decision_time: str = "15:00"
    varaha_min_dte: int = 2
    varaha_max_dte: int = 12
    varaha_max_expiries: int = 2
    varaha_lot_size: int = 65
    varaha_lots: int = 1
    varaha_max_loss_inr: float = 50000.0
    varaha_big_move_score: int = 6
    varaha_watch_score: int = 4
    varaha_em_atr_normal: float = 0.9
    varaha_em_atr_elevated: float = 1.2
    varaha_vix_sharp_rise_percent: float = 5.0
    varaha_direction_confidence_percent: float = 65.0
    varaha_min_reward_risk: float = 1.0
    varaha_loss_width_em_target: float = 0.75
    varaha_max_spread_points: float = 2.0
    varaha_max_spread_percent: float = 20.0
    varaha_ai_top_n: int = 3

    # Logs each new oi_signal_engine poll to oi_upgraded_signal_log (phase 5
    # signal history) -- read-only, no order placement, off by default.
    oi_upgraded_monitor_enabled: bool = False
    oi_upgraded_poll_interval_seconds: int = 180
    oi_upgraded_session_start_time: str = "09:15"
    oi_upgraded_session_end_time: str = "15:30"

    gamma_blast_monitor_enabled: bool = True
    gamma_blast_mode: str = "PAPER"
    gamma_blast_paper_auto_approve: bool = True
    gamma_blast_capital_base: float = 200000.0
    gamma_blast_risk_percent_per_trade: float = 1.5
    gamma_blast_max_lots_per_trade: int = 3
    gamma_blast_nifty_expiry_weekday: int = 1
    gamma_blast_sensex_expiry_weekday: int = 3
    gamma_blast_strike_range: int = 12
    gamma_blast_nifty_lot_size: int = 65
    gamma_blast_sensex_lot_size: int = 20
    gamma_blast_nifty_strike_step: float = 50.0
    gamma_blast_sensex_strike_step: float = 100.0
    gamma_blast_min_oi_threshold: float = 200000.0
    gamma_blast_wall_buffer_points: float = 5.0
    gamma_blast_quiet_day_max_percent: float = 1.0
    gamma_blast_entry_window_start: str = "14:00"
    gamma_blast_entry_window_end: str = "15:00"
    gamma_blast_force_exit_time: str = "15:20"
    gamma_blast_scale_out_percent: float = 45.0
    gamma_blast_hard_stop_percent: float = -27.0
    gamma_blast_blast_failed_minutes: int = 15
    gamma_blast_evaluation_interval_seconds: int = 3
    gamma_blast_alert_repeat_seconds: int = 15
    gamma_blast_reconciliation_interval_seconds: int = 45
    gamma_blast_retrospective_time: str = "15:35"
    gamma_blast_session_start_time: str = "09:15"
    gamma_blast_session_end_time: str = "15:40"

    ema5_monitor_enabled: bool = True
    ema5_mode: str = "PAPER"
    ema5_paper_auto_approve: bool = True
    ema5_lot_size: int = 65
    ema5_lots_per_trade: int = 3
    ema5_strike_step: float = 50.0
    ema5_min_sl_points: float = 15.0
    ema5_max_trades_per_day_per_side: int = 3
    ema5_max_consecutive_sl_per_side: int = 3
    ema5_pe_interval_minutes: int = 5
    ema5_ce_interval_minutes: int = 15
    ema5_ema_period: int = 5
    ema5_session_start_time: str = "09:15"
    ema5_session_end_time: str = "15:25"
    ema5_force_exit_time: str = "15:20"
    ema5_evaluation_interval_seconds: int = 3
    ema5_candle_poll_interval_seconds: int = 30
    ema5_alert_repeat_seconds: int = 15

    animesh_monitor_enabled: bool = True
    animesh_mode: str = "PAPER"
    animesh_paper_auto_approve: bool = True
    animesh_lot_size: int = 65
    animesh_lots_per_trade: int = 3
    animesh_strike_step: float = 50.0
    animesh_execution_interval_minutes: int = 1
    animesh_macd_fast: int = 8
    animesh_macd_slow: int = 21
    animesh_macd_signal: int = 8
    animesh_ema_band_period: int = 21
    animesh_large_candle_multiplier: float = 1.5
    animesh_max_consecutive_sl_per_side: int = 3
    animesh_gap_threshold_points: float = 100.0
    animesh_gap_delay_minutes: int = 10
    animesh_daily_bias_lookback_days: int = 20
    animesh_session_start_time: str = "09:15"
    animesh_session_end_time: str = "15:30"
    animesh_entry_window_1_start: str = "09:30"
    animesh_entry_window_1_end: str = "11:00"
    animesh_entry_window_2_start: str = "14:00"
    animesh_entry_window_2_end: str = "15:30"
    animesh_force_exit_time: str = "15:25"
    animesh_evaluation_interval_seconds: int = 3
    animesh_candle_poll_interval_seconds: int = 15
    animesh_alert_repeat_seconds: int = 15

    theta_monitor_enabled: bool = True
    theta_mode: str = "PAPER"
    theta_paper_auto_approve: bool = True
    theta_lots_per_tranche: int = 2
    theta_max_tranches_per_position: int = 5
    theta_nifty_lot_size: int = 65
    theta_sensex_lot_size: int = 20
    theta_nifty_strike_step: float = 50.0
    theta_sensex_strike_step: float = 100.0
    theta_max_concurrent_margin: float = 2_600_000.0
    theta_estimated_margin_per_lot_nifty: float = 50_000.0
    theta_estimated_margin_per_lot_sensex: float = 65_000.0
    theta_band_wide_min_pct: float = 1.8
    theta_band_wide_max_pct: float = 2.4
    theta_band_morning_min_pct: float = 0.9
    theta_band_morning_max_pct: float = 1.3
    theta_band_tight_min_pct: float = 0.5
    theta_band_tight_max_pct: float = 0.9
    theta_hard_floor_pct: float = 0.35
    theta_add_trigger_premium_pct: float = 30.0
    theta_distance_stop_pct: float = 0.15
    theta_distance_stop_min_minutes_left: int = 30
    theta_premium_stop_multiple: float = 2.5
    theta_force_exit_time: str = "15:20"
    theta_max_daily_loss: float = 104_000.0
    theta_max_concurrent_positions: int = 20
    theta_session_start_time: str = "09:15"
    theta_session_end_time: str = "15:30"
    theta_entry_window_1_start: str = "10:00"
    theta_entry_window_1_end: str = "10:30"
    theta_entry_window_2_start: str = "13:00"
    theta_entry_window_2_end: str = "15:00"
    theta_opening_range_minutes: int = 45
    theta_opening_range_pct: float = 0.3
    theta_vix_lookback_days: int = 5
    theta_entry_scan_interval_seconds: int = 5
    theta_chain_poll_interval_seconds: int = 20
    theta_alert_repeat_seconds: int = 15

    credit_spread_monitor_enabled: bool = True
    credit_spread_mode: str = "PAPER"
    credit_spread_paper_auto_approve: bool = True
    credit_spread_lot_size: int = 30
    credit_spread_lots: int = 1
    credit_spread_capital_base: float = 150000.0
    credit_spread_entry_time: str = "09:45"
    credit_spread_entry_window_end: str = "14:30"
    credit_spread_exit_time: str = "09:20"
    credit_spread_exit_trading_days_before_expiry: int = 10
    credit_spread_hedge_premium_target: float = 100.0
    credit_spread_min_net_credit: float = 500.0
    credit_spread_min_credit_width_percent: float = 22.0
    credit_spread_max_entry_vix: float = 24.0
    credit_spread_profit_target_percent: float = 50.0
    credit_spread_hard_stop_credit_multiple: float = 0.0
    credit_spread_allow_late_entry: bool = True
    credit_spread_min_entry_trading_days_left: int = 12
    credit_spread_skip_dates: str = ""
    credit_spread_session_start_time: str = "09:15"
    credit_spread_session_end_time: str = "15:30"
    credit_spread_evaluation_interval_seconds: int = 30
    credit_spread_chain_poll_interval_seconds: int = 180
    credit_spread_expiry_refresh_seconds: int = 900
    credit_spread_alert_repeat_seconds: int = 300
    # NSE trading holidays (yyyy-mm-dd, comma separated). Drives the
    # trading-days-to-expiry countdown, so keep it current from the official
    # NSE holiday circular each January — a missing holiday shifts the
    # T-10 exit one day late.
    # Defaults mirror ops/trade_instance_scheduler.py (Zerodha holiday calendar);
    # keep both in sync when the next year's circular is published.
    nse_holidays: str = (
        "2026-01-15,2026-01-26,2026-03-03,2026-03-26,2026-03-31,2026-04-03,"
        "2026-04-14,2026-05-01,2026-05-28,2026-06-26,2026-09-14,2026-10-02,"
        "2026-10-20,2026-11-10,2026-11-24,2026-12-25"
    )

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def market_news_feed_url_list(self) -> list[str]:
        return [url.strip() for url in self.market_news_feed_urls.split(",") if url.strip()]

    @property
    def resolved_dhan_client_id(self) -> str | None:
        return self.dhan_client_id

    @property
    def resolved_openai_api_key(self) -> str | None:
        return self.openai_api_key

    @field_validator("dhan_india_vix_security_id", mode="before")
    @classmethod
    def blank_int_as_none(cls, value):
        return None if value == "" else value


@lru_cache
def get_settings() -> Settings:
    return Settings()
