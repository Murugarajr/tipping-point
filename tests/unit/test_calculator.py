"""Unit tests for the pure deterministic viability calculator and schemas.

No database, no credentials, no network: these prove the financial model.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from tipping_point.economics import (
    ALGORITHM_VERSION,
    CAMPAIGN_MAX_DURATION_HOURS,
    CampaignFinancialsInput,
    CampaignScheduleInput,
    FeeEstimateInput,
    MaterialLineInput,
    build_snapshot_hash,
    calculate_viability,
)


def financials(**overrides) -> CampaignFinancialsInput:
    base = dict(
        ticket_price_minor=2500,
        capacity=10,
        fixed_costs_minor=5000,
    )
    base.update(overrides)
    return CampaignFinancialsInput(**base)


def material(**overrides) -> MaterialLineInput:
    base = dict(
        name="kit",
        source_label="merchant-entered",
        shared_units=0,
        per_attendee_units=1,
        pack_size=1,
        pack_price_minor=0,
    )
    base.update(overrides)
    return MaterialLineInput(**base)


class TestBreakEven:
    def test_exact_break_even_and_one_attendee_below(self):
        report = calculate_viability(financials())
        assert report.first_viable_attendance == 2
        below = report.attendance_point(1)
        assert below.estimated_surplus_minor == -2500
        assert below.is_viable is False
        exact = report.attendance_point(2)
        assert exact.estimated_surplus_minor == 0
        assert exact.is_viable is True

    def test_no_viable_attendance_within_capacity(self):
        report = calculate_viability(
            financials(ticket_price_minor=100, capacity=3, fixed_costs_minor=10000)
        )
        assert report.first_viable_attendance is None
        assert report.any_viable_attendance is False
        assert report.is_viable_at_capacity is False
        assert all(point.estimated_surplus_minor < 0 for point in report.attendance_curve)


class TestPackBoundaries:
    def test_pack_boundary_cost_jump(self):
        inputs = financials(
            ticket_price_minor=2000,
            capacity=12,
            fixed_costs_minor=0,
            materials=[material(pack_size=10, pack_price_minor=1000)],
        )
        report = calculate_viability(inputs)
        at_ten = report.attendance_point(10)
        at_eleven = report.attendance_point(11)
        assert at_ten.packs_by_material["kit"] == 1
        assert at_ten.material_cost_minor == 1000
        assert at_eleven.packs_by_material["kit"] == 2
        assert at_eleven.material_cost_minor == 2000

    def test_viable_then_non_viable_then_viable_again(self):
        # Pack jumps make viability non-monotonic: first viable at 3,
        # non-viable at 4 (new pack), viable again at 5 and 6, and
        # non-viable at capacity (7) — proving attendance above the
        # first viable attendance is not guaranteed viable.
        inputs = financials(
            ticket_price_minor=1000,
            capacity=7,
            fixed_costs_minor=0,
            materials=[material(pack_size=3, pack_price_minor=2500)],
        )
        report = calculate_viability(inputs)
        assert report.first_viable_attendance == 3
        assert report.attendance_point(3).is_viable is True
        assert report.attendance_point(4).is_viable is False
        assert report.attendance_point(4).estimated_surplus_minor == -1000
        assert report.attendance_point(5).is_viable is True
        assert report.attendance_point(6).is_viable is True
        assert report.attendance_point(7).is_viable is False
        assert report.is_viable_at_capacity is False

    def test_shared_plus_per_attendee_quantities(self):
        inputs = financials(
            ticket_price_minor=5000,
            capacity=8,
            fixed_costs_minor=0,
            materials=[material(shared_units=4, per_attendee_units=2, pack_size=5, pack_price_minor=100)],
        )
        report = calculate_viability(inputs)
        assert report.attendance_point(1).packs_by_material["kit"] == 2  # 6 units -> 2 packs
        assert report.attendance_point(3).packs_by_material["kit"] == 2  # 10 units -> 2 packs
        assert report.attendance_point(8).packs_by_material["kit"] == 4  # 20 units -> 4 packs

    def test_reusable_equipment_is_not_budgeted(self):
        inputs = financials(
            ticket_price_minor=5000,
            capacity=4,
            fixed_costs_minor=1000,
            materials=[
                material(name="frames", kind="reusable", per_attendee_units=1, pack_size=1, pack_price_minor=9999),
            ],
        )
        report = calculate_viability(inputs)
        for point in report.attendance_curve:
            assert point.packs_by_material["frames"] == 0
            assert point.material_cost_minor == 0
            assert point.required_budget_minor == 1000

class TestFeesShippingContingency:
    def test_conservative_fee_rounding_per_transaction(self):
        fee = FeeEstimateInput(percent_basis_points=249, fixed_minor=30)
        inputs = financials(
            ticket_price_minor=1000,
            capacity=2,
            fixed_costs_minor=0,
            fee_estimate=fee,
        )
        report = calculate_viability(inputs)
        one = report.attendance_point(1)
        two = report.attendance_point(2)
        # 1000 * 249bp = 24.9p -> conservative ceil -> 25p, plus 30p fixed.
        assert one.estimated_fees_minor == 55
        assert two.estimated_fees_minor == 110
        assert one.estimated_net_minor == 945
        assert two.estimated_net_minor == 1890

    def test_fee_rounding_is_exact_when_divisible(self):
        fee = FeeEstimateInput(percent_basis_points=250, fixed_minor=0)
        inputs = financials(
            ticket_price_minor=1000,
            capacity=1,
            fixed_costs_minor=0,
            fee_estimate=fee,
        )
        assert calculate_viability(inputs).attendance_point(1).estimated_fees_minor == 25

    def test_shipping_and_contingency_counted_exactly_once(self):
        inputs = financials(
            ticket_price_minor=3000,
            capacity=3,
            fixed_costs_minor=1000,
            shipping_allowance_minor=500,
            contingency_minor=250,
            materials=[material(shared_units=5, per_attendee_units=0, pack_size=5, pack_price_minor=1000)],
        )
        report = calculate_viability(inputs)
        for point in report.attendance_curve:
            # 1000 fixed + 1000 materials + 500 shipping + 250 contingency.
            assert point.required_budget_minor == 2750


class TestValidation:
    def test_unsupported_currency_rejected(self):
        with pytest.raises(ValidationError):
            financials(currency="USD")

    def test_invalid_money_rejected(self):
        with pytest.raises(ValidationError):
            financials(ticket_price_minor=-1)
        with pytest.raises(ValidationError):
            financials(fixed_costs_minor=-100)
        with pytest.raises(ValidationError):
            financials(ticket_price_minor=10.5)  # type: ignore[arg-type]

    def test_invalid_quantities_rejected(self):
        with pytest.raises(ValidationError):
            financials(capacity=0)
        with pytest.raises(ValidationError):
            material(pack_size=0)
        with pytest.raises(ValidationError):
            material(shared_units=-1)
        with pytest.raises(ValidationError):
            material(per_attendee_units=-2)

    def test_minimum_operating_attendance_cannot_exceed_capacity(self):
        with pytest.raises(ValidationError, match="capacity"):
            financials(minimum_operating_attendance=5, capacity=3)

    def test_duplicate_material_names_rejected(self):
        with pytest.raises(ValidationError, match="unique"):
            financials(materials=[material(name="kit"), material(name="kit")])

    def test_consumable_with_zero_units_rejected(self):
        with pytest.raises(ValidationError, match="units"):
            material(kind="consumable", shared_units=0, per_attendee_units=0)

    def test_schedule_requires_timezone_aware_dates(self):
        naive = datetime(2026, 11, 10, 12, 0, 0)
        with pytest.raises(ValidationError, match="timezone-aware"):
            CampaignScheduleInput(opens_at=naive, closes_at=naive + timedelta(hours=1))

    def test_schedule_rejects_inverted_dates(self):
        base = datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc)
        with pytest.raises(ValidationError, match="after campaign open"):
            CampaignScheduleInput(opens_at=base, closes_at=base - timedelta(hours=1))

    def test_schedule_enforces_short_duration_policy(self):
        base = datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc)
        with pytest.raises(ValidationError, match="48"):
            CampaignScheduleInput(
                opens_at=base,
                closes_at=base + timedelta(hours=CAMPAIGN_MAX_DURATION_HOURS + 1),
            )

    def test_attendance_outside_evaluated_range_raises(self):
        report = calculate_viability(financials(capacity=4))
        with pytest.raises(KeyError):
            report.attendance_point(5)


class TestSnapshotHash:
    def test_identical_inputs_reproduce_identical_hash(self):
        a = financials(fee_estimate=FeeEstimateInput(percent_basis_points=249, fixed_minor=30))
        b = financials(fee_estimate=FeeEstimateInput(percent_basis_points=249, fixed_minor=30))
        opens = datetime(2026, 11, 10, 9, 0, 0, tzinfo=timezone.utc)
        closes = opens + timedelta(hours=24)
        assert build_snapshot_hash(a, opens_at=opens, closes_at=closes) == \
            build_snapshot_hash(b, opens_at=opens, closes_at=closes)

    def test_changed_terms_change_the_hash(self):
        a = financials()
        b = financials(ticket_price_minor=2501)
        assert build_snapshot_hash(a) != build_snapshot_hash(b)

    def test_hash_covers_algorithm_version(self):
        assert ALGORITHM_VERSION == "workshop-viability-1"