from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Forex Intelligence Lab"
    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8088
    app_secret_key: str = "change-me-to-a-long-random-string"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://127.0.0.1:8088"

    dashboard_username: str = "admin"
    dashboard_password: str = "change-me-strong-password"
    jwt_expire_minutes: int = 720
    jwt_algorithm: str = "HS256"

    database_url: str = "postgresql+psycopg://orakool@localhost:5432/forex_intelligence"

    mt5_mode: str = "mock"
    mt5_login: int | None = None
    mt5_password: str = ""
    mt5_server: str = ""
    mt5_terminal_path: str = ""
    mt5_timeout_ms: int = 60000
    # Broker server clock offset from UTC in minutes. None auto-detects from a live
    # tick on connect. Pin it when the market is closed at startup (FBS = 120 in
    # winter, 180 in summer).
    mt5_server_utc_offset_minutes: int | None = None
    # macOS Wine bridge (MT5_MODE=bridge). Windows official/agent ignore these.
    mt5_bridge_host: str = "127.0.0.1"
    mt5_bridge_port: int = 18813

    agent_api_key: str = "change-me-agent-api-key"
    saas_api_key: str = "local-fil-saas-key-2026"

    collector_interval_seconds: int = 5
    default_timeframes: str = "M5"
    seed_history_days: int = 30
    # When true, the collector backfills SEED_HISTORY_DAYS for thin instruments
    # via the active MT5 adapter (bridge/official/mock). Agent mode skips this.
    auto_backfill: bool = True

    prediction_threshold: float = 0.55
    spread_cost_pips: float = 0.8
    transaction_cost_pips: float = 0.2

    stale_candle_seconds: int = 180
    large_spread_pips: float = 5.0
    # Relative width; a BTC $20 spread is ~3 bps and must not trip the FX pip gate.
    large_spread_bps: float = 8.0
    alert_probability_threshold: float = 0.70

    @field_validator("mt5_login", mode="before")
    @classmethod
    def empty_login(cls, value):
        if value in ("", None):
            return None
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def is_mock(self) -> bool:
        return self.mt5_mode.lower() == "mock"

    @property
    def is_agent_mode(self) -> bool:
        return self.mt5_mode.lower() == "agent"

    @property
    def is_official_mode(self) -> bool:
        return self.mt5_mode.lower() == "official"

    @property
    def is_bridge_mode(self) -> bool:
        return self.mt5_mode.lower() == "bridge"


@lru_cache
def get_settings() -> Settings:
    return Settings()
