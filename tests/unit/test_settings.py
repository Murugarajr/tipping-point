"""Settings tests for server-side Channel3 credentials and aliases."""

from pydantic import SecretStr

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
