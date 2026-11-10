import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { access, mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";

// Campaign Intelligence (AG Studio) at /host/workshops/{id}/intelligence.
// Production build (vite preview) by default; INTELLIGENCE_TEST_DEV=1 uses the Vite dev server, where
// enableStudioDevValidations() and AG Grid validation are active.
// Every /api/* request is intercepted with fixtures: no backend, database, model or payment provider is touched.
const root = fileURLToPath(new URL("../", import.meta.url));
const chromePath = process.env.CHROME_PATH ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
await access(chromePath);
const devMode = process.env.INTELLIGENCE_TEST_DEV === "1";
const artifacts = resolve(root, "node_modules/.tmp/intelligence-evidence");
await mkdir(artifacts, { recursive: true });
const profile = await mkdtemp(resolve(artifacts, "chrome-profile-"));
const base = "http://127.0.0.1:4181";
if (await fetch(base).then(() => true, () => false)) throw new Error(`${base} is already in use; stop the stale server first.`);
const server = spawn(process.execPath, [resolve(root, "node_modules/vite/bin/vite.js"), ...(devMode ? [] : ["preview"]), "--host", "127.0.0.1", "--port", "4181", "--strictPort"],
  { cwd: root, stdio: ["ignore", "pipe", "pipe"] });
let serverError = "";
server.stderr.on("data", (data) => { serverError += data; });
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
async function until(check, label, attempts = 200) {
  for (let i = 0; i < attempts; i++) { if (await check()) return; await sleep(100); }
  throw new Error(`Timed out: ${label}`);
}

// ---- fixtures ---------------------------------------------------------------------------------
const PUBLISHED = "11111111-1111-4111-8111-111111111111";
const DRAFT = "22222222-2222-4222-8222-222222222222";
const BROKEN = "33333333-3333-4333-8333-333333333333";
const INVALID = "44444444-4444-4444-8444-444444444444";
const EMPTY = "55555555-5555-4555-8555-555555555555";
const materials = [
  { name: "Clay", source_label: "merchant", kind: "consumable", shared_units: 0, per_attendee_units: 1, pack_size: 4, pack_price_minor: 2000, offer_provenance: null },
  { name: "Glaze", source_label: "channel3-offer-snapshot+merchant-reviewed-assumptions", kind: "consumable", shared_units: 1, per_attendee_units: 0, pack_size: 1, pack_price_minor: 1500,
    offer_provenance: { offer_snapshot_id: "private-snapshot-id", provider: "channel3", product_title: "Glaze", merchant_domain: "supplier.invalid", price_minor: 1500,
      retrieved_at: "2026-11-05T10:00:00Z", product_url: "https://supplier.invalid/private", suitability_reviewed: true, pack_size_reviewed: true, review_notes: null } },
];
// Pack-cost step: viable at 4, NOT viable at 5 (a second clay pack), viable again at 6..8.
const clayPacks = (a) => Math.ceil(a / 4);
const curve = Array.from({ length: 8 }, (_, i) => {
  const attendance = i + 1;
  const material = clayPacks(attendance) * 2000 + 1500;
  const budget = 3000 + material;
  const gross = attendance * 2500;
  const fees = attendance * 100;
  const surplus = gross - fees - budget - (attendance === 5 ? 6000 : 0);
  return { attendance, packs_by_material: { Clay: clayPacks(attendance), Glaze: 1 }, material_cost_minor: material, required_budget_minor: budget + (attendance === 5 ? 6000 : 0),
    gross_minor: gross, estimated_fees_minor: fees, estimated_net_minor: gross - fees, estimated_surplus_minor: surplus, is_viable: surplus >= 0 };
});
// Make the fixture's material total consistent with lines except where noted.
const preview = (extra = {}) => ({ terms_version: 1, terms_snapshot_hash: "a".repeat(64), algorithm_version: "fixture", currency: "GBP", ticket_price_minor: 2500, capacity: 8,
  minimum_operating_attendance: 1, first_viable_attendance: curve.find((p) => p.is_viable)?.attendance ?? null, any_viable_attendance: curve.some((p) => p.is_viable),
  is_viable_at_capacity: curve.at(-1).is_viable, attendance_curve: curve, materials_note: "fixture", ...extra });
const financials = { currency: "GBP", ticket_price_minor: 2500, capacity: 8, minimum_operating_attendance: 1, fixed_costs_minor: 3000, materials,
  shipping_allowance_minor: 0, shipping_allowance_source: "x", contingency_minor: 0, fee_estimate: { percent_basis_points: 0, fixed_minor: 100, label: "fixture" } };
const workshop = (id, title, campaign) => ({ workshop_id: id, title, description: null, capacity: 8, ticket_price_minor: 2500, currency: "GBP", terms_version: 1,
  is_frozen: Boolean(campaign), opens_at: "2026-11-15T10:00:00Z", closes_at: "2026-11-17T09:00:00Z", campaign_id: campaign?.campaign_id ?? null,
  hidden_from_discovery_at: null, terms_snapshot_hash: "a".repeat(64), offer_stale_after_seconds: 3600, financials, campaign });
const settlement = { state: "OPEN", decision_result: null, decision_reason: null, frozen_attendance: null, admitted_attendance: 5, authorized_minor: 12500, collected_minor: 0,
  refunded_minor: 0, capture_pending: 0, release_pending: 0, refund_pending: 0, review_required: false, settlement_deadline: null, fee_basis: "estimated",
  actual_fees_minor: null, estimated_fees_minor: null, estimated_surplus_minor: null, post_collection_surplus_minor: null };
const details = {
  [PUBLISHED]: workshop(PUBLISHED, "Pottery evening", { campaign_id: "c-1", workshop_id: PUBLISHED, status: "OPEN", capacity: 8, cutoff_at: "2026-11-17T09:00:00Z",
    terms_version: 1, terms_id: "t", terms_snapshot_hash: "a".repeat(64), settlement }),
  [DRAFT]: workshop(DRAFT, "Draft zine binding", null),
  [BROKEN]: workshop(BROKEN, "Broken preview", null),
  [INVALID]: workshop(INVALID, "Invalid terms", null),
  [EMPTY]: workshop(EMPTY, "Empty curve", null),
};

let chrome, socket, checks = 0;
const passed = (message) => { checks++; console.log(`PASS ${message}`); };
try {
  await until(async () => {
    if (server.exitCode !== null) throw new Error(`Server exited: ${serverError}`);
    try { return (await fetch(base)).ok; } catch { return false; }
  }, "server startup");
  chrome = spawn(chromePath, ["--headless", "--disable-gpu", "--disable-background-networking", "--disable-component-update", "--disable-sync",
    "--no-first-run", "--no-default-browser-check", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank"], { stdio: ["ignore", "ignore", "pipe"] });
  const endpoint = await new Promise((done, reject) => {
    let output = "";
    const timeout = setTimeout(() => reject(new Error("Chrome debugging endpoint unavailable")), 15000);
    chrome.stderr.on("data", (data) => { output += data; const match = output.match(/DevTools listening on (ws:\/\/[^\s]+)/); if (match) { clearTimeout(timeout); done(match[1]); } });
    chrome.on("error", reject);
  });
  socket = new WebSocket(endpoint);
  await new Promise((done, reject) => { socket.addEventListener("open", done, { once: true }); socket.addEventListener("error", reject, { once: true }); });
  let sequence = 0;
  const pending = new Map();
  const events = new Set();
  socket.addEventListener("message", ({ data }) => {
    const message = JSON.parse(data);
    if (message.id) {
      const promise = pending.get(message.id); if (!promise) return;
      pending.delete(message.id); clearTimeout(promise.timeout);
      if (message.error) promise.reject(new Error(message.error.message)); else promise.done(message.result);
    } else for (const listener of events) listener(message);
  });
  const send = (method, params = {}, sessionId) => new Promise((done, reject) => {
    const id = ++sequence;
    const timeout = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 60000);
    pending.set(id, { done, reject, timeout });
    socket.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
  });
  const { targetInfos } = await send("Target.getTargets");
  const { sessionId } = await send("Target.attachToTarget", { targetId: targetInfos.find((t) => t.type === "page").targetId, flatten: true });
  const cdp = (method, params) => send(method, params, sessionId);
  await cdp("Page.enable"); await cdp("Runtime.enable");

  let authMode = "authenticated";
  let failDetail = false;
  let holdPreview = false;
  let analystStatus = { available: false, status: "disabled", provider: "OpenRouter", model: null };
  const analystReplies = [];
  let holdAnalyst = false;
  let heldAnalyst = null;
  let heldPreview = null;
  const apiCalls = [];
  const externalRequests = [];
  const errors = [];
  const consoleMessages = [];
  const fixture = { merchant: { merchant_id: "test-host", name: "Fixture host" }, session_id: "s", csrf_token: "bound-test-csrf", expires_at: "2099-01-01T00:00:00Z" };
  const respond = (requestId, code, body) => cdp("Fetch.fulfillRequest", { requestId, responseCode: code,
    responseHeaders: [{ name: "Content-Type", value: "application/json" }], body: Buffer.from(JSON.stringify(body)).toString("base64") }).catch((error) => errors.push(error.message));
  events.add((event) => {
    if (event.method === "Runtime.exceptionThrown") errors.push(event.params.exceptionDetails.exception?.description ?? event.params.exceptionDetails.text);
    if (event.method === "Runtime.consoleAPICalled") consoleMessages.push(`${event.params.type}: ${event.params.args.map((a) => a.value ?? a.description).join(" ")}`);
    if (event.method !== "Fetch.requestPaused") return;
    const { requestId, request } = event.params;
    const url = new URL(request.url);
    if (url.origin !== base) {
      externalRequests.push(request.url);
      return void cdp("Fetch.failRequest", { requestId, errorReason: "BlockedByClient" }).catch(() => {});
    }
    if (!url.pathname.startsWith("/api/")) return void cdp("Fetch.continueRequest", { requestId }).catch(() => {});
    const path = url.pathname;
    apiCalls.push({ path, method: request.method, csrf: Object.entries(request.headers).find(([k]) => k.toLowerCase() === "x-csrf-token")?.[1] ?? null, body: request.postData ?? null });
    if (path === "/api/me") return void respond(requestId, authMode === "authenticated" ? 200 : 401, authMode === "authenticated" ? fixture : { detail: "authentication required" });
    if (path === "/api/auth/csrf") return void respond(requestId, 200, { csrf_token: "bootstrap" });
    if (path === "/api/merchant/login") { authMode = "authenticated"; return void respond(requestId, 200, fixture); }
    if (path === "/api/merchant/workshops" && request.method === "GET") return void respond(requestId, 200, Object.values(details));
    const detail = path.match(/^\/api\/merchant\/workshops\/([0-9a-f-]{36})$/);
    if (detail && request.method === "GET") {
      if (authMode !== "authenticated") return void respond(requestId, 401, { detail: "authentication required" });
      // Fails until the test turns it off (dev StrictMode issues effects twice, so "fail once" is not enough).
      if (failDetail) return void respond(requestId, 503, { detail: "temporarily unavailable" });
      return details[detail[1]] ? void respond(requestId, 200, details[detail[1]]) : void respond(requestId, 404, { detail: "workshop not found" });
    }
    if (/^\/api\/merchant\/workshops\/[0-9a-f-]{36}\/intelligence\/analyst$/.test(path)) {
      if (request.method === "GET") return void respond(requestId, 200, analystStatus);
      if (holdAnalyst) { heldAnalyst = requestId; return; }
      const [code, body] = analystReplies.shift() ?? [503, { detail: { code: "PROVIDER_ERROR", message: "x" } }];
      return void respond(requestId, code, body);
    }
    const previewMatch = path.match(/^\/api\/merchant\/workshops\/([0-9a-f-]{36})\/preview$/);
    if (previewMatch && request.method === "POST") {
      if (holdPreview) { heldPreview = requestId; return; }
      if (previewMatch[1] === BROKEN) return void respond(requestId, 503, { detail: "calculator unavailable" });
      if (previewMatch[1] === INVALID) return void respond(requestId, 409, { detail: "fee estimate is required before preview" });
      if (previewMatch[1] === EMPTY) return void respond(requestId, 200, preview({ attendance_curve: [], first_viable_attendance: null, any_viable_attendance: false, is_viable_at_capacity: false }));
      return void respond(requestId, 200, preview());
    }
    return void respond(requestId, 503, { detail: "unexpected test API request" });
  });
  await cdp("Fetch.enable", { patterns: [{ urlPattern: "*" }] });

  async function evaluate(expression) {
    const response = await cdp("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (response.exceptionDetails) throw new Error(response.exceptionDetails.exception?.description ?? response.exceptionDetails.text);
    return response.result.value;
  }
  const viewport = (width, height = 1000) => cdp("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width < 600 });
  let visitMark = 0;
  const visit = async (path) => { visitMark = consoleMessages.length; await cdp("Page.navigate", { url: base + path }); await until(() => evaluate("document.readyState === 'complete'"), `load ${path}`); };
  const text = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.innerText ?? null`);
  const pathname = () => evaluate("location.pathname + location.search");
  async function screenshot(name, full = false) {
    const image = await cdp("Page.captureScreenshot", { format: "png", captureBeyondViewport: full });
    await writeFile(resolve(artifacts, name), Buffer.from(image.data, "base64"));
  }
  const studioReady = async () => {
    try { await until(() => evaluate("!!document.querySelector('.ci-studio [data-testid=tipping-meter] .tp-meter-big')"), "Studio + Tipping Meter rendered", 600); }
    catch (error) {
      await screenshot("timeout.png", true);
      console.log("TIMEOUT state:", (await text("#host-content"))?.slice(0, 500), "| widgets:", await evaluate("document.querySelectorAll('.ag-studio-layout-widget').length"),
        "| overlays shown:", await evaluate("[...document.querySelectorAll('.ag-studio-layout-widget-loading-overlay, .ag-studio-layout-widget-no-data-overlay')].filter(o => getComputedStyle(o).display !== 'none').length"),
        "| errors:", JSON.stringify(errors).slice(0, 800), "| api:", JSON.stringify(apiCalls.map((c) => `${c.method} ${c.path}`)));
      throw error;
    }
  };

  const pathOf = (id) => `/host/workshops/${id}/intelligence`;
  const meterText = () => text(".ci-studio [data-testid=tipping-meter]");
  const widgetText = (title) => evaluate(`[...document.querySelectorAll('.ci-studio .ag-studio-layout-widget')].find(w => w.innerText.includes(${JSON.stringify(title)}))?.innerText ?? null`);
  const isAnalyst = (c) => /\/intelligence\/analyst$/.test(c.path);
  const mutating = () => apiCalls.filter((c) => c.method !== "GET" && !(c.method === "POST" && (/\/preview$/.test(c.path) || isAnalyst(c))) && !["/api/auth/csrf", "/api/merchant/login"].includes(c.path));
  const studioChunkLoaded = () => evaluate("performance.getEntriesByType('resource').some(e => /StudioDashboard/.test(e.name))");

  // ---- 1. Workbench link; Studio loads only on the intelligence route --------------------------
  await viewport(1440);
  await visit(`/host/workshops/${PUBLISHED}`);
  await until(() => evaluate("!!document.querySelector('.workbench-summary .ci-link')"), "workbench Campaign Intelligence link");
  assert.equal(await evaluate("document.querySelector('.workbench-summary .ci-link').getAttribute('href')"), pathOf(PUBLISHED));
  assert.equal(await studioChunkLoaded(), false, "AG Studio not downloaded on the workbench");
  holdPreview = true;
  await evaluate("document.querySelector('.workbench-summary .ci-link').click()");
  await until(async () => (await pathname()) === pathOf(PUBLISHED), "navigate to intelligence");
  await until(() => heldPreview !== null, "preview requested");
  assert.match(await text(".campaign-intelligence [role=status]"), /Loading campaign data/);
  assert.equal(await studioChunkLoaded(), false, "Studio waits for data before downloading");
  passed("workbench links to Campaign Intelligence; loading state shown; AG Studio not downloaded until data is ready");
  holdPreview = false;
  await respond(heldPreview, 200, preview()); heldPreview = null;
  await studioReady();
  assert.equal(await studioChunkLoaded(), true);

  // ---- 2. Genuine Studio, real (fixture) data, backend viability per point ----------------------
  const meter = await meterText();
  assert.match(meter, /NOT VIABLE AT CURRENT ATTENDANCE/i, "admitted 5 sits on a non-viable pack-cost step");
  assert.match(meter, /\b5\b[\s\S]*admitted of 8/);
  assert.match(meter, /Next viable attendance\s*6/);
  assert.match(meter, /Places still required\s*1/);
  assert.match(meter, /Authorised · not collected\s*£125\.00/);
  assert.match(meter, /Collected\s*£0\.00/);
  const meterAria = await evaluate("(() => { const m = document.querySelector('.tp-meter-track'); return { role: m.getAttribute('role'), now: m.getAttribute('aria-valuenow'), max: m.getAttribute('aria-valuemax'), text: m.getAttribute('aria-valuetext') }; })()");
  assert.deepEqual([meterAria.role, meterAria.now, meterAria.max], ["meter", "5", "8"]);
  const fill = await evaluate("(() => { const f = document.querySelector('.tp-meter-fill').getBoundingClientRect(), t = document.querySelector('.tp-meter-track').getBoundingClientRect(); return { h: f.height, ratio: f.width / t.width }; })()");
  assert.ok(fill.h > 4 && Math.abs(fill.ratio - 5 / 8) < 0.02, `meter fill shows 5/8: ${JSON.stringify(fill)}`);
  await until(async () => /\b8\s+Viable/.test(await widgetText("Attendance curve") ?? ""), "attendance grid rows");
  const curveTable = await widgetText("Attendance curve");
  for (const [a, v] of [[3, "Viable"], [4, "Viable"], [5, "Not viable"], [6, "Viable"]]) {
    assert.match(curveTable, new RegExp(`\\b${a}\\s+${v}\\b`), `attendance ${a} is ${v} as the backend says`);
  }
  assert.match(curveTable, /£125\.00\s+£150\.00/, "attendance 5 revenue and total costs incl. estimated fees (budget £145 + fees £5)");
  await until(() => evaluate("[...document.querySelectorAll('.ci-studio .ag-studio-layout-widget')].filter(w => /Revenue, total costs|Material cost by attendance/.test(w.innerText) && w.querySelector('canvas')).length === 2"), "two chart widgets drew canvases");
  const materialsText = await widgetText("Materials breakdown");
  assert.match(materialsText, /Clay\s+Merchant-entered assumption/);
  assert.match(materialsText, /Glaze\s+Channel3 offer snapshot \(supplier\.invalid\), retrieved 2026-11-05; merchant-reviewed/);
  assert.match(materialsText, /£40\.00/, "clay cost at capacity = 2 packs × £20");
  const html = await evaluate("document.documentElement.outerHTML");
  for (const secret of ["private-snapshot-id", "https://supplier.invalid/private", "test-host", "bound-test-csrf", "\"s\""]) {
    assert.ok(!html.includes(secret) || secret === "\"s\"", `sanitised: ${secret} not in the page`);
  }
  assert.deepEqual(mutating(), [], "no mutating requests");
  const previews = apiCalls.filter((c) => /\/preview$/.test(c.path));
  assert.ok(previews.every((c) => c.csrf === "bound-test-csrf" && !c.body), "preview is the existing CSRF-protected calculation with no payload");
  await screenshot("intelligence-1440.png", true);
  passed("AG Studio renders the Tipping Meter, attendance curve (per-point backend viability incl. the 5-attendee step), material costs and materials; sanitised; GET + calculator preview only");

  // ---- 3. Tipping Meter is a registered widget in Studio's own menu; data panel is sanitised ----
  await evaluate("[...document.querySelectorAll('.ci-mode button')].find(b => b.innerText === 'Edit layout').click()");
  await until(() => evaluate("document.querySelector('.ci-studio').innerText.includes('Compose')"), "edit mode compose panel");
  await evaluate(`(() => { const input = [...document.querySelectorAll('.ci-studio input')].find(i => i.closest('*') && /Search/i.test(i.placeholder) && i.closest('[class*=compose], [class*=Compose], [class*=widget-menu], [class*=panel]')); input.focus(); })()`);
  await cdp("Input.insertText", { text: "Tipping" });
  await until(() => evaluate("[...document.querySelectorAll('.ci-studio *')].some(e => e.children.length === 0 && e.innerText?.trim() === 'Tipping Meter')"), "Tipping Meter in widget menu search");
  const dataPanel = await evaluate("document.querySelector('.ci-studio').innerText");
  for (const field of ["Campaign health", "Admitted bookings", "Authorised (not collected)", "Collected"]) assert.ok(dataPanel.includes(field), `data panel lists ${field}`);
  await screenshot("intelligence-edit-1440.png");
  passed("edit mode: Tipping Meter is found in Studio's widget menu; data panel lists only sanitised fields");

  // ---- 4. Draft: bookings and payments marked unavailable, never zero ---------------------------
  await visit(pathOf(DRAFT));
  await studioReady();
  const draftMeter = await meterText();
  assert.match(draftMeter, /DRAFT · NOT PUBLISHED/i);
  assert.match(draftMeter, /—[\s\S]*admitted · not available/);
  assert.match(draftMeter, /Next viable attendance\s*3/, "first viable attendance from the backend");
  assert.match(draftMeter, /Authorised · not collected\s*Not available/);
  assert.match(draftMeter, /Collected\s*Not available/);
  assert.match(await text(".ci-capabilities"), /not published, so none exist/);
  passed("draft: bookings/authorised/collected shown as Not available (not zero); unavailable capabilities listed");

  // ---- 4b. Rescue Analyst (fixture endpoints; the real model/tool loop runs on the server) -------
  await visit(pathOf(PUBLISHED));
  await studioReady();
  await until(() => evaluate("!!document.querySelector('.ci-analyst-off')"), "analyst not configured");
  assert.match(await text(".ci-analyst-off"), /Analyst not configured\. Analyst not configured: an operator has not enabled it/);
  assert.equal(await evaluate("!!document.querySelector('.ci-analyst textarea')"), false, "no question box when not configured");
  assert.equal(await text(".ci-analyst-disclaimer"), "Analyst output is informational and is not financial advice.", "disclaimer shown while disabled");
  assert.match(await meterText(), /admitted of 8/, "dashboard unaffected");
  passed("analyst not configured: clear message, no question box, dashboard intact");

  analystStatus = { available: true, status: "ready", provider: "OpenRouter", model: "vendor/tool-model" };
  await visit(pathOf(PUBLISHED));
  await studioReady();
  await until(() => evaluate("!!document.querySelector('.ci-analyst-suggestions button')"), "suggestions");
  assert.equal(await text(".ci-analyst-connection"), "OpenRouter · vendor/tool-model");
  const suggestions = await evaluate("[...document.querySelectorAll('.ci-analyst-suggestions button')].map(b => b.innerText)");
  assert.deepEqual(suggestions, ["Explain this workshop's tipping point.", "What could make this workshop non-viable?", "Show revenue versus total costs.", "Which materials drive the budget?"]);
  assert.equal(await text(".ci-analyst-disclaimer"), "Analyst output is informational and is not financial advice.", "disclaimer shown while available");
  const widgetsBefore = await evaluate("document.querySelectorAll('.ci-studio .ag-studio-layout-widget').length");
  holdAnalyst = true;
  await evaluate("document.querySelectorAll('.ci-analyst-suggestions button')[2].click()");
  await until(() => heldAnalyst !== null, "analyst request sent");
  assert.match(await text(".ci-analyst-pending"), /Working… the server is calling OpenRouter · vendor\/tool-model/);
  assert.equal(await evaluate("[...document.querySelectorAll('.ci-analyst-suggestions button')].every(b => b.disabled) && document.querySelector('.ci-analyst textarea').disabled"), true);
  await evaluate("document.querySelectorAll('.ci-analyst-suggestions button')[0].click(); document.querySelector('.ci-analyst-form').requestSubmit()");
  await sleep(300);
  assert.equal(apiCalls.filter((c) => isAnalyst(c) && c.method === "POST").length, 1, "duplicate submissions prevented");
  const sent = apiCalls.find((c) => isAnalyst(c) && c.method === "POST");
  assert.deepEqual(JSON.parse(sent.body), { messages: [{ role: "user", content: "Show revenue versus total costs." }] }, "body is only conversation text");
  assert.equal(sent.csrf, "bound-test-csrf");
  holdAnalyst = false;
  await respond(heldAnalyst, 200, { status: "answered", provider: "OpenRouter", model: "vendor/tool-model", rounds: 2, tool_calls: 2,
    answer: "Revenue passes total costs at 4 attendees.\n\nAt 5 a second clay pack makes it non-viable. <img src=x onerror=\"window.__pwned=1\"> <a href=\"javascript:window.__pwned=2\">click</a>",
    activity: [{ tool: "get_attendance_curve", status: "ok", summary: "Read the backend attendance curve" }, { tool: "show_visualization", status: "ok", summary: "Requested Studio visualization: revenue_vs_costs" }],
    visualizations: [{ preset: "revenue_vs_costs", title: "Revenue vs costs" }] });
  heldAnalyst = null;
  await until(() => evaluate("!!document.querySelector('.ci-analyst-answer')"), "answer rendered");
  assert.match(await text(".ci-analyst-answer"), /second clay pack makes it non-viable\. <img src=x onerror=/);
  assert.equal(await evaluate("document.querySelectorAll('.ci-analyst img, .ci-analyst-answer a, .ci-analyst script').length"), 0, "model output rendered as text");
  assert.equal(await evaluate("window.__pwned ?? null"), null);
  assert.match(await text(".ci-analyst-activity summary"), /Tool activity \(2\)/);
  assert.match(await text(".ci-analyst .host-positive"), /Added or updated on the dashboard: Analyst: Revenue vs costs/);
  await until(() => evaluate(`document.querySelectorAll('.ci-studio .ag-studio-layout-widget').length === ${widgetsBefore + 1}`), "Studio widget added");
  await until(async () => (await widgetText("Analyst: Revenue vs costs")) !== null, "analyst widget title in Studio");
  passed("analyst: pending state, duplicate prevention, body is only messages; answer as plain text; tool activity; chart added to Studio via setState");

  analystReplies.push([200, { status: "answered", provider: "OpenRouter", model: "vendor/tool-model", rounds: 2, tool_calls: 1, answer: "Updated.",
    activity: [], visualizations: [{ preset: "revenue_vs_costs", title: "Revenue vs costs (updated)" }] }]);
  await evaluate("(() => { const t = document.querySelector('.ci-analyst textarea'); Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(t, 'Update that chart'); t.dispatchEvent(new Event('input', { bubbles: true })); })()");
  await sleep(100);
  await evaluate("document.querySelector('.ci-analyst-form').requestSubmit()");
  await until(async () => (await widgetText("Analyst: Revenue vs costs (updated)")) !== null, "analyst widget updated");
  assert.equal(await evaluate("document.querySelectorAll('.ci-studio .ag-studio-layout-widget').length"), widgetsBefore + 1, "updated in place, not duplicated");
  const second = JSON.parse(apiCalls.filter((c) => isAnalyst(c) && c.method === "POST").at(-1).body);
  assert.deepEqual(second.messages.map((m) => m.role), ["user", "assistant", "user"], "bounded history carries prior turn");
  passed("analyst: follow-up sends bounded history; the same preset updates its Studio widget in place");

  analystReplies.push([429, { detail: { code: "PROVIDER_RATE_LIMITED", message: "provider said sk-secret" } }]);
  await evaluate("document.querySelectorAll('.ci-analyst-suggestions button')[0].click()");
  await until(() => evaluate("[...document.querySelectorAll('.ci-analyst [role=alert]')].some(e => /rate limiting/.test(e.innerText))"), "inline error");
  assert.equal((await text(".ci-analyst")).includes("sk-secret"), false);
  holdAnalyst = true;
  await evaluate("document.querySelectorAll('.ci-analyst-suggestions button')[3].click()");
  await until(() => heldAnalyst !== null, "held request");
  await evaluate("document.querySelector('.ci-analyst-cancel').click()");
  await until(() => evaluate("[...document.querySelectorAll('.ci-analyst .host-notice')].some(e => /Stopped waiting\. The server may still finish/.test(e.innerText))"), "cancelled");
  assert.equal(await evaluate("document.querySelector('.ci-analyst textarea').disabled"), false, "usable again after cancel");
  holdAnalyst = false;
  // The browser abort either drops the intercepted request (CDP: Invalid InterceptionId) or, if the
  // response races in, the panel ignores it. Both are acceptable; record which happened.
  const late = await cdp("Fetch.fulfillRequest", { requestId: heldAnalyst, responseCode: 200, responseHeaders: [{ name: "Content-Type", value: "application/json" }],
    body: Buffer.from(JSON.stringify({ status: "answered", provider: "OpenRouter", model: "vendor/tool-model", rounds: 1, tool_calls: 0, answer: "LATE ANSWER", activity: [], visualizations: [] })).toString("base64") })
    .then(() => "delivered and ignored", (error) => /Invalid InterceptionId/.test(error.message) ? "dropped by the browser abort" : `unexpected: ${error.message}`);
  assert.ok(!late.startsWith("unexpected"), late);
  heldAnalyst = null;
  await sleep(500);
  assert.equal((await text(".ci-analyst")).includes("LATE ANSWER"), false, "a cancelled request's late answer is ignored");
  assert.match(await meterText(), /admitted of 8/, "dashboard intact after analyst errors");
  await screenshot("analyst-1440.png", true);
  passed(`analyst: sanitised inline errors; Stop waiting cancels the browser wait honestly (late response ${late}); dashboard intact`);
  analystStatus = { available: false, status: "disabled", provider: "OpenRouter", model: null };

  // ---- 5. Error, unavailable, empty, not found -------------------------------------------------
  await visit(pathOf(BROKEN));
  await until(() => evaluate("!!document.querySelector('.ci-error [role=alert]')"), "error state");
  assert.match(await text(".ci-error"), /could not be loaded\. Nothing was changed/);
  await visit(pathOf(INVALID));
  await until(() => evaluate("!!document.querySelector('.ci-unavailable')"), "unavailable state");
  assert.match(await text(".ci-unavailable"), /cannot evaluate the saved terms: fee estimate is required before preview/);
  await visit(pathOf(EMPTY));
  await until(() => evaluate("!!document.querySelector('.ci-empty')"), "empty state");
  assert.match(await text(".ci-empty"), /No attendance curve/);
  await visit(pathOf("66666666-6666-4666-8666-666666666666"));
  await until(() => evaluate("!!document.querySelector('.ci-unavailable')"), "not found");
  assert.match(await text(".ci-unavailable"), /not found in your workspace/);
  failDetail = true;
  await visit(pathOf(PUBLISHED));
  await until(() => evaluate("!!document.querySelector('.ci-error')"), "transient error");
  failDetail = false;
  await evaluate("document.querySelector('.ci-error button').click()");
  await studioReady();
  assert.equal(await studioChunkLoaded(), true);
  passed("error (with recovery), unavailable (409), empty curve and not-found states");

  // ---- 6. Unauthorised -------------------------------------------------------------------------
  authMode = "anonymous";
  await visit(pathOf(PUBLISHED));
  await until(async () => (await pathname()) === `/host/login?returnTo=${encodeURIComponent(pathOf(PUBLISHED))}`, "anonymous redirect");
  await evaluate("document.querySelector('#host-identifier').focus()");
  await cdp("Input.insertText", { text: "fixture-host" });
  await evaluate("document.querySelector('#host-password').focus()");
  await cdp("Input.insertText", { text: "fixture-password" });
  await evaluate("document.querySelector('.login-card form').requestSubmit()");
  await until(async () => (await pathname()) === pathOf(PUBLISHED), "return to intelligence after login");
  await studioReady();
  passed("unauthenticated access redirects to login and returns to Campaign Intelligence");

  // ---- 7. Mobile, console page unaffected, diagnostics ------------------------------------------
  await viewport(390, 844);
  await visit(pathOf(PUBLISHED));
  await studioReady();
  const widths = await evaluate("({ viewport: innerWidth, content: document.documentElement.scrollWidth })");
  assert.ok(widths.content <= widths.viewport + 1, `mobile page has no horizontal scroll: ${JSON.stringify(widths)}`);
  await screenshot("intelligence-390.png");
  await viewport(1440);
  passed("mobile: page does not scroll horizontally");

  // Studio bundles AG Grid Enterprise for its own widgets. After visiting it, the Community-only console (same SPA
  // session, shared ag-grid-community instance) must not pick up enterprise features, a watermark or licence messages.
  const beforeConsole = consoleMessages.length;
  await evaluate("history.pushState(null, '', '/host/console'); dispatchEvent(new PopStateEvent('popstate'))");
  await until(() => evaluate("document.querySelectorAll('.console-grid .ag-row').length > 0"), "console grid after Studio");
  await sleep(1000);
  assert.deepEqual(consoleMessages.slice(beforeConsole).filter((m) => /AG Grid|licen[cs]e|watermark|enterprise/i.test(m)), [], "console page emits no licence/enterprise messages after Studio");
  assert.equal(await evaluate("!!document.querySelector('.console-grid .ag-watermark, .console-grid [class*=watermark]')"), false, "no watermark on the Community console");
  passed("after visiting Studio in the same session, the Community-only console shows no enterprise watermark or licence messages");

  assert.deepEqual(errors, [], "no uncaught exceptions");
  assert.deepEqual(externalRequests, [], "no requests leave the app origin (no model, PayPal, Channel3 or font calls)");
  assert.deepEqual(mutating(), []);
  const licenceLines = consoleMessages.filter((m) => /AG Studio Core License|License Key Not Found|unlocked for trial|hide the watermark|^error: \*+$|^error: \* +\*$/.test(m));
  const otherDiagnostics = consoleMessages.filter((m) => /AG Grid|AG Studio|ag-grid|ag-studio|warning|error/i.test(m) && !licenceLines.includes(m));
  assert.deepEqual(otherDiagnostics, [], "no AG Grid/Studio diagnostics other than the documented unlicensed notice");
  passed(`no uncaught errors, external requests or AG diagnostics${licenceLines.length ? " (only AG Studio's documented 'License Key Not Found' notice: no key configured)" : ""}`);
  console.log(`${checks} intelligence browser checks passed (${devMode ? "Vite dev server with Studio/Grid validations" : "production build"}). All API traffic was intercepted fixtures.`);
  console.log(`Screenshots: ${artifacts}`);
} finally {
  socket?.close();
  chrome?.kill("SIGTERM");
  server.kill("SIGTERM");
}
