"""Shared fixtures for PostgreSQL integration tests.

Every migration or write is preceded by an allowlist guard so a missing or
misapplied test configuration can never fall back to the development database.

The application engine is imported INSIDE the fixture, after the test
environment has been applied by ``pytest_configure`` — importing it at
module scope would bind it to the development database before the
overrides exist, and the guard would (correctly) refuse to run.
"""

from __future__ import annotations

import pathlib

import pytest
from alembic import command
from alembic.config import Config

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def migrated_database():
    """Upgrade the isolated test database to head, then restore it to base."""
    # Both imports happen AFTER pytest_configure applied the test
    # environment: importing anything from tipping_point.db executes the
    # package __init__ and builds the engine singleton, so it must not
    # happen at conftest-load time.
    from tipping_point.db.engine import engine
    from tipping_point.db.testguard import assert_test_database_target

    assert_test_database_target(engine)
    alembic_cfg = Config(str(REPO_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option(
        "sqlalchemy.url",
        engine.url.render_as_string(hide_password=False),
    )
    command.upgrade(alembic_cfg, "head")
    yield engine
    command.downgrade(alembic_cfg, "base")