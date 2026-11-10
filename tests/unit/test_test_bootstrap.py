"""The pytest bootstrap supplies only non-secret local flags, through the settings file source.

It must let a fresh checkout (no private .env) import the app, without weakening validation,
leaking into process environment, or reaching settings that disable the env file.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.harness import LOCAL_TEST_ENV_FILE, TEST_DATABASE, TEST_ENV_OVERRIDES
from tipping_point.db.config import DatabaseConfig
from tipping_point.settings import AppSettings

ALLOWED = {"TIPPING_POINT_ENV": "local", "TIPPING_POINT_ALLOW_INSECURE_DEV_COOKIES": "true"}


def _entries(path: Path) -> dict[str, str]:
    lines = [line.strip() for line in path.read_text().splitlines()]
    return dict(line.split("=", 1) for line in lines if line and not line.startswith("#"))


def test_committed_test_file_holds_only_the_two_non_secret_local_flags():
    assert LOCAL_TEST_ENV_FILE.is_file()
    assert _entries(LOCAL_TEST_ENV_FILE) == ALLOWED


def test_settings_default_file_source_is_the_test_file_not_the_private_env():
    assert AppSettings.model_config["env_file"] == str(LOCAL_TEST_ENV_FILE)
    assert Path(AppSettings.model_config["env_file"]).name != ".env"


def test_database_config_uses_the_test_file_code_pool_defaults_and_the_test_database():
    assert DatabaseConfig.model_config["env_file"] == str(LOCAL_TEST_ENV_FILE)
    config = DatabaseConfig()
    defaults = {name: field.default for name, field in DatabaseConfig.model_fields.items()
                if name in ("pool_size", "max_overflow", "pool_timeout", "pool_recycle", "pool_pre_ping")}
    assert {name: getattr(config, name) for name in defaults} == defaults
    assert config.name == TEST_DATABASE
    assert config.database_url.rsplit("/", 1)[-1].split("?")[0] == TEST_DATABASE


def test_default_settings_start_locally_without_a_private_env():
    settings = AppSettings()
    assert (settings.environment, settings.cookie_secure, settings.allow_insecure_dev_cookies) == ("local", False, True)
    settings.validate_startup()


def test_flags_are_not_in_process_environment_or_harness_overrides():
    for key in ALLOWED:
        assert key not in TEST_ENV_OVERRIDES
        assert key not in os.environ, f"{key} must come only from the test settings file"


def test_disabling_the_env_file_still_gives_secure_defaults_and_refuses_insecure_startup():
    defaults = AppSettings(_env_file=None)
    assert defaults.allow_insecure_dev_cookies is False
    with pytest.raises(RuntimeError, match="insecure"):
        defaults.validate_startup()


def test_hosted_mode_still_rejects_the_local_insecure_flag():
    hosted = AppSettings(environment="hosted", cookie_secure=True, public_url="https://tipping-point.example.test")
    with pytest.raises(RuntimeError, match="hosted environments must not allow insecure development cookies"):
        hosted.validate_startup()
