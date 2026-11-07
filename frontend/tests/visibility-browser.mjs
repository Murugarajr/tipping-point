import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import { access, mkdir, mkdtemp } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";

// Real clicks on Hide from discovery / Restore visibility in the host list, workbench and public pages.
// Vite dev server on an isolated port.
// Every /api/* request is intercepted with fixtures: no backend, database or provider is touched.
const root = fileURLToPath(new URL("../", import.meta.url));
const chromePath = process.env.CHROME_PATH ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
await access(chromePath);
const artifacts = resolve(root, "node_modules/.tmp/visibility-evidence");
await mkdir(artifacts, { recursive: true });
const profile = await mkdtemp(resolve(artifacts, "chrome-profile-"));
const base = "http://127.0.0.1:4177";
const server = spawn(process.execPath, [resolve(root, "node_modules/vite/bin/vite.js"), "--host", "127.0.0.1", "--port", "4177", "--strictPort"],
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

  const published = "11111111-1111-4111-8111-111111111111", draft = "22222222-2222-4222-8222-222222222222";
  const campaignId = "33333333-3333-4333-8333-333333333333";
  const fixture = { merchant: { merchant_id: "visibility-host", name: "Visibility fixture host" }, session_id: "s", csrf_token: "c", expires_at: "2099-01-01T00:00:00Z" };
  const opens = "2026-11-07T20:00:00.000Z", closes = "2099-11-08T20:00:00.000Z";
  const base_ = (id, title, frozen) => ({ workshop_id: id, title, description: `${title} description`, capacity: 1, ticket_price_minor: 100,
    currency: "GBP", terms_version: 1, is_frozen: frozen, campaign_id: frozen ? campaignId : null, opens_at: opens, closes_at: closes,
    hidden_from_discovery_at: null });
  const store = { [published]: base_(published, "Published fixture workshop", true), [draft]: base_(draft, "Draft fixture workshop", false) };
  const detail = (id) => ({ ...store[id], terms_snapshot_hash: "a".repeat(64), offer_stale_after_seconds: 3600,
    financials: { currency: "GBP", ticket_price_minor: 100, capacity: 1, minimum_operating_attendance: 1, fixed_costs_minor: 0, materials: [],
      shipping_allowance_minor: 0, shipping_allowance_source: "merchant-entered estimate", contingency_minor: 0,
      fee_estimate: { percent_basis_points: 0, fixed_minor: 0, label: "fixture" } },
    campaign: store[id].is_frozen ? { campaign_id: campaignId, workshop_id: id, status: "OPEN", capacity: 1, cutoff_at: closes, terms_version: 1,
      terms_id: "44444444-4444-4444-8444-444444444444", terms_snapshot_hash: "a".repeat(64), settlement: null } : null });
  const publicItem = (id) => ({ workshop_id: id, campaign_id: campaignId, title: store[id].title, description: store[id].description, currency: "GBP",
    ticket_price_minor: 100, capacity: 1, opens_at: opens, cutoff_at: closes, publication_status: "OPEN", booking_window_status: "open",
    reservations_available: false, availability_reason: "payment_unconfigured", availability_note: "Fixture." });
  const apiCalls = [], errors = [];
  let clock = Date.parse("2026-11-07T22:00:00Z");
  events.add((event) => {
    if (event.method === "Runtime.exceptionThrown") errors.push(event.params.exceptionDetails.text);
    if (event.method !== "Fetch.requestPaused") return;
    const { requestId, request } = event.params;
    const url = new URL(request.url), path = url.pathname;
    apiCalls.push({ path, query: url.search, method: request.method, csrf: request.headers["X-CSRF-Token"] ?? request.headers["x-csrf-token"] });
    let code = 503, body = { detail: "unexpected test API request" };
    const match = path.match(/^\/api\/merchant\/workshops\/([0-9a-f-]{36})(?:\/(hide-from-discovery|restore-visibility))?$/);
    if (path === "/api/me") { code = 200; body = fixture; }
    if (path === "/api/merchant/workshops" && request.method === "GET") {
      const view = url.searchParams.get("visibility") ?? "listed";
      code = 200; body = Object.values(store).filter((w) => view === "all" || (view === "hidden") === Boolean(w.hidden_from_discovery_at));
    }
    if (match && store[match[1]] && !match[2] && request.method === "GET") { code = 200; body = detail(match[1]); }
    if (match && store[match[1]] && match[2] && request.method === "POST") {
      const w = store[match[1]], hide = match[2] === "hide-from-discovery";
      const changed = Boolean(w.hidden_from_discovery_at) !== hide;
      if (changed) w.hidden_from_discovery_at = hide ? new Date(clock += 1000).toISOString() : null;
      code = 200; body = { workshop_id: w.workshop_id, hidden_from_discovery_at: w.hidden_from_discovery_at, changed };
    }
    if (path === "/api/workshops") { code = 200; body = Object.values(store).filter((w) => w.is_frozen && !w.hidden_from_discovery_at).map((w) => publicItem(w.workshop_id)); }
    if (path === `/api/workshops/${published}`) { code = 200; body = publicItem(published); }
    void cdp("Fetch.fulfillRequest", { requestId, responseCode: code, responseHeaders: [{ name: "Content-Type", value: "application/json" }],
      body: Buffer.from(JSON.stringify(body)).toString("base64") }).catch((e) => errors.push(e.message));
  });
  await cdp("Fetch.enable", { patterns: [{ urlPattern: `${base}/api/*` }] });
  const evaluate = async (expression) => {
    const r = await cdp("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description ?? r.exceptionDetails.text);
    return r.result.value;
  };
  const q = JSON.stringify;
  const rowSelector = (title) => `[...document.querySelectorAll('.host-workshop-row')].find((r) => r.querySelector('h2')?.textContent === ${q(title)})`;
  const rowTitles = () => evaluate("[...document.querySelectorAll('.host-workshop-row h2')].map((h) => h.textContent)");
  const inRow = (title, selector) => evaluate(`${rowSelector(title)}?.querySelector(${q(selector)})?.innerText ?? null`);
  const clickInRow = async (title, selector) => { assert.ok(await evaluate(`!!${rowSelector(title)}?.querySelector(${q(selector)})`), `Missing ${selector} in ${title}`); await evaluate(`${rowSelector(title)}.querySelector(${q(selector)}).click()`); await sleep(200); };
  const click = async (selector) => { assert.ok(await evaluate(`!!document.querySelector(${q(selector)})`), `Missing ${selector}`); await evaluate(`document.querySelector(${q(selector)}).click()`); await sleep(200); };
  const filter = async (label) => { await evaluate(`[...document.querySelectorAll('.host-filter button')].find((b) => b.textContent === ${q(label)}).click()`); await sleep(250); };
  const writes = () => apiCalls.filter((c) => c.method !== "GET");
  const PUB = "Published fixture workshop", DRAFT = "Draft fixture workshop";
  const EXPLANATION = "Hides this workshop from browsing. Existing links and bookings remain valid. This does not cancel the workshop or its payments.";

  await cdp("Page.navigate", { url: `${base}/host` });
  await until(() => evaluate("document.querySelectorAll('.host-workshop-row').length === 2"), "listed host workshops");
  assert.equal(apiCalls.find((c) => c.path === "/api/merchant/workshops").query, "?visibility=listed");
  assert.equal(await evaluate("document.querySelector('.host-filter button[aria-pressed=true]').textContent"), "Listed");
  assert.equal(await inRow(PUB, ".visibility-badge"), "Listed in public browsing");
  assert.equal(await inRow(DRAFT, ".visibility-badge"), "Listed in public browsing");
  passed("host list defaults to Listed and shows each workshop's visibility");

  await clickInRow(PUB, ".hide-from-discovery");
  assert.equal(await inRow(PUB, ".visibility-confirm p"), EXPLANATION);
  assert.match(await inRow(PUB, ".visibility-confirm"), /not a privacy or access-control setting/);
  assert.equal(writes().length, 0, "opening the confirmation sends nothing");
  await clickInRow(PUB, ".cancel-hide");
  assert.equal(await inRow(PUB, ".visibility-confirm"), null);
  assert.equal(writes().length, 0, "Keep listed sends nothing");
  passed("confirmation shows the exact explanation; cancelling sends nothing");

  await clickInRow(PUB, ".hide-from-discovery");
  await clickInRow(PUB, ".confirm-hide");
  await until(async () => !(await rowTitles()).includes(PUB), "hidden workshop leaves Listed");
  assert.deepEqual(writes().map((c) => [c.method, c.path, c.csrf]), [["POST", `/api/merchant/workshops/${published}/hide-from-discovery`, "c"]]);
  assert.match(await evaluate("document.querySelector('.host-notice.host-positive')?.innerText ?? ''"), /hidden from discovery\. Its link, bookings and payments are unchanged/);
  await filter("Hidden from discovery");
  await until(async () => (await rowTitles()).join() === PUB, "Hidden filter");
  assert.match(await inRow(PUB, ".visibility-badge"), /^Hidden from discovery since 7 Nov 2026, 22:00:01 GMT$/);
  assert.equal(await inRow(PUB, ".restore-visibility"), "Restore visibility");
  await filter("All");
  await until(async () => (await rowTitles()).length === 2, "All filter");
  passed("confirmed hide sends one CSRF-bound POST; the workshop moves to the Hidden filter with its timestamp");

  await cdp("Page.navigate", { url: `${base}/workshops` });
  await until(() => evaluate("!!document.querySelector('.published-collection') && !document.querySelector('.published-collection [role=status]')"), "public collection");
  assert.ok(!(await evaluate("document.querySelector('.published-collection').innerText")).includes(PUB), "public browsing omits the hidden workshop");
  await cdp("Page.navigate", { url: `${base}/workshops/${published}` });
  await until(() => evaluate("document.querySelector('main')?.innerText.includes(" + q(PUB) + ")"), "direct public link");
  passed("public browsing omits it while the direct public link still opens");

  await cdp("Page.navigate", { url: `${base}/host/workshops/${published}` });
  await until(() => evaluate("!!document.querySelector('.workbench-visibility .visibility-badge')"), "workbench visibility");
  assert.match(await evaluate("document.querySelector('.workbench-visibility .visibility-badge').innerText"), /^Hidden from discovery since/);
  await click(".workbench-visibility .restore-visibility");
  await until(() => evaluate("document.querySelector('.workbench-visibility .visibility-badge')?.innerText === 'Listed in public browsing'"), "workbench restore");
  assert.equal(await evaluate("document.querySelector('.workbench [role=status]:not(.visibility-badge)')?.innerText ?? ''").then((t) => /Unsaved/.test(t)), false, "visibility does not dirty the draft");
  await click(".workbench-visibility .hide-from-discovery");
  assert.equal(await evaluate("document.querySelector('.workbench-visibility .visibility-confirm p').innerText"), EXPLANATION);
  await click(".workbench-visibility .confirm-hide");
  await until(() => evaluate("/^Hidden from discovery since/.test(document.querySelector('.workbench-visibility .visibility-badge')?.innerText ?? '')"), "workbench hide");
  passed("workbench shows status and restores/hides with the same confirmation");

  assert.deepEqual(writes().map((c) => [c.method, c.path.replace(/.*\//, ""), c.csrf]), [
    ["POST", "hide-from-discovery", "c"], ["POST", "restore-visibility", "c"], ["POST", "hide-from-discovery", "c"]]);
  assert.ok(!apiCalls.some((c) => /\/(publish|preview|cancel|paypal|bookings)/.test(c.path) || c.method === "PATCH"), "no other writes");
  assert.deepEqual(errors, []);
  passed("only explicit visibility actions write; no edits, publication, booking or payment requests; no browser errors");
  console.log(`${checks} visibility browser checks passed. All API traffic was intercepted fixtures; dev-mode Vite on :4177.`);
} finally {
  socket?.close(); chrome?.kill("SIGKILL"); server.kill("SIGTERM");
}
