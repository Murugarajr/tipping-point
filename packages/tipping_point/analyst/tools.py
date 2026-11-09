"""Read-only Rescue Analyst tools.

All financial figures come from the backend calculator's ViabilityReport, computed once from the
saved terms before any model call (no database access while the model runs). Tools only select,
compare and describe those backend values; they never recompute economics and never accept a
workshop or merchant id (the route binds the authenticated, owned workshop).

`show_visualization` is the only browser-side effect: the server validates a fixed preset and returns
it to the browser, which applies it with AG Studio's public getState/setState. Nothing the browser
returns is fed back to the model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ..economics import CampaignFinancialsInput, ViabilityReport


def gbp(minor: int) -> str:
    sign = "-" if minor < 0 else ""
    minor = abs(minor)
    return f"{sign}£{minor // 100}.{minor % 100:02d}"


@dataclass
class AnalystContext:
    """Sanitised, owned-workshop data captured before the model run."""

    title: str
    description: str | None
    terms_version: int
    published: bool
    campaign_status: str | None
    inputs: CampaignFinancialsInput
    report: ViabilityReport
    admitted_attendance: int | None = None
    authorized_minor: int | None = None
    collected_minor: int | None = None
    # Booking eligibility (time-based) is reported separately from financial scenario viability.
    booking_cutoff_at: datetime | None = None
    bookings_closed: bool | None = None
    visualizations: list[dict] = field(default_factory=list)

    def point(self, attendance: int):
        return next((p for p in self.report.attendance_curve if p.attendance == attendance), None)


VISUALIZATION_PRESETS: dict[str, str] = {
    "revenue_vs_costs": "Line chart: revenue, total costs including estimated payment fees, and estimated surplus by attendance",
    "surplus_by_attendance": "Column chart: estimated surplus by attendance",
    "material_cost_by_attendance": "Stacked column chart: material cost by attendance and material",
    "attendance_table": "Table: attendance curve with backend viability per point",
    "materials_table": "Table: materials, pack sizes, pack prices and cost at capacity",
}


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class NoArgs(_Args):
    pass


class CurveArgs(_Args):
    from_attendance: int | None = Field(default=None, ge=0, le=10000)
    to_attendance: int | None = Field(default=None, ge=0, le=10000)


class CompareArgs(_Args):
    attendances: list[int] = Field(min_length=2, max_length=4)

    @model_validator(mode="after")
    def _bounds(self):
        if any(a < 0 or a > 10000 for a in self.attendances):
            raise ValueError("attendance out of range")
        return self


class DriversArgs(_Args):
    attendance: int | None = Field(default=None, ge=0, le=10000)


class VisualizationArgs(_Args):
    preset: Literal["revenue_vs_costs", "surplus_by_attendance", "material_cost_by_attendance", "attendance_table", "materials_table"]
    title: str | None = Field(default=None, max_length=80)


def _point_out(p) -> dict:
    return {
        "attendance": p.attendance,
        "viable": p.is_viable,
        "revenue": gbp(p.gross_minor),
        "estimated_fees": gbp(p.estimated_fees_minor),
        "material_cost": gbp(p.material_cost_minor),
        "approved_budget_excluding_estimated_fees": gbp(p.required_budget_minor),
        # revenue - total_costs_including_estimated_fees == estimated_surplus (calculator: net - budget).
        "total_costs_including_estimated_fees": gbp(p.required_budget_minor + p.estimated_fees_minor),
        "estimated_surplus": gbp(p.estimated_surplus_minor),
        "packs_by_material": dict(p.packs_by_material),
    }


def _adjacent(curve) -> list[tuple]:
    return [(a, b) for a, b in zip(curve, curve[1:]) if b.attendance == a.attendance + 1]


def _material_minor(ctx: AnalystContext, point, name: str) -> int:
    price = next((m.pack_price_minor for m in ctx.inputs.materials if m.name == name), 0)
    return point.packs_by_material.get(name, 0) * price


def _increment_pattern(increments: list[tuple]) -> tuple[int, list[tuple]]:
    """increments: [(a, b, change_minor)] over adjacent points. The usual change is the smallest one; steps above
    it are pack-boundary jumps. Uniform increments (however large) are ordinary per-attendee costs, not jumps."""
    usual = min(change for _, _, change in increments)
    return usual, [(a, b, change) for a, b, change in increments if change > usual]


def cost_observations(ctx: AnalystContext) -> dict:
    """Deterministic observations read from adjacent points of the backend curve (no economics recomputed):
    material cost change per added attendee, irregular pack-boundary steps, and backend viability reversals."""
    curve = ctx.report.attendance_curve
    steps = _adjacent(curve)
    if not steps:
        return {"summary": "Not enough adjacent attendance points to describe cost changes.", "pack_boundary_jumps": [], "viability_reversals": []}
    usual, irregular = _increment_pattern([(a, b, b.material_cost_minor - a.material_cost_minor) for a, b in steps])
    jumps = [{
        "from": a.attendance, "to": b.attendance, "material_cost_change": gbp(change), "usual_change": gbp(usual),
        "extra_over_usual": gbp(change - usual),
        "pack_changes": {k: b.packs_by_material.get(k, 0) - a.packs_by_material.get(k, 0)
                         for k in sorted(set(a.packs_by_material) | set(b.packs_by_material))
                         if b.packs_by_material.get(k, 0) != a.packs_by_material.get(k, 0)},
        "viable_before": a.is_viable, "viable_after": b.is_viable,
    } for a, b, change in irregular][:20]
    reversals = [{"from": a.attendance, "to": b.attendance, "estimated_surplus_before": gbp(a.estimated_surplus_minor),
                  "estimated_surplus_after": gbp(b.estimated_surplus_minor)} for a, b in steps if a.is_viable and not b.is_viable][:20]
    span = f"attendance {steps[0][0].attendance} to {steps[-1][1].attendance}"
    if not irregular:
        summary = f"Even: material cost rises by {gbp(usual)} per added attendee at every step from {span}. No pack-boundary jumps."
    else:
        summary = (f"Stepped: usually {gbp(usual)} per added attendee from {span}, with pack-boundary jumps at attendance "
                   + ", ".join(str(j["to"]) for j in jumps) + ".")
    summary += (" No viability reversals: once viable, every higher attendance in the curve stays viable." if not reversals else
                " Viability reversals (backend): " + ", ".join(f"{r['from']} viable -> {r['to']} not viable" for r in reversals) + ".")
    return {"summary": summary, "usual_material_cost_change_per_added_attendee": gbp(usual),
            "pack_boundary_jumps": jumps, "viability_reversals": reversals}


def get_workshop_overview(ctx: AnalystContext, _: NoArgs) -> dict:
    i, r = ctx.inputs, ctx.report
    fee = i.fee_estimate
    return {
        "workshop_title": ctx.title,
        "description_untrusted_text": (ctx.description or "")[:1000],
        "terms_version": ctx.terms_version,
        "publication": ctx.campaign_status or "DRAFT (not published)",
        "ticket_price": gbp(i.ticket_price_minor),
        "capacity": i.capacity,
        "minimum_operating_attendance": r.minimum_operating_attendance,
        "fixed_costs": gbp(i.fixed_costs_minor),
        "shipping_allowance": gbp(i.shipping_allowance_minor),
        "contingency": gbp(i.contingency_minor),
        "fee_estimate": None if fee is None else {"percent_basis_points": fee.percent_basis_points, "fixed_per_attendee": gbp(fee.fixed_minor)},
        "first_viable_attendance": r.first_viable_attendance,
        "any_viable_attendance": r.any_viable_attendance,
        "viable_at_capacity": r.is_viable_at_capacity,
        "viable_attendances": [p.attendance for p in r.attendance_curve if p.is_viable],
        "cost_observations": cost_observations(ctx),
        "non_viable_attendances": [p.attendance for p in r.attendance_curve if not p.is_viable],
        "booking_window": (
            "Not published" if not ctx.published or ctx.bookings_closed is None
            else {"cutoff_utc": ctx.booking_cutoff_at.isoformat() if ctx.booking_cutoff_at else None,
                  "new_bookings": "closed: cutoff passed" if ctx.bookings_closed else "open until cutoff",
                  "note": "Booking eligibility depends on time and status, not on financial viability. A stored status of OPEN after the cutoff means the settlement decision has not run yet."}
        ),
        "bookings": (
            {"admitted_bookings": ctx.admitted_attendance, "authorised_not_collected": gbp(ctx.authorized_minor or 0), "collected": gbp(ctx.collected_minor or 0)}
            if ctx.admitted_attendance is not None else "Not available (not published or settlement data unavailable)"
        ),
        "materials": [
            {"name_untrusted_text": m.name[:200], "kind": m.kind, "pack_size": m.pack_size, "pack_price": gbp(m.pack_price_minor),
             "shared_units": m.shared_units, "per_attendee_units": m.per_attendee_units,
             "source": "reviewed supplier snapshot" if m.offer_provenance else "merchant-entered assumption"}
            for m in i.materials
        ],
        "basis": "Saved terms and the backend calculator (algorithm " + r.algorithm_version + "). Estimates, not collected money.",
    }


def get_attendance_curve(ctx: AnalystContext, args: CurveArgs) -> dict:
    lo = args.from_attendance if args.from_attendance is not None else 0
    hi = args.to_attendance if args.to_attendance is not None else 10000
    points = [p for p in ctx.report.attendance_curve if lo <= p.attendance <= hi][:60]
    return {"points": [_point_out(p) for p in points], "cost_observations": cost_observations(ctx),
            "note": "Viability is per attendance point from the backend calculator."}


def compare_attendance(ctx: AnalystContext, args: CompareArgs) -> dict:
    out, missing = [], []
    for attendance in args.attendances:
        p = ctx.point(attendance)
        (out.append(_point_out(p)) if p else missing.append(attendance))
    changes = []
    for a, b in zip(out, out[1:]):
        pa, pb = ctx.point(a["attendance"]), ctx.point(b["attendance"])
        between = [(x, y) for x, y in _adjacent(ctx.report.attendance_curve) if pa.attendance <= x.attendance and y.attendance <= pb.attendance]
        per_step = sorted({y.material_cost_minor - x.material_cost_minor for x, y in between})
        changes.append({
            "from": pa.attendance, "to": pb.attendance,
            "attendance_steps": pb.attendance - pa.attendance,
            "material_cost_change_per_added_attendee": (gbp(per_step[0]) if len(per_step) == 1 else "varies: see cost_observations"),
            "revenue_change": gbp(pb.gross_minor - pa.gross_minor),
            "material_cost_change": gbp(pb.material_cost_minor - pa.material_cost_minor),
            "approved_budget_change": gbp(pb.required_budget_minor - pa.required_budget_minor),
            "total_cost_including_fees_change": gbp((pb.required_budget_minor + pb.estimated_fees_minor) - (pa.required_budget_minor + pa.estimated_fees_minor)),
            "surplus_change": gbp(pb.estimated_surplus_minor - pa.estimated_surplus_minor),
            "pack_changes": {k: pb.packs_by_material.get(k, 0) - pa.packs_by_material.get(k, 0)
                             for k in sorted(set(pa.packs_by_material) | set(pb.packs_by_material))
                             if pb.packs_by_material.get(k, 0) != pa.packs_by_material.get(k, 0)},
        })
    return {"points": out, "changes": changes, "outside_curve": missing,
            "note": ("Hypothetical attendance scenarios from the backend calculator; not bookings. Changes between "
                     "non-adjacent attendances span several steps: pack counts there add up across steps and are not "
                     "jumps. Use cost_observations for step-by-step behaviour.")}


def get_material_cost_drivers(ctx: AnalystContext, args: DriversArgs) -> dict:
    curve = ctx.report.attendance_curve
    if not curve:
        return {"materials": [], "note": "No attendance curve."}
    attendance = args.attendance if args.attendance is not None else ctx.report.capacity
    p = ctx.point(attendance)
    if p is None:
        return {"error": f"Attendance {attendance} is outside the calculated curve ({curve[0].attendance}..{curve[-1].attendance})."}
    prices = {m.name: m.pack_price_minor for m in ctx.inputs.materials}
    drivers = []
    for m in ctx.inputs.materials:
        packs = p.packs_by_material.get(m.name, 0)
        # Pack-step attendances: where the backend's pack count for this material increases.
        steps = [b.attendance for a, b in zip(curve, curve[1:]) if b.packs_by_material.get(m.name, 0) > a.packs_by_material.get(m.name, 0)]
        adjacent = _adjacent(curve)
        if adjacent:
            usual, irregular = _increment_pattern([(a, b, _material_minor(ctx, b, m.name) - _material_minor(ctx, a, m.name)) for a, b in adjacent])
            pattern = (("Fixed: does not change with attendance." if usual == 0 else f"Even: +{gbp(usual)} per added attendee; no pack-boundary jumps.")
                       if not irregular else f"Stepped: usually +{gbp(usual)} per added attendee; jumps at attendance "
                       + ", ".join(f"{b.attendance} (+{gbp(c)})" for _, b, c in irregular[:20]) + ".")
        else:
            pattern = "Not enough adjacent attendance points."
        drivers.append({
            "material_untrusted_text": m.name[:200], "packs": packs, "cost": gbp(packs * prices[m.name]),
            "share_of_material_cost": round(packs * prices[m.name] / p.material_cost_minor, 3) if p.material_cost_minor else None,
            "cost_pattern": pattern,
            # A higher pack count is not by itself a jump: with one pack per attendee it rises at every step.
            "pack_count_increases_at_attendance": steps[:20],
        })
    drivers.sort(key=lambda d: -(d["share_of_material_cost"] or 0))
    return {"attendance": attendance, "material_cost": gbp(p.material_cost_minor), "cost_observations": cost_observations(ctx)["summary"],
            "fixed_shipping_contingency": gbp(p.required_budget_minor - p.material_cost_minor), "materials": drivers}


def show_visualization(ctx: AnalystContext, args: VisualizationArgs) -> dict:
    title = " ".join((args.title or "").split())[:80] or None
    action = {"preset": args.preset, "title": title}
    ctx.visualizations = [v for v in ctx.visualizations if v["preset"] != args.preset] + [action]
    return {"status": "requested", "preset": args.preset,
            "note": "The browser will add or update this Studio widget from saved data; nothing is returned from the browser."}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args: type[_Args]
    run: Any
    parameters: dict


def _schema(args: type[_Args]) -> dict:
    schema = args.model_json_schema()
    schema.pop("title", None)
    for prop in schema.get("properties", {}).values():
        prop.pop("title", None)
    schema["additionalProperties"] = False
    return schema


TOOLS: dict[str, ToolSpec] = {spec.name: spec for spec in [
    ToolSpec("get_workshop_overview", "Saved financial inputs, publication status, viability summary and materials for this workshop.", NoArgs, get_workshop_overview, _schema(NoArgs)),
    ToolSpec("get_attendance_curve", "Backend calculator points (revenue, costs, surplus, viability, packs) for an attendance range.", CurveArgs, get_attendance_curve, _schema(CurveArgs)),
    ToolSpec("compare_attendance", "Compare 2-4 attendance scenarios using backend calculator points, including pack-count changes.", CompareArgs, compare_attendance, _schema(CompareArgs)),
    ToolSpec("get_material_cost_drivers", "Material cost breakdown at one attendance (default capacity) and the attendances where extra packs are needed.", DriversArgs, get_material_cost_drivers, _schema(DriversArgs)),
    ToolSpec("show_visualization", "Add or update a Studio chart/table on the dashboard from a fixed preset: " + "; ".join(f"{k} = {v}" for k, v in VISUALIZATION_PRESETS.items()), VisualizationArgs, show_visualization, _schema(VisualizationArgs)),
]}


def tool_definitions() -> list[dict]:
    return [{"type": "function", "function": {"name": s.name, "description": s.description, "parameters": s.parameters}} for s in TOOLS.values()]


class ToolRejected(Exception):
    """Unsupported tool or invalid arguments: reported to the model, never executed."""


def execute_tool(ctx: AnalystContext, name: str, arguments: dict) -> dict:
    spec = TOOLS.get(name)
    if spec is None:
        raise ToolRejected(f"Unsupported tool: {name[:60]}")
    try:
        args = spec.args.model_validate(arguments)
    except ValidationError:
        raise ToolRejected(f"Invalid arguments for {name}") from None
    return spec.run(ctx, args)
