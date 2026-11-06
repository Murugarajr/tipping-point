"""PostgreSQL regression tests for the foundation schema.

All tests run through the guarded ``migrated_database`` fixture, which
refuses to operate on any database outside the test allowlist.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from tipping_point.db.models import CampaignTerms, Merchant, Workshop
from tipping_point.db.session import session_scope


def test_connection_succeeds(migrated_database):
    with migrated_database.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        assert result.scalar() == 1


def test_connection_uses_dedicated_non_superuser(migrated_database):
    with migrated_database.connect() as conn:
        db = conn.execute(text("SELECT current_database()")).scalar()
        session_user = conn.execute(text("SELECT session_user")).scalar()
        attrs = conn.execute(
            text(
                "SELECT rolsuper, rolcreatedb, rolcreaterole "
                "FROM pg_roles WHERE rolname = :u"
            ),
            {"u": session_user},
        ).one()
    assert db == "tipping_point_test"
    assert session_user == "tipping_point_app"
    assert attrs == (False, False, False)


def test_merchant_insert_and_retrieve(migrated_database):
    merchant_id = uuid.uuid4()
    with session_scope() as session:
        session.add(Merchant(id=merchant_id, name="Test Merchant"))
    with session_scope() as session:
        merchant = session.scalars(
            select(Merchant).where(Merchant.id == merchant_id)
        ).one()
        assert merchant.name == "Test Merchant"
        assert merchant.created_at is not None
        assert merchant.updated_at is not None


def test_workshop_insert_and_retrieve(migrated_database):
    merchant_id = uuid.uuid4()
    workshop_id = uuid.uuid4()
    with session_scope() as session:
        session.add(Merchant(id=merchant_id, name="Workshop Host"))
        session.add(
            Workshop(
                id=workshop_id,
                merchant_id=merchant_id,
                title="Embroidery Basics",
                description="Learn basic stitches.",
                capacity=12,
                ticket_price_minor=2500,
                currency="GBP",
            )
        )
    with session_scope() as session:
        workshop = session.scalars(
            select(Workshop).where(Workshop.id == workshop_id)
        ).one()
        assert workshop.title == "Embroidery Basics"
        assert workshop.capacity == 12
        assert workshop.ticket_price_minor == 2500
        assert workshop.currency == "GBP"


def test_workshop_capacity_constraints_reject_invalid(migrated_database):
    merchant_id = uuid.uuid4()
    with session_scope() as session:
        session.add(Merchant(id=merchant_id, name="Capacity Test"))
    for bad_capacity in (0, -5):
        with pytest.raises(IntegrityError):
            with session_scope() as session:
                session.add(
                    Workshop(
                        id=uuid.uuid4(),
                        merchant_id=merchant_id,
                        title=f"Capacity {bad_capacity}",
                        capacity=bad_capacity,
                        ticket_price_minor=1000,
                        currency="GBP",
                    )
                )


def _make_workshop_owner(title: str):
    merchant_id = uuid.uuid4()
    workshop_id = uuid.uuid4()
    with session_scope() as session:
        session.add(Merchant(id=merchant_id, name=f"Host {uuid.uuid4().hex[:8]}"))
        session.add(
            Workshop(
                id=workshop_id,
                merchant_id=merchant_id,
                title=title,
                capacity=5,
                ticket_price_minor=1500,
                currency="GBP",
            )
        )
    return merchant_id, workshop_id


def test_merchant_deletion_is_restricted_while_workshops_exist(migrated_database):
    merchant_id, workshop_id = _make_workshop_owner("Restrict Test")
    # RESTRICT (migration 0002) must reject deleting a referenced merchant.
    with pytest.raises(IntegrityError):
        with session_scope() as session:
            session.delete(session.get(Merchant, merchant_id))
    # After removing the workshop (flushed explicitly first, because the
    # ORM declares no relationship and thus no ORM-level delete ordering),
    # the merchant can be deleted.
    with session_scope() as session:
        session.delete(session.get(Workshop, workshop_id))
        session.flush()
        session.delete(session.get(Merchant, merchant_id))
    with session_scope() as session:
        assert session.get(Workshop, workshop_id) is None
        assert session.get(Merchant, merchant_id) is None


def test_workshop_deletion_is_restricted_while_terms_exist(migrated_database):
    from tipping_point.economics import CampaignFinancialsInput, CampaignTermsService

    merchant_id, workshop_id = _make_workshop_owner("Terms Restrict")
    with session_scope() as session:
        CampaignTermsService(session).create_draft(
            workshop_id,
            CampaignFinancialsInput(
                ticket_price_minor=2000, capacity=6, fixed_costs_minor=3000
            ),
        )
    with pytest.raises(IntegrityError):
        with session_scope() as session:
            session.delete(session.get(Workshop, workshop_id))


def test_campaign_terms_currency_constrained_to_gbp(migrated_database):
    merchant_id, workshop_id = _make_workshop_owner("Currency Check")
    with pytest.raises(IntegrityError):
        with session_scope() as session:
            session.add(
                CampaignTerms(
                    workshop_id=workshop_id,
                    version=99,
                    currency="USD",
                    financial_inputs={},
                    assumption_labels={},
                    calculation={},
                    algorithm_version="x",
                    snapshot_hash="0" * 64,
                )
            )


def test_transaction_rollback_on_failure(migrated_database):
    merchant_id = uuid.uuid4()
    with pytest.raises(RuntimeError):
        with session_scope() as session:
            session.add(Merchant(id=merchant_id, name="Rollback Test"))
            raise RuntimeError("Simulated failure")
    with session_scope() as session:
        assert (
            session.scalars(
                select(Merchant).where(Merchant.id == merchant_id)
            ).first()
            is None
        )


def test_unique_merchant_name(migrated_database):
    with session_scope() as session:
        session.add(Merchant(name="Unique Merchant"))
    with pytest.raises(IntegrityError):
        with session_scope() as session:
            session.add(Merchant(name="Unique Merchant"))


def test_migration_head_is_single(migrated_database):
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config("alembic.ini"))
    heads = script.get_revisions(script.get_heads())
    assert len(heads) == 1
    assert heads[0].revision == "0002_campaign_terms"


def test_second_upgrade_head_is_harmless(migrated_database):
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config("alembic.ini"), "head")
    command.upgrade(Config("alembic.ini"), "head")
    with migrated_database.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1