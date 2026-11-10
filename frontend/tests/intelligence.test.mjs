import assert from "node:assert/strict";
import test from "node:test";
import {
  attendanceRows, buildIntelligence, campaignHealth, intelligencePath, materialCostRows, materialRows, nextViableAttendance, unavailableCapabilities,
} from "../src/host/intelligence/intelligenceModel.ts";
import { intelligenceRoute, safeHostReturn } from "../src/host/model.ts";

const ID = "11111111-1111-4111-8111-111111111111";
const health = (d, p) => campaignHealth(d, p, NOW);
const build = (d, p) => buildIntelligence(d, p, NOW);
const NOW = new Date("2026-11-10T12:00:00Z"); // before the fixture cutoff (2026-11-17T09:00Z)
// Pack-cost step: 3 and 4 viable, 5 NOT viable, 6 viable again.
const viable = { 1: false, 2: false, 3: true, 4: true, 5: false, 6: true };
const point = (attendance) => ({
  attendance, packs_by_material: { Clay: Math.ceil(attendance / 4), Glaze: 1 },
  material_cost_minor: Math.ceil(attendance / 4) * 2000 + 1500, required_budget_minor: 3000 + Math.ceil(attendance / 4) * 2000 + 1500,
  gross_minor: attendance * 2500, estimated_fees_minor: attendance * 100, estimated_net_minor: attendance * 2400,
  estimated_surplus_minor: viable[attendance] ? 700 : -900, is_viable: viable[attendance],
});
const curve = [1, 2, 3, 4, 5, 6].map(point);
const preview = (extra = {}) => ({
  terms_version: 2, terms_snapshot_hash: "a".repeat(64), algorithm_version: "t", currency: "GBP", ticket_price_minor: 2500, capacity: 6,
  minimum_operating_attendance: 1, first_viable_attendance: 3, any_viable_attendance: true, is_viable_at_capacity: true,
  attendance_curve: curve, materials_note: "", ...extra,
});
const materials = [
  { name: "Clay", source_label: "m", kind: "consumable", shared_units: 0, per_attendee_units: 1, pack_size: 4, pack_price_minor: 2000, offer_provenance: null },
  { name: "Glaze", source_label: "c", kind: "consumable", shared_units: 1, per_attendee_units: 0, pack_size: 1, pack_price_minor: 1500,
    offer_provenance: { offer_snapshot_id: "private-id", provider: "channel3", product_title: "G", merchant_domain: "supplier.invalid", price_minor: 1500,
      retrieved_at: "2026-11-05T10:00:00Z", product_url: "https://supplier.invalid/private", suitability_reviewed: true, pack_size_reviewed: true, review_notes: null } },
];
const settlement = (extra = {}) => ({
  state: "OPEN", decision_result: null, decision_reason: null, frozen_attendance: null, admitted_attendance: 5, authorized_minor: 12500, collected_minor: 0,
  refunded_minor: 0, capture_pending: 0, release_pending: 0, refund_pending: 0, review_required: false, settlement_deadline: null, fee_basis: "estimated",
  actual_fees_minor: null, estimated_fees_minor: null, estimated_surplus_minor: null, post_collection_surplus_minor: null, ...extra,
});
const detail = (campaign = null, extra = {}) => ({
  workshop_id: ID, title: "Pottery", description: null, capacity: 6, ticket_price_minor: 2500, currency: "GBP", terms_version: 2, is_frozen: Boolean(campaign),
  opens_at: "2026-11-15T10:00:00Z", closes_at: "2026-11-17T09:00:00Z", campaign_id: campaign ? "c" : null, hidden_from_discovery_at: null,
  terms_snapshot_hash: "a".repeat(64), offer_stale_after_seconds: 3600, financials: { materials }, campaign, ...extra,
});
const campaign = (extra = {}, settle = settlement()) => ({ campaign_id: "c", workshop_id: ID, status: "OPEN", capacity: 6, cutoff_at: "2026-11-17T09:00:00Z",
  terms_version: 2, terms_id: "t", terms_snapshot_hash: "a".repeat(64), settlement: settle, ...extra });

test("attendance rows keep backend viability per point and convert pence to pounds", () => {
  const rows = attendanceRows(curve);
  assert.deepEqual(rows.map((r) => r.viability), ["Not viable", "Not viable", "Viable", "Viable", "Not viable", "Viable"]);
  assert.equal(rows[4].revenue_gbp, 125);
  assert.equal(rows[4].approved_budget_gbp, 3000 / 100 + 55, "approved budget excludes estimated payment fees");
  assert.equal(rows[4].total_costs_gbp, 3000 / 100 + 55 + 5, "total costs include estimated payment fees");
  assert.equal(rows[4].fixed_and_other_costs_gbp, 30, "required budget minus material cost");
  assert.equal(rows[4].estimated_surplus_gbp, -9);
});

test("next viable attendance never assumes viability above the first viable point", () => {
  assert.equal(nextViableAttendance(curve, 1), 3);
  assert.equal(nextViableAttendance(curve, 4), 4);
  assert.equal(nextViableAttendance(curve, 5), 6, "5 is a non-viable step");
  assert.equal(nextViableAttendance(curve.map((p) => ({ ...p, is_viable: false })), 1), null);
});

test("campaign health: tipping state follows the backend point at current admitted attendance", () => {
  const step = health(detail(campaign()), preview());
  assert.equal(step.tipping_state, "Not viable at current attendance");
  assert.equal(step.admitted_attendance, 5);
  assert.equal(step.next_viable_attendance, 6);
  assert.equal(step.target_attendance, 6);
  assert.equal(step.places_still_required, 1);
  assert.equal(step.viable_at_current_attendance, "Not viable");
  assert.equal(step.estimated_surplus_at_current_gbp, -9);
  assert.equal(step.authorized_gbp, 125);
  assert.equal(step.collected_gbp, 0);

  const reached = health(detail(campaign({}, settlement({ admitted_attendance: 4 }))), preview());
  assert.equal(reached.tipping_state, "Threshold reached · awaiting cutoff");
  assert.equal(reached.places_still_required, 0);

  const below = health(detail(campaign({}, settlement({ admitted_attendance: 1 }))), preview());
  assert.equal(below.tipping_state, "Below threshold");
  assert.equal(below.places_still_required, 2);

  const zero = health(detail(campaign({}, settlement({ admitted_attendance: 0 }))), preview());
  assert.equal(zero.next_viable_attendance, 3, "search starts at the minimum operating attendance");
  assert.equal(zero.viable_at_current_attendance, "Not viable", "0 admitted is outside the curve, not viable");
  assert.equal(zero.estimated_surplus_at_current_gbp, null);
});

test("campaign health: drafts and missing settlement are unavailable, never zero", () => {
  const draft = health(detail(null), preview());
  assert.equal(draft.tipping_state, "Draft · not published");
  assert.equal(draft.publication, "DRAFT");
  for (const key of ["admitted_attendance", "next_viable_attendance", "places_still_required", "authorized_gbp", "collected_gbp", "estimated_surplus_at_current_gbp"]) {
    assert.equal(draft[key], null, key);
  }
  assert.equal(draft.target_attendance, 3, "meter target falls back to the first viable attendance");
  assert.equal(draft.viable_at_current_attendance, "Not available");
  assert.equal(draft.cutoff_at, "2026-11-17T09:00:00Z");

  const noSettlement = health(detail(campaign({}, null)), preview());
  assert.equal(noSettlement.tipping_state, "Booking data unavailable");
  assert.equal(noSettlement.authorized_gbp, null);
  assert.equal(noSettlement.collected_gbp, null);
});

test("campaign health: confirmed, cancelled, review, closed and no-viable states", () => {
  assert.equal(health(detail(campaign({ status: "CONFIRMED" })), preview()).tipping_state, "Confirmed");
  assert.equal(health(detail(campaign({ status: "CANCELLED" })), preview()).tipping_state, "Cancelled");
  assert.equal(health(detail(campaign({}, settlement({ review_required: true }))), preview()).tipping_state, "Review required");
  assert.equal(health(detail(campaign({ status: "DECIDING" })), preview()).tipping_state, "Campaign closed");
  const none = health(detail(campaign()), preview({ any_viable_attendance: false, first_viable_attendance: null, attendance_curve: curve.map((p) => ({ ...p, is_viable: false })) }));
  assert.equal(none.tipping_state, "No viable attendance");
  assert.equal(none.target_attendance, null);
});

test("materials are sanitised: provenance summarised, no snapshot IDs or product URLs", () => {
  const rows = materialRows(detail(null), preview());
  assert.equal(rows[0].source, "Merchant-entered assumption");
  assert.equal(rows[1].source, "Channel3 offer snapshot (supplier.invalid), retrieved 2026-11-05; merchant-reviewed");
  assert.equal(rows[0].packs_at_capacity, 2);
  assert.equal(rows[0].cost_at_capacity_gbp, 40);
  const serialised = JSON.stringify(build(detail(campaign()), preview()));
  for (const secret of ["private-id", "https://supplier.invalid/private", "offer_snapshot_id", "product_url", "csrf", "merchant_id"]) {
    assert.ok(!serialised.includes(secret), `${secret} not exposed to Studio`);
  }
});

test("material costs come from backend pack counts; mismatches are warned, not corrected", () => {
  const ok = materialCostRows(detail(null), preview());
  assert.deepEqual(ok.warnings, []);
  assert.deepEqual(ok.rows.filter((r) => r.attendance === 5), [
    { attendance: 5, material: "Clay", packs: 2, cost_gbp: 40 }, { attendance: 5, material: "Glaze", packs: 1, cost_gbp: 15 },
  ]);
  const bad = materialCostRows(detail(null), preview({ attendance_curve: [{ ...point(2), material_cost_minor: 9999, packs_by_material: { Clay: 1, Unknown: 1 } }] }));
  assert.equal(bad.warnings.length, 2);
  assert.match(bad.warnings[0], /"Unknown" is in the backend calculation but not in the saved materials/);
  assert.match(bad.warnings[1], /backend total is authoritative/);
});

test("stale preview terms are flagged; unavailable capabilities are explicit", () => {
  const data = build(detail(null, { terms_version: 3 }), preview());
  assert.match(data.warnings[0], /preview is for terms v2 but the saved workshop is v3/);
  const notes = unavailableCapabilities(detail(null));
  assert.ok(notes.some((n) => /not published, so none exist/.test(n)));
  assert.ok(!notes.some((n) => /Rescue Analyst/.test(n)), "the analyst panel reports its own status");
  assert.ok(notes.some((n) => /never captures, voids, refunds or publishes/.test(n)));
  assert.ok(unavailableCapabilities(detail(campaign({}, null))).some((n) => /settlement projection is unavailable/.test(n)));
});

test("intelligence route is owned-workshop scoped and an allowed post-login return", () => {
  assert.equal(intelligencePath(ID), `/host/workshops/${ID}/intelligence`);
  assert.equal(intelligenceRoute.exec(`/host/workshops/${ID}/intelligence`)?.[1], ID);
  assert.equal(intelligenceRoute.test("/host/workshops/new/intelligence"), false);
  assert.equal(safeHostReturn(`/host/workshops/${ID}/intelligence`), `/host/workshops/${ID}/intelligence`);
  assert.equal(safeHostReturn(`/host/workshops/${ID}/intelligence?x=1`), "/host");
  assert.equal(safeHostReturn(`/host/workshops/${ID}/intelligence/extra`), "/host");
});

test("total costs include estimated fees, so revenue minus total costs equals the backend surplus", () => {
  // Real "Anyone can Paint" shape: £10 ticket, 3.1% fee estimate, attendance 1 budget £13.00, fees £0.31.
  const one = { attendance: 1, packs_by_material: { Box: 1, Brush: 1 }, material_cost_minor: 300, required_budget_minor: 1300, gross_minor: 1000,
    estimated_fees_minor: 31, estimated_net_minor: 969, estimated_surplus_minor: -331, is_viable: false };
  const [row] = attendanceRows([one]);
  assert.equal(row.approved_budget_gbp, 13);
  assert.equal(row.total_costs_gbp, 13.31);
  assert.equal(Math.round((row.revenue_gbp - row.total_costs_gbp) * 100), one.estimated_surplus_minor, "no gap inconsistent with surplus");
});

test("booking window: a passed cutoff closes bookings without changing financial viability", () => {
  const open = health(detail(campaign({}, settlement({ admitted_attendance: 0 }))), preview());
  assert.equal(open.booking_window, "Open");
  const after = new Date("2026-11-17T09:00:00Z");
  const closed = campaignHealth(detail(campaign({}, settlement({ admitted_attendance: 0 }))), preview(), after);
  assert.equal(closed.publication, "OPEN", "stored status is reported as stored");
  assert.equal(closed.booking_window, "Closed · cutoff passed");
  assert.equal(closed.tipping_state, "Cutoff passed · awaiting decision");
  for (const key of ["first_viable_attendance", "viable_at_capacity", "next_viable_attendance", "places_still_required", "viable_at_current_attendance", "estimated_surplus_at_current_gbp"]) {
    assert.deepEqual(closed[key], open[key], `${key} is financial and unaffected by the cutoff`);
  }
  // The earlier of the campaign cutoff and the terms close applies (same rule as the guest booking service).
  const early = campaignHealth(detail(campaign(), { closes_at: "2026-11-09T00:00:00Z" }), preview(), NOW);
  assert.equal(early.booking_window, "Closed · cutoff passed");
  assert.equal(health(detail(null), preview()).booking_window, "Not open");
  assert.equal(health(detail(campaign({ status: "CONFIRMED" })), preview()).booking_window, "Not open");
});
