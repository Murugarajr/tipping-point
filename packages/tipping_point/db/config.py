"""Validated database configuration for Tipping Point."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseConfig(BaseSettings):
    """PostgreSQL connection settings, validated from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="TIPPING_POINT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "localhost"
    port: int = 5432
    user: str = "tipping_point_app"
    password: str = ""
    name: str = "tipping_point_dev"
    pool_size: int = 5
    max_overflow: int = 10
    pool_timeout: int = 30
    pool_recycle: int = 300
    pool_pre_ping: bool = True

    def is_configured(self) -> bool:
        """Return True when the configuration points at a usable database."""
        return bool(self.host and self.user and self.name)

    @property
    def database_url(self) -> str:
        """Build a synchronous psycopg3 SQLAlchemy URL."""
        return (
            f"postgresql+psycopg://{self.user}"
            f":{self.password}@{self.host}:{self.port}/{self.name}"
        )

    def validate_for_engine(self) -> None:
        """Raise ValueError if the configuration is unsafe for an engine."""
        if not self.host:
            raise ValueError("TIPPING_POINT_HOST must be set")
        if not self.user:
            raise ValueError("TIPPING_POINT_USER must be set")
        if not self.name:
            raise ValueError("TIPPING_POINT_NAME must be set")
        if self.port <= 0 or self.port > 65535:
            raise ValueError("TIPPING_POINT_PORT must be between 1 and 65535")
        if self.pool_size < 1:
            raise ValueError("TIPPING_POINT_POOL_SIZE must be >= 1")
        if self.max_overflow < 0:
            raise ValueError("TIPPING_POINT_MAX_OVERFLOW must be >= 0")