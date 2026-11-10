import type { AttendancePoint, ViabilityPreview, WorkshopDetail } from "../../types";

/**
 * Campaign Intelligence datasets for AG Studio.
 *
 * Every figure comes from the authenticated merchant APIs: the saved workshop detail
 * (GET /api/merchant/workshops/{id}) and the backend calculator
 * (POST /api/merchant/workshops/{id}/preview, a pure calculation). Nothing here recalculates
 * viability: each attendance point keeps the backend's own `is_viable`, because pack-cost steps
 * mean attendance above the first viable point is not necessarily viable.
 *
 * Sanitised: no merchant IDs, session data, offer snapshot IDs, product URLs or guest data.
 * Money is converted from integer pence to pounds for display only.
 */

const pounds = (minor: number) => minor / 100;

export interface AttendanceRow {
  attendance: number;
  revenue_gbp: number;
  fees_gbp: number;
  net_revenue_gbp: number;
  material_cost_gbp: number;
  fixed_and_other_costs_gbp: number;
  /** Approved budget: materials, fixed, shipping and contingency. Excludes estimated payment fees. */
  approved_budget_gbp: number;
  /** Approved budget plus estimated payment fees, so revenue - total costs = estimated surplus. */
  total_costs_gbp: number;
  estimated_surplus_gbp: number;
  viability: "Viable" | "Not viable";
}

export interface MaterialRow {
  material: string;
  kind: string;
  source: string;
  pack_size: number;
  pack_price_gbp: number;
  shared_units: number;
  per_attendee_units: number;
  packs_at_capacity: number | null;
  cost_at_capacity_gbp: number | null;
}

export interface MaterialCostRow {
  attendance: number;
  material: string;
  packs: number;
  cost_gbp: number;
}

export type TippingState =
  | "Draft · not published"
  | "Booking data unavailable"
  | "No viable attendance"
  | "Below threshold"
  | "Not viable at current attendance"
  | "Threshold reached · awaiting cutoff"
  | "Cutoff passed · awaiting decision"
  | "Confirmed"
  | "Cancelled"
  | "Review required"
  | "Campaign closed";

export interface CampaignHealthRow {
  workshop: string;
  terms_version: number;
  publication: string;
  tipping_state: TippingState;
  capacity: number;
  minimum_operating_attendance: number;
  first_viable_attendance: number | null;
  viable_at_capacity: "Yes" | "No";
  /** Admitted bookings from the settlement projection; null when not published or unavailable. */
  admitted_attendance: number | null;
  /** Smallest backend-viable attendance at or above current admitted attendance. */
  next_viable_attendance: number | null;
  /** Meter target: next viable attendance when bookings are known, otherwise the first viable attendance. */
  target_attendance: number | null;
  places_still_required: number | null;
  viable_at_current_attendance: "Viable" | "Not viable" | "Not available";
  estimated_surplus_at_current_gbp: number | null;
  /** Authorised, not collected. Kept separate from collected. */
  authorized_gbp: number | null;
  collected_gbp: number | null;
  cutoff_at: string | null;
  /** Time-based booking eligibility (same rule as the guest booking service); independent of viability. */
  booking_window: "Open" | "Closed · cutoff passed" | "Not open";
}

export interface IntelligenceData {
  health: CampaignHealthRow;
  attendance: AttendanceRow[];
  materials: MaterialRow[];
  materialCosts: MaterialCostRow[];
  /** Mismatches between backend material totals and per-line pack × price; shown, never "corrected". */
  warnings: string[];
  /** Capabilities intentionally shown as unavailable, with reasons. */
  unavailable: string[];
}

export function attendanceRows(curve: AttendancePoint[]): AttendanceRow[] {
  return curve.map((p) => ({
    attendance: p.attendance,
    revenue_gbp: pounds(p.gross_minor),
    fees_gbp: pounds(p.estimated_fees_minor),
    net_revenue_gbp: pounds(p.estimated_net_minor),
    material_cost_gbp: pounds(p.material_cost_minor),
    fixed_and_other_costs_gbp: pounds(p.required_budget_minor - p.material_cost_minor),
    approved_budget_gbp: pounds(p.required_budget_minor),
    total_costs_gbp: pounds(p.required_budget_minor + p.estimated_fees_minor),
    estimated_surplus_gbp: pounds(p.estimated_surplus_minor),
    viability: p.is_viable ? "Viable" : "Not viable",
  }));
}

/** Smallest attendance >= `from` that the backend marked viable; null if none. */
export function nextViableAttendance(curve: AttendancePoint[], from: number): number | null {
  return curve.find((p) => p.attendance >= from && p.is_viable)?.attendance ?? null;
}

export function materialRows(detail: WorkshopDetail, preview: ViabilityPreview): MaterialRow[] {
  const atCapacity = preview.attendance_curve.find((p) => p.attendance === preview.capacity);
  return detail.financials.materials.map((line) => {
    const packs = atCapacity ? atCapacity.packs_by_material[line.name] ?? null : null;
    const provenance = line.offer_provenance;
    return {
      material: line.name,
      kind: line.kind,
      source: provenance
        ? `Channel3 offer snapshot (${provenance.merchant_domain}), retrieved ${provenance.retrieved_at.slice(0, 10)}; merchant-reviewed`
        : "Merchant-entered assumption",
      pack_size: line.pack_size,
      pack_price_gbp: pounds(line.pack_price_minor),
      shared_units: line.shared_units,
      per_attendee_units: line.per_attendee_units,
      packs_at_capacity: packs,
      cost_at_capacity_gbp: packs === null ? null : pounds(packs * line.pack_price_minor),
    };
  });
}

/**
 * Per-material cost by attendance from the backend's pack counts × saved pack price.
 * Returns warnings when a point's per-line sum disagrees with the backend total.
 */
export function materialCostRows(detail: WorkshopDetail, preview: ViabilityPreview): { rows: MaterialCostRow[]; warnings: string[] } {
  const price = new Map(detail.financials.materials.map((line) => [line.name, line.pack_price_minor]));
  const rows: MaterialCostRow[] = [];
  const warnings: string[] = [];
  for (const point of preview.attendance_curve) {
    let total = 0;
    for (const [material, packs] of Object.entries(point.packs_by_material)) {
      const unit = price.get(material);
      if (unit === undefined) { warnings.push(`Attendance ${point.attendance}: "${material}" is in the backend calculation but not in the saved materials.`); continue; }
      total += packs * unit;
      rows.push({ attendance: point.attendance, material, packs, cost_gbp: pounds(packs * unit) });
    }
    if (total !== point.material_cost_minor) {
      warnings.push(`Attendance ${point.attendance}: material lines sum to ${pounds(total)} but the backend total is ${pounds(point.material_cost_minor)}; the backend total is authoritative.`);
    }
  }
  return { rows, warnings };
}

/** New bookings stop at the earlier of the campaign cutoff and the terms closing time. */
export function bookingCutoff(detail: WorkshopDetail): string | null {
  const times = [detail.campaign?.cutoff_at, detail.closes_at].filter((t): t is string => Boolean(t));
  if (!detail.campaign || times.length === 0) return null;
  return times.reduce((a, b) => (Date.parse(a) <= Date.parse(b) ? a : b));
}

export function campaignHealth(detail: WorkshopDetail, preview: ViabilityPreview, now: Date = new Date()): CampaignHealthRow {
  const curve = preview.attendance_curve;
  const campaign = detail.campaign;
  const settlement = campaign?.settlement ?? null;
  const admitted = settlement ? settlement.admitted_attendance : null;
  const current = admitted === null ? undefined : curve.find((p) => p.attendance === admitted);
  const next = admitted === null ? null : nextViableAttendance(curve, Math.max(admitted, preview.minimum_operating_attendance));
  const viableNow = admitted === null ? "Not available" : current?.is_viable ? "Viable" : "Not viable";
  const cutoff = bookingCutoff(detail);
  const cutoffPassed = cutoff !== null && now.getTime() >= Date.parse(cutoff);

  let state: TippingState;
  if (!campaign) state = "Draft · not published";
  else if (campaign.status === "CONFIRMED") state = "Confirmed";
  else if (campaign.status === "CANCELLED") state = "Cancelled";
  else if (settlement?.review_required) state = "Review required";
  else if (!settlement) state = "Booking data unavailable";
  else if (campaign.status !== "OPEN") state = "Campaign closed";
  else if (cutoffPassed) state = "Cutoff passed · awaiting decision";
  else if (!preview.any_viable_attendance) state = "No viable attendance";
  else if (viableNow === "Viable") state = "Threshold reached · awaiting cutoff";
  else if (preview.first_viable_attendance !== null && admitted !== null && admitted >= preview.first_viable_attendance) state = "Not viable at current attendance";
  else state = "Below threshold";

  return {
    workshop: detail.title,
    terms_version: detail.terms_version,
    publication: campaign ? campaign.status : "DRAFT",
    tipping_state: state,
    capacity: preview.capacity,
    minimum_operating_attendance: preview.minimum_operating_attendance,
    first_viable_attendance: preview.first_viable_attendance,
    viable_at_capacity: preview.is_viable_at_capacity ? "Yes" : "No",
    admitted_attendance: admitted,
    next_viable_attendance: next,
    target_attendance: admitted === null ? preview.first_viable_attendance : next,
    places_still_required: admitted === null || next === null ? null : Math.max(0, next - admitted),
    viable_at_current_attendance: viableNow,
    estimated_surplus_at_current_gbp: current ? pounds(current.estimated_surplus_minor) : null,
    authorized_gbp: settlement ? pounds(settlement.authorized_minor) : null,
    collected_gbp: settlement ? pounds(settlement.collected_minor) : null,
    cutoff_at: campaign?.cutoff_at ?? detail.closes_at,
    booking_window: campaign?.status === "OPEN" ? (cutoffPassed ? "Closed · cutoff passed" : "Open") : "Not open",
  };
}

export function unavailableCapabilities(detail: WorkshopDetail): string[] {
  const notes: string[] = [];
  if (!detail.campaign) notes.push("Bookings, authorised and collected amounts: the workshop is not published, so none exist.");
  else if (!detail.campaign.settlement) notes.push("Bookings, authorised and collected amounts: the settlement projection is unavailable on this backend; none are assumed.");
  if (!detail.financials.materials.some((line) => line.offer_provenance)) {
    notes.push("Supplier results: no Channel3 offer is selected; materials are merchant-entered assumptions. No live supplier search runs on this page.");
  } else {
    notes.push("Supplier results: only saved, merchant-reviewed Channel3 snapshots are shown, with their retrieval dates. No live supplier search runs on this page.");
  }
  notes.push("Payments: this page never captures, voids, refunds or publishes. PayPal is Sandbox-only and its figures come from the settlement projection.");
  return notes;
}

export function buildIntelligence(detail: WorkshopDetail, preview: ViabilityPreview, now: Date = new Date()): IntelligenceData {
  const { rows, warnings } = materialCostRows(detail, preview);
  if (preview.terms_version !== detail.terms_version) {
    warnings.unshift(`The preview is for terms v${preview.terms_version} but the saved workshop is v${detail.terms_version}. Reload before relying on it.`);
  }
  return {
    health: campaignHealth(detail, preview, now),
    attendance: attendanceRows(preview.attendance_curve),
    materials: materialRows(detail, preview),
    materialCosts: rows,
    warnings,
    unavailable: unavailableCapabilities(detail),
  };
}

export const intelligencePath = (workshopId: string) => `/host/workshops/${encodeURIComponent(workshopId)}/intelligence`;
