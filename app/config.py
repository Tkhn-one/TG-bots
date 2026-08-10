from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str
    task_database_path: str = "data/task_planner.sqlite3"
    log_level: str = "INFO"
    telegram_proxy: str | None = None
    completed_task_retention_days: int = Field(default=30, ge=1, le=365)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
