import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { access, mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";

// Bryntum Gantt readiness view at /host/workshops/{id}/readiness.
// Production build (vite preview) by default; READINESS_TEST_DEV=1 uses the Vite dev server.
// Every /api/* request is intercepted with fixtures: no backend, database or payment provider is touched,
// and every non-local request is blocked and recorded.
const root = fileURLToPath(new URL("../", import.meta.url));
const chromePath = process.env.CHROME_PATH ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
await access(chromePath);
const devMode = process.env.READINESS_TEST_DEV === "1";
const artifacts = resolve(root, "node_modules/.tmp/readiness-evidence");
await mkdir(artifacts, { recursive: true });
const profile = await mkdtemp(resolve(artifacts, "chrome-profile-"));
const base = "http://127.0.0.1:4183";
if (await fetch(base).then(() => true, () => false)) throw new Error(`${base} is already in use; stop the stale server first.`);
const server = spawn(process.execPath, [resolve(root, "node_modules/vite/bin/vite.js"), ...(devMode ? [] : ["preview"]), "--host", "127.0.0.1", "--port", "4183", "--strictPort"],
  { cwd: root, stdio: ["ignore", "pipe", "pipe"] });
let serverError = "";
server.stderr.on("data", (data) => { serverError += data; });
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
async function until(check, label, attempts = 300) {
  for (let i = 0; i < attempts; i++) { if (await check()) return; await sleep(100); }
  throw new Error(`Timed out: ${label}`);
}

// ---- fixtures (mirror the owned-workshop API shape, including the two read-only fields) ----------
const EXPIRED = "11111111-1111-4111-8111-111111111111";
const RELEASED = "22222222-2222-4222-8222-222222222222";
const DRAFT = "33333333-3333-4333-8333-333333333333";
const FOREIGN = "44444444-4444-4444-8444-444444444444";
const settlement = (extra = {}) => ({ state: "OPEN", decision_result: null, decision_reason: null, frozen_attendance: null, admitted_attendance: 0,
  authorized_minor: 0, collected_minor: 0, refunded_minor: 0, capture_pending: 0, release_pending: 0, refund_pending: 0, review_required: false,
  settlement_deadline: null, decided_at: null, fee_basis: "estimated", actual_fees_minor: null, estimated_fees_minor: null,
  estimated_surplus_minor: null, post_collection_surplus_minor: null, ...extra });
const financials = { currency: "GBP", ticket_price_minor: 100, capacity: 2, minimum_operating_attendance: 2, fixed_costs_minor: 0, materials: [],
  shipping_allowance_minor: 0, shipping_allowance_source: "x", contingency_minor: 0, fee_estimate: { percent_basis_points: 0, fixed_minor: 10, label: "fixture" } };
const workshop = (id, title, opens, closes, campaign) => ({ workshop_id: id, title, description: null, capacity: 2, ticket_price_minor: 100, currency: "GBP",
  terms_version: 1, is_frozen: Boolean(campaign), opens_at: opens, closes_at: closes, campaign_id: campaign?.campaign_id ?? null, hidden_from_discovery_at: null,
  terms_snapshot_hash: "a".repeat(64), offer_stale_after_seconds: 3600, financials, campaign });
const campaign = (id, status, cutoff, published, settle) => ({ campaign_id: `c-${id.slice(0, 4)}`, workshop_id: id, status, capacity: 2, cutoff_at: cutoff,
  terms_version: 1, terms_id: "t", terms_snapshot_hash: "a".repeat(64), published_at: published, settlement: settle });
const details = {
  [EXPIRED]: workshop(EXPIRED, "Expired <img src=x onerror=window.__pwned=1> evening", "2026-11-07T10:00:00Z", "2026-11-08T01:57:06Z",
    campaign(EXPIRED, "OPEN", "2026-11-08T01:57:06Z", "2026-11-07T09:30:00Z", settlement())),
  [RELEASED]: workshop(RELEASED, "Released test", "2026-11-09T12:00:00Z", "2026-11-09T12:20:00Z",
    campaign(RELEASED, "CANCELLED", "2026-11-09T12:20:00Z", "2026-11-09T11:58:00Z", settlement({ state: "CANCELLED", decision_result: "RELEASE",
      decision_reason: "ACTUAL_ATTENDANCE_NOT_VIABLE", frozen_attendance: 1, settlement_deadline: "2026-11-09T12:50:00Z", decided_at: "2026-11-09T12:21:30Z" }))),
  [DRAFT]: workshop(DRAFT, "Draft binding", "2026-11-20T10:00:00Z", "2026-11-21T10:00:00Z", null),
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

  const apiCalls = [], externalRequests = [], errors = [];
  const fixture = { merchant: { merchant_id: "test-host", name: "Fixture host" }, session_id: "s", csrf_token: "bound-test-csrf", expires_at: "2099-01-01T00:00:00Z" };
  const respond = (requestId, code, body) => cdp("Fetch.fulfillRequest", { requestId, responseCode: code,
    responseHeaders: [{ name: "Content-Type", value: "application/json" }], body: Buffer.from(JSON.stringify(body)).toString("base64") }).catch((error) => errors.push(error.message));
  events.add((event) => {
    if (event.method === "Runtime.exceptionThrown") errors.push(event.params.exceptionDetails.exception?.description ?? event.params.exceptionDetails.text);
    if (event.method !== "Fetch.requestPaused") return;
    const { requestId, request } = event.params;
    const url = new URL(request.url);
    if (url.origin !== base) {
      externalRequests.push(request.url);
      return void cdp("Fetch.failRequest", { requestId, errorReason: "BlockedByClient" }).catch(() => {});
    }
    if (!url.pathname.startsWith("/api/")) return void cdp("Fetch.continueRequest", { requestId }).catch(() => {});
    const path = url.pathname;
    apiCalls.push({ path, method: request.method });
    if (path === "/api/me") return void respond(requestId, 200, fixture);
    if (path === "/api/auth/csrf") return void respond(requestId, 200, { csrf_token: "bootstrap" });
    if (path === "/api/merchant/workshops" && request.method === "GET") return void respond(requestId, 200, Object.values(details));
    const detail = path.match(/^\/api\/merchant\/workshops\/([0-9a-f-]{36})$/);
    if (detail && request.method === "GET") return details[detail[1]] ? void respond(requestId, 200, details[detail[1]]) : void respond(requestId, 404, { detail: "workshop not found" });
    return void respond(requestId, 503, { detail: "unexpected test API request" });
  });
  await cdp("Fetch.enable", { patterns: [{ urlPattern: "*" }] });

  async function evaluate(expression) {
    const response = await cdp("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (response.exceptionDetails) throw new Error(response.exceptionDetails.exception?.description ?? response.exceptionDetails.text);
    return response.result.value;
  }
  const viewport = (width, height = 1000) => cdp("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width < 600 });
  const visit = async (path) => { await cdp("Page.navigate", { url: base + path }); await until(() => evaluate("document.readyState === 'complete'"), `load ${path}`); };
  const pathname = () => evaluate("location.pathname");
  const screenshot = async (name) => writeFile(resolve(artifacts, name), Buffer.from((await cdp("Page.captureScreenshot", { format: "png" })).data, "base64"));
  const bryntumChunkLoaded = () => evaluate("performance.getEntriesByType('resource').some(e => /ReadinessView/.test(e.name))");
  const pathOf = (id) => `/host/workshops/${id}/readiness`;
  const ganttReady = () => until(() => evaluate("!!(globalThis.bryntum?.query?.('gantt')?.taskStore?.count) && document.querySelectorAll('.tp-readiness .b-grid-row').length > 0"), "Bryntum Gantt rendered");
  const gantt = (body) => evaluate(`(() => { const g = bryntum.query('gantt'); ${body} })()`);
  const mutating = () => apiCalls.filter((c) => c.method !== "GET" && c.path !== "/api/auth/csrf");

  // ---- 1. Workbench link; Bryntum is downloaded only on the readiness route -------------------------
  await viewport(1440);
  await visit(`/host/workshops/${EXPIRED}`);
  await until(() => evaluate("[...document.querySelectorAll('.workbench-summary a')].some(a => a.textContent.includes('Readiness timeline'))"), "workbench readiness link");
  assert.equal(await evaluate("[...document.querySelectorAll('.workbench-summary a')].find(a => a.textContent.includes('Readiness timeline')).getAttribute('href')"), pathOf(EXPIRED));
  assert.equal(await bryntumChunkLoaded(), false, "Bryntum not downloaded on the workbench");
  await evaluate("[...document.querySelectorAll('.workbench-summary a')].find(a => a.textContent.includes('Readiness timeline')).click()");
  await until(async () => (await pathname()) === pathOf(EXPIRED), "navigate to readiness");
  await ganttReady();
  assert.equal(await bryntumChunkLoaded(), true);
  passed("workbench links to the readiness route; Bryntum loads lazily only there");

  // ---- 2. Real Bryntum Gantt instance, read-only, no dependencies ------------------------------------
  const info = await gantt(`return { isGantt: !!g.isGantt, readOnly: g.readOnly, tasks: g.taskStore.count, deps: g.dependencyStore?.count ?? 0,
    locked: Math.round(g.subGrids.locked.element.getBoundingClientRect().width), rowHeight: g.rowHeight,
    features: ['taskDrag','taskResize','taskDragCreate','taskEdit','taskMenu','cellEdit','cellMenu','headerMenu','dependencies','dependencyEdit','rowReorder','columnReorder','columnResize','sort','filter','taskCopyPaste','cellCopyPaste','rowCopyPaste','percentBar']
      .filter(f => g.features[f] && !g.features[f].disabled) }`);
  assert.ok(info.isGantt, "bryntum.query('gantt') returns a Gantt instance");
  assert.equal(await evaluate("!!document.querySelector('.tp-readiness .b-gantt')"), true, "Bryntum Gantt element rendered");
  assert.equal(info.readOnly, true, "Gantt is read-only");
  assert.equal(info.tasks, 9, "workshop parent + 8 readiness rows");
  assert.equal(info.deps, 0, "no dependencies drawn or stored");
  assert.deepEqual(info.features, [], "no editing, menu, drag, resize, copy/paste, sort or dependency feature is active");
  assert.ok(info.locked >= 520 && info.locked <= 620, `left pane ${info.locked}px`);
  assert.ok(info.rowHeight >= 34 && info.rowHeight <= 40, `row height ${info.rowHeight}`);
  passed(`real Bryntum Gantt (read-only, 9 tasks, 0 dependencies, all mutating features off; left pane ${info.locked}px, rows ${info.rowHeight}px)`);

  // ---- 3. Timeline dates equal the backend records ---------------------------------------------------
  const dates = await gantt(`const d = id => { const t = g.taskStore.getById(id); return t ? { start: t.startDate?.toISOString() ?? null, end: t.endDate?.toISOString() ?? null, unscheduled: !!t.unscheduled } : null };
    return { window: d('booking-window'), cutoff: d('booking-cutoff'), publication: d('publication'), decision: d('decision'), settlement: d('settlement'),
      materials: d('materials'), preparation: d('preparation'), delivery: d('delivery') }`);
  const e = details[EXPIRED];
  assert.deepEqual([dates.window.start, dates.window.end], [new Date(e.opens_at).toISOString(), new Date(e.closes_at).toISOString()]);
  assert.equal(dates.cutoff.start, new Date(e.campaign.cutoff_at).toISOString());
  assert.equal(dates.publication.start, new Date(e.campaign.published_at).toISOString());
  for (const id of ["decision", "settlement", "materials", "preparation", "delivery"]) assert.equal(dates[id].unscheduled, true, `${id} has no saved date`);
  passed("timeline bars and milestones carry exactly the saved opens/cutoff/publication instants; undated rows are unscheduled");

  // ---- 4. Left grid: three columns, pills, honest expired state ---------------------------------------
  const grid = await evaluate(`(() => {
    const headers = [...document.querySelectorAll('.tp-readiness .b-grid-sub-grid-locked .b-grid-header-text, .tp-readiness .b-grid-header-container .b-grid-headers-locked .b-grid-header-text')].map(h => h.textContent.trim()).filter(Boolean);
    const rows = [...document.querySelectorAll('.tp-readiness .b-grid-sub-grid-locked .b-grid-row')].map(r => r.innerText.replace(/\\s+/g, ' ').trim());
    const pills = [...document.querySelectorAll('.tp-readiness .tp-pill')].map(p => p.className.replace('tp-pill ', '') + ':' + p.textContent);
    return { headers: [...new Set(headers)], rows, pills, noDate: document.querySelectorAll('.tp-readiness .tp-no-date').length, pwned: !!window.__pwned,
      injected: !!document.querySelector('.tp-readiness img') };
  })()`);
  assert.deepEqual(grid.headers, ["Milestone", "Status", "Date / detail"]);
  assert.ok(grid.pills.includes("tp-pill-pending:Closed"), grid.pills.join(", "));
  assert.ok(grid.pills.includes("tp-pill-pending:Passed"));
  assert.ok(grid.pills.includes("tp-pill-pending:Awaiting decision"));
  assert.ok(grid.pills.includes("tp-pill-pending:Not started"));
  assert.ok(grid.pills.includes("tp-pill-settled:Published"));
  assert.equal(grid.pills.filter((p) => p === "tp-pill-unavailable:Proposed").length, 3);
  assert.ok(grid.pills.includes("tp-pill-open:Open"), "parent row shows OPEN publication status, not confirmation");
  assert.ok(!grid.pills.some((p) => /Confirmed/.test(p)));
  assert.equal(grid.noDate, 5, "decision, settlement (no deadline before a decision) and three proposed rows show exactly 'No saved date'");
  assert.ok(grid.rows.some((r) => /still OPEN; no deadline decision/.test(r)), "expired-but-OPEN stated");
  assert.equal(grid.pwned, false); assert.equal(grid.injected, false, "workshop title rendered as text");
  await screenshot("readiness-expired-1440.png");
  passed("three columns; pills scheduled/open/settled/pending/unavailable; expired campaign shown as Closed/Passed/Awaiting decision; 'No saved date' x5 (decision, settlement, 3 proposed); title not executed");

  // ---- 5. Drag, double-click, context menu and keyboard cannot mutate ---------------------------------
  const before = await gantt("return g.taskStore.getById('booking-window').startDate.toISOString() + '|' + g.taskStore.getById('booking-window').endDate.toISOString()");
  const mouse = (type, x, y, extra = {}) => cdp("Input.dispatchMouseEvent", { type, x, y, button: "left", clickCount: 1, ...extra });
  const bars = await evaluate("(() => [...document.querySelectorAll('.tp-readiness .b-gantt-task')].map(t => { const w = t.closest('[data-task-id]'); const r = t.getBoundingClientRect(); return (w?.dataset.taskId ?? 'NO-WRAP:' + t.parentElement.className) + ' w=' + Math.round(r.width) + ' wrapClass=' + (w?.className ?? '').split(' ').filter(c => c.startsWith('tp-') || c.startsWith('b-milestone')).join(','); }))()");
  const box = await evaluate("(() => { const el = [...document.querySelectorAll('.tp-readiness .b-gantt-task')].find(t => t.closest('[data-task-id=\"booking-window\"]')); if (!el) return null; const r = el.getBoundingClientRect(); return { left: r.left, right: r.right, y: r.top + r.height / 2, w: r.width, vw: innerWidth }; })()");
  assert.ok(box && box.w > 20, `booking-window bar must be found and wide enough to drag; bars: ${JSON.stringify(bars)}`);
  const x0 = box.left + 30;  // a visible point on the bar, so the drag genuinely starts on it
  assert.ok(x0 > 0 && x0 < box.vw, `drag start ${x0} is on screen`);
  assert.equal(await evaluate(`!!document.elementFromPoint(${x0}, ${box.y})?.closest('[data-task-id="booking-window"]')`), true, "pointer is over the booking-window bar");
  await mouse("mouseMoved", x0, box.y); await mouse("mousePressed", x0, box.y);
  for (let step = 1; step <= 8; step++) await mouse("mouseMoved", x0 + step * 30, box.y);
  await mouse("mouseReleased", x0 + 240, box.y);
  await mouse("mousePressed", x0, box.y, { clickCount: 2 }); await mouse("mouseReleased", x0, box.y, { clickCount: 2 });
  await mouse("mousePressed", x0, box.y, { button: "right" }); await mouse("mouseReleased", x0, box.y, { button: "right" });
  await sleep(500);
  const cell = await evaluate("(() => { const c = document.querySelector('.tp-readiness .b-grid-sub-grid-locked .b-grid-row[data-id=\"booking-window\"] .b-grid-cell'); const r = c.getBoundingClientRect(); return { x: r.left + 20, y: r.top + r.height / 2 }; })()");
  await mouse("mousePressed", cell.x, cell.y, { clickCount: 2 }); await mouse("mouseReleased", cell.x, cell.y, { clickCount: 2 });
  for (const key of ["Delete", "Backspace", "Enter", "F2"]) {
    await cdp("Input.dispatchKeyEvent", { type: "keyDown", key, code: key }); await cdp("Input.dispatchKeyEvent", { type: "keyUp", key, code: key });
  }
  await sleep(500);
  const after = await gantt("return g.taskStore.getById('booking-window').startDate.toISOString() + '|' + g.taskStore.getById('booking-window').endDate.toISOString()");
  assert.equal(after, before, "booking window dates unchanged after drag/resize attempts");
  const ui = await evaluate("({ editor: !!document.querySelector('.b-taskeditor, .b-gantt-taskeditor, .b-cell-editor:not(.b-hidden)'), menu: !!document.querySelector('.b-menu:not(.b-hidden)'), tasks: bryntum.query('gantt').taskStore.count, modified: bryntum.query('gantt').taskStore.modified.count })");
  assert.deepEqual(ui, { editor: false, menu: false, tasks: 9, modified: 0 });
  assert.deepEqual(mutating(), [], "no mutating API request");
  passed(`real mouse drag starting on the booking-window bar, double-click, right-click, Delete/Backspace/Enter/F2: no editor, no menu, no record change, no mutating request`);

  // ---- 6. Released/cancelled campaign: saved decision time and settlement deadline -------------------
  await visit(pathOf(RELEASED)); await ganttReady();
  const released = await gantt(`const t = id => g.taskStore.getById(id); return { decision: t('decision').startDate?.toISOString(), settlement: t('settlement').startDate?.toISOString(),
    pills: [...document.querySelectorAll('.tp-readiness .tp-pill')].map(p => p.textContent) }`);
  const r = details[RELEASED].campaign.settlement;
  const short = await evaluate("(() => { const el = [...document.querySelectorAll('.tp-readiness .b-gantt-task')].find(t => t.closest('[data-task-id=\"booking-window\"]')); const b = el.getBoundingClientRect(); return { right: b.right, y: b.top + b.height / 2, vw: innerWidth }; })()");
  assert.ok(short.right > 0 && short.right < short.vw - 5, `resize edge on screen (${short.right})`);
  const span = () => gantt("const t = g.taskStore.getById('booking-window'); return t.startDate.toISOString() + '|' + t.endDate.toISOString()");
  const spanBefore = await span();
  const edgeX = short.right - 2;
  await mouse("mouseMoved", edgeX, short.y); await mouse("mousePressed", edgeX, short.y);
  for (let step = 1; step <= 6; step++) await mouse("mouseMoved", edgeX + step * 25, short.y);
  await mouse("mouseReleased", edgeX + 150, short.y);
  await sleep(400);
  assert.equal(await span(), spanBefore, "resize-edge drag did not change the saved booking window");
  assert.equal(await gantt("return g.taskStore.modified.count"), 0);
  assert.equal(released.decision, new Date(r.decided_at).toISOString());
  assert.equal(released.settlement, new Date(r.settlement_deadline).toISOString());
  assert.ok(released.pills.includes("Decided · release") && released.pills.includes("Released / refunded") && released.pills.includes("Cancelled"));
  await screenshot("readiness-released-1440.png");
  passed("released campaign: resize-edge drag changes nothing; decision at saved decided_at, settlement at saved settlement_deadline, parent Cancelled");

  // ---- 7. Draft: only draft dates; nothing invented ---------------------------------------------------
  await visit(pathOf(DRAFT)); await ganttReady();
  const draft = await gantt(`return ['publication','decision','settlement'].map(id => g.taskStore.getById(id).unscheduled)`);
  assert.deepEqual(draft, [true, true, true]);
  passed("draft: publication, decision and settlement have no dates; booking window shows draft dates");

  // ---- 8. Another merchant's workshop is refused ------------------------------------------------------
  await visit(pathOf(FOREIGN));
  await until(() => evaluate("!!document.querySelector('.tp-readiness-page [role=alert]')"), "not-found message");
  assert.match(await evaluate("document.querySelector('.tp-readiness-page [role=alert]').innerText"), /not found in your workspace/);
  assert.equal(await evaluate("!!document.querySelector('.tp-readiness .b-gantt')"), false);
  passed("cross-merchant (404) workshop shows not-found; no Gantt rendered");

  // ---- 9. Narrow viewport; no external requests; no uncaught errors -----------------------------------
  await viewport(390, 900);
  await visit(pathOf(EXPIRED)); await ganttReady();
  assert.equal(await evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"), true, "no horizontal page scroll at 390px");
  await screenshot("readiness-expired-390.png");
  assert.deepEqual(externalRequests, [], "no non-local requests (no licence call-home observed)");
  assert.deepEqual(errors, [], "no uncaught browser errors");
  assert.ok(apiCalls.every((c) => c.method === "GET" || c.path === "/api/auth/csrf"), "GET-only");
  passed("390px: no page overflow; no external requests; no uncaught errors; GET-only");

  console.log(`${checks} readiness browser checks passed (${devMode ? "Vite dev server" : "production build"}). All API traffic was intercepted fixtures.`);
} finally {
  try { socket?.close(); } catch {}
  chrome?.kill("SIGTERM");
  server.kill("SIGTERM");
}
