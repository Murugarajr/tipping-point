"""Deterministic workshop viability calculation.

The authority for the minimum viable attendance threshold. All money is
integer minor units (GBP pence); no binary floating-point arithmetic is
used anywhere in this module. Viability is enumerated per attendance
because pack-cost boundaries make the surplus curve discontinuous: an
attendance above the first viable attendance is NOT guaranteed viable.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from .schemas import CampaignFinancialsInput, FeeEstimateInput

#: Version stamped into every snapshot so results stay reproducible.
ALGORITHM_VERSION = "workshop-viability-1"

#: Explicit costing policy: consumable packs are budgeted; reusable
#: equipment is recorded as an assumption but is not part of the budget.
COSTING_POLICY = (
    "consumable materials are budgeted as whole packs; "
    "reusable equipment is recorded but not budgeted"
)

_MIN_FEE_DENOMINATOR = 10_000  # basis points -> fraction


@dataclass(frozen=True)
class AttendancePoint:
    """One row of the attendance/cost curve."""

    attendance: int
    packs_by_material: dict[str, int]
    material_cost_minor: int
    required_budget_minor: int
    gross_minor: int
    estimated_fees_minor: int
    estimated_net_minor: int
    estimated_surplus_minor: int
    is_viable: bool


@dataclass(frozen=True)
class ViabilityReport:
    """Complete enumerated attendance/cost curve for one campaign."""

    algorithm_version: str
    currency: str
    ticket_price_minor: int
    capacity: int
    minimum_operating_attendance: int
    attendance_curve: list[AttendancePoint] = field(default_factory=list)
    first_viable_attendance: int | None = None
    any_viable_attendance: bool = False
    is_viable_at_capacity: bool = False

    def attendance_point(self, attendance: int) -> AttendancePoint:
        """Return the evaluated curve point for ``attendance``.

        Raises ``KeyError`` for attendances outside the evaluated range.
        """
        for point in self.attendance_curve:
            if point.attendance == attendance:
                return point
        raise KeyError(
            f"attendance {attendance} was not evaluated "
            f"(range {self.minimum_operating_attendance}..{self.capacity})"
        )


def _ceil_div(numerator: int, denominator: int) -> int:
    """Exact integer ceiling division for non-negative values."""
    return -(-numerator // denominator)


def _fee_per_transaction_minor(
    ticket_price_minor: int,
    fee_estimate: FeeEstimateInput | None,
) -> int:
    """Conservative per-transaction fee estimate, rounded UP."""
    if fee_estimate is None:
        return 0
    variable = _ceil_div(
        ticket_price_minor * fee_estimate.percent_basis_points,
        _MIN_FEE_DENOMINATOR,
    )
    return fee_estimate.fixed_minor + variable


def calculate_viability(
    inputs: CampaignFinancialsInput,
) -> ViabilityReport:
    """Enumerate every permitted attendance and its viability.

    The curve covers ``minimum_operating_attendance`` (default 1) through
    ``capacity`` inclusive. Each consumable material contributes
    ``ceil((shared_units + per_attendee_units * n) / pack_size)`` packs
    at the approved pack price. Fixed costs, the shipping allowance, and
    the contingency are counted exactly once per attendance value. The
    estimated fee is subtracted conservatively (rounded up per
    transaction).
    """
    fee_estimate = inputs.fee_estimate
    minimum_attendance = inputs.minimum_operating_attendance or 1

    curve: list[AttendancePoint] = []
    for attendance in range(minimum_attendance, inputs.capacity + 1):
        packs_by_material: dict[str, int] = {}
        material_cost = 0
        for material in inputs.materials:
            if material.kind == "reusable":
                packs_by_material[material.name] = 0
                continue
            units = material.shared_units + material.per_attendee_units * attendance
            packs = _ceil_div(units, material.pack_size)
            packs_by_material[material.name] = packs
            material_cost += packs * material.pack_price_minor

        required_budget = (
            inputs.fixed_costs_minor
            + material_cost
            + inputs.shipping_allowance_minor
            + inputs.contingency_minor
        )
        gross = attendance * inputs.ticket_price_minor
        fees = attendance * _fee_per_transaction_minor(
            inputs.ticket_price_minor, fee_estimate
        )
        net = gross - fees
        surplus = net - required_budget

        curve.append(
            AttendancePoint(
                attendance=attendance,
                packs_by_material=packs_by_material,
                material_cost_minor=material_cost,
                required_budget_minor=required_budget,
                gross_minor=gross,
                estimated_fees_minor=fees,
                estimated_net_minor=net,
                estimated_surplus_minor=surplus,
                is_viable=surplus >= 0,
            )
        )

    viable = [point.attendance for point in curve if point.is_viable]
    return ViabilityReport(
        algorithm_version=ALGORITHM_VERSION,
        currency=inputs.currency,
        ticket_price_minor=inputs.ticket_price_minor,
        capacity=inputs.capacity,
        minimum_operating_attendance=minimum_attendance,
        attendance_curve=curve,
        first_viable_attendance=viable[0] if viable else None,
        any_viable_attendance=bool(viable),
        is_viable_at_capacity=bool(curve) and curve[-1].is_viable,
    )


def build_snapshot_hash(
    inputs: CampaignFinancialsInput,
    *,
    opens_at: object = None,
    closes_at: object = None,
) -> str:
    """Deterministic SHA-256 over canonical snapshot content.

    The hash covers the validated financial inputs, the algorithm
    version, and the campaign dates — never row identity — so identical
    terms always reproduce the identical hash.
    """
    payload = {
        "algorithm_version": ALGORITHM_VERSION,
        "inputs": inputs.model_dump(mode="json"),
        "opens_at": opens_at.isoformat() if opens_at is not None else None,
        "closes_at": closes_at.isoformat() if closes_at is not None else None,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()