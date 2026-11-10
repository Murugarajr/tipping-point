"""Test-harness environment helpers.

Only ``TIPPING_POINT_*`` variables are overridden, and their original values
are snapshotted so they can be restored exactly. Unrelated environment
configuration is never touched.
"""

from __future__ import annotations

import os
from pathlib import Path

TEST_ENV_PREFIX = "TIPPING_POINT_"
# Committed, non-secret local-test application settings (see the file for its contents).
LOCAL_TEST_ENV_FILE = Path(__file__).resolve().with_name("local-test.env")
TEST_DATABASE = "tipping_point_test"
TEST_USER = "tipping_point_app"

TEST_ENV_OVERRIDES: dict[str, str] = {
    f"{TEST_ENV_PREFIX}HOST": "localhost",
    f"{TEST_ENV_PREFIX}PORT": "5432",
    f"{TEST_ENV_PREFIX}USER": TEST_USER,
    f"{TEST_ENV_PREFIX}PASSWORD": "",
    f"{TEST_ENV_PREFIX}NAME": TEST_DATABASE,
    # A hosted connection string must never redirect tests away from the test DB.
    f"{TEST_ENV_PREFIX}DATABASE_URL": "",
}

_saved_overrides: dict[str, str | None] = {}


def apply_test_database_env() -> dict[str, str | None]:
    """Override only the TIPPING_POINT_* variables, snapshotting originals."""
    _saved_overrides.clear()
    for key, value in TEST_ENV_OVERRIDES.items():
        _saved_overrides[key] = os.environ.get(key)
        os.environ[key] = value
    return dict(_saved_overrides)


def restore_database_env() -> None:
    """Restore every overridden variable to its exact original state."""
    for key, original in _saved_overrides.items():
        if original is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original
    _saved_overrides.clear()


_saved_settings_env_files: dict[type, object] = {}


def _settings_classes() -> tuple[type, ...]:
    from tipping_point.db.config import DatabaseConfig
    from tipping_point.settings import AppSettings

    return (AppSettings, DatabaseConfig)


def use_local_test_settings_file() -> None:
    """Point the default env-file source of AppSettings and DatabaseConfig at the committed local-test file.

    This replaces the checkout's private ``.env`` for the test session only. Nothing is
    written to ``os.environ``, so settings built with ``_env_file=None`` (isolation tests)
    still see the secure defaults, and explicit hosted settings are validated unchanged.
    The test-database target is still forced by ``apply_test_database_env``.
    """
    for cls in _settings_classes():
        _saved_settings_env_files.setdefault(cls, cls.model_config.get("env_file"))
        cls.model_config["env_file"] = str(LOCAL_TEST_ENV_FILE)


def restore_settings_env_file() -> None:
    """Restore the original env-file configuration of every patched settings class."""
    for cls, original in _saved_settings_env_files.items():
        cls.model_config["env_file"] = original
    _saved_settings_env_files.clear()