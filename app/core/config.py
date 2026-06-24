# app/core/config.py
"""
Central configuration using pydantic-settings.
Reads from environment variables / .env file automatically.
All settings are typed and validated at startup — no silent misconfigs.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ───────────────────────────────────────────
    APP_NAME: str = "Real-Time Signal Anomaly Detection Platform"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = Field(default=False)
    ENVIRONMENT: str = Field(default="development")  # development | production

    # ── Database ──────────────────────────────────────────────
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/anomaly_db"
    )
    # Sync URL used by Alembic (alembic doesn't support asyncpg natively)
    DATABASE_SYNC_URL: str = Field(
        default="postgresql+psycopg2://postgres:postgres@localhost:5432/anomaly_db"
    )

    # ── Redis ─────────────────────────────────────────────────
    REDIS_URL: str = Field(default="redis://localhost:6379/0")

    # ── Security ──────────────────────────────────────────────
    SECRET_KEY: str = Field(default="change-me-in-production-use-secrets-module")

    # ── ML ────────────────────────────────────────────────────
    DEFAULT_ANOMALY_MODEL: str = Field(default="isolation_forest")
    ANOMALY_THRESHOLD: float = Field(default=0.5)


# Singleton — import this everywhere instead of re-instantiating
settings = Settings()