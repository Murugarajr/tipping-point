import assert from "node:assert/strict";
import { test } from "node:test";
import { defaultDraft, draftFromDetail, draftDateLabel, firstViableLabel, materialIsSaved, previewMatchesSaved, publicationSetupIssues, savedTermsKey } from "../src/host/model.ts";
import * as api from "../src/api.ts";

const draft = defaultDraft();
const detail = {
  workshop_id: "11111111-1111-4111-8111-111111111111",
  title: "Workshop", description: "", terms_version: 1, terms_snapshot_hash: "a".repeat(64),
  opens_at: new Date(Date.now() + 3600000).toISOString(),
  closes_at: new Date(Date.now() + 86400000).toISOString(),
  financials: { ...draft.financials, ticket_price_minor: 5000, materials: [{
    name: "Clay", source_label: "manual", kind: "consumable",
    shared_units: 0, per_attendee_units: 1, pack_size: 4, pack_price_minor: 1600, offer_provenance: null,
  }] },
};

test("review identity includes workshop, version and existing saved hash", () => {
  const preview = { terms_version: 1, terms_snapshot_hash: "a".repeat(64) };
  assert.ok(previewMatchesSaved(detail, preview));
  assert.ok(!previewMatchesSaved(detail, { ...preview, terms_snapshot_hash: "b".repeat(64) }));
  assert.ok(!previewMatchesSaved(detail, { ...preview, terms_version: 2 }));
  assert.ok(!previewMatchesSaved(detail, null));
  assert.ok(!previewMatchesSaved({ ...detail, terms_snapshot_hash: "" }, preview));
  assert.notEqual(savedTermsKey(detail), savedTermsKey({ ...detail, workshop_id: "another-workshop" }));
});

test("added manual lines remain unsaved until the saved detail contains those exact inputs", () => {
  const line = draftFromDetail(detail).financials.materials[0];
  assert.equal(materialIsSaved(line, null), false);
  assert.equal(materialIsSaved(line, detail), true);
  assert.equal(materialIsSaved({ ...line, pack_price_minor: 1700 }, detail), false);
  assert.equal(materialIsSaved({ ...line, name: "Box" }, detail), false);
});

test("incomplete saved inputs have specific actionable setup issues", () => {
  assert.match(publicationSetupIssues(null).join(" "), /Save the draft/);
  assert.match(publicationSetupIssues({ ...detail, opens_at: null }).join(" "), /booking dates in Basics/);
  assert.match(publicationSetupIssues({ ...detail, financials: { ...detail.financials, fee_estimate: null } }).join(" "), /fee assumptions in Economics/);
  assert.deepEqual(publicationSetupIssues(detail), []);
});

test("entered booking dates and completed non-viable previews are labelled honestly", () => {
  assert.equal(draftDateLabel(""), "Not set");
  assert.notEqual(draftDateLabel(draft.schedule.opens_at), "Not set");
  assert.equal(firstViableLabel(null), "Not calculated");
  assert.equal(firstViableLabel({ first_viable_attendance: null }), "None");
});

test("validation errors identify the field without exposing raw request input", async (t) => {
  const original = globalThis.fetch;
  t.after(() => { globalThis.fetch = original; });
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: [{
    loc: ["body", "schedule", "closes_at"], msg: "Invalid booking cutoff", input: "do-not-echo-raw-input",
  }] }), { status: 422 });
  await assert.rejects(api.createWorkshop(draft), (error) => {
    assert.match(error.message, /schedule.closes_at: Invalid booking cutoff/);
    assert.doesNotMatch(error.message, /do-not-echo/);
    return true;
  });
});

test("summary-only and malformed detail responses never reach materials.map", async (t) => {
  const original = globalThis.fetch;
  t.after(() => { globalThis.fetch = original; });
  for (const response of [
    { workshop_id: detail.workshop_id, title: "Saved summary" },
    { ...detail, financials: undefined },
    { ...detail, financials: { materials: null } },
  ]) {
    globalThis.fetch = async () => new Response(JSON.stringify(response), { status: 200 });
    await assert.rejects(api.getWorkshop(detail.workshop_id), (error) => {
      assert.ok(error instanceof api.ApiContractError);
      assert.match(error.message, /Restart the local API/);
      assert.doesNotMatch(error.message, /Cannot read properties/);
      return true;
    });
  }
  assert.throws(() => api.requireWorkshopDetail({ ...detail, financials: { materials: [null] } }), api.ApiContractError);
});

test("valid detail preserves actual saved materials instead of replacing them with defaults", () => {
  const validated = api.requireWorkshopDetail(detail);
  assert.equal(validated, detail);
  assert.equal(draftFromDetail(validated).financials.materials[0].name, "Clay");
  assert.equal(draftFromDetail(validated).financials.materials[0].pack_price_minor, 1600);
});
