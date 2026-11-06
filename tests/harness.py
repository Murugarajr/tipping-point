"""Test-harness environment helpers.

Only ``TIPPING_POINT_*`` variables are overridden, and their original values
are snapshotted so they can be restored exactly. Unrelated environment
configuration is never touched.
"""

from __future__ import annotations

import os

TEST_ENV_PREFIX = "TIPPING_POINT_"
TEST_DATABASE = "tipping_point_test"
TEST_USER = "tipping_point_app"

TEST_ENV_OVERRIDES: dict[str, str] = {
    f"{TEST_ENV_PREFIX}HOST": "localhost",
    f"{TEST_ENV_PREFIX}PORT": "5432",
    f"{TEST_ENV_PREFIX}USER": TEST_USER,
    f"{TEST_ENV_PREFIX}PASSWORD": "",
    f"{TEST_ENV_PREFIX}NAME": TEST_DATABASE,
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