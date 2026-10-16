"""Environment-based configuration (secrets never hard-coded).

All credentials come from environment variables / ``.env`` and stay server-side.
Settings that an administrator tunes at runtime (universe, risk, scheduling,
auto-trading) live in the database :class:`~app.models.Settings` row, not here.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Application
    app_env: str = "development"
    secret_key: str = "dev-insecure-secret-change-me"
    log_level: str = "INFO"

    # Database
    database_url: str = "sqlite:///./data/app.db"

    # Admin bootstrap
    admin_username: str = "admin"
    admin_password: str = "admin"

    # Dhan
    dhan_client_id: str = ""
    dhan_access_token: str = ""
    dhan_api_base: str = "https://api.dhan.co/v2"
    dhan_rate_limit_rps: float = 5.0

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_api_base: str = "https://api.openai.com/v1"
    openai_timeout_seconds: float = 40.0

    # News
    news_api_key: str = ""
    news_api_base: str = "https://newsapi.org/v2"

    # Scheduler
    scheduler_enabled: bool = True
    scan_interval_minutes: int = 30

    @property
    def dhan_configured(self) -> bool:
        return bool(self.dhan_client_id and self.dhan_access_token)

    @property
    def openai_configured(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def news_configured(self) -> bool:
        return bool(self.news_api_key)


@lru_cache
def get_config() -> Config:
    return Config()
