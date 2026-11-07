import assert from "node:assert/strict";
import { test } from "node:test";
import { authorizationExplanation, bookingPresentation, bookingStates, sandboxApproveUrl, isPublishedId } from "../src/guest/model.ts";
import * as api from "../src/api.ts";

test("all guest states distinguish authorization, collection, expiry and release", () => {
  assert.equal(Object.keys(bookingStates).length, 10);
  assert.match(bookingPresentation("AUTHORIZED").join(" "), /not collected.*does not confirm/);
  assert.match(bookingPresentation("RELEASE_PENDING").join(" "), /not yet confirmed voided/);
  assert.match(bookingPresentation("CANCELLED").join(" "), /does not prove provider cleanup/);
  assert.match(bookingPresentation("UNKNOWN").join(" "), /No payment success/);
  assert.match(authorizationExplanation, /not a completed charge/);
});

test("empty guest CSRF restoration falls back only to the readable guest cookie", async (t) => {
  const originalFetch = globalThis.fetch, originalDocument = globalThis.document;
  t.after(() => { globalThis.fetch = originalFetch; globalThis.document = originalDocument; api.clearGuestCsrfToken(); });
  globalThis.document = { cookie: "tipping_csrf=merchant-only; tipping_guest_bootstrap=bootstrap-only; tipping_guest_csrf=guest%2Dbound" };
  const calls = [];
  globalThis.fetch = async (path, init) => {
    calls.push({ path, init });
    return new Response(JSON.stringify(path === "/api/guest/session" ? { csrf_token: "" } : { booking_id: "fixture" }), { status: 200 });
  };
  await api.restoreGuestSession();
  await api.createGuestOrder("fixture");
  assert.equal(calls.length, 2);
  assert.equal(calls[1].init.headers.get("X-CSRF-Token"), "guest-bound");
  assert.equal(calls[1].init.body, "{}");
});

test("missing or malformed guest CSRF never uses merchant/bootstrap cookies or sends a mutation", async (t) => {
  const originalFetch = globalThis.fetch, originalDocument = globalThis.document;
  t.after(() => { globalThis.fetch = originalFetch; globalThis.document = originalDocument; api.clearGuestCsrfToken(); });
  for (const cookie of ["tipping_csrf=merchant-only; tipping_guest_bootstrap=bootstrap-only",
    "tipping_guest_csrf=", "tipping_guest_csrf=%ZZ", "tipping_guest_csrf=%0Ainvalid"]) {
    api.clearGuestCsrfToken();
    globalThis.document = { cookie };
    const calls = [];
    globalThis.fetch = async (path, init) => {
      calls.push({ path, init });
      return new Response(JSON.stringify({ csrf_token: "" }), { status: 200 });
    };
    await assert.rejects(api.authorizeGuestBooking("fixture"), (error) =>
      error instanceof api.ApiContractError && /no mutation was sent/i.test(error.message));
    assert.equal(calls.length, 1);
    assert.equal(calls[0].path, "/api/guest/session");
    assert.equal(calls[0].init.method, undefined);
  }
});

test("only definitive framework body 422 allows a corrected reservation submission", () => {
  assert.equal(api.isGuestReservationValidationError(new api.ApiError("invalid email", 422,
    { detail: [{ loc: ["body", "email"], msg: "invalid email", type: "value_error" }] })), true);
  for (const cause of [
    new TypeError("network unavailable"),
    new api.ApiError("unknown outcome", 503, { detail: { code: "RESERVATIONS_UNAVAILABLE" } }),
    new api.ApiError("conflict", 409, { detail: { code: "IDEMPOTENCY_CONFLICT" } }),
    new api.ApiError("not a framework validation response", 422, { detail: { code: "UNKNOWN" } }),
    new api.ApiError("query validation", 422, { detail: [{ loc: ["query", "id"], msg: "invalid" }] }),
  ]) assert.equal(api.isGuestReservationValidationError(cause), false);
});

test("canonical guest endpoints isolate guest bootstrap and bound CSRF from merchant tokens", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; api.clearGuestCsrfToken(); api.clearCsrfToken(); });
  const calls = [];
  globalThis.fetch = async (path, init) => {
    calls.push({ path, init });
    const body = path === "/api/auth/csrf" ? { csrf_token: "merchant-bootstrap" }
      : path === "/api/merchant/login" ? { csrf_token: "merchant-bound" }
      : path === "/api/guest/csrf" ? { csrf_token: "guest-bootstrap" }
      : path === "/api/guest/session" ? { expires_at: "2099-01-01T00:00:00Z", csrf_token: "guest-bound" }
      : { booking_id: "fixture" };
    return new Response(JSON.stringify(body), { status: path.endsWith("/bookings") ? 201 : 200 });
  };
  await api.login("host", "fixture");
  await api.createGuestSession();
  const guestSession = calls.find(({ path, init }) => path === "/api/guest/session" && init.method === "POST");
  assert.equal(guestSession.init.body, "{}");
  assert.equal(guestSession.init.headers.get("X-CSRF-Token"), "guest-bootstrap");
  const key = "11111111-1111-4111-8111-111111111111";
  await api.reserveGuestSeat("campaign", "fixture@example.com", key);
  await api.createGuestOrder("booking");
  await api.authorizeGuestBooking("booking");
  await api.cancelGuestBooking("booking");
  const mutations = calls.slice(4);
  assert.deepEqual(mutations.map(({ path }) => path), [
    "/api/campaigns/campaign/bookings", "/api/bookings/booking/paypal/order",
    "/api/bookings/booking/paypal/authorize", "/api/bookings/booking/cancel",
  ]);
  assert.deepEqual(JSON.parse(mutations[0].init.body), { email: "fixture@example.com", idempotency_key: key });
  assert.ok(mutations.every(({ init }) => init.method === "POST" && init.headers.get("X-CSRF-Token") === "guest-bound"));
  assert.ok(mutations.slice(1).every(({ init }) => init.body === "{}"));
  assert.ok(calls.every(({ init }) => init.credentials === "same-origin" && init.cache === "no-store"));
  await api.logout();
  assert.equal(calls.at(-1).init.headers.get("X-CSRF-Token"), "merchant-bound");
});

test("guest restore and booking load are GET-only and cookie restoration never creates a session", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; api.clearGuestCsrfToken(); });
  const calls = [];
  globalThis.fetch = async (path, init) => {
    calls.push({ path, init });
    return new Response(JSON.stringify({ csrf_token: "restored" }), { status: 200 });
  };
  await api.restoreGuestSession();
  await api.getGuestBooking("fixture");
  assert.deepEqual(calls.map(({ path }) => path), ["/api/guest/session", "/api/bookings/fixture"]);
  assert.ok(calls.every(({ init }) => !init.method && !init.body && !init.headers.has("X-CSRF-Token")));
});

test("canonical domain errors preserve code/message and mutation errors are not auto-retried", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; api.clearGuestCsrfToken(); });
  let count = 0;
  globalThis.fetch = async (path) => {
    count++;
    return new Response(JSON.stringify(path === "/api/guest/session" ? { csrf_token: "restored" }
      : { detail: { code: "BUYER_APPROVAL_REQUIRED", message: "Approve in Sandbox before checking." } }), { status: path === "/api/guest/session" ? 200 : 409 });
  };
  await api.restoreGuestSession();
  await assert.rejects(api.authorizeGuestBooking("fixture"), (error) =>
    api.guestErrorCode(error) === "BUYER_APPROVAL_REQUIRED" && error.message === "Approve in Sandbox before checking.");
  assert.equal(count, 2);
});

test("approval handoff only accepts an actual exact-host credential-free Sandbox HTTPS URL", () => {
  assert.equal(sandboxApproveUrl("https://www.sandbox.paypal.com/checkoutnow?token=fixture"), "https://www.sandbox.paypal.com/checkoutnow?token=fixture");
  for (const url of [null, "", "/checkout", "http://www.sandbox.paypal.com/x", "https://paypal.com/x",
    "https://www.sandbox.paypal.com.evil.invalid/x", "https://buyer:password@www.sandbox.paypal.com/x",
    "https://www.sandbox.paypal.com:444/x", "javascript:alert(1)"]) assert.equal(sandboxApproveUrl(url), null);
});

test("published IDs cannot be confused with editorial example IDs", () => {
  assert.equal(isPublishedId("11111111-1111-4111-8111-111111111111"), true);
  for (const id of [null, "", "a-little-clay", "../host"]) assert.equal(isPublishedId(id), false);
});
