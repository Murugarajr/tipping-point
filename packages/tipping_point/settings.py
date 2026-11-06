"""Application settings for cookies, sessions, origins, and throttling.

All values are environment-driven via the TIPPING_POINT_ prefix (same
prefix as the database settings; unrelated keys are ignored). Hosted
environments must set TIPPING_POINT_ENV=hosted and
TIPPING_POINT_COOKIE_SECURE=true; the application refuses to serve
authentication in hosted mode without secure cookies.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

SESSION_COOKIE_NAME = "tipping_session"
CSRF_COOKIE_NAME = "tipping_csrf"
BOOTSTRAP_CSRF_MAX_AGE_SECONDS = 900


class AppSettings(BaseSettings):
    """Security-relevant application configuration."""

    model_config = SettingsConfigDict(
        env_prefix="TIPPING_POINT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    environment: Literal["local", "hosted"] = Field(
        default="local",
        validation_alias=AliasChoices(
            "TIPPING_POINT_ENV",
            "TIPPING_POINT_ENVIRONMENT",
            "environment",
        ),
    )
    cookie_secure: bool = False
    allow_insecure_dev_cookies: bool = True
    allowed_origins: str = (
        "http://localhost:8000,http://localhost:5173,http://localhost:3000"
    )
    session_ttl_hours: int = 12
    throttle_max_failures: int = 5
    throttle_window_minutes: int = 15

    @property
    def origins(self) -> frozenset[str]:
        """Configured browser origins; wildcard credentialed CORS is never enabled."""
        return frozenset(
            origin.strip()
            for origin in self.allowed_origins.split(",")
            if origin.strip()
        )

    def validate_startup(self) -> None:
        """Refuse unsafe hosted or unapproved insecure cookie configurations."""
        if not self.cookie_secure:
            if self.environment != "local" or not self.allow_insecure_dev_cookies:
                raise RuntimeError(
                    "insecure (plain-HTTP) cookies are refused unless both "
                    "TIPPING_POINT_ENV=local and "
                    "TIPPING_POINT_ALLOW_INSECURE_DEV_COOKIES=true are "
                    "explicitly configured; hosted environments require "
                    "TIPPING_POINT_COOKIE_SECURE=true"
                )
