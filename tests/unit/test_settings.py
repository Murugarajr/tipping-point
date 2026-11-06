"""Settings tests for server-side integration credentials and aliases."""

import pytest
from pydantic import SecretStr, ValidationError

from tipping_point.settings import AppSettings


def test_channel3_key_is_optional_and_defaults_do_not_break_offline_app():
    settings = AppSettings(_env_file=None)
    assert settings.channel3_api_key is None
    assert not settings.has_channel3_credentials
    assert settings.channel3_base_url == "https://api.trychannel3.com"
    assert settings.channel3_timeout_seconds == 10.0
    assert settings.channel3_offer_stale_after_seconds == 3600


def test_channel3_key_reads_standard_and_prefixed_server_environment_aliases():
    standard = AppSettings(_env_file=None, CHANNEL3_API_KEY="fixture-secret")
    assert standard.has_channel3_credentials
    assert isinstance(standard.channel3_api_key, SecretStr)
    assert "fixture-secret" not in repr(standard)

    prefixed = AppSettings(
        _env_file=None,
        TIPPING_POINT_CHANNEL3_API_KEY="fixture-other-secret",
    )
    assert prefixed.has_channel3_credentials
    assert isinstance(prefixed.channel3_api_key, SecretStr)



def test_insecure_cookie_configuration_requires_explicit_local_opt_in():
    defaults = AppSettings(_env_file=None)
    assert defaults.environment == "local"
    assert defaults.allow_insecure_dev_cookies is False
    try:
        defaults.validate_startup()
    except RuntimeError as exc:
        assert "explicitly configured" in str(exc)
    else:
        raise AssertionError("insecure cookie defaults unexpectedly accepted")

    explicit = AppSettings(
        _env_file=None,
        environment="local",
        allow_insecure_dev_cookies=True,
    )
    explicit.validate_startup()

    hosted = AppSettings(
        _env_file=None,
        environment="hosted",
        cookie_secure=False,
        allow_insecure_dev_cookies=True,
    )
    try:
        hosted.validate_startup()
    except RuntimeError:
        pass
    else:
        raise AssertionError("hosted insecure cookies unexpectedly accepted")


def test_paypal_settings_default_to_sandbox_without_credentials() -> None:
    settings = AppSettings(_env_file=None)
    assert settings.paypal_env == "sandbox"
    assert settings.paypal_client_id is None
    assert settings.paypal_client_secret is None
    assert settings.paypal_timeout_seconds == 10.0
    assert settings.has_paypal_credentials is False


def test_paypal_settings_read_env_aliases_and_hide_secret_value() -> None:
    settings = AppSettings(
        _env_file=None,
        PAYPAL_CLIENT_ID="fixture-paypal-client-id",
        PAYPAL_CLIENT_SECRET="fixture-paypal-client-secret",
    )
    assert settings.paypal_env == "sandbox"
    assert settings.has_paypal_credentials is True
    assert isinstance(settings.paypal_client_secret, SecretStr)
    assert settings.paypal_client_secret.get_secret_value() == (
        "fixture-paypal-client-secret"
    )
    assert "fixture-paypal-client-secret" not in repr(settings)


def test_paypal_live_mode_is_refused_by_settings_validation() -> None:
    with pytest.raises(ValidationError):
        AppSettings(_env_file=None, PAYPAL_ENV="live")
