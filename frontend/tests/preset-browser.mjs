import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import { access, mkdir, mkdtemp } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";

// Real click on the local-only "Sandbox: close in 15 minutes" preset.
// Vite runs in DEV mode (the only mode that renders the preset) on an isolated port.
// Every /api/* request is intercepted with fixtures: no backend, database or provider is touched.
const root = fileURLToPath(new URL("../", import.meta.url));
const chromePath = process.env.CHROME_PATH ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
await access(chromePath);
const artifacts = resolve(root, "node_modules/.tmp/preset-evidence");
await mkdir(artifacts, { recursive: true });
const profile = await mkdtemp(resolve(artifacts, "chrome-profile-"));
const base = "http://127.0.0.1:4176";
const server = spawn(process.execPath, [resolve(root, "node_modules/vite/bin/vite.js"), "--host", "127.0.0.1", "--port", "4176", "--strictPort"],
  { cwd: root, stdio: ["ignore", "pipe", "pipe"] });
let serverError = "";
server.stderr.on("data", (data) => { serverError += data; });
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
async function until(check, label, attempts = 150) {
  for (let i = 0; i < attempts; i++) { if (await check()) return; await sleep(100); }
  throw new Error(`Timed out: ${label}`);
}
let chrome, socket, checks = 0;
const passed = (message) => { checks++; console.log(`PASS ${message}`); };
try {
  await until(async () => {
    if (server.exitCode !== null) throw new Error(`Vite dev server exited: ${serverError}`);
    try { return (await fetch(base)).ok; } catch { return false; }
  }, "vite dev startup");
  chrome = spawn(chromePath, ["--headless", "--disable-gpu", "--disable-background-networking", "--disable-component-update", "--disable-sync",
    "--no-first-run", "--no-default-browser-check", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank"], { stdio: ["ignore", "ignore", "pipe"] });
  const endpoint = await new Promise((done, reject) => {
    let output = "";
    const timeout = setTimeout(() => reject(new Error("Chrome debugging endpoint unavailable")), 15000);
    chrome.stderr.on("data", (data) => { output += data; const match = output.match(/DevTools listening on (ws:\/\/[^\s]+)/); if (match) { clearTimeout(timeout); done(match[1]); } });
    chrome.on("exit", (code) => { clearTimeout(timeout); reject(new Error(`Chrome exited ${code}`)); });
  });
  socket = new WebSocket(endpoint);
  await new Promise((done, reject) => { socket.addEventListener("open", done, { once: true }); socket.addEventListener("error", reject, { once: true }); });
  let sequence = 0;
  const pending = new Map(), events = new Set();
  socket.addEventListener("message", ({ data }) => {
    const message = JSON.parse(data);
    if (message.id) { const p = pending.get(message.id); if (!p) return; pending.delete(message.id); message.error ? p.reject(new Error(message.error.message)) : p.done(message.result); }
    else for (const listener of events) listener(message);
  });
  const send = (method, params = {}, sessionId) => new Promise((done, reject) => {
    const id = ++sequence; pending.set(id, { done, reject });
    socket.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
  });
  const { targetInfos } = await send("Target.getTargets");
  const { sessionId } = await send("Target.attachToTarget", { targetId: targetInfos.find((t) => t.type === "page").targetId, flatten: true });
  const cdp = (method, params) => send(method, params, sessionId);
  await cdp("Page.enable"); await cdp("Runtime.enable");

  const workshopId = "55555555-5555-4555-8555-555555555555";
  const campaignId = "66666666-6666-4666-8666-666666666666";
  const fixture = { merchant: { merchant_id: "preset-host", name: "Preset fixture host" }, session_id: "s", csrf_token: "c", expires_at: "2099-01-01T00:00:00Z" };
  let workshop = null;
  const apiCalls = [], errors = [];
  const hash = () => createHash("sha256").update(JSON.stringify([workshop.financials, workshop.opens_at, workshop.closes_at])).digest("hex");
  const fromPayload = (payload, previous = {}) => ({ ...previous, workshop_id: workshopId, title: payload.title, description: payload.description,
    capacity: payload.financials.capacity, ticket_price_minor: payload.financials.ticket_price_minor, currency: "GBP", terms_version: 1,
    is_frozen: false, campaign_id: null, campaign: null, opens_at: payload.schedule.opens_at, closes_at: payload.schedule.closes_at,
    offer_stale_after_seconds: 3600, financials: { ...payload.financials, materials: payload.financials.materials.map((l) => ({ ...l, offer_provenance: null })) } });
  const point = { attendance: 1, packs_by_material: {}, material_cost_minor: 0, required_budget_minor: 0, gross_minor: 100,
    estimated_fees_minor: 50, estimated_net_minor: 50, estimated_surplus_minor: 50, is_viable: true };
  events.add((event) => {
    if (event.method === "Runtime.exceptionThrown") errors.push(event.params.exceptionDetails.text);
    if (event.method !== "Fetch.requestPaused") return;
    const { requestId, request } = event.params;
    const path = new URL(request.url).pathname;
    apiCalls.push({ path, method: request.method, body: request.postData });
    let code = 503, body = { detail: "unexpected test API request" };
    if (path === "/api/me") { code = 200; body = fixture; }
    if (path === "/api/auth/csrf") { code = 200; body = { csrf_token: "c" }; }
    if (path === "/api/merchant/workshops") {
      code = 200; body = workshop ? [workshop] : [];
      if (request.method === "POST") { workshop = fromPayload(JSON.parse(request.postData)); workshop.terms_snapshot_hash = hash(); code = 201; body = workshop; }
    }
    if (path === `/api/merchant/workshops/${workshopId}`) {
      code = 200; body = workshop;
      if (request.method === "PATCH") { workshop = fromPayload(JSON.parse(request.postData), workshop); workshop.terms_snapshot_hash = hash(); body = workshop; }
    }
    if (path === `/api/merchant/workshops/${workshopId}/preview`) {
      code = 200; body = { algorithm_version: "preset-fixture", currency: "GBP", ticket_price_minor: 100, capacity: 1, minimum_operating_attendance: 1,
        first_viable_attendance: 1, any_viable_attendance: true, is_viable_at_capacity: true, attendance_curve: [point],
        materials_note: "Offline preset fixture.", terms_version: 1, terms_snapshot_hash: workshop.terms_snapshot_hash };
    }
    if (path === `/api/merchant/workshops/${workshopId}/publish`) {
      const campaign = { campaign_id: campaignId, workshop_id: workshopId, status: "OPEN", capacity: 1, cutoff_at: workshop.closes_at,
        terms_version: 1, terms_id: "77777777-7777-4777-8777-777777777777", terms_snapshot_hash: workshop.terms_snapshot_hash };
      workshop = { ...workshop, is_frozen: true, campaign_id: campaignId, campaign }; code = 201; body = campaign;
    }
    if (path === `/api/workshops/${workshopId}` && workshop?.is_frozen) {
      code = 200; body = { workshop_id: workshopId, campaign_id: campaignId, title: workshop.title, description: workshop.description,
        currency: "GBP", ticket_price_minor: 100, capacity: 1, opens_at: workshop.opens_at, cutoff_at: workshop.closes_at,
        publication_status: "OPEN", booking_window_status: "open", reservations_available: false, availability_note: "Fixture." };
    }
    void cdp("Fetch.fulfillRequest", { requestId, responseCode: code, responseHeaders: [{ name: "Content-Type", value: "application/json" }],
      body: Buffer.from(JSON.stringify(body)).toString("base64") }).catch((e) => errors.push(e.message));
  });
  await cdp("Fetch.enable", { patterns: [{ urlPattern: `${base}/api/*` }] });
  const evaluate = async (expression) => {
    const r = await cdp("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description ?? r.exceptionDetails.text);
    return r.result.value;
  };
  const click = async (selector) => { assert.ok(await evaluate(`!!document.querySelector(${JSON.stringify(selector)})`), `Missing ${selector}`); await evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`); await sleep(150); };
  const setField = async (label, value, scope = ".workbench") => { await evaluate(`(() => {
    const found = [...document.querySelector(${JSON.stringify(scope)}).querySelectorAll('label')].find((l) => l.textContent.trim().startsWith(${JSON.stringify(label)}));
    const input = found?.querySelector('input,textarea,select'); if (!input) throw new Error('Missing field ' + ${JSON.stringify(label)});
    if (input.type === 'checkbox') { if (input.checked !== ${JSON.stringify(value)}) input.click(); return; }
    Object.getOwnPropertyDescriptor(input.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, 'value').set.call(input, ${JSON.stringify(String(value))});
    input.dispatchEvent(new Event('input', { bubbles: true })); })()`); await sleep(120); };
  const dateInputs = () => evaluate("[...document.querySelectorAll('[data-section=basics] input[type=datetime-local]')].map((i) => i.value)");
  const instants = (values) => evaluate(`${JSON.stringify(values)}.map((v) => new Date(v).getTime())`);
  const summary = (section) => evaluate(`document.querySelector('[data-section=${section}] .schedule-summary')?.innerText ?? ''`);
  const londonText = (ms) => evaluate(`new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/London", year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit", timeZoneName: "short" }).format(new Date(${ms}))`);

  await cdp("Page.navigate", { url: `${base}/host/workshops/new` });
  await until(() => evaluate("!!document.querySelector('.workbench') && !!document.querySelector('[data-section=basics] input[type=datetime-local]')"), "new draft workbench");
  const [defaultOpen, defaultClose] = await instants(await dateInputs());
  // defaultDraft() reads Date.now() once per field, so the default gap may exceed 24 h by a millisecond or two.
  assert.ok(Math.abs(defaultClose - defaultOpen - 24 * 3600_000) <= 5, "ordinary default window is unchanged");
  assert.ok(await evaluate("!!document.querySelector('.sandbox-preset button')"), "preset is offered in local dev mode for a new draft");
  assert.equal(await evaluate("document.querySelector('.sandbox-preset button').innerText"), "Sandbox: close in 15 minutes");
  assert.match(await summary("basics"), /Closes tomorrow at/);
  passed("dev-mode new draft shows the preset; defaults are the unchanged 25-hour policy");

  await sleep(1500); // ensure click time is clearly distinct from page-load time
  const before = await evaluate("Date.now()");
  await click(".sandbox-preset button");
  const after = await evaluate("Date.now()");
  const presetValues = await dateInputs();
  const [opens, closes] = await instants(presetValues);
  const clicked = opens + 60_000;
  assert.equal(closes - opens, 16 * 60_000, "cutoff is 16 minutes after opening");
  assert.ok(clicked >= before && clicked <= after, `click instant ${clicked} within [${before}, ${after}]`);
  assert.ok(clicked - (defaultOpen - 3600_000) >= 1500, "preset uses click time, not page/module load time");
  assert.equal(closes, clicked + 15 * 60_000);
  const basicsSummary = await summary("basics");
  assert.match(basicsSummary, /Opened today at \d{2}:\d{2}:\d{2} (GMT|BST)/);
  assert.match(basicsSummary, /Closes today at \d{2}:\d{2}:\d{2} (GMT|BST)/);
  assert.ok(basicsSummary.includes(await londonText(closes)), "summary shows the exact cutoff timestamp");
  assert.match(basicsSummary, /Booking window duration\s*16 min/);
  assert.match(basicsSummary, /1[45] min( \d+ s)? until cutoff/);
  passed("click sets opening = click − 1 min, cutoff = click + 15 min; inputs and summary update");

  await setField("Workshop title", "Preset fixture workshop");
  await setField("Ticket price", "1.00");
  for (const tab of [2, 3, 4, 1, 4, 1]) { await click(`.workbench-tabs button:nth-child(${tab})`); }
  await sleep(16_000); // the summary clock ticks every 15 s; it must not touch the draft
  assert.deepEqual(await dateInputs(), presetValues, "unrelated edits, tab changes and clock ticks keep preset dates");
  assert.match(await summary("basics"), /1[34] min( \d+ s)? until cutoff/);
  passed("unrelated edits, tab changes and the summary clock do not restore default dates");

  await click(".workbench .host-page-heading .host-button");
  await until(() => evaluate(`location.pathname.endsWith('${workshopId}')`), "draft created");
  const create = apiCalls.filter((c) => c.path === "/api/merchant/workshops" && c.method === "POST").at(-1);
  const sent = JSON.parse(create.body).schedule;
  assert.deepEqual([Date.parse(sent.opens_at), Date.parse(sent.closes_at)], [opens, closes], "create request carries the exact preset instants");
  assert.deepEqual([sent.opens_at, sent.closes_at], [new Date(opens).toISOString(), new Date(closes).toISOString()]);
  await until(async () => JSON.stringify(await dateInputs()) === JSON.stringify(presetValues), "reloaded detail restores the same editor values");
  passed("create request contains the exact timestamps; persisted draft reloads the same editor values");

  await click(".workbench-tabs button:nth-child(4)");
  const reviewSummary = await summary("review");
  assert.ok(reviewSummary.includes(await londonText(closes)) && reviewSummary.includes(await londonText(opens)), "review summary shows saved dates");
  assert.match(reviewSummary, /Closes today at/);
  await click("[data-section=review] > button:first-of-type");
  await until(() => evaluate("!document.querySelector('[data-section=review] .host-check input').disabled"), "preview permits acknowledgement");
  await setField("I have reviewed", true, "[data-section=review]");
  await click("[data-section=review] > button:last-of-type");
  await until(() => evaluate("!!document.querySelector('.published-reference')"), "fixture publication");
  assert.equal(Date.parse(workshop.campaign.cutoff_at), closes);
  assert.equal(await evaluate("!!document.querySelector('.sandbox-preset')"), false, "preset is not offered once terms are frozen");
  assert.deepEqual(await dateInputs(), presetValues);
  await click(".published-reference > a");
  await until(() => evaluate("!!document.querySelector('.real-detail-page')"), "public detail");
  const publicText = await evaluate("document.querySelector('main').innerText");
  assert.ok(publicText.includes(await londonText(closes)), "public projection shows the saved cutoff");
  assert.ok(publicText.includes(await londonText(opens)), "public projection shows the saved opening");
  passed("review, fixture publication and public projection retain the preset dates; preset hidden after freeze");

  const writes = apiCalls.filter((c) => ["POST", "PATCH"].includes(c.method)).map((c) => c.path);
  assert.deepEqual(writes, ["/api/merchant/workshops", `/api/merchant/workshops/${workshopId}/preview`, `/api/merchant/workshops/${workshopId}/publish`],
    "preset itself sends nothing; only explicit save, preview and publish clicks write");
  assert.deepEqual(errors, []);
  passed("the preset click alone makes no request; no uncaught browser errors");
  console.log(`${checks} preset browser checks passed. All API traffic was intercepted fixtures; dev-mode Vite on :4176.`);
} finally {
  socket?.close(); chrome?.kill("SIGKILL"); server.kill("SIGTERM");
}
