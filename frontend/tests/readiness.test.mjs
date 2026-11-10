import assert from "node:assert/strict";
import test from "node:test";
import { NO_SAVED_DATE, READINESS_TIME_ZONE, VISIBLE_DATE_EDGE_OFFSET, buildReadiness, ganttProject, ganttTasks, readinessPath, shortDateText, timelineWindow } from "../src/host/readiness/readinessModel.ts";
import { readinessRoute, safeHostReturn } from "../src/host/model.ts";

const ID = "22222222-2222-4222-8222-222222222222";
const OPENS = "2026-11-15T10:00:00Z", CUTOFF = "2026-11-17T09:00:00Z";
const settlement = (extra = {}) => ({
  state: "OPEN", decision_result: null, decision_reason: null, frozen_attendance: null, admitted_attendance: 1, authorized_minor: 100,
  collected_minor: 0, refunded_minor: 0, capture_pending: 0, release_pending: 0, refund_pending: 0, review_required: false,
  settlement_deadline: null, decided_at: null, fee_basis: "estimated", actual_fees_minor: null, estimated_fees_minor: null,
  estimated_surplus_minor: null, post_collection_surplus_minor: null, ...extra,
});
const campaign = (extra = {}, settle = settlement()) => ({ campaign_id: "c", workshop_id: ID, status: "OPEN", capacity: 4, cutoff_at: CUTOFF,
  terms_version: 1, terms_id: "t", terms_snapshot_hash: "a".repeat(64), published_at: "2026-11-14T08:00:00Z", settlement: settle, ...extra });
const detail = (camp = null, extra = {}) => ({ workshop_id: ID, title: "Pottery <b>evening</b>", description: null, capacity: 4,
  ticket_price_minor: 100, currency: "GBP", terms_version: 1, is_frozen: Boolean(camp), opens_at: OPENS, closes_at: CUTOFF,
  campaign_id: camp ? "c" : null, hidden_from_discovery_at: null, terms_snapshot_hash: "a".repeat(64),
  financials: { materials: [] }, offer_stale_after_seconds: 3600, campaign: camp, ...extra });
const row = (r, id) => r.rows.find((x) => x.id === id);
const BEFORE = new Date("2026-11-15T09:00:00Z"), DURING = new Date("2026-11-16T09:00:00Z"), AFTER = new Date("2026-11-18T09:00:00Z");

test("draft: saved draft dates only; publication, decision and settlement are unavailable", () => {
  const r = buildReadiness(detail(null), BEFORE);
  assert.equal(r.workshop.status, "Draft");
  assert.deepEqual([row(r, "booking-window").status, row(r, "booking-window").kind], ["Draft dates", "saved"]);
  for (const id of ["publication", "decision", "settlement"]) {
    assert.equal(row(r, id).kind, "unavailable", id);
    assert.equal(row(r, id).start, null, id);
  }
});

test("published and open: booking window open, cutoff scheduled, publication time saved", () => {
  const r = buildReadiness(detail(campaign()), DURING);
  assert.deepEqual([row(r, "booking-window").tone, row(r, "booking-window").status], ["open", "Open"]);
  assert.deepEqual([row(r, "booking-cutoff").tone, row(r, "booking-cutoff").start], ["scheduled", CUTOFF]);
  assert.deepEqual([row(r, "publication").tone, row(r, "publication").start], ["settled", "2026-11-14T08:00:00Z"]);
  assert.equal(r.workshop.status, "Open", "OPEN is never shown as confirmed");
  assert.deepEqual([r.workshop.start, r.workshop.end], [new Date("2026-11-14T08:00:00Z").toISOString(), new Date(CUTOFF).toISOString()], "parent spans saved dates");
});

test("expired campaign still OPEN without a decision is represented honestly", () => {
  const r = buildReadiness(detail(campaign()), AFTER);
  assert.deepEqual([row(r, "booking-window").tone, row(r, "booking-window").status], ["pending", "Closed"]);
  assert.equal(row(r, "booking-cutoff").tone, "pending");
  assert.match(row(r, "booking-cutoff").detail, /still OPEN; no deadline decision/);
  assert.deepEqual([row(r, "decision").status, row(r, "decision").start, row(r, "decision").detail], ["Awaiting decision", null, "No deadline decision recorded yet."]);
  assert.deepEqual([row(r, "settlement").status, row(r, "settlement").tone], ["Not started", "pending"]);
});

test("decided release and cancellation use saved decision time and settlement deadline", () => {
  const settle = settlement({ state: "CANCELLED", decision_result: "RELEASE", decision_reason: "ACTUAL_ATTENDANCE_NOT_VIABLE", frozen_attendance: 1,
    settlement_deadline: "2026-11-17T09:30:00Z", decided_at: "2026-11-17T09:01:00Z" });
  const r = buildReadiness(detail(campaign({ status: "CANCELLED" }, settle)), AFTER);
  const d = row(r, "decision");
  assert.deepEqual([d.status, d.tone, d.start], ["Decided · release", "settled", "2026-11-17T09:01:00Z"]);
  assert.match(d.detail, /actual attendance not viable · frozen attendance 1/);
  const s = row(r, "settlement");
  assert.deepEqual([s.status, s.tone, s.start], ["Released / refunded", "settled", "2026-11-17T09:30:00Z"]);
  assert.equal(r.workshop.status, "Cancelled");
});

test("pending settlement and review are pending, with backend pending counts", () => {
  const settle = settlement({ state: "RELEASING", decision_result: "RELEASE", release_pending: 1, review_required: true,
    settlement_deadline: "2026-11-17T09:30:00Z", decided_at: "2026-11-17T09:01:00Z" });
  const r = buildReadiness(detail(campaign({ status: "RELEASING" }, settle)), AFTER);
  const s = row(r, "settlement");
  assert.deepEqual([s.status, s.tone], ["Review required", "pending"]);
  assert.equal(s.detail, "Capture pending 0 · release pending 1 · refund pending 0 · review required");
  assert.deepEqual([r.workshop.status, r.workshop.tone], ["RELEASING", "pending"]);
  const progress = buildReadiness(detail(campaign({ status: "SETTLING" }, settlement({ state: "SETTLING", decision_result: "COLLECT", capture_pending: 1 }))), AFTER);
  assert.deepEqual([row(progress, "settlement").status, row(progress, "settlement").tone], ["In progress", "pending"]);
});

test("confirmed comes only from the persisted campaign status", () => {
  const settle = settlement({ state: "CONFIRMED", decision_result: "COLLECT", decided_at: "2026-11-17T09:01:00Z", settlement_deadline: "2026-11-17T09:30:00Z", collected_minor: 100 });
  const confirmed = buildReadiness(detail(campaign({ status: "CONFIRMED" }, settle)), AFTER);
  assert.deepEqual([confirmed.workshop.status, row(confirmed, "settlement").status], ["Confirmed", "Collected"]);
  const collectNotConfirmed = buildReadiness(detail(campaign({ status: "SETTLING" }, settlement({ decision_result: "COLLECT" }))), AFTER);
  assert.notEqual(collectNotConfirmed.workshop.status, "Confirmed", "a COLLECT decision is not confirmation");
});

test("proposed operational rows have no invented dates", () => {
  const r = buildReadiness(detail(campaign()), DURING);
  for (const id of ["materials", "preparation", "delivery"]) {
    const p = row(r, id);
    assert.deepEqual([p.kind, p.tone, p.status, p.start, p.end], ["proposed", "unavailable", "Proposed", null, null], id);
  }
  assert.match(row(r, "delivery").detail, /not stored by the backend/);
});

test("Gantt tasks: read-only, manually scheduled, no dependencies, unscheduled when undated", () => {
  const settle = settlement({ decision_result: "RELEASE", decided_at: "2026-11-17T09:01:00Z", settlement_deadline: "2026-11-17T09:30:00Z" });
  const [parent] = ganttTasks(buildReadiness(detail(campaign({ status: "CANCELLED" }, settle)), AFTER));
  assert.equal(parent.children.length, 8);
  const all = [parent, ...parent.children];
  assert.ok(all.every((t) => t.readOnly === true && t.manuallyScheduled === true));
  assert.ok(all.every((t) => !("dependencies" in t) && !("predecessors" in t) && !("successors" in t)));
  const byId = Object.fromEntries(parent.children.map((t) => [t.id, t]));
  assert.deepEqual([byId["booking-window"].startDate, byId["booking-window"].endDate], [OPENS, CUTOFF]);
  assert.deepEqual([byId["booking-cutoff"].startDate, byId["booking-cutoff"].duration], [CUTOFF, 0]);
  for (const id of ["materials", "preparation", "delivery"]) assert.equal(byId[id].unscheduled, true, id);
  assert.deepEqual([parent.startDate, parent.endDate], ["2026-11-14T08:00:00.000Z", "2026-11-17T09:30:00.000Z"]);
  assert.match(byId["booking-cutoff"].cls, /tp-tone-settled tp-kind-saved/);
});

test("multi-day campaign opens on its earliest saved date, not the start of the padded week", () => {
  // Published 8 Nov, booking 15–17 Nov: a 9-day span uses weekAndDay, whose axis Bryntum rounds back to Sunday 1 Nov.
  const range = { start: "2026-11-08T08:00:00Z", end: "2026-11-17T09:00:00Z" };
  const w = timelineWindow(range);
  assert.equal(w.viewPreset, "weekAndDay");
  assert.ok(w.startDate < new Date(range.start) && w.endDate > new Date(range.end));
  assert.deepEqual(w.visibleDate, { date: new Date(range.start), block: "start", edgeOffset: VISIBLE_DATE_EDGE_OFFSET, animate: false });
  const short = timelineWindow({ start: OPENS, end: "2026-11-16T10:00:00Z" });
  assert.equal(short.visibleDate.date.toISOString(), new Date(OPENS).toISOString(), "short campaigns also open on their first saved date");
  assert.equal(range.start, "2026-11-08T08:00:00Z", "saved instant not modified");
});

test("timeline window pads the saved span and picks hour resolution for short campaigns", () => {
  const short = timelineWindow({ start: OPENS, end: "2026-11-16T10:00:00Z" });
  assert.equal(short.viewPreset, "hourAndDay");
  assert.ok(short.startDate < new Date(OPENS) && short.endDate > new Date("2026-11-16T10:00:00Z"));
  assert.equal(timelineWindow({ start: "2026-11-01T00:00:00Z", end: CUTOFF }).viewPreset, "weekAndDay");
});

test("grid dates are compact Europe/London labels; undated rows have none", () => {
  assert.equal(shortDateText({ start: "2026-11-07T10:00:00Z", end: "2026-11-08T01:57:06Z" }), "7 Nov, 10:00 → 8 Nov, 01:57");
  assert.equal(shortDateText({ start: "2026-07-01T09:30:00Z", end: null }), "1 Jul, 10:30", "BST applied");
  assert.equal(shortDateText({ start: "2026-11-09T12:00:00Z", end: "2026-11-09T12:20:00Z" }), "9 Nov, 12:00 → 12:20", "same London day: time only");
  assert.equal(shortDateText({ start: null, end: null }), null);
  assert.equal(NO_SAVED_DATE, "No saved date");
});

test("near-midnight BST instants show the London calendar date; the GMT case is unchanged", () => {
  // Summer (BST, UTC+1): 23:30Z on 1 July is 00:30 on 2 July in London.
  assert.equal(shortDateText({ start: "2026-07-01T23:30:00Z", end: "2026-07-02T23:15:00Z" }), "2 Jul, 00:30 → 3 Jul, 00:15");
  assert.equal(shortDateText({ start: "2026-07-02T23:20:00Z", end: null }), "3 Jul, 00:20");
  // Winter (GMT): London equals UTC, so the same wall-clock values keep their UTC dates.
  assert.equal(shortDateText({ start: "2026-11-07T23:30:00Z", end: "2026-11-08T23:45:00Z" }), "7 Nov, 23:30 → 8 Nov, 23:45");
});

test("Gantt project presents in Europe/London and keeps the saved UTC instants unchanged", () => {
  assert.equal(READINESS_TIME_ZONE, "Europe/London");
  const OPENS_BST = "2026-07-01T23:30:00Z", CUTOFF_BST = "2026-07-02T23:15:00Z";
  const r = buildReadiness(detail(campaign({ cutoff_at: CUTOFF_BST, published_at: "2026-07-01T22:30:00Z" }), { opens_at: OPENS_BST, closes_at: CUTOFF_BST }),
    new Date("2026-07-02T12:00:00Z"));
  const project = ganttProject(r);
  assert.equal(project.timeZone, "Europe/London", "IANA zone, not a numeric or fixed offset");
  const byId = Object.fromEntries(project.tasks[0].children.map((t) => [t.id, t]));
  assert.deepEqual([byId["booking-window"].startDate, byId["booking-window"].endDate], [OPENS_BST, CUTOFF_BST], "no hours added or removed");
  assert.equal(byId["booking-cutoff"].startDate, CUTOFF_BST);
  assert.equal(byId.publication.startDate, "2026-07-01T22:30:00Z");
  assert.deepEqual(project.tasks, ganttTasks(r), "task data identical to the zone-free projection");
});

test("readiness route is owned-workshop scoped and an allowed post-login return", () => {
  assert.equal(readinessPath(ID), `/host/workshops/${ID}/readiness`);
  assert.equal(readinessRoute.exec(`/host/workshops/${ID}/readiness`)?.[1], ID);
  assert.equal(readinessRoute.test("/host/workshops/new/readiness"), false);
  assert.equal(safeHostReturn(`/host/workshops/${ID}/readiness`), `/host/workshops/${ID}/readiness`);
  assert.equal(safeHostReturn(`/host/workshops/${ID}/readiness?x=1`), "/host");
});
