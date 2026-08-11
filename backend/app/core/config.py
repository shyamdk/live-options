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

    @field_validator("dhan_india_vix_security_id", mode="before")
    @classmethod
    def blank_int_as_none(cls, value):
        return None if value == "" else value


@lru_cache
def get_settings() -> Settings:
    return Settings()
