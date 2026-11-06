"""PostgreSQL regression tests for the foundation schema.

Every test registers the records it creates in the ``owned`` registry;
teardown deletes exactly those records. The verification sentinel and
any unrelated row are never touched.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from tipping_point.db.models import CampaignTerms, Merchant, Workshop
from tipping_point.db.session import session_scope
from tests.integration.conftest import _OwnedRecords


def _make_workshop_owner(
    owned: _OwnedRecords, title: str
) -> tuple[uuid.UUID, uuid.UUID]:
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
    owned.add(Merchant, merchant_id)
    owned.add(Workshop, workshop_id)
    return merchant_id, workshop_id


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


def test_merchant_insert_and_retrieve(owned):
    merchant_id = uuid.uuid4()
    with session_scope() as session:
        session.add(Merchant(id=merchant_id, name="Test Merchant"))
    owned.add(Merchant, merchant_id)
    with session_scope() as session:
        merchant = session.scalars(
            select(Merchant).where(Merchant.id == merchant_id)
        ).one()
        assert merchant.name == "Test Merchant"
        assert merchant.created_at is not None
        assert merchant.updated_at is not None


def test_workshop_insert_and_retrieve(owned):
    merchant_id, workshop_id = _make_workshop_owner(owned, "Embroidery Basics")
    with session_scope() as session:
        workshop = session.scalars(
            select(Workshop).where(Workshop.id == workshop_id)
        ).one()
        assert workshop.merchant_id == merchant_id
        assert workshop.title == "Embroidery Basics"
        assert workshop.capacity == 5
        assert workshop.ticket_price_minor == 1500
        assert workshop.currency == "GBP"


def test_workshop_capacity_constraints_reject_invalid(owned):
    merchant_id, _ = _make_workshop_owner(owned, "Capacity Test")
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


def test_merchant_deletion_is_restricted_while_workshops_exist(owned):
    merchant_id, workshop_id = _make_workshop_owner(owned, "Restrict Test")
    # RESTRICT (migration 0002) must reject deleting a referenced merchant.
    with pytest.raises(IntegrityError):
        with session_scope() as session:
            session.delete(session.get(Merchant, merchant_id))
    # After removing the workshop (flushed first; the ORM declares no
    # relationships, so the unit of work alone orders no deletes), the
    # merchant can be deleted.
    with session_scope() as session:
        session.delete(session.get(Workshop, workshop_id))
        session.flush()
        session.delete(session.get(Merchant, merchant_id))
    with session_scope() as session:
        assert session.get(Workshop, workshop_id) is None
        assert session.get(Merchant, merchant_id) is None


def test_workshop_deletion_is_restricted_while_terms_exist(owned):
    from tipping_point.economics import CampaignFinancialsInput, CampaignTermsService

    merchant_id, workshop_id = _make_workshop_owner(owned, "Terms Restrict")
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


def test_campaign_terms_currency_constrained_to_gbp(owned):
    merchant_id, workshop_id = _make_workshop_owner(owned, "Currency Check")
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


def test_transaction_rollback_on_failure(owned):
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


def test_unique_merchant_name(owned):
    merchant_id = uuid.uuid4()
    with session_scope() as session:
        session.add(Merchant(id=merchant_id, name="Unique Merchant"))
    owned.add(Merchant, merchant_id)
    with pytest.raises(IntegrityError):
        with session_scope() as session:
            session.add(Merchant(name="Unique Merchant"))


def test_migration_head_is_single(owned):
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config("alembic.ini"))
    heads = script.get_revisions(script.get_heads())
    assert len(heads) == 1
    assert heads[0].revision == "0004_material_costing"


def test_second_upgrade_head_is_harmless(migrated_database):
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config("alembic.ini"), "head")
    command.upgrade(Config("alembic.ini"), "head")
    with migrated_database.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1