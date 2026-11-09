"""Application settings for cookies, sessions, integration credentials, and throttling.

All values are environment-driven via the TIPPING_POINT_ prefix (same
prefix as the database settings; unrelated keys are ignored). Hosted
environments must set TIPPING_POINT_ENV=hosted and
TIPPING_POINT_COOKIE_SECURE=true; the application refuses to serve
authentication in hosted mode without secure cookies.
"""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit
import ipaddress
import re

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SESSION_COOKIE_NAME = "tipping_session"
CSRF_COOKIE_NAME = "tipping_csrf"
BOOTSTRAP_CSRF_MAX_AGE_SECONDS = 900
GUEST_SESSION_COOKIE_NAME = "tipping_guest_session"
GUEST_CSRF_COOKIE_NAME = "tipping_guest_csrf"
GUEST_BOOTSTRAP_COOKIE_NAME = "tipping_guest_bootstrap"
# Provider model slugs, e.g. "openai/gpt-4o-mini", "anthropic/claude-sonnet-4", "vendor/model:free".
RESCUE_ANALYST_MODEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")


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
    guest_session_ttl_hours: int = Field(default=24, ge=1, le=168)
    authorization_safety_buffer_hours: int = Field(default=6, ge=1, le=24)
    settlement_timeout_seconds: int = Field(default=1800, ge=60, le=21600)
    paypal_expected_payee: str | None = Field(
        default=None, validation_alias=AliasChoices(
            "PAYPAL_EXPECTED_PAYEE", "TIPPING_POINT_PAYPAL_EXPECTED_PAYEE", "paypal_expected_payee"
        )
    )
    public_url: str | None = Field(
        default=None, validation_alias=AliasChoices("APP_PUBLIC_URL", "TIPPING_POINT_PUBLIC_URL", "public_url")
    )

    @field_validator("public_url")
    @classmethod
    def validate_public_origin(cls, value):
        if value is None:
            return None
        parts = urlsplit(value)
        try:
            loopback = ipaddress.ip_address(parts.hostname or "").is_loopback
        except ValueError:
            loopback = parts.hostname == "localhost"
        if (
            not parts.hostname or parts.username or parts.password
            or parts.path not in ("", "/") or parts.query or parts.fragment
            or (parts.scheme != "https" and not (parts.scheme == "http" and loopback))
        ):
            raise ValueError("public_url must be a bare HTTPS origin or local loopback HTTP origin")
        # Force validation of a malformed/out-of-range port.
        parts.port
        return value.rstrip("/")

    @property
    def reservations_configured(self) -> bool:
        return bool(
            self.has_paypal_credentials and self.paypal_expected_payee
            and self.paypal_expected_payee.strip() and self.public_url
            and (self.environment == "local" or self.public_url.startswith("https://"))
        )
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

    # Rescue Analyst (read-only, server-side model connection). Disabled unless explicitly
    # enabled AND the selected provider's own key and a valid model id are configured.
    # Missing configuration disables only the analyst, never the dashboard.
    rescue_analyst_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "RESCUE_ANALYST_ENABLED", "TIPPING_POINT_RESCUE_ANALYST_ENABLED", "rescue_analyst_enabled"
        ),
    )
    rescue_analyst_provider: Literal["openrouter", "openai"] = Field(
        default="openrouter",
        validation_alias=AliasChoices(
            "RESCUE_ANALYST_PROVIDER", "TIPPING_POINT_RESCUE_ANALYST_PROVIDER", "rescue_analyst_provider"
        ),
    )
    rescue_analyst_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "RESCUE_ANALYST_MODEL", "TIPPING_POINT_RESCUE_ANALYST_MODEL", "rescue_analyst_model"
        ),
    )
    openrouter_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENROUTER_API_KEY", "TIPPING_POINT_OPENROUTER_API_KEY", "openrouter_api_key"),
    )
    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "TIPPING_POINT_OPENAI_API_KEY", "openai_api_key"),
    )

    @field_validator("rescue_analyst_model")
    @classmethod
    def validate_rescue_analyst_model(cls, value):
        """A provider model slug only: no URL, whitespace, query or control characters."""
        if value is None or not value.strip():
            return None
        value = value.strip()
        if not RESCUE_ANALYST_MODEL_PATTERN.fullmatch(value) or "//" in value or ".." in value:
            raise ValueError("rescue_analyst_model must be a provider model identifier such as vendor/model-name")
        return value

    def rescue_analyst_key(self) -> SecretStr | None:
        """Only the selected provider's own credential; never the other provider's."""
        key = self.openrouter_api_key if self.rescue_analyst_provider == "openrouter" else self.openai_api_key
        return key if key is not None and key.get_secret_value().strip() else None

    @property
    def rescue_analyst_status(self) -> Literal["ready", "disabled", "missing_key", "missing_model"]:
        if not self.rescue_analyst_enabled:
            return "disabled"
        if self.rescue_analyst_key() is None:
            return "missing_key"
        if not self.rescue_analyst_model:
            return "missing_model"
        return "ready"

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
        if self.environment == "hosted" and self.public_url and not self.public_url.startswith("https://"):
            raise RuntimeError("hosted public_url must use HTTPS")
        if not self.cookie_secure:
            if self.environment != "local" or not self.allow_insecure_dev_cookies:
                raise RuntimeError(
                    "insecure (plain-HTTP) cookies are refused unless both "
                    "TIPPING_POINT_ENV=local and "
                    "TIPPING_POINT_ALLOW_INSECURE_DEV_COOKIES=true are "
                    "explicitly configured; hosted environments require "
                    "TIPPING_POINT_COOKIE_SECURE=true"
                )
