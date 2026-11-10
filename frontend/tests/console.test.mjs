import assert from "node:assert/strict";
import test from "node:test";
import * as api from "../src/api.ts";
import {
  CONSOLE_FILTERS, DEFAULT_CONSOLE_FILTER, DETAIL_CONCURRENCY, NOT_AVAILABLE, NOT_PUBLISHED, SEATS_NOTE, SETTLEMENT_NOTE, UNAVAILABLE,
  cellNumber, countText, cutoffText, dateFilterComparator, loadConsoleRows, mapSettledWithLimit, nullsLast, priceText,
  settlementText, statusText, toConsoleRow, visibilityText, visibilityTooltip,
} from "../src/host/consoleModel.ts";
import { safeHostReturn } from "../src/host/model.ts";

const DRAFT = "11111111-1111-4111-8111-111111111111";
const OPEN = "22222222-2222-4222-8222-222222222222";
const HIDDEN = "33333333-3333-4333-8333-333333333333";

const workshop = (id, extra = {}) => ({
  workshop_id: id, title: `Workshop ${id.slice(0, 4)}`, description: null, capacity: 8, ticket_price_minor: 4500,
  currency: "GBP", terms_version: 1, is_frozen: false, opens_at: "2026-11-15T10:00:00Z", closes_at: "2026-11-17T09:00:00Z",
  campaign_id: null, hidden_from_discovery_at: null, ...extra,
});
const settlement = (extra = {}) => ({
  state: "OPEN", decision_result: null, decision_reason: null, frozen_attendance: null, admitted_attendance: 3,
  authorized_minor: 0, collected_minor: 0, refunded_minor: 0, capture_pending: 0, release_pending: 0, refund_pending: 0,
  review_required: false, settlement_deadline: null, fee_basis: "estimated", actual_fees_minor: null,
  estimated_fees_minor: null, estimated_surplus_minor: null, post_collection_surplus_minor: null, ...extra,
});
const detail = (w, campaign = {}) => ({
  ...w, terms_snapshot_hash: "a".repeat(64), offer_stale_after_seconds: 3600, financials: { materials: [] },
  campaign: campaign === null ? null : {
    campaign_id: w.campaign_id, workshop_id: w.workshop_id, status: "OPEN", capacity: 10, cutoff_at: "2026-11-17T09:00:00Z",
    terms_version: 1, terms_id: "t", terms_snapshot_hash: "a".repeat(64), settlement: settlement(), ...campaign,
  },
});

test("labels and defaults match the approved wording", () => {
  assert.equal(SEATS_NOTE, "Derived; excludes in-progress reservation holds.");
  assert.equal(SETTLEMENT_NOTE, "Settlement outcome; not the work-queue state.");
  assert.equal(DEFAULT_CONSOLE_FILTER, "all");
  assert.deepEqual(CONSOLE_FILTERS.map((f) => f.value).sort(), ["all", "hidden", "listed"]);
  assert.equal(DETAIL_CONCURRENCY, 4);
});

test("draft rows use list data only and mark campaign fields as not published", () => {
  const row = toConsoleRow(workshop(DRAFT));
  assert.equal(row.detail, "not_needed");
  assert.equal(row.workbenchHref, `/host/workshops/${DRAFT}`);
  assert.equal(statusText(row), "Draft");
  assert.equal(visibilityText(row), "Listed");
  assert.equal(cellNumber(row.capacity), 8);
  assert.match(cutoffText(row), /\(planned\)$/);
  for (const cell of [row.bookings, row.seatsAvailable]) assert.equal(countText(cell), NOT_PUBLISHED);
  assert.equal(settlementText(row), NOT_PUBLISHED);
});

test("published rows map campaign status, cutoff, capacity, admitted bookings and derived seats", () => {
  const w = workshop(OPEN, { is_frozen: true, campaign_id: "c-open", hidden_from_discovery_at: "2026-11-08T11:24:40Z" });
  const row = toConsoleRow(w, detail(w, { settlement: settlement({ admitted_attendance: 3, decision_result: "COLLECT", settlement_deadline: "2026-11-20T09:00:00Z" }) }));
  assert.equal(row.detail, "loaded");
  assert.equal(statusText(row), "OPEN");
  assert.equal(visibilityText(row), "Hidden from discovery");
  assert.equal(cellNumber(row.capacity), 10, "campaign capacity, not draft capacity");
  assert.equal(cellNumber(row.bookings), 3);
  assert.equal(cellNumber(row.seatsAvailable), 7);
  assert.doesNotMatch(cutoffText(row), /planned/);
  assert.equal(settlementText(row), "COLLECT · deadline 20 Nov 2026, 09:00:00 GMT");
});

test("seats are derived without clamping so anomalies stay visible", () => {
  const w = workshop(OPEN, { is_frozen: true, campaign_id: "c" });
  const row = toConsoleRow(w, detail(w, { capacity: 2, settlement: settlement({ admitted_attendance: 3 }) }));
  assert.equal(cellNumber(row.seatsAvailable), -1);
});

test("null settlement shows Not available and never infers settlement work", () => {
  const w = workshop(OPEN, { is_frozen: true, campaign_id: "c" });
  const row = toConsoleRow(w, detail(w, { settlement: null }));
  assert.equal(statusText(row), "OPEN");
  assert.equal(settlementText(row), NOT_AVAILABLE);
  assert.equal(countText(row.bookings), NOT_AVAILABLE);
  assert.equal(countText(row.seatsAvailable), NOT_AVAILABLE);
  const pending = toConsoleRow(w, detail(w));
  assert.equal(settlementText(pending), "No decision yet · no deadline set");
  assert.doesNotMatch(settlementText(pending), /READY|LEASED|DONE/);
});

test("failed detail marks every detail field Unavailable without guessing", () => {
  const w = workshop(OPEN, { is_frozen: true, campaign_id: "c" });
  const row = toConsoleRow(w, null);
  assert.equal(row.detail, "failed");
  assert.equal(statusText(row), UNAVAILABLE);
  assert.equal(cutoffText(row), UNAVAILABLE);
  for (const cell of [row.capacity, row.bookings, row.seatsAvailable]) { assert.equal(countText(cell), UNAVAILABLE); assert.equal(cellNumber(cell), null); }
  assert.equal(settlementText(row), UNAVAILABLE);
  assert.equal(row.title, w.title, "list fields remain real data");
  assert.equal(priceText(row), "£45.00");
});

test("visibility tooltip shows the London hide time only for hidden rows, including failed-detail rows", () => {
  const hidden = toConsoleRow(workshop(DRAFT, { hidden_from_discovery_at: "2026-11-08T11:24:40.329Z" }));
  assert.equal(visibilityTooltip(hidden), "Hidden since 8 Nov 2026, 11:24:40 GMT");
  assert.equal(visibilityTooltip(toConsoleRow(workshop(DRAFT))), undefined, "listed: no tooltip");
  assert.equal(visibilityTooltip(undefined), undefined, "no row data: no tooltip");
  const failed = toConsoleRow(workshop(OPEN, { is_frozen: true, campaign_id: "c", hidden_from_discovery_at: "2026-07-01T09:00:00Z" }), null);
  assert.equal(failed.detail, "failed");
  assert.equal(visibilityTooltip(failed), "Hidden since 1 Jul 2026, 10:00:00 BST", "list-derived tooltip survives a failed detail");
  assert.equal(visibilityTooltip(toConsoleRow(workshop(OPEN, { is_frozen: true, campaign_id: "c" }), null)), undefined);
});

test("money uses integer pence with GBP formatting", () => {
  assert.equal(priceText(toConsoleRow(workshop(DRAFT, { ticket_price_minor: 5205 }))), "£52.05");
  assert.equal(priceText(toConsoleRow(workshop(DRAFT, { ticket_price_minor: 1 }))), "£0.01");
  assert.equal(priceText(toConsoleRow(workshop(DRAFT, { ticket_price_minor: 0 }))), "Price not set");
});

test("null-safe comparator keeps missing values last in both directions", () => {
  const values = [3, null, 1, undefined, 2];
  const ascending = [...values].sort((a, b) => nullsLast(a, b, null, null, false));
  assert.deepEqual(ascending.slice(0, 3), [1, 2, 3]);
  // AG Grid negates the comparator for descending sorts.
  const descending = [...values].sort((a, b) => -nullsLast(a, b, null, null, true));
  assert.deepEqual(descending.slice(0, 3), [3, 2, 1]);
  assert.ok(descending.slice(3).every((v) => v == null));
  assert.ok(nullsLast(new Date("2026-01-01"), new Date("2026-02-01")) < 0);
  assert.ok(nullsLast(new Date("2026-01-01"), null) < 0);
  assert.ok(nullsLast("apple", "Banana") < 0, "text is case-insensitive");
  assert.equal(nullsLast(null, undefined), 0);
});

test("date filter compares calendar days and excludes missing dates", () => {
  const day = new Date(2026, 10, 17);
  assert.equal(dateFilterComparator(day, new Date(2026, 10, 17, 15, 30)), 0);
  assert.equal(dateFilterComparator(day, new Date(2026, 10, 16, 23, 59)), -1);
  assert.equal(dateFilterComparator(day, new Date(2026, 10, 18, 0, 1)), 1);
  assert.equal(dateFilterComparator(day, null), -1);
});

test("detail requests never exceed the concurrency limit and keep order", async () => {
  let inFlight = 0, peak = 0;
  const items = Array.from({ length: 11 }, (_, i) => i);
  const results = await mapSettledWithLimit(items, 4, async (i) => {
    inFlight++; peak = Math.max(peak, inFlight);
    await new Promise((done) => setTimeout(done, 5 + (i % 3) * 3));
    inFlight--;
    if (i === 5) throw new Error("boom");
    return i * 2;
  });
  assert.equal(peak, 4);
  assert.equal(results[5].status, "rejected");
  assert.deepEqual(results.filter((r) => r.status === "fulfilled").map((r) => r.value), items.filter((i) => i !== 5).map((i) => i * 2));
  assert.deepEqual(await mapSettledWithLimit([], 4, async () => 1), []);
});

function mockFetch(t, handler) {
  const original = globalThis.fetch;
  t.after(() => { globalThis.fetch = original; });
  const calls = [];
  globalThis.fetch = async (path, init = {}) => {
    calls.push({ path: String(path), method: init.method, body: init.body });
    const [code, body] = handler(String(path));
    return new Response(JSON.stringify(body), { status: code });
  };
  return calls;
}

test("real loader issues GET requests only, with the selected visibility, and fetches detail only for published rows", async (t) => {
  const open = workshop(OPEN, { is_frozen: true, campaign_id: "c-open" });
  const hidden = workshop(HIDDEN, { is_frozen: true, campaign_id: "c-hidden", hidden_from_discovery_at: "2026-11-08T11:24:40Z" });
  const calls = mockFetch(t, (path) => {
    if (path.startsWith("/api/merchant/workshops?")) return [200, [workshop(DRAFT), open, hidden]];
    if (path === `/api/merchant/workshops/${OPEN}`) return [200, detail(open)];
    if (path === `/api/merchant/workshops/${HIDDEN}`) return [200, detail(hidden, { settlement: null })];
    return [500, { detail: "unexpected" }];
  });
  const result = await loadConsoleRows("all");
  assert.equal(result.failedDetails, 0);
  assert.deepEqual(result.rows.map((r) => r.workshopId), [DRAFT, OPEN, HIDDEN]);
  assert.deepEqual(calls.map((c) => c.path), ["/api/merchant/workshops?visibility=all", `/api/merchant/workshops/${OPEN}`, `/api/merchant/workshops/${HIDDEN}`]);
  for (const call of calls) {
    assert.equal(call.method, undefined, "fetch defaults to GET");
    assert.equal(call.body, undefined);
    assert.doesNotMatch(call.path, /hide-from-discovery|restore-visibility|publish|preview|materials/);
  }
});

test("a detail failure marks only that row and is counted as partial", async (t) => {
  const open = workshop(OPEN, { is_frozen: true, campaign_id: "c-open" });
  const broken = workshop(HIDDEN, { is_frozen: true, campaign_id: "c-broken" });
  mockFetch(t, (path) => {
    if (path.startsWith("/api/merchant/workshops?")) return [200, [open, broken]];
    if (path === `/api/merchant/workshops/${OPEN}`) return [200, detail(open)];
    return [503, { detail: "temporarily unavailable" }];
  });
  const result = await loadConsoleRows("listed");
  assert.equal(result.failedDetails, 1);
  assert.equal(result.rows[0].detail, "loaded");
  assert.equal(result.rows[1].detail, "failed");
  assert.equal(statusText(result.rows[1]), UNAVAILABLE);
});

test("a contract-invalid detail body is treated as a failed detail, not mapped", async (t) => {
  const open = workshop(OPEN, { is_frozen: true, campaign_id: "c-open" });
  mockFetch(t, (path) => path.startsWith("/api/merchant/workshops?") ? [200, [open]] : [200, { workshop_id: OPEN }]);
  const result = await loadConsoleRows("all");
  assert.equal(result.failedDetails, 1);
  assert.equal(result.rows[0].detail, "failed");
});

test("401 from the list or any detail request is rethrown as unauthorised", async (t) => {
  mockFetch(t, () => [401, { detail: "authentication required" }]);
  await assert.rejects(loadConsoleRows("all"), (e) => e instanceof api.ApiError && e.status === 401);

  const open = workshop(OPEN, { is_frozen: true, campaign_id: "c-open" });
  const other = workshop(HIDDEN, { is_frozen: true, campaign_id: "c-other" });
  const original = globalThis.fetch;
  globalThis.fetch = async (path) => {
    if (String(path).startsWith("/api/merchant/workshops?")) return new Response(JSON.stringify([open, other]), { status: 200 });
    if (String(path).endsWith(OPEN)) return new Response(JSON.stringify(detail(open)), { status: 200 });
    return new Response(JSON.stringify({ detail: "expired" }), { status: 401 });
  };
  try {
    await assert.rejects(loadConsoleRows("all"), (e) => e instanceof api.ApiError && e.status === 401);
  } finally { globalThis.fetch = original; }
});

test("injected API: list failure propagates and no detail call is made", async () => {
  let detailCalls = 0;
  await assert.rejects(loadConsoleRows("all", {
    listWorkshops: async () => { throw new api.ApiError("down", 503, null); },
    getWorkshop: async () => { detailCalls++; throw new Error("unreachable"); },
  }), (e) => e instanceof api.ApiError && e.status === 503);
  assert.equal(detailCalls, 0);
});

test("/host/console is an allowlisted return destination; hashes and queries are dropped", () => {
  assert.equal(safeHostReturn("/host/console"), "/host/console");
  assert.equal(safeHostReturn("/host/console#basics"), "/host/console");
  assert.equal(safeHostReturn("/host/console?x=1"), "/host");
  assert.equal(safeHostReturn("/host/console/extra"), "/host");
  assert.equal(safeHostReturn("//host/console"), "/host");
});
