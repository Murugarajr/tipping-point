import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import { access, mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";

// Uses installed Chrome + Node's WebSocket implementation; no package download.
// All API responses are intercepted test fixtures. No backend or provider is called.
const root = fileURLToPath(new URL("../", import.meta.url));
const chromePath = process.env.CHROME_PATH ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
await access(chromePath);
const artifacts = resolve(root, "node_modules/.tmp/frontend-evidence");
await mkdir(artifacts, { recursive: true });
const profile = await mkdtemp(resolve(artifacts, "chrome-profile-"));
const base = "http://127.0.0.1:4175";
const server = spawn(process.execPath, [resolve(root, "node_modules/vite/bin/vite.js"), "preview", "--host", "127.0.0.1", "--port", "4175", "--strictPort"], { cwd: root, stdio: ["ignore", "pipe", "pipe"] });
let serverError = "";
server.stderr.on("data", (data) => { serverError += data; });
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
async function until(check, label) {
  for (let i = 0; i < 100; i++) {
    if (await check()) return;
    await sleep(100);
  }
  throw new Error(`Timed out: ${label}`);
}
let chrome;
let socket;
try {
  await until(async () => {
    if (server.exitCode !== null) throw new Error(`Preview server exited: ${serverError}`);
    try { return (await fetch(base)).ok; } catch { return false; }
  }, "preview startup");
  chrome = spawn(chromePath, ["--headless", "--disable-gpu", "--disable-background-networking", "--disable-component-update", "--disable-sync", "--no-first-run", "--no-default-browser-check", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank"], { stdio: ["ignore", "ignore", "pipe"] });
  const endpoint = await new Promise((done, reject) => {
    let output = "";
    const timeout = setTimeout(() => reject(new Error("Chrome debugging endpoint unavailable")), 15000);
    chrome.stderr.on("data", (data) => {
      output += data;
      const match = output.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if (match) { clearTimeout(timeout); done(match[1]); }
    });
    chrome.on("error", reject);
    chrome.on("exit", (code) => { clearTimeout(timeout); reject(new Error(`Chrome exited ${code}`)); });
  });
  socket = new WebSocket(endpoint);
  await new Promise((done, reject) => { socket.addEventListener("open", done, { once: true }); socket.addEventListener("error", reject, { once: true }); });
  let sequence = 0;
  const pending = new Map();
  const events = new Set();
  socket.addEventListener("message", ({ data }) => {
    const message = JSON.parse(data);
    if (message.id) {
      const promise = pending.get(message.id);
      if (!promise) return;
      pending.delete(message.id);
      clearTimeout(promise.timeout);
      if (message.error) promise.reject(new Error(message.error.message));
      else promise.done(message.result);
    } else {
      for (const listener of events) listener(message);
    }
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
  assert.ok(targetId, "Chrome should expose its initial blank tab");
  const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
  const cdp = (method, params) => send(method, params, sessionId);
  await cdp("Page.enable");
  await cdp("Runtime.enable");
  await cdp("Network.enable");
  let authMode = "anonymous";
  let failLogin = false;
  let expireListing = false;
  let expireNextSave = false;
  let failDetailAfterSave = false;
  let failNextDetail = false;
  let failCreate = false;
  let failPreview = false;
  let stalePreview = false;
  let publicUnavailable = false;
  let providerMode = "unconfigured";
  let workshop = null;
  const syncBinding = () => {
    if (workshop) workshop.terms_snapshot_hash = createHash("sha256")
      .update(JSON.stringify([workshop.financials, workshop.opens_at, workshop.closes_at])).digest("hex");
  };
  const workshopId = "11111111-1111-4111-8111-111111111111";
  const campaignId = "33333333-3333-4333-8333-333333333333";
  const offer = { offer_snapshot_id: "22222222-2222-4222-8222-222222222222", product_title: "Fixture needle pack",
    merchant_domain: "fixture.invalid", price_minor: 599, currency: "GBP", product_url: "https://fixture.invalid/needles",
    retrieved_at: new Date().toISOString(), is_stale: false, freshness_label: "fresh at retrieval",
    limitations_note: "Offline test fixture: no stock or delivered-price guarantee." };
  const curve = [1, 2, 3, 4].map((attendance) => ({
    attendance, packs_by_material: { Needles: attendance > 2 ? 2 : 1 },
    material_cost_minor: attendance > 2 ? 700 : 350, required_budget_minor: attendance > 2 ? 700 : 350,
    gross_minor: attendance * 200, estimated_fees_minor: 0, estimated_net_minor: attendance * 200,
    estimated_surplus_minor: attendance * 200 - (attendance > 2 ? 700 : 350), is_viable: attendance % 2 === 0,
  }));
  const preview = { algorithm_version: "browser-fixture", currency: "GBP", ticket_price_minor: 200, capacity: 4,
    minimum_operating_attendance: 1, first_viable_attendance: 2, any_viable_attendance: true,
    is_viable_at_capacity: true, attendance_curve: curve, materials_note: "Explicit offline browser fixture, not a provider response." };
  const publicItem = () => workshop?.is_frozen ? {
    workshop_id: workshopId, campaign_id: campaignId, title: workshop.title, description: workshop.description,
    currency: "GBP", ticket_price_minor: workshop.ticket_price_minor, capacity: workshop.capacity,
    opens_at: workshop.opens_at, cutoff_at: workshop.closes_at, publication_status: "OPEN",
    booking_window_status: "not_open_yet", reservations_available: false,
    availability_note: "Guest reservations and payments are not enabled in this prototype.",
  } : null;
  const apiCalls = [];
  const errors = [];
  const fixture = { merchant: { merchant_id: "test-host", name: "Fixture host" }, session_id: "test-session", csrf_token: "bound-test-csrf", expires_at: "2099-01-01T00:00:00Z" };
  events.add((event) => {
    if (event.method === "Runtime.exceptionThrown") errors.push(event.params.exceptionDetails.text);
    if (event.method !== "Fetch.requestPaused") return;
    const { requestId, request } = event.params;
    const path = new URL(request.url).pathname;
    apiCalls.push({ path, method: request.method, headers: request.headers, body: request.postData });
    let body = { detail: "unexpected test API request" };
    let code = 503;
    if (path === "/api/me") { code = authMode === "authenticated" ? 200 : authMode === "unavailable" ? 503 : 401; body = code === 200 ? fixture : { detail: "test session unavailable" }; }
    if (path === "/api/auth/csrf") { code = 200; body = { csrf_token: "bootstrap-test-csrf" }; }
    if (path === "/api/merchant/login") { code = failLogin ? 401 : 200; body = failLogin ? { detail: "invalid login credentials" } : fixture; if (!failLogin) authMode = "authenticated"; }
    if (path === "/api/merchant/workshops") {
      code = expireListing ? 401 : 200; body = code === 200 ? workshop ? [workshop] : [] : { detail: "expired" };
      if (request.method === "POST" && !failCreate) {
        const payload = JSON.parse(request.postData);
        workshop = { workshop_id: workshopId, title: payload.title, description: payload.description,
          capacity: payload.financials.capacity, ticket_price_minor: payload.financials.ticket_price_minor,
          currency: "GBP", terms_version: 1, is_frozen: false, campaign_id: null, campaign: null,
          opens_at: payload.schedule.opens_at, closes_at: payload.schedule.closes_at, offer_stale_after_seconds: 3600,
          financials: { ...payload.financials, materials: payload.financials.materials.map((line) => ({ ...line, offer_provenance: null })) } };
        syncBinding(); code = 201; body = workshop;
      }
      if (request.method === "POST" && failCreate) {
        code = 422; body = { detail: [{ loc: ["body", "schedule", "closes_at"], msg: "Fixture cutoff validation failed" }] };
      }
    }
    if (path === `/api/merchant/workshops/${workshopId}`) {
      code = workshop ? 200 : 404; body = workshop ?? { detail: "not found" };
      if (request.method === "PATCH" && workshop) {
        if (expireNextSave) { expireNextSave = false; authMode = "anonymous"; code = 401; body = { detail: "expired" }; }
        else if (workshop.is_frozen) { code = 409; body = { detail: "published terms are immutable" }; }
        else {
          const payload = JSON.parse(request.postData);
          workshop = { ...workshop, title: payload.title, description: payload.description,
            ticket_price_minor: payload.financials.ticket_price_minor, capacity: payload.financials.capacity,
            opens_at: payload.schedule.opens_at, closes_at: payload.schedule.closes_at,
            financials: { ...payload.financials, materials: payload.financials.materials.map((line) => {
              const old = workshop.financials.materials.find((item) => item.name === line.name);
              return { ...line, offer_provenance: line.selected_offer_snapshot_id ? old?.offer_provenance : null };
            }) } };
          syncBinding(); body = workshop;
          if (failDetailAfterSave) { failDetailAfterSave = false; failNextDetail = true; }
        }
      }
      if (request.method === "GET" && failNextDetail) { failNextDetail = false; code = 503; body = { detail: "saved detail temporarily unavailable" }; }
    }
    if (path === `/api/merchant/workshops/${workshopId}/preview`) {
      code = failPreview ? 503 : 200;
      body = failPreview ? { detail: "Fixture preview unavailable" } : {
        ...preview, terms_version: workshop.terms_version,
        terms_snapshot_hash: stalePreview ? "d".repeat(64) : workshop.terms_snapshot_hash,
      };
    }
    if (path === `/api/merchant/workshops/${workshopId}/publish` && workshop) {
      const campaign = { campaign_id: campaignId, workshop_id: workshopId, status: "OPEN", capacity: workshop.capacity,
        cutoff_at: workshop.closes_at, terms_version: 1, terms_id: "44444444-4444-4444-8444-444444444444", terms_snapshot_hash: workshop.terms_snapshot_hash };
      workshop = { ...workshop, is_frozen: true, campaign_id: campaignId, campaign };
      code = 201; body = campaign;
    }
    if (path.endsWith("/materials/search")) {
      code = providerMode === "unconfigured" ? 503 : 200;
      body = code === 503 ? { detail: { state: "unconfigured", message: "Channel3 not configured" } }
        : { offers: providerMode === "empty" ? [] : [{ ...offer, is_stale: providerMode === "stale" }],
          rejected_count: 0, rejected_offers: [], retrieved_at: offer.retrieved_at };
    }
    if (path.endsWith("/materials/select") && workshop) {
      const selected = JSON.parse(request.postData);
      const line = { name: selected.material_name, source_label: "channel3-offer-snapshot+merchant-reviewed-assumptions",
        kind: selected.kind, shared_units: selected.shared_units, per_attendee_units: selected.per_attendee_units,
        pack_size: selected.pack_size, pack_price_minor: offer.price_minor,
        offer_provenance: { ...offer, provider: "channel3", suitability_reviewed: true, pack_size_reviewed: true, review_notes: selected.review_notes } };
      workshop.financials = { ...workshop.financials, materials: [...workshop.financials.materials.filter((item) => item.name !== line.name), line],
        shipping_allowance_minor: selected.shipping_allowance_minor, shipping_allowance_source: selected.shipping_allowance_source };
      syncBinding(); code = 200; body = { viability_preview: { ...preview, terms_version: workshop.terms_version, terms_snapshot_hash: workshop.terms_snapshot_hash } };
    }
    if (path === "/api/workshops") { code = publicUnavailable ? 503 : 200; body = publicUnavailable ? { detail: "unavailable" } : publicItem() ? [publicItem()] : []; }
    if (path.startsWith("/api/workshops/")) { code = path === `/api/workshops/${workshopId}` && publicItem() ? 200 : 404; body = code === 200 ? publicItem() : { detail: "published workshop not found" }; }
    if (path === "/api/merchant/logout") { code = 200; body = { status: "logged out" }; authMode = "anonymous"; }
    apiCalls.at(-1).code = code;  // recorded for failure diagnostics
    void cdp("Fetch.fulfillRequest", { requestId, responseCode: code, responseHeaders: [{ name: "Content-Type", value: "application/json" }], body: Buffer.from(JSON.stringify(body)).toString("base64") }).catch((error) => errors.push(error.message));
  });
  await cdp("Fetch.enable", { patterns: [{ urlPattern: `${base}/api/*` }] });
  async function evaluate(expression) {
    const response = await cdp("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (response.exceptionDetails) throw new Error(response.exceptionDetails.exception?.description ?? response.exceptionDetails.text);
    return response.result.value;
  }
  async function viewport(width, height = 900) {
    await cdp("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
  }
  async function visit(path) {
    console.log(`Checking browser route ${path}`);
    await cdp("Page.navigate", { url: base + path });
    await until(() => evaluate("document.readyState === 'complete' && !!document.querySelector('#root h1')"), path);
    await sleep(150);
  }
  async function click(selector) {
    assert.ok(await evaluate(`!!document.querySelector(${JSON.stringify(selector)})`), `Missing control ${selector}`);
    await evaluate(`document.querySelector(${JSON.stringify(selector)}).focus(); document.querySelector(${JSON.stringify(selector)}).click()`);
    await sleep(100);
  }
  async function fill(selector, text) {
    await evaluate(`document.querySelector(${JSON.stringify(selector)}).focus()`);
    await cdp("Input.insertText", { text });
  }
  async function setField(label, value, scope = ".workbench") {
    await evaluate(`(() => {
      const labels = [...document.querySelector(${JSON.stringify(scope)}).querySelectorAll('label')];
      const found = labels.find(item => item.textContent.trim().startsWith(${JSON.stringify(label)}));
      const input = found?.querySelector('input,textarea,select');
      if (!input) throw new Error('Missing field: ' + ${JSON.stringify(label)});
      if (input.type === 'checkbox') { if (input.checked !== ${JSON.stringify(value)}) input.click(); return; }
      const prototype = input.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : input.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(prototype, 'value').set.call(input, ${JSON.stringify(String(value))});
      input.dispatchEvent(new Event(input.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }));
    })()`);
    await sleep(100);
  }
  async function screenshot(name) {
    await evaluate("Promise.all(document.getAnimations().map(animation => animation.finished.catch(() => {})))");
    const image = await cdp("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    await writeFile(resolve(artifacts, name), Buffer.from(image.data, "base64"));
  }
  async function noOverflow(label) {
    const widths = await evaluate("({ viewport: innerWidth, content: document.documentElement.scrollWidth })");
    assert.ok(widths.content <= widths.viewport + 1, `${label} overflows: ${JSON.stringify(widths)}`);
  }
  let checks = 0;
  const passed = (message) => { checks++; console.log(`PASS ${message}`); };

  await viewport(1440);
  await visit("/");
  assert.equal(await evaluate("document.querySelectorAll('h1').length"), 1);
  assert.equal(await evaluate("!!document.querySelector('input')"), false);
  assert.equal(apiCalls.length, 0);
  await noOverflow("desktop home");
  await screenshot("home-1440.png");
  passed("public homepage has one h1, no login form, no API requests and no overflow");
  for (const [selector, name] of [[".discovery", "discovery-1440.png"], [".host-section", "hosts-1440.png"]]) {
    await evaluate(`document.querySelector(${JSON.stringify(selector)}).scrollIntoView({ behavior: 'instant' })`);
    await screenshot(name);
  }
  await click("#questions details summary");
  assert.equal(await evaluate("document.querySelector('#questions details').open"), true);
  passed("FAQ expands");
  await visit("/workshops");
  assert.equal(await evaluate("document.querySelectorAll('.example-card').length"), 3);
  await click('.filter-row button:nth-child(2)');
  assert.equal(await evaluate("document.querySelectorAll('.example-card').length"), 1);
  assert.equal(await evaluate("document.querySelector('.filter-row button:nth-child(2)').getAttribute('aria-pressed')"), "true");
  await click('.filter-row button:nth-child(5)');
  assert.equal(await evaluate("document.querySelectorAll('.example-card').length"), 0);
  await click(".public-empty button");
  assert.equal(await evaluate("document.querySelectorAll('.example-card').length"), 3);
  passed("category filters, accessible pressed state, empty state and reset");
  await click(".example-card .text-link");
  await until(() => evaluate("!!document.querySelector('.detail-copy')"), "detail navigation");
  assert.match(await evaluate("document.querySelector('.detail-copy').innerText"), /No authorization or collection/);
  await noOverflow("desktop detail");
  await click(".detail-copy > .tp-button");
  await until(() => evaluate("!!document.querySelector('#guest-email')"), "guest navigation");
  const requestsBeforeEmail = apiCalls.length;
  await click(".guest-form-panel form button");
  assert.equal(await evaluate("document.querySelector('#guest-email').getAttribute('aria-invalid')"), "true");
  await fill("#guest-email", "preview@example.com");
  await click(".guest-form-panel form button");
  assert.match(await evaluate("document.querySelector('.guest-result').innerText"), /Your email was not saved or sent/);
  assert.equal(await evaluate("document.activeElement.className"), "guest-result");
  assert.equal(apiCalls.length, requestsBeforeEmail);
  assert.equal(await evaluate("location.href.includes('preview%40') || localStorage.length > 0 || sessionStorage.length > 0"), false);
  await click(".guest-result button");
  assert.equal(await evaluate("document.querySelector('#guest-email').value"), "");
  passed("guest validation, honest preview, result focus, email cleared and no network/storage persistence");
  await visit("/example-plan");
  assert.match(await evaluate("document.querySelector('main').innerText"), /not merchant data/);
  await visit("/workshops/no-such-example");
  assert.match(await evaluate("document.querySelector('h1').innerText"), /Nothing to make/);
  passed("public read-only plan and unknown workshop handling");

  await viewport(390, 844);
  await visit("/");
  await noOverflow("mobile home");
  await screenshot("home-390.png");
  await evaluate("document.querySelector('.hero-bento').scrollIntoView({ behavior: 'instant' })");
  await screenshot("bento-390.png");
  await evaluate("window.scrollTo({ top: 0, behavior: 'instant' })");
  assert.ok(await evaluate("document.querySelector('.header-cta').getBoundingClientRect().width > 300"));
  await click(".menu-toggle");
  assert.equal(await evaluate("document.querySelector('.menu-toggle').getAttribute('aria-expanded')"), "true");
  await cdp("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape" });
  assert.equal(await evaluate("document.querySelector('.menu-toggle').getAttribute('aria-expanded')"), "false");
  assert.equal(await evaluate("document.activeElement.className"), "menu-toggle");
  passed("mobile navigation, persistent main CTA and Escape focus return");
  for (const width of [375, 390, 720, 1024, 1440]) {
    await viewport(width);
    for (const path of ["/", "/workshops", "/workshops/a-little-clay", "/continue", "/example-plan"]) {
      await visit(path);
      await noOverflow(`${width}px ${path}`);
      assert.equal(await evaluate("document.querySelectorAll('h1').length"), 1);
    }
  }
  passed("all public routes have one h1 and no horizontal overflow at 375, 390, 720, 1024 and 1440px");
  await viewport(720, 450);
  await visit("/");
  await noOverflow("200% desktop-equivalent viewport");
  await cdp("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
  assert.equal(await evaluate("getComputedStyle(document.querySelector('.hero-copy')).animationName"), "none");
  passed("200%-equivalent reflow and reduced-motion preference");

  await viewport(390, 844);
  await visit("/host/login");
  await until(() => evaluate("!!document.querySelector('#host-password')"), "host login");
  await noOverflow("mobile login");
  await screenshot("host-login-390.png");
  await click(".password-toggle");
  assert.equal(await evaluate("document.querySelector('#host-password').type"), "text");
  await click(".password-toggle");
  assert.equal(await evaluate("document.querySelector('#host-password').type"), "password");
  failLogin = true;
  await fill("#host-identifier", "fixture-host");
  await fill("#host-password", "fixture-password");
  await click(".login-card form > button");
  await until(() => evaluate("!!document.querySelector('[role=alert]')"), "invalid login");
  assert.match(await evaluate("document.querySelector('[role=alert]').innerText"), /identifier or password is incorrect/);
  assert.equal(await evaluate("document.querySelector('#host-password').value"), "");
  passed("host password visibility, generic credential error and password clearing (mocked API)");
  failLogin = false;
  await fill("#host-password", "fixture-password");
  await click(".login-card form > button");
  await until(() => evaluate("!!document.querySelector('.host-shell:not([hidden]) .merchant-menu')"), "authenticated host");
  assert.equal(await evaluate("location.pathname"), "/host");
  const login = apiCalls.filter((item) => item.path === "/api/merchant/login").at(-1);
  assert.equal(new Headers(login.headers).get("X-CSRF-Token"), "bootstrap-test-csrf");
  assert.deepEqual(JSON.parse(login.body), { login_identifier: "fixture-host", password: "fixture-password" });
  await noOverflow("authenticated mobile host");
  await click(".merchant-menu button");
  await until(() => evaluate("location.pathname === '/'"), "logout to public browsing");
  const logout = apiCalls.find((item) => item.path === "/api/merchant/logout");
  assert.equal(new Headers(logout.headers).get("X-CSRF-Token"), "bound-test-csrf");
  passed("host login bootstrap, bound logout CSRF and workspace access (mocked API)");
  authMode = "authenticated"; expireListing = true;
  await visit("/host");
  await until(() => evaluate("!!document.querySelector('.notice.warning')"), "expired host session");
  assert.match(await evaluate("document.querySelector('.notice.warning').innerText"), /expired/);
  assert.equal(await evaluate("!!document.querySelector('.host-shell:not([hidden]) .merchant-menu')"), false);
  passed("session expiry hides merchant data and returns to sign-in (mocked API)");
  authMode = "authenticated"; expireListing = false;
  await viewport(1440);
  await visit("/host/login?returnTo=https%3A%2F%2Fevil.invalid");
  await until(() => evaluate("location.pathname === '/host' && !!document.querySelector('.host-empty')"), "authenticated login redirect");
  await screenshot("host-list-1440.png");
  await click(".host-page-heading > .host-button");
  await until(() => evaluate("!!document.querySelector('.workbench')"), "new workbench");
  await setField("Workshop title", "A workshop from the workbench");
  await setField("Description", "A real-contract browser test fixture.");
  await setField("Ticket price", "52.05");
  await setField("Capacity", "4");
  failCreate = true;
  await click(".workbench .host-page-heading .host-button");
  await until(() => evaluate("!!document.querySelector('.workbench [role=alert]')"), "failed create");
  assert.equal(await evaluate("location.pathname"), "/host/workshops/new");
  assert.match(await evaluate("document.querySelector('.workbench [role=alert]').innerText"), /Could not create draft: schedule.closes_at/);
  assert.equal(await evaluate("document.querySelector('[data-section=basics] input').value"), "A workshop from the workbench");
  failCreate = false;
  await click(".workbench .host-page-heading .host-button");
  await until(() => evaluate(`location.pathname.endsWith('${workshopId}') && /^(All changes saved|Saved on the server[.])$/.test(document.querySelector('.workbench-status [role=status]')?.innerText ?? '')`), "saved workbench");
  assert.equal(workshop.ticket_price_minor, 5205);
  await noOverflow("desktop workbench");
  await screenshot("workbench-basics-1440.png");
  await click(".workbench > .back-link");
  await until(() => evaluate("!!document.querySelector('.host-workshop-row')"), "owned list");
  await click(".host-workshop-row .row-actions button");
  await until(() => evaluate("!!document.querySelector('[data-section=basics] input')"), "reopened workbench");
  assert.equal(await evaluate("document.querySelector('[data-section=basics] input').value"), "A workshop from the workbench");
  passed("authenticated redirect, validated return, draft creation, decimal-safe save and reopen (mocked API)");
  await click(".workbench-tabs button:nth-child(2)");
  await setField("Material name", "Clay assumption", ".manual-material-form");
  await setField("Assumed pack price", "3.50", ".manual-material-form");
  await setField("Units per pack", "2", ".manual-material-form");
  await click(".manual-material-form button[type=submit]");
  assert.match(await evaluate("document.querySelector('.workbench-status').innerText"), /Unsaved/);
  await click(".workbench .host-page-heading .host-button");
  await until(() => evaluate("/^(All changes saved|Saved on the server[.])$/.test(document.querySelector('.workbench-status [role=status]')?.innerText ?? '')"), "saved material assumption");
  assert.equal(workshop.financials.materials[0].pack_price_minor, 350);
  assert.equal(apiCalls.filter((item) => item.path.endsWith("/materials/search")).length, 0);
  await setField("I have reconciled", true, ".channel3-section");
  await setField("Material search", "needles", ".channel3-section");
  assert.equal(apiCalls.filter((item) => item.path.endsWith("/materials/search")).length, 0);
  await click(".channel3-section form button[type=submit]");
  assert.match(await evaluate("document.querySelector('.materials-workbench [role=alert]').innerText"), /not configured/);
  providerMode = "empty";
  await click(".channel3-section form button[type=submit]");
  assert.match(await evaluate("document.querySelector('.offer-results').innerText"), /No eligible GBP offers/);
  providerMode = "stale";
  await click(".channel3-section form button[type=submit]");
  assert.equal(await evaluate("document.querySelector('.offer-result button').disabled"), true);
  providerMode = "offers";
  await click(".channel3-section form button[type=submit]");
  await click(".offer-result button");
  await setField("Material line name", "Needles", ".offer-review");
  await setField("Reviewed units per pack", "12", ".offer-review");
  await setField("I reviewed this product", true, ".offer-review");
  await setField("I reviewed the pack", true, ".offer-review");
  await click(".offer-review button[type=submit]");
  await until(() => evaluate("!!document.querySelector('.material-provenance')"), "provider selection saved");
  assert.equal(workshop.financials.materials.at(-1).pack_price_minor, 599);
  const selectionCall = JSON.parse(apiCalls.filter((item) => item.path.endsWith("/materials/select")).at(-1).body);
  assert.ok(!("price_minor" in selectionCall) && !("pack_price_minor" in selectionCall));
  await screenshot("workbench-materials-1440.png");
  passed("manual materials, explicit-only search, unconfigured/empty/stale states and reviewed selection (mocked provider API)");
  await click(".workbench-tabs button:nth-child(3)");
  await click("[data-section=economics] > button");
  await until(() => evaluate("!!document.querySelector('.economics-results')"), "explicit saved preview after material selection");
  await setField("Scenario attendance", "2", ".economics-results");
  assert.match(await evaluate("document.querySelector('.economics-results .host-notice').innerText"), /This attendance covers/);
  await setField("Scenario attendance", "3", ".economics-results");
  assert.match(await evaluate("document.querySelector('.economics-results .host-notice').innerText"), /does not cover/);
  await screenshot("workbench-economics-1440.png");
  passed("attendance selection displays returned non-monotonic viability, not an inferred threshold rule");
  await click(".workbench-tabs button:nth-child(1)");
  await setField("Description", "Retain this unsaved description across expiry.");
  expireNextSave = true;
  await click(".workbench .host-page-heading .host-button");
  await until(() => evaluate("!!document.querySelector('#host-password')"), "workbench reauthentication");
  await fill("#host-identifier", "fixture-host");
  await fill("#host-password", "fixture-password");
  await click(".login-card form > button");
  await until(() => evaluate("!!document.querySelector('.host-shell:not([hidden]) .workbench')"), "restored unsaved workbench");
  assert.equal(await evaluate("document.querySelector('[data-section=basics] textarea').value"), "Retain this unsaved description across expiry.");
  assert.match(await evaluate("document.querySelector('.workbench-status').innerText"), /Unsaved/);
  await click(".workbench .host-page-heading .host-button");
  await until(() => evaluate("/^(All changes saved|Saved on the server[.])$/.test(document.querySelector('.workbench-status [role=status]')?.innerText ?? '')"), "save after reauth");
  passed("same-host reauthentication preserves unsaved draft input without browser storage");
  await setField("Description", "Saved data survives a failed detail refresh.");
  failDetailAfterSave = true;
  await click(".workbench .host-page-heading .host-button");
  await until(() => evaluate("document.querySelector('.host-content h1')?.innerText === 'Workshop unavailable.'"), "post-save refresh outage");
  assert.match(await evaluate("document.querySelector('.host-content [role=alert]').innerText"), /save succeeded/);
  assert.equal(await evaluate("!!document.querySelector('.workbench')"), false);
  await click(".host-content .host-panel > button");
  await until(() => evaluate("!!document.querySelector('.workbench')"), "retry saved detail");
  assert.equal(await evaluate("document.querySelector('[data-section=basics] textarea').value"), "Saved data survives a failed detail refresh.");
  passed("successful save with failed detail refresh blocks stale editing and supports a safe reload");
  await click(".workbench-tabs button:nth-child(4)");
  assert.equal(await evaluate("document.querySelector('[data-section=review] > button:last-of-type').disabled"), true);
  await click("[data-section=review] > button:first-of-type");
  await until(() => evaluate("!!document.querySelector('[data-section=review] .host-positive')"), "review server preview");
  await setField("I have reviewed", true, "[data-section=review]");
  await screenshot("workbench-review-1440.png");
  await click("[data-section=review] > button:last-of-type");
  await until(() => evaluate("!!document.querySelector('.published-reference')"), "persisted campaign");
  assert.match(await evaluate("document.querySelector('.published-reference').innerText"), new RegExp(campaignId));
  assert.equal(await evaluate("document.querySelectorAll('[data-section=basics] input:not(:disabled)').length"), 0);
  passed("review gating, publish response, real-contract campaign reference and frozen controls (mocked API)");
  await click(".published-reference > a");
  await until(() => evaluate("!!document.querySelector('.real-detail-page')"), "published public detail");
  assert.match(await evaluate("document.querySelector('h1').innerText"), /A workshop from the workbench/);
  assert.equal(await evaluate("document.querySelector('.public-booking-panel button').disabled"), true);
  assert.doesNotMatch(await evaluate("document.querySelector('main').innerText"), /fixture.invalid|Needles|shipping_allowance_minor/);
  await noOverflow("desktop published detail");
  await screenshot("published-detail-1440.png");
  await visit("/workshops");
  assert.equal(await evaluate("document.querySelectorAll('.published-card').length"), 1);
  assert.equal(await evaluate("document.querySelectorAll('#example-collection .example-card').length"), 3);
  publicUnavailable = true;
  await visit("/workshops");
  await until(() => evaluate("!!document.querySelector('.published-collection [role=alert]')"), "public inventory outage");
  assert.equal(await evaluate("document.querySelectorAll('.published-card').length"), 0);
  publicUnavailable = false;
  passed("public listing/detail is separate from examples, guest booking is disabled and API failures do not fabricate inventory");
  for (const width of [375, 390, 720, 1024, 1440]) {
    await viewport(width, 900);
    await visit(`/host/workshops/${workshopId}#review`);
    await until(() => evaluate("!!document.querySelector('.published-reference')"), "responsive frozen workbench");
    await noOverflow(`${width}px frozen host workbench`);
    if (width === 390 || width === 1440) await screenshot(`workbench-frozen-${width}.png`);
    await visit(`/workshops/${workshopId}`);
    await until(() => evaluate("!!document.querySelector('.real-detail-page')"), "responsive public detail");
    await noOverflow(`${width}px published detail`);
    if (width === 390) await screenshot("published-detail-390.png");
  }
  passed("host workbench and actual-contract public detail reflow at 375–1440px");
  const providerCallsBeforeManual = apiCalls.filter((item) => item.path.endsWith("/materials/search")).length;
  await viewport(1440);
  await visit("/host/workshops/new#review");
  await until(() => evaluate("!!document.querySelector('.workbench')"), "new manual workflow");
  assert.match(await evaluate("document.querySelector('[data-section=review] .workflow-prerequisites').innerText"), /Save this workshop/);
  assert.equal(await evaluate("document.querySelector('[data-section=review] .host-check input').disabled"), true);
  assert.notEqual(await evaluate("document.querySelector('[data-section=review] .cost-breakdown > div:nth-child(4) dd').innerText"), "Not set");
  await click(".workbench-tabs button:nth-child(1)");
  await setField("Workshop title", "Manual materials — browser fixture");
  await setField("Ticket price", "10.00");
  const validClose = await evaluate("document.querySelectorAll('[data-section=basics] input[type=datetime-local]')[1].value");
  const openValue = await evaluate("document.querySelector('[data-section=basics] input[type=datetime-local]').value");
  await setField("Booking cutoff", openValue);
  const createCount = apiCalls.filter((item) => item.path === "/api/merchant/workshops" && item.method === "POST").length;
  await click(".workbench .host-page-heading .host-button");
  assert.match(await evaluate("document.querySelector('.workbench [role=alert]').innerText"), /after booking open/);
  assert.equal(apiCalls.filter((item) => item.path === "/api/merchant/workshops" && item.method === "POST").length, createCount);
  await setField("Booking cutoff", validClose);
  const callsBeforeSave = apiCalls.length, saveClickedAt = Date.now();
  await click(".workbench .host-page-heading .host-button");
  try {
    await until(() => evaluate(`location.pathname.endsWith('${workshopId}') && !!document.querySelector('.workbench-status')`), "manual draft persisted");
    console.log(`manual draft persisted ${Date.now() - saveClickedAt} ms after the save click`);
  } catch (error) {
    // Evidence only: which stage (request, response, navigation, render) did not happen. No retry.
    const state = await evaluate(`({ path: location.pathname, hash: location.hash, h1: document.querySelector('main h1, #root h1')?.innerText ?? null,
      alert: document.querySelector('.workbench [role=alert]')?.innerText ?? null, status: !!document.querySelector('.workbench-status'),
      workbench: !!document.querySelector('.workbench'), saveButton: (() => { const b = document.querySelector('.workbench .host-page-heading .host-button'); return b ? { text: b.innerText, disabled: b.disabled } : null; })() })`).catch((e) => ({ evaluateError: e.message }));
    const calls = apiCalls.slice(callsBeforeSave).map(({ method, path, code }) => `${method} ${path} -> ${code}`);
    console.error(`manual draft save diagnostics after ${Date.now() - saveClickedAt} ms: ${JSON.stringify({ calls, state })}`);
    throw error;
  }
  await click(".workbench-tabs button:nth-child(2)");
  await setField("Material name", "box", ".manual-material-form");
  await setField("Assumed pack price", "3.50", ".manual-material-form");
  assert.match(await evaluate("document.querySelector('.pending-material-notice').innerText"), /entered but not added/);
  await click(".workbench .host-page-heading .host-button");
  assert.match(await evaluate("document.querySelector('.workbench [role=alert]').innerText"), /has not been added/);
  await click(".manual-material-form button[type=submit]");
  assert.match(await evaluate("document.querySelector('.material-save-state').innerText"), /Not saved yet/);
  await click(".workbench .host-page-heading .host-button");
  await until(() => evaluate("document.querySelector('.material-save-state')?.innerText === 'Saved on server'"), "manual line persisted");
  assert.equal(workshop.financials.materials[0].name, "box");
  await click(".workbench-tabs button:nth-child(1)");
  await setField("Booking cutoff", "");
  await click(".workbench .host-page-heading .host-button");
  assert.match(await evaluate("document.querySelector('.workbench [role=alert]').innerText"), /Booking cutoff/);
  await setField("Booking cutoff", validClose);
  await click(".workbench .host-page-heading .host-button");
  await until(() => evaluate("/^(All changes saved|Saved on the server[.])$/.test(document.querySelector('.workbench-status [role=status]')?.innerText ?? '')"), "booking dates saved");
  {
    // Editor values -> exact save-request instants -> persisted fixture -> reloaded editor values.
    const editorValues = JSON.parse(await evaluate("JSON.stringify([...document.querySelectorAll('[data-section=basics] input[type=datetime-local]')].map((input) => input.value))"));
    const expectedIso = JSON.parse(await evaluate(`JSON.stringify(${JSON.stringify(editorValues)}.map((value) => new Date(value).toISOString()))`));
    const lastWrite = apiCalls.filter((item) => item.path.startsWith("/api/merchant/workshops") && ["POST", "PATCH"].includes(item.method) && item.body?.includes("schedule")).at(-1);
    const sent = JSON.parse(lastWrite.body).schedule;
    assert.deepEqual([sent.opens_at, sent.closes_at], expectedIso);
    assert.deepEqual([workshop.opens_at, workshop.closes_at], expectedIso);
    assert.match(await evaluate("document.querySelector('[data-section=basics] .schedule-summary').innerText"), /Booking cutoff · London time[\s\S]*Closes (today|tomorrow|on .+) at \d{2}:\d{2}:\d{2} (GMT|BST)/);
    assert.match(await evaluate("document.querySelector('[data-section=basics] .schedule-summary').innerText"), /Time remaining until cutoff[\s\S]*until cutoff/);
    assert.match(await evaluate("document.querySelector('[data-section=review] .schedule-summary').innerText"), /Booking window duration/);
    assert.equal(await evaluate("!!document.querySelector('.sandbox-preset')"), false, "production bundle never offers the local Sandbox preset");
    passed("booking dates survive editor → save request → persisted draft; summaries render; no Sandbox preset in production bundle");
  }
  await click(".workbench-tabs button:nth-child(4)");
  assert.equal(await evaluate("document.querySelector('[data-section=review] .host-check input').disabled"), true);
  failPreview = true;
  await click("[data-section=review] > button:first-of-type");
  await until(() => evaluate("!!document.querySelector('.workbench [role=alert]')"), "preview failure");
  assert.match(await evaluate("document.querySelector('.workbench [role=alert]').innerText"), /Could not run preview/);
  assert.equal(await evaluate("document.querySelector('[data-section=review] .host-check input').disabled"), true);
  failPreview = false; stalePreview = true;
  await click("[data-section=review] > button:first-of-type");
  await until(() => evaluate("document.querySelector('.workbench [role=alert]')?.innerText.includes('Saved terms changed')"), "stale preview rejected");
  assert.equal(await evaluate("document.querySelector('[data-section=review] .host-check input').disabled"), true);
  stalePreview = false;
  await click("[data-section=review] > button:first-of-type");
  await until(() => evaluate("!document.querySelector('[data-section=review] .host-check input').disabled"), "preview permits acknowledgement");
  await setField("I have reviewed", true, "[data-section=review]");
  await click(".workbench-tabs button:nth-child(2)");
  await setField("Material name", "not yet added", ".manual-material-form");
  await click(".workbench-tabs button:nth-child(4)");
  assert.equal(await evaluate("document.querySelector('[data-section=review] .host-check input').checked"), false);
  assert.equal(await evaluate("document.querySelector('[data-section=review] .host-check input').disabled"), true);
  assert.match(await evaluate("document.querySelector('[data-section=review] .workflow-prerequisites').innerText"), /not in the draft/);
  await screenshot("review-material-prerequisite-1440.png");
  await click(".workbench-tabs button:nth-child(2)");
  await screenshot("materials-prerequisite-1440.png");
  await evaluate("document.querySelector('.provider-prerequisites').scrollIntoView({ behavior: 'instant', block: 'center' })");
  await screenshot("provider-search-prerequisite-1440.png");
  await click(".manual-material-form button[type=button]");
  await click(".workbench-tabs button:nth-child(4)");
  await click("[data-section=review] > button:first-of-type");
  await until(() => evaluate("!document.querySelector('[data-section=review] .host-check input').disabled"), "new preview after discarding pending line");
  await setField("I have reviewed", true, "[data-section=review]");
  await click(".workbench-tabs button:nth-child(1)");
  await setField("Ticket price", "11.00");
  await click(".workbench-tabs button:nth-child(4)");
  assert.equal(await evaluate("document.querySelector('[data-section=review] .host-check input').checked"), false);
  assert.equal(await evaluate("document.querySelector('[data-section=review] > button:last-of-type').disabled"), true);
  await click(".workbench .host-page-heading .host-button");
  await until(() => evaluate("/^(All changes saved|Saved on the server[.])$/.test(document.querySelector('.workbench-status [role=status]')?.innerText ?? '')"), "edited terms saved");
  await click("[data-section=review] > button:first-of-type");
  await until(() => evaluate("!document.querySelector('[data-section=review] .host-check input').disabled"), "preview edited saved terms");
  await setField("I have reviewed", true, "[data-section=review]");
  assert.equal(await evaluate("document.querySelector('.channel3-section .host-check input').checked"), false);
  const expectedHash = workshop.terms_snapshot_hash;
  await screenshot("manual-review-ready-1440.png");
  await viewport(390, 844);
  await screenshot("manual-review-ready-390.png");
  await evaluate("document.querySelector('[data-section=review] > .host-check').scrollIntoView({ behavior: 'instant', block: 'center' })");
  await screenshot("manual-review-controls-390.png");
  await noOverflow("mobile manual review prerequisites");
  await click("[data-section=review] > button:last-of-type");
  await until(() => evaluate("!!document.querySelector('.published-reference')"), "manual-only publication");
  const reviewedRequest = JSON.parse(apiCalls.filter((item) => item.path.endsWith("/publish")).at(-1).body);
  assert.equal(reviewedRequest.expected_terms_snapshot_hash, expectedHash);
  assert.equal(reviewedRequest.expected_terms_version, workshop.terms_version);
  assert.equal(apiCalls.filter((item) => item.path.endsWith("/materials/search")).length, providerCallsBeforeManual);
  passed("new → create → add material → save → dates → save → preview → acknowledge → publish needs no Channel3 acknowledgement");
  passed("invalid dates, preview failure, stale preview and post-ack edits keep publication disabled and preserve entered data");
  authMode = "unavailable"; expireListing = false;
  await visit("/host/login");
  await until(() => evaluate("document.querySelector('h1').innerText.includes('unavailable')"), "unavailable session");
  passed("server outage is distinguished from anonymous or invalid credentials (mocked API)");
  assert.deepEqual(errors, []);
  passed("no uncaught browser exceptions");
  console.log(`${checks} browser checks passed. API checks used intercepted fixtures, not real sessions.`);
  console.log(`Screenshots: ${artifacts}`);
} finally {
  socket?.close();
  chrome?.kill("SIGTERM");
  server.kill("SIGTERM");
}
