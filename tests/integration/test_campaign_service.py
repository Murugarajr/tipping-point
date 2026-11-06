"""PostgreSQL integration tests for the campaign terms service.

Exercises the application service directly. Every test registers its
workshop/merchant roots in the ``owned`` registry; terms rows created
for a registered workshop are removed by the registry's scoped
teardown, and the sentinel is never touched.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from tipping_point.db.models import CampaignTerms, Merchant, Workshop
from tipping_point.db.session import session_scope
from tipping_point.economics import (
    ALGORITHM_VERSION,
    CampaignFinancialsInput,
    CampaignScheduleInput,
    CampaignTermsService,
    FeeEstimateInput,
    InvalidCampaignDatesError,
    MaterialLineInput,
    MissingAssumptionsError,
    TermsFrozenError,
    ZeroTicketPriceError,
    build_snapshot_hash,
    calculate_viability,
)

NOW = datetime.now(timezone.utc)


def _new_workshop(owned, title: str) -> uuid.UUID:
    merchant_id = uuid.uuid4()
    workshop_id = uuid.uuid4()
    with session_scope() as session:
        session.add(Merchant(id=merchant_id, name=f"Host {uuid.uuid4().hex[:8]}"))
        session.add(
            Workshop(
                id=workshop_id,
                merchant_id=merchant_id,
                title=title,
                capacity=10,
                ticket_price_minor=2500,
                currency="GBP",
            )
        )
    owned.add(Merchant, merchant_id)
    owned.add(Workshop, workshop_id)
    return workshop_id


def _full_financials() -> CampaignFinancialsInput:
    return CampaignFinancialsInput(
        ticket_price_minor=2500,
        capacity=10,
        fixed_costs_minor=5000,
        materials=[
            MaterialLineInput(
                name="embroidery kit",
                source_label="merchant-entered",
                shared_units=0,
                per_attendee_units=1,
                pack_size=4,
                pack_price_minor=1200,
            )
        ],
        shipping_allowance_minor=300,
        contingency_minor=500,
        fee_estimate=FeeEstimateInput(percent_basis_points=249, fixed_minor=30),
    )


def _valid_schedule() -> CampaignScheduleInput:
    return CampaignScheduleInput(
        opens_at=NOW + timedelta(hours=1),
        closes_at=NOW + timedelta(hours=25),
    )


def _create_draft(owned, session, workshop_id, financials, schedule=None):
    row = CampaignTermsService(session).create_draft(
        workshop_id, financials, schedule
    )
    owned.add(CampaignTerms, row.id)
    return row


def _get_row(terms_id) -> CampaignTerms:
    with session_scope() as session:
        row = session.get(CampaignTerms, terms_id)
        assert row is not None
        return row


def test_draft_may_be_incomplete(owned):
    workshop_id = _new_workshop(owned, "Incomplete Draft")
    with session_scope() as session:
        row = _create_draft(
            owned,
            session,
            workshop_id,
            CampaignFinancialsInput(ticket_price_minor=0, capacity=5),
        )
        terms_id = row.id
    stored = _get_row(terms_id)
    assert stored.is_frozen is False
    assert stored.version == 1
    assert stored.opens_at is None and stored.closes_at is None
    assert stored.algorithm_version == ALGORITHM_VERSION
    assert len(stored.snapshot_hash) == 64


def test_freeze_rejects_zero_ticket_price(owned):
    workshop_id = _new_workshop(owned, "Zero Price")
    with session_scope() as session:
        row = _create_draft(
            owned,
            session,
            workshop_id,
            CampaignFinancialsInput(
                ticket_price_minor=0,
                capacity=5,
                fee_estimate=FeeEstimateInput(percent_basis_points=0, fixed_minor=0),
            ),
            _valid_schedule(),
        )
        with pytest.raises(ZeroTicketPriceError):
            CampaignTermsService(session).freeze(row.id)


def test_freeze_rejects_missing_fee_assumption(owned):
    workshop_id = _new_workshop(owned, "Missing Fee")
    with session_scope() as session:
        row = _create_draft(
            owned,
            session,
            workshop_id,
            CampaignFinancialsInput(ticket_price_minor=2500, capacity=5),
            _valid_schedule(),
        )
        with pytest.raises(MissingAssumptionsError, match="fee"):
            CampaignTermsService(session).freeze(row.id)


def test_freeze_rejects_missing_dates(owned):
    workshop_id = _new_workshop(owned, "Missing Dates")
    with session_scope() as session:
        row = _create_draft(
            owned,
            session,
            workshop_id,
            CampaignFinancialsInput(
                ticket_price_minor=2500,
                capacity=5,
                fee_estimate=FeeEstimateInput(percent_basis_points=0, fixed_minor=0),
            ),
        )
        with pytest.raises(MissingAssumptionsError, match="dates"):
            CampaignTermsService(session).freeze(row.id)


def test_freeze_rejects_past_deadline(owned):
    workshop_id = _new_workshop(owned, "Past Deadline")
    with session_scope() as session:
        row = _create_draft(
            owned,
            session,
            workshop_id,
            _full_financials(),
            CampaignScheduleInput(
                opens_at=NOW - timedelta(hours=48),
                closes_at=NOW - timedelta(hours=24),
            ),
        )
        with pytest.raises(InvalidCampaignDatesError):
            CampaignTermsService(session).freeze(row.id)


def test_freeze_publishes_terms_and_stores_curve(owned):
    workshop_id = _new_workshop(owned, "Published Terms")
    with session_scope() as session:
        service = CampaignTermsService(session)
        terms_id = _create_draft(
            owned, session, workshop_id, _full_financials(), _valid_schedule()
        ).id
        frozen = service.freeze(terms_id)

    assert frozen.is_frozen is True
    assert frozen.frozen_at is not None

    stored = _get_row(terms_id)
    assert stored.is_frozen is True
    inputs = CampaignFinancialsInput.model_validate(stored.financial_inputs)
    report = calculate_viability(inputs)
    assert (
        stored.calculation["first_viable_attendance"]
        == report.first_viable_attendance
    )
    assert stored.calculation["attendance_curve"][0]["attendance"] == 1
    assert stored.calculation["attendance_curve"][-1]["attendance"] == inputs.capacity
    assert stored.snapshot_hash == build_snapshot_hash(
        inputs, opens_at=stored.opens_at, closes_at=stored.closes_at
    )
    assert stored.assumption_labels["materials"]["embroidery kit"] == "merchant-entered"
    assert "not Channel3 data" in stored.assumption_labels["note"]


def test_snapshot_hash_is_reproducible_across_rows(owned):
    workshop_a = _new_workshop(owned, "Repro A")
    workshop_b = _new_workshop(owned, "Repro B")
    schedule = _valid_schedule()
    ids = []
    for workshop_id in (workshop_a, workshop_b):
        with session_scope() as session:
            ids.append(
                _create_draft(
                    owned, session, workshop_id, _full_financials(), schedule
                ).id
            )
    first, second = (_get_row(terms_id) for terms_id in ids)
    # Identical content produces the identical hash (row identity excluded).
    assert first.snapshot_hash == second.snapshot_hash
    assert first.calculation == second.calculation


def test_frozen_terms_are_immutable(owned):
    workshop_id = _new_workshop(owned, "Immutable")
    with session_scope() as session:
        service = CampaignTermsService(session)
        terms_id = _create_draft(
            owned, session, workshop_id, _full_financials(), _valid_schedule()
        ).id
        service.freeze(terms_id)
    with session_scope() as session:
        service = CampaignTermsService(session)
        with pytest.raises(TermsFrozenError):
            service.update_draft(terms_id, _full_financials())
        with pytest.raises(TermsFrozenError):
            service.freeze(terms_id)
    assert _get_row(terms_id).is_frozen is True


def test_draft_versions_increment_per_workshop(owned):
    workshop_id = _new_workshop(owned, "Versioned")
    with session_scope() as session:
        first = _create_draft(owned, session, workshop_id, _full_financials())
        second = _create_draft(owned, session, workshop_id, _full_financials())
    assert first.version == 1
    assert second.version == 2


def test_freeze_rolls_back_with_transaction(owned):
    workshop_id = _new_workshop(owned, "Rollback Freeze")
    with session_scope() as session:
        terms_id = _create_draft(
            owned, session, workshop_id, _full_financials(), _valid_schedule()
        ).id
    with pytest.raises(RuntimeError):
        with session_scope() as session:
            service = CampaignTermsService(session)
            service.freeze(terms_id)
            raise RuntimeError("Simulated failure after freeze")
    stored = _get_row(terms_id)
    assert stored.is_frozen is False
    assert stored.frozen_at is None


def test_service_rejects_unknown_workshop(owned):
    with session_scope() as session:
        service = CampaignTermsService(session)
        with pytest.raises(LookupError):
            service.create_draft(
                uuid.uuid4(),
                CampaignFinancialsInput(ticket_price_minor=1000, capacity=3),
            )


def test_proposed_attendance_evaluation_via_stored_curve(owned):
    workshop_id = _new_workshop(owned, "Attendance Eval")
    with session_scope() as session:
        terms_id = _create_draft(
            owned, session, workshop_id, _full_financials(), _valid_schedule()
        ).id
    stored = _get_row(terms_id)
    curve = {
        entry["attendance"]: entry
        for entry in stored.calculation["attendance_curve"]
    }
    inputs = CampaignFinancialsInput.model_validate(stored.financial_inputs)
    report = calculate_viability(inputs)
    # The service can evaluate the actual proposed attendance from the
    # stored, reproducible curve. Viability at the first viable
    # attendance does not imply every larger attendance is viable.
    for point in report.attendance_curve:
        assert curve[point.attendance]["is_viable"] == point.is_viable
        assert (
            curve[point.attendance]["estimated_surplus_minor"]
            == point.estimated_surplus_minor
        )
    assert stored.calculation["attendance_curve"]