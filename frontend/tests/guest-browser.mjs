import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { access, mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";

// Offline fixtures only. Every API/provider URL is intercepted; no backend runs.
const root = fileURLToPath(new URL("../", import.meta.url));
const chromePath = process.env.CHROME_PATH ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
await access(chromePath);
const artifacts = process.env.TP_GUEST_ARTIFACTS ?? resolve(root, "node_modules/.tmp/guest-reservation-evidence");
await mkdir(artifacts, { recursive: true });
const profile = await mkdtemp(resolve(artifacts, "chrome-profile-"));
const base = "http://127.0.0.1:4175";
const server = spawn(process.execPath, [resolve(root, "node_modules/vite/bin/vite.js"), "preview", "--host", "127.0.0.1", "--port", "4175", "--strictPort"], { cwd: root, stdio: ["ignore", "pipe", "pipe"] });
let serverError = "";
server.stderr.on("data", (data) => { serverError += data; });
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
async function until(check, label) {
  for (let i = 0; i < 100; i++) { if (await check()) return; await sleep(100); }
  throw new Error(`Timed out: ${label}`);
}
let chrome, socket;
try {
  await until(async () => {
    if (server.exitCode !== null) throw new Error(`Preview exited: ${serverError}`);
    try { return (await fetch(base)).ok; } catch { return false; }
  }, "preview");
  chrome = spawn(chromePath, ["--headless", "--disable-gpu", "--disable-background-networking", "--disable-component-update", "--disable-sync", "--no-first-run", "--no-default-browser-check", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank"], { stdio: ["ignore", "ignore", "pipe"] });
  const endpoint = await new Promise((done, reject) => {
    let output = "";
    const timeout = setTimeout(() => reject(new Error("Chrome endpoint unavailable")), 15000);
    chrome.stderr.on("data", (data) => {
      output += data;
      const match = output.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if (match) { clearTimeout(timeout); done(match[1]); }
    });
    chrome.on("error", reject);
  });
  socket = new WebSocket(endpoint);
  await new Promise((done, reject) => { socket.addEventListener("open", done, { once: true }); socket.addEventListener("error", reject, { once: true }); });
  let sequence = 0;
  const pending = new Map(), events = new Set();
  socket.addEventListener("message", ({ data }) => {
    const message = JSON.parse(data);
    if (message.id) {
      const promise = pending.get(message.id);
      if (!promise) return;
      pending.delete(message.id); clearTimeout(promise.timeout);
      if (message.error) promise.reject(new Error(message.error.message)); else promise.done(message.result);
    } else for (const listener of events) listener(message);
  });
  function send(method, params = {}, sessionId) {
    const id = ++sequence;
    return new Promise((done, reject) => {
      const timeout = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 30000);
      pending.set(id, { done, reject, timeout });
      socket.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
    });
  }
  const { targetInfos } = await send("Target.getTargets");
  const targetId = targetInfos.find((target) => target.type === "page")?.targetId;
  assert.ok(targetId);
  const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
  const cdp = (method, params) => send(method, params, sessionId);
  await cdp("Page.enable"); await cdp("Runtime.enable"); await cdp("Network.enable");
  const workshopId = "11111111-1111-4111-8111-111111111111";
  const campaignId = "22222222-2222-4222-8222-222222222222";
  const bookingId = "33333333-3333-4333-8333-333333333333";
  const bookingPath = `/bookings/${bookingId}`;
  const apiPath = `/api${bookingPath}`;
  let available = true, reserveError = false, reserveValidation = false, sessionLost = false, ownershipLost = false, approvalRequired = false;
  let booking = {
    booking_id: bookingId, campaign_id: campaignId, workshop_id: workshopId,
    workshop_title: "Guest journey · offline fixture", state: "CHECKOUT_RESERVED", payment_state: "NOT_STARTED",
    amount_minor: 4805, currency: "GBP", reservation_expires_at: "2099-01-01T10:10:00Z",
    seat_held: true, approve_url: null, notice: "Offline browser fixture. No live PayPal operation.",
    can_create_order: true, can_authorize: false, can_cancel: true, updated_at: "2099-01-01T10:00:00Z",
  };
  const initialBooking = { ...booking };
  const calls = [], errors = [], unexpected = [], handoffs = [];
  events.add((event) => {
    if (event.method === "Runtime.exceptionThrown") errors.push(event.params.exceptionDetails.text);
    if (event.method !== "Fetch.requestPaused") return;
    const { requestId, request } = event.params;
    const url = new URL(request.url);
    const fulfill = (code, body, type = "application/json") => cdp("Fetch.fulfillRequest", {
      requestId, responseCode: code, responseHeaders: [{ name: "Content-Type", value: type }],
      body: Buffer.from(type === "application/json" ? JSON.stringify(body) : body).toString("base64"),
    }).catch((error) => errors.push(error.message));
    if (url.origin !== base) {
      if (url.hostname === "www.sandbox.paypal.com") {
        if (event.params.resourceType === "Document") handoffs.push(request.url);
        void fulfill(200, "<!doctype html><h1>Intercepted offline PayPal handoff</h1>", "text/html");
      } else { unexpected.push(request.url); void cdp("Fetch.failRequest", { requestId, errorReason: "BlockedByClient" }); }
      return;
    }
    if (!url.pathname.startsWith("/api/")) { void cdp("Fetch.continueRequest", { requestId }); return; }
    calls.push({ path: url.pathname, method: request.method, headers: request.headers, body: request.postData });
    let code = 503, body = { detail: { code: "UNEXPECTED", message: "Unexpected fixture API" } };
    const path = url.pathname;
    if (path === `/api/workshops/${workshopId}`) {
      code = 200; body = {
        workshop_id: workshopId, campaign_id: campaignId, title: initialBooking.workshop_title,
        description: "Explicit fixture, not a real published campaign.", currency: "GBP", ticket_price_minor: 4805,
        capacity: 4, opens_at: "2099-01-01T00:00:00Z", cutoff_at: "2099-01-01T20:00:00Z",
        publication_status: "OPEN", booking_window_status: "open", reservations_available: available,
        availability_reason: available ? "available" : "full", available_seats: available ? null : 0,
        availability_note: available ? "Sandbox authorization is available." : "All places are currently held.",
      };
    } else if (path === "/api/guest/csrf") { code = 200; body = { csrf_token: "guest-bootstrap-fixture" }; }
    else if (path === "/api/guest/session") {
      code = sessionLost && request.method === "GET" ? 401 : 200;
      body = code === 200 ? { expires_at: "2099-01-01T20:00:00Z", csrf_token: "guest-bound-fixture" }
        : { detail: { code: "GUEST_SESSION_REQUIRED", message: "Guest session expired." } };
    } else if (path === `/api/campaigns/${campaignId}/bookings`) {
      code = reserveValidation ? 422 : reserveError ? 503 : 201;
      body = reserveValidation ? { detail: [{ loc: ["body", "email"], msg: "Fixture contact validation rejected before reservation.", type: "value_error" }] }
        : reserveError ? { detail: { code: "RESERVATIONS_UNAVAILABLE", message: "Fixture reservation temporarily unavailable." } } : booking;
    } else if (path === apiPath) {
      code = ownershipLost ? 404 : 200;
      body = ownershipLost ? { detail: { code: "BOOKING_NOT_FOUND", message: "Booking not found." } } : booking;
    } else if (path === `${apiPath}/paypal/order`) {
      booking = { ...booking, state: "AWAITING_APPROVAL", payment_state: "AWAITING_APPROVAL", can_create_order: false, can_authorize: true, approve_url: "https://www.sandbox.paypal.com/checkoutnow?token=OFFLINE-FIXTURE" };
      code = 200; body = booking;
    } else if (path === `${apiPath}/paypal/authorize`) {
      code = approvalRequired ? 409 : 200;
      if (!approvalRequired) booking = { ...booking, state: "AUTHORIZED", payment_state: "AUTHORIZED", approve_url: null, can_authorize: false };
      body = approvalRequired ? { detail: { code: "BUYER_APPROVAL_REQUIRED", message: "Approve in Sandbox first." } } : booking;
    } else if (path === `${apiPath}/cancel`) {
      booking = { ...booking, state: "RELEASE_PENDING", payment_state: "RELEASE_PENDING", can_cancel: false, can_authorize: false, approve_url: null, seat_held: false };
      code = 200; body = booking;
    } else unexpected.push(path);
    void fulfill(code, body);
  });
  await cdp("Fetch.enable", { patterns: [{ urlPattern: "*" }] });
  async function evaluate(expression) {
    const response = await cdp("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (response.exceptionDetails) throw new Error(response.exceptionDetails.exception?.description ?? response.exceptionDetails.text);
    return response.result.value;
  }
  const text = () => evaluate("document.querySelector('main')?.innerText ?? ''");
  const mutations = () => calls.filter(({ method }) => method !== "GET");
  async function visit(path) {
    await cdp("Page.navigate", { url: base + path });
    await until(() => evaluate("document.readyState === 'complete' && !!document.querySelector('main h1')"), path);
    await sleep(250);
  }
  async function clickText(value) {
    assert.ok(await evaluate(`(() => { const item = [...document.querySelectorAll('main button, main a')].find(item => item.textContent === ${JSON.stringify(value)}); if (!item) return false; item.click(); return true; })()`), `Missing ${value}`);
    await sleep(250);
  }
  async function shot(name) {
    const result = await cdp("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    await writeFile(resolve(artifacts, name), Buffer.from(result.data, "base64"));
  }
  async function viewport(width, height = 900) {
    await cdp("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
  }
  let checks = 0;
  const passed = (message) => { checks++; console.log(`PASS ${message}`); };

  await viewport(1440);
  await visit(`/workshops/${workshopId}`);
  assert.ok(await evaluate("!!document.querySelector('a[href^=\"/continue?workshop=\"]')"));
  assert.equal(mutations().length, 0);
  passed("eligible published OPEN campaign uses server availability and supports unknown seat count");
  await visit(`/continue?workshop=${workshopId}`);
  assert.deepEqual(calls.filter(({ path }) => path.startsWith("/api/guest/")), []);
  await shot("guest-continue-1440.png");
  await clickText("Continue — reserve one temporary seat");
  assert.match(await text(), /Enter a valid email/);
  assert.equal(mutations().length, 0);
  await evaluate("document.querySelector('#guest-email').focus()");
  await cdp("Input.insertText", { text: "guest-fixture@example.com" });
  reserveValidation = true;
  await clickText("Continue — reserve one temporary seat");
  assert.match(await text(), /Fixture contact validation rejected before reservation/);
  assert.equal(await evaluate("document.querySelector('#guest-email').value"), "guest-fixture@example.com");
  assert.equal(await evaluate("document.querySelector('#guest-email').readOnly"), false);
  const rejectedPayload = JSON.parse(calls.filter(({ path }) => path.endsWith("/bookings")).at(-1).body);
  await evaluate(`(() => {
    const input = document.querySelector('#guest-email');
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, 'corrected-guest@example.com');
    input.dispatchEvent(new Event('input', { bubbles: true }));
  })()`);
  reserveValidation = false;
  reserveError = true;
  await clickText("Continue — reserve one temporary seat");
  assert.match(await text(), /Fixture reservation temporarily unavailable/);
  assert.equal(await evaluate("document.querySelector('#guest-email').value"), "corrected-guest@example.com");
  assert.equal(await evaluate("document.querySelector('#guest-email').readOnly"), true);
  const firstReserve = calls.filter(({ path }) => path.endsWith("/bookings")).at(-1);
  const firstPayload = JSON.parse(firstReserve.body);
  assert.notEqual(firstPayload.idempotency_key, rejectedPayload.idempotency_key);
  assert.equal(firstPayload.email, "corrected-guest@example.com");
  assert.deepEqual(Object.keys(firstPayload).sort(), ["email", "idempotency_key"]);
  assert.match(firstPayload.idempotency_key, /^[0-9a-f-]{36}$/);
  await shot("guest-reserve-error-1440.png");
  reserveError = false;
  await evaluate("[...document.querySelectorAll('main button')].find(item => item.textContent === 'Retry same reservation').click(); [...document.querySelectorAll('main button')].find(item => item.textContent === 'Retry same reservation')?.click()");
  await until(() => evaluate(`location.pathname === '${bookingPath}' && document.querySelector('h1')?.innerText === 'Seat held temporarily'`), "reserved status");
  const reservations = calls.filter(({ path }) => path.endsWith("/bookings"));
  assert.equal(reservations.length, 3);
  assert.equal(reservations[2].body, firstReserve.body);
  assert.equal(new Headers(firstReserve.headers).get("X-CSRF-Token"), "guest-bound-fixture");
  assert.equal(new Headers(calls.find(({ path, method }) => path === "/api/guest/session" && method === "POST").headers).get("X-CSRF-Token"), "guest-bootstrap-fixture");
  assert.equal(calls.filter(({ path }) => path.endsWith("/paypal/order")).length, 0);
  assert.equal(await evaluate("localStorage.length + sessionStorage.length"), 0);
  assert.equal(await evaluate("location.href.includes('guest-fixture')"), false);
  passed("framework422 permits contact correction/new key; uncertain retry preserves error/email/UUID and suppresses duplicates with guest-only CSRF and no storage");
  await clickText("Create PayPal Sandbox order");
  assert.match(await text(), /Awaiting buyer approval/);
  await shot("guest-awaiting-approval-1440.png");
  await clickText("Continue to PayPal Sandbox");
  await until(() => evaluate("location.hostname === 'www.sandbox.paypal.com'"), "intercepted provider");
  assert.equal(handoffs.length, 1);
  assert.equal(await evaluate("document.querySelector('h1').innerText"), "Intercepted offline PayPal handoff");
  const beforeReturn = mutations().length;
  await visit(`${bookingPath}/paypal/return?token=UNTRUSTED&PayerID=NOT-PROOF`);
  assert.equal(mutations().length, beforeReturn);
  assert.match(await text(), /not proof of approval/);
  assert.match(await text(), /Awaiting buyer approval/);
  approvalRequired = true;
  await clickText("Check approval and authorize");
  assert.match(await text(), /Approve in Sandbox first/);
  assert.match(await text(), /Awaiting buyer approval/);
  approvalRequired = false;
  await clickText("Check approval and authorize");
  assert.match(await text(), /Authorized reservation/);
  assert.match(await text(), /not collected.*does not confirm/s);
  await shot("guest-authorized-1440.png");
  passed("actual approval URL is intercepted; redirect is GET-only, approval error persists, explicit authorize displays not-collected result");
  const beforeCancel = mutations().length;
  await visit(`${bookingPath}/paypal/cancel?token=UNTRUSTED`);
  assert.equal(mutations().length, beforeCancel);
  assert.match(await text(), /No cancellation or financial cleanup/);
  await clickText("Request cancellation");
  assert.match(await text(), /Authorization release pending/);
  assert.match(await text(), /not yet confirmed voided/);
  await shot("guest-release-pending-1440.png");
  passed("cancel return never mutates; explicit cancellation stays release-pending, not provider cleanup complete");
  for (const [state, label] of [
    ["AUTHORIZATION_PENDING", "Checking payment"], ["REVIEW_REQUIRED", "Payment status requires review"],
    ["EXPIRED", "Temporary seat expired"], ["VOIDED", "Authorization voided"], ["AUTHORIZATION_FAILED", "Authorization failed"],
    ["CAPTURE_PENDING", "Collection pending"], ["PAID", "Payment collected · campaign processing"],
    ["REFUND_PENDING", "Refund processing"], ["REFUNDED", "Payment refunded"],
  ]) {
    booking = { ...booking, state, can_create_order: false, can_authorize: false, can_cancel: false };
    const before = mutations().length;
    await visit(bookingPath);
    assert.equal(await evaluate("document.querySelector('h1').innerText"), label);
    assert.equal(mutations().length, before);
  }
  passed("pending, unknown/review, expired, voided and failed status mounts only read persisted state");
  booking = { ...initialBooking, state: "PAID", payment_state: "PAID", campaign_status: "CONFIRMED",
    workshop_confirmed: true, captured_minor: 4805, refunded_minor: 0, can_create_order: false, can_authorize: false, can_cancel: false };
  const beforeConfirmed = mutations().length;
  await visit(bookingPath);
  assert.equal(await evaluate("document.querySelector('h1').innerText"), "Workshop confirmed");
  assert.equal(mutations().length, beforeConfirmed);
  booking = { ...booking, campaign_status: "SETTLING", workshop_confirmed: false };
  await visit(bookingPath);
  assert.notEqual(await evaluate("document.querySelector('h1').innerText"), "Workshop confirmed");
  assert.match(await text(), /Campaign processing/);
  booking = { ...booking, state: "REFUND_PENDING", payment_state: "REFUND_PENDING", campaign_status: "COMPENSATING", captured_minor: 4805 };
  await visit(bookingPath);
  assert.match(await text(), /Refund processing/);
  assert.doesNotMatch(await text(), /Your test payment is authorized, not collected/);
  passed("collection is distinct from campaign confirmation and pending refunds never imply completion");
  booking = { ...initialBooking, state: "AWAITING_APPROVAL", approve_url: "https://www.sandbox.paypal.com.evil.invalid/x", can_create_order: false };
  await visit(bookingPath);
  assert.match(await text(), /approval link could not be validated/);
  assert.equal(await evaluate("!!document.querySelector('a[href*=\"evil.invalid\"]')"), false);
  passed("invalid provider URL is never offered");
  sessionLost = true;
  await visit(bookingPath);
  assert.match(await text(), /Reservation access unavailable/);
  assert.match(await text(), /cannot restore private bookings by email/);
  assert.equal(await evaluate("!!document.querySelector('main input')"), false);
  await shot("guest-lost-session-1440.png");
  sessionLost = false; ownershipLost = true;
  await visit(bookingPath);
  assert.match(await text(), /Reservation access unavailable/);
  assert.doesNotMatch(await text(), /Guest journey · offline fixture/);
  passed("lost/expired session and ownership 404 do not disclose bookings or offer email recovery");
  ownershipLost = false; available = false;
  await visit(`/workshops/${workshopId}`);
  assert.equal(await evaluate("document.querySelector('.public-booking-panel button').disabled"), true);
  assert.match(await text(), /All places are currently held/);
  await visit(`/continue?workshop=${workshopId}`);
  assert.equal(await evaluate("!!document.querySelector('#guest-email')"), false);
  assert.match(await text(), /Reservations unavailable/);
  passed("OPEN status alone cannot enable reservation when server says full");
  available = true; booking = { ...initialBooking };
  for (const width of [375, 390, 720, 1024, 1440]) {
    await viewport(width);
    for (const path of [`/continue?workshop=${workshopId}`, bookingPath]) {
      await visit(path);
      assert.equal(await evaluate("document.querySelectorAll('h1').length"), 1);
      assert.ok(await evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), `${width} ${path} overflow`);
    }
    if (width === 390) await shot("guest-status-390.png");
  }
  assert.deepEqual(errors, []); assert.deepEqual(unexpected, []);
  passed("guest screens reflow 375–1440px with one h1, no uncaught errors and no unexpected/network-provider calls");
  console.log(`${checks} offline guest browser checks passed. Screenshots: ${artifacts}`);
} finally {
  socket?.close(); chrome?.kill("SIGTERM"); server.kill("SIGTERM");
}
