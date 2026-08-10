from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str
    database_path: str = "data/avito_watcher.sqlite3"
    min_check_interval_minutes: int = 5
    log_level: str = "INFO"
    # Optional HTTP/HTTPS proxy URL for access to Telegram Bot API.
    telegram_proxy: str | None = None
    # Bound database growth. Older IDs may be treated as new if they reappear.
    max_seen_listings_per_watch: int = Field(default=5000, ge=100)
    seen_listing_retention_days: int = Field(default=90, ge=1)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
