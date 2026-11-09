import assert from "node:assert/strict";
import { test } from "node:test";
import { poundsToMinor, minorToPounds, safeHostReturn, draftFromDetail, payloadForSave } from "../src/host/model.ts";
import * as api from "../src/api.ts";

test("GBP entry uses decimal-safe integer pence and rejects unsupported formats", () => {
  for (const [raw, expected] of [["0", 0], ["0.29", 29], ["1.01", 101], ["52.05", 5205], ["999.99", 99999]]) assert.equal(poundsToMinor(raw), expected);
  for (const raw of ["", "1.", "-1", "1.001", "1e3", "£12", "NaN", "1,000", "9999999999999999", " 2 "]) assert.equal(poundsToMinor(raw), null);
  assert.equal(minorToPounds(5205), "52.05");
});

test("return destinations are allowlisted internal host routes only", () => {
  const id = "11111111-1111-4111-8111-111111111111";
  for (const valid of ["/host", "/host/console", "/host/workshops/new", `/host/workshops/${id}#materials`]) assert.equal(safeHostReturn(valid), valid);
  for (const invalid of [null, "https://evil.invalid", "//evil.invalid", "/host\\evil", "/host/login", "/host?x=1", "/host/../workshops", "/host/workshops/unknown", "/host/%2f%2fevil", "/continue"]) assert.equal(safeHostReturn(invalid), "/host");
  assert.equal(safeHostReturn(`/host/workshops/${id}#unknown`), `/host/workshops/${id}`);
});

test("saved inputs roundtrip without raw provenance or lost date precision", () => {
  const provenance = { offer_snapshot_id: "private-offer", product_title: "Needles", retrieved_at: "2026-11-06T00:00:00Z", price_minor: 599 };
  const detail = {
    title: "Workshop", description: null, opens_at: "2026-11-07T10:11:12.123Z", closes_at: "2026-11-08T10:11:12.123Z",
    financials: { currency: "GBP", ticket_price_minor: 5205, capacity: 8, minimum_operating_attendance: null,
      fixed_costs_minor: 10000, materials: [{ name: "Needles", source_label: "server reviewed", kind: "consumable",
        shared_units: 0, per_attendee_units: 2, pack_size: 12, pack_price_minor: 599, offer_provenance: provenance }],
      shipping_allowance_minor: 450, shipping_allowance_source: "reviewed", contingency_minor: 500, fee_estimate: null },
  };
  const draft = draftFromDetail(detail);
  const line = draft.financials.materials[0];
  assert.equal(line.selected_offer_snapshot_id, "private-offer");
  assert.ok(!("offer_provenance" in line));
  assert.equal(line.pack_price_minor, 599);
  assert.equal(draft.financials.fee_estimate, null);
  assert.equal(payloadForSave(draft).schedule.opens_at, detail.opens_at);
  assert.equal(payloadForSave(draft).schedule.closes_at, detail.closes_at);
});

test("public listing/detail requests do not use merchant APIs or forge success", async (t) => {
  const original = globalThis.fetch;
  t.after(() => { globalThis.fetch = original; });
  const paths = [];
  globalThis.fetch = async (path, init) => {
    paths.push(path);
    assert.equal(init.method, undefined);
    assert.equal(init.cache, "no-store");
    return new Response(path === "/api/workshops" ? "[]" : '{"detail":"published workshop not found"}', { status: path === "/api/workshops" ? 200 : 404 });
  };
  assert.deepEqual(await api.listPublicWorkshops(), []);
  await assert.rejects(api.getPublicWorkshop("private-reference"), (error) => error instanceof api.ApiError && error.status === 404);
  assert.deepEqual(paths, ["/api/workshops", "/api/workshops/private-reference"]);
});

test("structured provider errors remain explicit and no automatic retry is made", async (t) => {
  const original = globalThis.fetch;
  t.after(() => { globalThis.fetch = original; });
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    return new Response(JSON.stringify({ detail: { state: "unconfigured", message: "Channel3 not configured" } }), { status: 503 });
  };
  await assert.rejects(api.searchMaterials("workshop", "needles"), /Channel3 not configured/);
  assert.equal(calls, 1);
});
