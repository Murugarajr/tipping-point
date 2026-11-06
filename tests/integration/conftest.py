"""Shared fixtures for PostgreSQL integration tests.

Safety contract enforced here:

- Every migration or write is preceded by an allowlist guard, so a
  missing or misapplied test configuration can never fall back to the
  development database.
- The isolated test database stays MIGRATED to the expected revision
  after the suite; no schema teardown (no ``alembic downgrade``, no
  ``drop_all``, no ``DROP TABLE``/``TRUNCATE``/broad deletes) runs
  automatically at teardown.
- Per-test isolation is provided by deleting exactly the rows a test
  created (by primary key, in FK-safe order). This is targeted cleanup,
  not broad data deletion, and it proves test-created data cannot leak
  between tests while pre-existing rows — including verification
  sentinels — are never touched.
- This per-test, PK-targeted cleanup is NOT a substitute for genuine
  multi-connection concurrency tests (plan: Testing Matrix). Those will
  use separate sessions and explicit synchronization points.
"""

from __future__ import annotations

import pathlib

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def migrated_database():
    """Ensure the isolated test database is migrated to the single head.

    The engine import happens AFTER pytest_configure applied the test
    environment: importing anything from tipping_point.db executes the
    package __init__ and builds the engine singleton, so it must not
    happen at conftest-load time (the guard would refuse to run).

    There is deliberately NO teardown: the database stays migrated to
    the expected revision. A second ``upgrade head`` is a no-op (covered
    by ``test_second_upgrade_head_is_harmless``).
    """
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


@pytest.fixture(autouse=True)
def no_data_leak(migrated_database):
    """Delete exactly the rows this test created — nothing else.

    Row-ID sets are snapshotted before the test; afterwards only
    newly-created rows are removed, by primary key, in FK-safe order
    (campaign_terms -> workshops -> merchants). Pre-existing rows,
    including long-lived verification sentinels, are never modified or
    deleted, and no schema state is touched.
    """
    from tipping_point.db.models import CampaignTerms, Merchant, Workshop
    from tipping_point.db.session import session_scope

    def snapshot() -> dict[type, set]:
        with session_scope() as session:
            return {
                CampaignTerms: set(session.scalars(select(CampaignTerms.id))),
                Workshop: set(session.scalars(select(Workshop.id))),
                Merchant: set(session.scalars(select(Merchant.id))),
            }

    before = snapshot()
    yield
    after = snapshot()
    with session_scope() as session:
        for model in (CampaignTerms, Workshop, Merchant):
            for row_id in sorted(after[model] - before[model], key=str):
                row = session.get(model, row_id)
                if row is not None:
                    session.delete(row)
                    # Explicit flush enforces FK-safe deletion order; the
                    # ORM declares no relationships, so the unit of work
                    # alone does not order deletes across mappers.
                    session.flush()