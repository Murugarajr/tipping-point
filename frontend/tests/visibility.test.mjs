import assert from "node:assert/strict";
import test from "node:test";
import { HIDE_FROM_DISCOVERY_EXPLANATION, VISIBILITY_NOT_ACCESS_CONTROL, visibilityLabel } from "../src/host/model.ts";

test("hide confirmation states exactly what hiding does and does not do", () => {
  assert.equal(HIDE_FROM_DISCOVERY_EXPLANATION,
    "Hides this workshop from browsing. Existing links and bookings remain valid. This does not cancel the workshop or its payments.");
  assert.match(VISIBILITY_NOT_ACCESS_CONTROL, /not a privacy or access-control setting/);
});

test("visibility label distinguishes listed from hidden with the London-time timestamp", () => {
  assert.equal(visibilityLabel(null), "Listed in public browsing");
  assert.equal(visibilityLabel(undefined), "Listed in public browsing");
  assert.equal(visibilityLabel("2026-11-07T21:51:10Z"), "Hidden from discovery since 7 Nov 2026, 21:51:10 GMT");
  assert.equal(visibilityLabel("2026-07-01T09:00:00Z"), "Hidden from discovery since 1 Jul 2026, 10:00:00 BST");
});
