"""Application settings for cookies, sessions, integration credentials, and throttling.

All values are environment-driven via the TIPPING_POINT_ prefix (same
prefix as the database settings; unrelated keys are ignored). Hosted
environments must set TIPPING_POINT_ENV=hosted and
TIPPING_POINT_COOKIE_SECURE=true; the application refuses to serve
authentication in hosted mode without secure cookies.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
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
    allow_insecure_dev_cookies: bool = False
    allowed_origins: str = (
        "http://localhost:8000,http://localhost:5173,http://localhost:3000"
    )
    session_ttl_hours: int = 12
    throttle_max_failures: int = 5
    throttle_window_minutes: int = 15

    channel3_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "CHANNEL3_API_KEY",
            "TIPPING_POINT_CHANNEL3_API_KEY",
            "channel3_api_key",
        ),
    )
    channel3_base_url: str = Field(
        default="https://api.trychannel3.com",
        validation_alias=AliasChoices(
            "CHANNEL3_BASE_URL",
            "TIPPING_POINT_CHANNEL3_BASE_URL",
            "channel3_base_url",
        ),
    )
    channel3_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        le=30.0,
        validation_alias=AliasChoices(
            "CHANNEL3_TIMEOUT_SECONDS",
            "TIPPING_POINT_CHANNEL3_TIMEOUT_SECONDS",
            "channel3_timeout_seconds",
        ),
    )
    channel3_offer_stale_after_seconds: int = Field(
        default=3600,
        ge=60,
        validation_alias=AliasChoices(
            "CHANNEL3_OFFER_STALE_AFTER_SECONDS",
            "TIPPING_POINT_CHANNEL3_OFFER_STALE_AFTER_SECONDS",
            "channel3_offer_stale_after_seconds",
        ),
    )

    paypal_env: Literal["sandbox"] = Field(
        default="sandbox",
        validation_alias=AliasChoices(
            "PAYPAL_ENV",
            "TIPPING_POINT_PAYPAL_ENV",
            "paypal_env",
        ),
    )
    paypal_client_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "PAYPAL_CLIENT_ID",
            "TIPPING_POINT_PAYPAL_CLIENT_ID",
            "paypal_client_id",
        ),
    )
    paypal_client_secret: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "PAYPAL_CLIENT_SECRET",
            "TIPPING_POINT_PAYPAL_CLIENT_SECRET",
            "paypal_client_secret",
        ),
    )
    paypal_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        le=30.0,
        validation_alias=AliasChoices(
            "PAYPAL_TIMEOUT_SECONDS",
            "TIPPING_POINT_PAYPAL_TIMEOUT_SECONDS",
            "paypal_timeout_seconds",
        ),
    )

    @property
    def has_channel3_credentials(self) -> bool:
        """Whether a non-empty Channel3 API key is configured server-side."""
        if self.channel3_api_key is None:
            return False
        return bool(self.channel3_api_key.get_secret_value().strip())

    @property
    def has_paypal_credentials(self) -> bool:
        """Whether non-empty PayPal Sandbox credentials are configured."""
        if self.paypal_client_id is None or self.paypal_client_secret is None:
            return False
        return bool(
            self.paypal_client_id.strip()
            and self.paypal_client_secret.get_secret_value().strip()
        )

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
