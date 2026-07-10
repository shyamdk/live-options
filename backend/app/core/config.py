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

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

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
