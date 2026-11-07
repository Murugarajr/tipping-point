"""Shared fixtures for PostgreSQL integration tests.

Safety contract enforced here:

- Every migration or write is preceded by an allowlist guard, so a
  missing or misapplied test configuration can never fall back to the
  development database.
- The isolated test database stays MIGRATED to the expected revision;
  no schema teardown (no ``alembic downgrade``, no ``drop_all``, no
  ``DROP TABLE``/``TRUNCATE``/broad deletes) ever runs automatically.
- Per-test isolation uses EXPLICIT REGISTRATION: each test registers
  exactly the records it creates (or their owned roots), and teardown
  deletes only those records, scoped by registered primary keys.
  Records are never identified by "all rows that appeared since a
  pre-test snapshot", and the sentinel or any unrelated row is never
  touched.
- This registry is NOT a substitute for genuine multi-connection
  concurrency tests (plan: Testing Matrix); those use the separate
  coordinated-session pattern in test_concurrent_publish.py.
"""

from __future__ import annotations

import pathlib

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import delete, select

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def migrated_database():
    """Verify the existing isolated test schema without applying migrations.

    No teardown: the database stays migrated. The engine import happens
    AFTER pytest_configure applied the test environment (importing
    anything from tipping_point.db executes the package __init__ and
    builds the engine singleton; doing that at conftest-load time would
    bind it to the development database and the guard would refuse).
    """
    from tipping_point.db.engine import engine
    from tipping_point.db.testguard import assert_test_database_target

    assert_test_database_target(engine)
    alembic_cfg = Config(str(REPO_ROOT / "alembic.ini"))
    expected_heads = set(ScriptDirectory.from_config(alembic_cfg).get_heads())
    try:
        with engine.connect() as connection:
            actual_heads = set(MigrationContext.configure(connection).get_current_heads())
    except SQLAlchemyError:
        pytest.skip("isolated PostgreSQL test database unavailable; no provisioning or migrations attempted")
    if actual_heads != expected_heads:
        pytest.skip("isolated PostgreSQL schema is not at the existing head; explicit migration approval is required")
    yield engine


class _OwnedRecords:
    """Explicit registry of records created by the current test."""

    def __init__(self) -> None:
        self.merchants: set = set()
        self.workshops: set = set()
        self.terms: set = set()
        self.campaigns: set = set()
        self.credentials: set = set()
        self.sessions: set = set()
        self.offer_snapshots: set = set()

    def add(self, model, row_id) -> None:
        """Register a record (or an owned root) created by this test."""
        name = model.__name__
        if name == "Merchant":
            self.merchants.add(row_id)
        elif name == "Workshop":
            self.workshops.add(row_id)
        elif name == "CampaignTerms":
            self.terms.add(row_id)
        elif name == "Campaign":
            self.campaigns.add(row_id)
        elif name == "MerchantCredential":
            self.credentials.add(row_id)
        elif name == "MerchantSession":
            self.sessions.add(row_id)
        elif name == "MaterialOfferSnapshot":
            self.offer_snapshots.add(row_id)
        else:  # pragma: no cover - guards against silent misregistration
            raise TypeError(f"unsupported model for registration: {name}")


@pytest.fixture()
def owned(migrated_database) -> _OwnedRecords:
    """Per-test registry; teardown deletes only the registered records.

    Deletes are scoped strictly by registered primary keys (or, for
    session/credential/campaign/terms rows, by the registered parent
    ids), in FK-safe order with a flush after each delete. No broad
    DELETE, TRUNCATE, downgrade, or database-reset behavior exists
    here.
    """
    from tipping_point.db.models import (
        Campaign,
        CampaignTerms,
        MaterialOfferSnapshot,
        Merchant,
        MerchantCredential,
        MerchantSession,
        Workshop,
    )
    from tipping_point.db.session import session_scope

    registry = _OwnedRecords()
    yield registry

    with session_scope() as session:
        workshop_ids = set(registry.workshops)
        if registry.merchants:
            workshop_ids.update(
                session.scalars(
                    select(Workshop.id).where(
                        Workshop.merchant_id.in_(registry.merchants)
                    )
                ).all()
            )
            session.execute(
                delete(MerchantSession).where(
                    MerchantSession.merchant_id.in_(registry.merchants)
                )
            )
            session.flush()
            session.execute(
                delete(MerchantCredential).where(
                    MerchantCredential.merchant_id.in_(registry.merchants)
                )
            )
            session.flush()
        if registry.sessions:
            session.execute(
                delete(MerchantSession).where(
                    MerchantSession.id.in_(registry.sessions)
                )
            )
            session.flush()
        if registry.credentials:
            session.execute(
                delete(MerchantCredential).where(
                    MerchantCredential.id.in_(registry.credentials)
                )
            )
            session.flush()
        snapshot_ids = set(registry.offer_snapshots)
        if snapshot_ids or workshop_ids:
            session.execute(
                delete(MaterialOfferSnapshot).where(
                    (MaterialOfferSnapshot.id.in_(snapshot_ids))
                    | (MaterialOfferSnapshot.workshop_id.in_(workshop_ids))
                )
            )
            session.flush()
        if workshop_ids or registry.campaigns:
            session.execute(
                delete(Campaign).where(
                    (Campaign.id.in_(registry.campaigns))
                    | (Campaign.workshop_id.in_(workshop_ids))
                )
            )
            session.flush()
        if workshop_ids or registry.terms:
            session.execute(
                delete(CampaignTerms).where(
                    (CampaignTerms.id.in_(registry.terms))
                    | (CampaignTerms.workshop_id.in_(workshop_ids))
                )
            )
            session.flush()
        if workshop_ids:
            session.execute(
                delete(Workshop).where(Workshop.id.in_(workshop_ids))
            )
            session.flush()
        if registry.merchants:
            session.execute(
                delete(Merchant).where(Merchant.id.in_(registry.merchants))
            )
            session.flush()