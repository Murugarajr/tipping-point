"""Focused test-isolation proofs.

Covers the connection/isolation addendum requirements:
- Missing test configuration cannot fall back to the development database.
- Development/non-allowlisted database targets are rejected before
  migrations or writes.
- Offline smoke tests need no database credentials.
- Unrelated environment configuration is never overwritten.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest
from sqlalchemy.engine import make_url

from tipping_point.db.testguard import assert_test_database_target

from tests import harness

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


class TestDatabaseTargetGuard:
    def test_test_database_is_accepted(self):
        url = make_url("postgresql+psycopg://tipping_point_app@localhost:5432/tipping_point_test")
        assert assert_test_database_target(str(url)) == "tipping_point_test"

    def test_development_database_is_rejected(self):
        url = make_url("postgresql+psycopg://tipping_point_app@localhost:5432/tipping_point_dev")
        with pytest.raises(RuntimeError, match="tipping_point_dev"):
            assert_test_database_target(str(url))

    def test_unrelated_database_is_rejected(self):
        url = make_url("postgresql+psycopg://ohm@localhost:5432/ohm")
        with pytest.raises(RuntimeError, match="Refusing"):
            assert_test_database_target(str(url))

    def test_missing_test_configuration_does_not_fall_back_to_dev(self, monkeypatch):
        # The application's DEFAULT configuration points at the
        # development database. If the test-harness override is missing,
        # the guard must reject the target loudly instead of letting a
        # migration or write reach the development database.
        from tipping_point.db.config import DatabaseConfig

        for key in (
            "TIPPING_POINT_HOST",
            "TIPPING_POINT_PORT",
            "TIPPING_POINT_USER",
            "TIPPING_POINT_PASSWORD",
            "TIPPING_POINT_NAME",
        ):
            monkeypatch.delenv(key, raising=False)
        default_name = DatabaseConfig(_env_file=None).name
        assert default_name == "tipping_point_dev"
        with pytest.raises(RuntimeError, match="tipping_point_dev"):
            assert_test_database_target(
                f"postgresql+psycopg://tipping_point_app@localhost:5432/{default_name}"
            )


class TestHarnessEnvironment:
    def test_unrelated_environment_is_not_overwritten(self):
        os.environ["TIPPING_POINT_ISOLATION_SENTINEL"] = "untouched"
        os.environ["TIPPING_POINT_NAME"] = "tipping_point_dev"
        try:
            harness.apply_test_database_env()
            assert os.environ["TIPPING_POINT_ISOLATION_SENTINEL"] == "untouched"
            assert os.environ["TIPPING_POINT_NAME"] == harness.TEST_DATABASE
            harness.restore_database_env()
            assert os.environ["TIPPING_POINT_NAME"] == "tipping_point_dev"
            assert os.environ["TIPPING_POINT_ISOLATION_SENTINEL"] == "untouched"
        finally:
            os.environ.pop("TIPPING_POINT_ISOLATION_SENTINEL", None)
            harness.restore_database_env()

    def test_restore_removes_variables_that_did_not_exist(self):
        saved = os.environ.pop("TIPPING_POINT_NAME", None)
        try:
            harness.apply_test_database_env()
            assert os.environ["TIPPING_POINT_NAME"] == harness.TEST_DATABASE
            harness.restore_database_env()
            assert "TIPPING_POINT_NAME" not in os.environ
        finally:
            if saved is not None:
                os.environ["TIPPING_POINT_NAME"] = saved


def test_orm_declares_no_cascading_relationships():
    """ORM relationship settings must not independently cascade deletion.

    No relationship() declarations exist; merchant/workshop deletion
    policy is enforced solely by database-level RESTRICT foreign keys.
    """
    from tipping_point.db.models import CampaignTerms, Merchant, Workshop

    for model in (Merchant, Workshop, CampaignTerms):
        assert len(model.__mapper__.relationships) == 0, (
            f"{model.__name__} unexpectedly declares ORM relationships; "
            "deletion policy must stay database-enforced"
        )
    """Smoke tests pass in a clean subprocess without any TIPPING_POINT_* env."""
    clean_env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("TIPPING_POINT_")
    }
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_smoke.py", "-q", "--no-header"],
        cwd=REPO_ROOT,
        env=clean_env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "3 passed" in result.stdout