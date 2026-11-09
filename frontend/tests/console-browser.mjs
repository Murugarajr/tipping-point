import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { access, mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";

// Read-only AG Grid table view (/host/console) against the production build (vite preview).
// Run twice (see package.json): production build (vite preview), then CONSOLE_TEST_DEV=1 on the Vite dev server,
// where AG Grid's ValidationModule is registered. The production bundle logs "AG Grid: error #200" for a missing
// module; the dev build additionally logs deprecations/invalid options and shows a diagnostics overlay.
// Any "AG Grid:" console message or overlay fails the run.
// Uses installed Chrome + Node's WebSocket implementation; no package download.
// Every /api/* request is intercepted with fixtures: no backend, database or provider is touched.
const root = fileURLToPath(new URL("../", import.meta.url));
const chromePath = process.env.CHROME_PATH ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
await access(chromePath);
const artifacts = resolve(root, "node_modules/.tmp/console-evidence");
await mkdir(artifacts, { recursive: true });
const profile = await mkdtemp(resolve(artifacts, "chrome-profile-"));
const base = "http://127.0.0.1:4179";
const devMode = process.env.CONSOLE_TEST_DEV === "1";
// A server left on this port would answer instead of ours and silently test stale code: refuse to run.
if (await fetch(base).then(() => true, () => false)) throw new Error(`${base} is already in use; stop the stale server first.`);
const server = spawn(process.execPath, [resolve(root, "node_modules/vite/bin/vite.js"), ...(devMode ? [] : ["preview"]), "--host", "127.0.0.1", "--port", "4179", "--strictPort"],
  { cwd: root, stdio: ["ignore", "pipe", "pipe"] });
let serverError = "";
server.stderr.on("data", (data) => { serverError += data; });
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
async function until(check, label, attempts = 150) {
  for (let i = 0; i < attempts; i++) { if (await check()) return; await sleep(100); }
  throw new Error(`Timed out: ${label}`);
}

// ---- fixtures -------------------------------------------------------------------------------
const uuid = (n) => `${String(n).padStart(8, "0")}-0000-4000-8000-${String(n).padStart(12, "0")}`;
const DRAFT = uuid(1), DEMO_HIDDEN = uuid(2), BROKEN = uuid(3), NO_SETTLEMENT = uuid(4);
const fixtureWorkshops = () => {
  const list = [
    { id: DRAFT, title: "Zine binding draft", price: 0, frozen: false },
    { id: DEMO_HIDDEN, title: "Demo hidden workshop", price: 4500, frozen: true, hidden: "2026-11-08T11:24:40.329Z" },
    { id: BROKEN, title: "Broken detail workshop", price: 3000, frozen: true },
    { id: NO_SETTLEMENT, title: "Legacy schema workshop", price: 2500, frozen: true },
  ];
  for (let n = 5; n <= 12; n++) list.push({ id: uuid(n), title: `Pottery evening ${String(n).padStart(2, "0")}`, price: 1000 + n * 100, frozen: true });
  return list.map((w, i) => ({
    workshop_id: w.id, title: w.title, description: null, capacity: 8, ticket_price_minor: w.price, currency: "GBP",
    terms_version: 1, is_frozen: w.frozen, opens_at: `2026-11-${String(10 + i).padStart(2, "0")}T10:00:00Z`,
    closes_at: `2026-11-${String(12 + i).padStart(2, "0")}T09:00:00Z`, campaign_id: w.frozen ? `c-${w.id}` : null,
    hidden_from_discovery_at: w.hidden ?? null,
  }));
};
const detailFor = (w, i) => ({
  ...w, terms_snapshot_hash: "a".repeat(64), offer_stale_after_seconds: 3600, financials: { materials: [] },
  campaign: { campaign_id: w.campaign_id, workshop_id: w.workshop_id, status: i % 3 === 0 ? "CONFIRMED" : "OPEN", capacity: 10,
    cutoff_at: w.closes_at, terms_version: 1, terms_id: "t", terms_snapshot_hash: "a".repeat(64),
    settlement: w.workshop_id === NO_SETTLEMENT ? null : {
      state: "OPEN", decision_result: i % 3 === 0 ? "COLLECT" : null, decision_reason: null, frozen_attendance: null,
      admitted_attendance: i % 5, authorized_minor: 0, collected_minor: 0, refunded_minor: 0, capture_pending: 0,
      release_pending: 0, refund_pending: 0, review_required: false, settlement_deadline: i % 3 === 0 ? "2026-11-20T09:00:00Z" : null,
      fee_basis: "estimated", actual_fees_minor: null, estimated_fees_minor: null, estimated_surplus_minor: null, post_collection_surplus_minor: null,
    } },
});

let chrome, socket, checks = 0;
const passed = (message) => { checks++; console.log(`PASS ${message}`); };
try {
  await until(async () => {
    if (server.exitCode !== null) throw new Error(`Preview server exited: ${serverError}`);
    try { return (await fetch(base)).ok; } catch { return false; }
  }, "preview startup");
  chrome = spawn(chromePath, ["--headless", "--disable-gpu", "--disable-background-networking", "--disable-component-update", "--disable-sync",
    "--no-first-run", "--no-default-browser-check", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank"], { stdio: ["ignore", "ignore", "pipe"] });
  const endpoint = await new Promise((done, reject) => {
    let output = "";
    const timeout = setTimeout(() => reject(new Error("Chrome debugging endpoint unavailable")), 15000);
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
  const pending = new Map();
  const events = new Set();
  socket.addEventListener("message", ({ data }) => {
    const message = JSON.parse(data);
    if (message.id) {
      const promise = pending.get(message.id);
      if (!promise) return;
      pending.delete(message.id); clearTimeout(promise.timeout);
      if (message.error) promise.reject(new Error(message.error.message)); else promise.done(message.result);
    } else for (const listener of events) listener(message);
  });
  const send = (method, params = {}, sessionId) => new Promise((done, reject) => {
    const id = ++sequence;
    const timeout = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 30000);
    pending.set(id, { done, reject, timeout });
    socket.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
  });
  const { targetInfos } = await send("Target.getTargets");
  const { sessionId } = await send("Target.attachToTarget", { targetId: targetInfos.find((t) => t.type === "page").targetId, flatten: true });
  const cdp = (method, params) => send(method, params, sessionId);
  await cdp("Page.enable"); await cdp("Runtime.enable");

  // ---- API interception ---------------------------------------------------------------------
  let authMode = "authenticated";
  let listMode = "ok"; // ok | empty | error | unauthorized | hold
  let detailUnauthorized = false;
  let held = null;
  const workshops = fixtureWorkshops();
  const apiCalls = [];
  const errors = [];
  const consoleProblems = [];
  const allConsole = [];
  let overlaySeen = false;
  const fixture = { merchant: { merchant_id: "test-host", name: "Fixture host" }, session_id: "s", csrf_token: "bound-test-csrf", expires_at: "2099-01-01T00:00:00Z" };
  const respond = (requestId, code, body) => cdp("Fetch.fulfillRequest", { requestId, responseCode: code,
    responseHeaders: [{ name: "Content-Type", value: "application/json" }], body: Buffer.from(JSON.stringify(body)).toString("base64") })
    .catch((error) => errors.push(error.message));
  events.add((event) => {
    if (event.method === "Runtime.exceptionThrown") errors.push(event.params.exceptionDetails.text);
    if (event.method === "Runtime.consoleAPICalled") allConsole.push(event.params.args.map((a) => a.value ?? a.description).join(" "));
    if (event.method === "Runtime.consoleAPICalled" && ["error", "warning"].includes(event.params.type)) {
      consoleProblems.push(event.params.args.map((a) => a.value ?? a.description).join(" "));
    }
    if (event.method !== "Fetch.requestPaused") return;
    const { requestId, request } = event.params;
    const url = new URL(request.url);
    const path = url.pathname;
    apiCalls.push({ path, search: url.search, method: request.method });
    if (path === "/api/me") return void respond(requestId, authMode === "authenticated" ? 200 : 401, authMode === "authenticated" ? fixture : { detail: "authentication required" });
    if (path === "/api/auth/csrf") return void respond(requestId, 200, { csrf_token: "bootstrap" });
    if (path === "/api/merchant/login") { authMode = "authenticated"; return void respond(requestId, 200, fixture); }
    if (path === "/api/merchant/workshops" && request.method === "GET") {
      if (listMode === "hold") { held = requestId; return; }
      if (listMode === "error") return void respond(requestId, 503, { detail: "temporarily unavailable" });
      if (listMode === "unauthorized") return void respond(requestId, 401, { detail: "authentication required" });
      const visibility = url.searchParams.get("visibility");
      const rows = listMode === "empty" ? [] : workshops.filter((w) => visibility === "all" || (visibility === "hidden") === Boolean(w.hidden_from_discovery_at));
      return void respond(requestId, 200, rows);
    }
    const detailMatch = path.match(/^\/api\/merchant\/workshops\/([0-9a-f-]{36})$/);
    if (detailMatch && request.method === "GET") {
      if (detailUnauthorized) return void respond(requestId, 401, { detail: "authentication required" });
      const index = workshops.findIndex((w) => w.workshop_id === detailMatch[1]);
      if (detailMatch[1] === BROKEN) return void respond(requestId, 503, { detail: "temporarily unavailable" });
      if (index < 0) return void respond(requestId, 404, { detail: "workshop not found" });
      const w = workshops[index];
      return void respond(requestId, 200, w.campaign_id ? detailFor(w, index) : { ...detailFor(w, index), campaign: null });
    }
    return void respond(requestId, 503, { detail: "unexpected test API request" });
  });
  await cdp("Fetch.enable", { patterns: [{ urlPattern: `${base}/api/*` }] });

  // ---- helpers ------------------------------------------------------------------------------
  async function evaluate(expression) {
    const response = await cdp("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (response.exceptionDetails) throw new Error(response.exceptionDetails.exception?.description ?? response.exceptionDetails.text);
    return response.result.value;
  }
  const viewport = (width, height = 900) => cdp("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width < 600 });
  async function visit(path) {
    await cdp("Page.navigate", { url: base + path });
    await until(() => evaluate("document.readyState === 'complete'"), `load ${path}`);
  }
  const text = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.innerText ?? null`);
  const pathname = () => evaluate("location.pathname + location.search");
  async function screenshot(name) {
    const image = await cdp("Page.captureScreenshot", { format: "png" });
    await writeFile(resolve(artifacts, name), Buffer.from(image.data, "base64"));
  }
  async function noOverflow(label) {
    const widths = await evaluate("({ viewport: innerWidth, content: document.documentElement.scrollWidth })");
    assert.ok(widths.content <= widths.viewport + 1, `${label} overflows: ${JSON.stringify(widths)}`);
  }
  async function key(keyName, code = keyName, keyCode = 0) {
    await cdp("Input.dispatchKeyEvent", { type: "keyDown", key: keyName, code, windowsVirtualKeyCode: keyCode });
    await cdp("Input.dispatchKeyEvent", { type: "keyUp", key: keyName, code, windowsVirtualKeyCode: keyCode });
    await sleep(80);
  }
  async function clickAt(selector) {
    const box = await evaluate(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); el?.scrollIntoView({ block: 'center', inline: 'center', behavior: 'instant' }); const r = el?.getBoundingClientRect(); return r && { x: r.x + r.width / 2, y: r.y + r.height / 2 }; })()`);
    assert.ok(box, `Missing ${selector}`);
    for (const type of ["mousePressed", "mouseReleased"]) await cdp("Input.dispatchMouseEvent", { type, x: box.x, y: box.y, button: "left", clickCount: 1 });
    await sleep(150);
  }
  const ROWS = ".console-grid .ag-grid-scrolling-container .ag-row";
  const gridReady = async () => {
    await until(() => evaluate(`document.querySelectorAll(${JSON.stringify(ROWS)}).length > 0`), "grid rows");
    await sleep(200);
    if (await evaluate("!!document.querySelector('.ag-overlay-error-panel')")) {
      overlaySeen = true;
      throw new Error(`AG Grid diagnostics overlay: ${await text(".ag-overlay-error-panel")}`);
    }
  };
  // AG Grid 36 renders one .ag-row per row (pinned + scrolling cells together); header and floating-filter cells share col-id.
  const header = (colId) => `.console-grid .ag-header-row-column .ag-header-cell[col-id=${colId}]`;
  // Visible row titles in display order (pinned title column).
  const sortedRows = `[...document.querySelectorAll(${JSON.stringify(ROWS)})].sort((a, b) => Number(a.getAttribute('row-index')) - Number(b.getAttribute('row-index')))`;
  const columnValues = (colId) => evaluate(`${sortedRows}.map(r => r.querySelector('[col-id=${colId}]')?.innerText.trim())`);
  const titles = () => columnValues("title");
  const cellText = (rowTitle, colId) => evaluate(`(() => {
    const row = [...document.querySelectorAll(${JSON.stringify(ROWS)})].find(r => r.querySelector('[col-id=title]')?.innerText.trim() === ${JSON.stringify(rowTitle)});
    const cell = row?.querySelector('[col-id=${colId}]');
    return cell ? { text: cell.innerText.trim(), unavailable: cell.classList.contains('console-unavailable') } : null;
  })()`);
  const pagingText = () => text(".console-grid .ag-paging-row-summary-panel");
  // Hover via real mouse events; returns visible tooltip text or null after the show delay.
  async function hoverTooltip(selector) {
    await cdp("Input.dispatchMouseEvent", { type: "mouseMoved", x: 2, y: 2 });
    await until(() => evaluate("!document.querySelector('.ag-tooltip:not(.ag-tooltip-hiding)')"), "previous tooltip hidden");
    const box = await evaluate(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); if (!el) return null;
      el.scrollIntoView({ block: 'center', inline: 'center', behavior: 'instant' }); const r = el.getBoundingClientRect();
      return { x: r.x + Math.min(r.width / 2, 40), y: r.y + r.height / 2 }; })()`);
    assert.ok(box, `Missing ${selector}`);
    await sleep(150);
    await cdp("Input.dispatchMouseEvent", { type: "mouseMoved", x: box.x - 1, y: box.y });
    await cdp("Input.dispatchMouseEvent", { type: "mouseMoved", x: box.x, y: box.y });
    for (let i = 0; i < 12; i++) {
      await sleep(100);
      const shown = await evaluate("document.querySelector('.ag-tooltip:not(.ag-tooltip-hiding)')?.innerText.trim() || null");
      if (shown) return shown;
    }
    return null;
  }
  const rowCell = (title, colId) => evaluate(`(() => {
    const row = [...document.querySelectorAll(${JSON.stringify(ROWS)})].find(r => r.querySelector('[col-id=title]')?.innerText.trim() === ${JSON.stringify(title)});
    return row ? ${JSON.stringify(ROWS)} + '[row-index="' + row.getAttribute('row-index') + '"] [col-id=${colId}]' : null;
  })()`);
  // Sweep the grid's own horizontal scroller (never the page). A column is reachable if, at some scroll position,
  // it lies entirely inside the unpinned area (right of any pinned column, left of the grid's right edge).
  async function horizontalReach() {
    return evaluate(`(async () => {
      const grid = document.querySelector('.console-grid');
      const scroller = grid.querySelector('.ag-body-horizontal-scroll-viewport');
      const frame = () => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done)));
      const headers = () => [...grid.querySelectorAll('.ag-header-row-column .ag-header-cell[col-id]')];
      const pinnedRight = () => Math.max(grid.querySelector('.ag-root-wrapper').getBoundingClientRect().left,
        ...[...grid.querySelectorAll('.ag-header-row-column .ag-grid-pinned-left-cells .ag-header-cell')].map(h => h.getBoundingClientRect().right));
      const right = grid.querySelector('.ag-root-wrapper').getBoundingClientRect().right;
      const pinned = [...grid.querySelectorAll('.ag-header-row-column .ag-grid-pinned-left-cells .ag-header-cell')].map(h => h.getAttribute('col-id'));
      const reached = new Set(pinned);
      const max = scroller.scrollWidth - scroller.clientWidth;
      for (let x = 0; x <= max + 40; x += 40) {
        scroller.scrollLeft = Math.min(x, max); scroller.dispatchEvent(new Event('scroll')); await frame();
        const left = pinnedRight();
        for (const h of headers()) { const r = h.getBoundingClientRect(); if (r.width > 0 && r.left >= left - 1 && r.right <= right + 1) reached.add(h.getAttribute('col-id')); }
      }
      const cellAtEnd = (() => { const c = grid.querySelector('.ag-grid-scrolling-container .ag-row[row-index="0"] [col-id=settlement]')?.getBoundingClientRect(); return !!c && c.right <= right + 1 && c.left >= pinnedRight() - 1; })();
      scroller.scrollLeft = 0; scroller.dispatchEvent(new Event('scroll')); await frame();
      const displayed = headers().map(h => h.getAttribute('col-id'));
      return { displayed, pinned, unreachable: displayed.filter(id => !reached.has(id)), settlementCellAtEnd: cellAtEnd, maxScroll: max,
        pageScrollX: scrollX, pageWidth: document.documentElement.scrollWidth, viewport: innerWidth };
    })()`);
  }
  const mutatingCalls = () => apiCalls.filter((c) => c.method !== "GET" && !["/api/auth/csrf", "/api/merchant/login"].includes(c.path));
  const consoleCalls = () => apiCalls.filter((c) => c.path.startsWith("/api/merchant/workshops"));

  // ---- 1. Entry from /host and lazy loading -------------------------------------------------
  await viewport(1440);
  await visit("/host");
  await until(() => evaluate("!!document.querySelector('.host-console-link a')"), "Table view link");
  assert.equal(await text(".host-console-link a"), "Table view");
  await until(() => evaluate("document.querySelector('.host-workshop-list') !== null || document.querySelector('.host-empty') !== null"), "card list still renders");
  assert.equal(await evaluate("[...document.scripts].some(s => s.src.includes('MerchantConsole')) || performance.getEntriesByType('resource').some(e => e.name.includes('MerchantConsole'))"), false,
    "AG Grid chunk is not loaded on /host");
  listMode = "hold";
  await evaluate("document.querySelector('.host-console-link a').click()");
  await until(async () => (await pathname()) === "/host/console", "navigate to /host/console");
  await until(() => evaluate("[...document.querySelectorAll('[role=status]')].some(e => /Loading (your workshops|table view)/.test(e.innerText))"), "loading state");
  await until(() => evaluate("performance.getEntriesByType('resource').some(e => e.name.includes('MerchantConsole'))"), "lazy chunk requested");
  await until(() => held !== null, "held list request");
  assert.equal(await evaluate("!!document.querySelector('.console-grid')"), false, "grid not shown while loading");
  passed("/host shows a Table view link; the console chunk lazy-loads only on /host/console; loading state is announced");
  listMode = "ok";
  const visibility = apiCalls.filter((c) => c.path === "/api/merchant/workshops").at(-1).search;
  assert.equal(visibility, "?visibility=all");
  await respond(held, 200, workshops); held = null;
  await gridReady();
  assert.equal(await evaluate("document.querySelector('.host-filter [aria-pressed=true]').innerText"), "All");
  passed("default toggle is All and requests visibility=all");

  // ---- 2. Real-shaped data, partial failure, labels ----------------------------------------
  await until(async () => (await pagingText())?.includes("of 12"), "paging summary");
  assert.equal((await titles()).length, 10, "first page shows 10 rows");
  const demo = await cellText("Demo hidden workshop", "visibility");
  assert.equal(demo.text, "Hidden from discovery");
  assert.equal((await cellText("Zine binding draft", "status")).text, "Draft");
  assert.equal((await cellText("Zine binding draft", "bookings")).text, "Not published");
  assert.equal((await cellText("Zine binding draft", "price")).text, "Price not set");
  assert.equal((await cellText("Demo hidden workshop", "price")).text, "£45.00");
  assert.equal((await cellText("Demo hidden workshop", "seatsAvailable")).text, String(10 - (1 % 5)));
  assert.equal((await cellText("Legacy schema workshop", "settlement")).text, "Not available");
  for (const col of ["status", "cutoff", "capacity", "bookings", "seatsAvailable", "settlement"]) {
    const cell = await cellText("Broken detail workshop", col);
    assert.deepEqual(cell, { text: "Unavailable", unavailable: true }, `broken ${col}`);
  }
  assert.equal((await cellText("Broken detail workshop", "price")).text, "£30.00", "list fields still real");
  assert.match(await text(".console-partial"), /Details for 1 published workshop could not be loaded/);
  assert.match(await text(".console-notes"), /Derived; excludes in-progress reservation holds\./);
  assert.match(await text(".console-notes"), /Settlement outcome; not the work-queue state\./);
  const detailCalls = consoleCalls().filter((c) => c.path !== "/api/merchant/workshops");
  assert.equal(detailCalls.length, 11, "detail requested only for the 11 published workshops");
  await screenshot("console-1440.png");
  passed("rows map list + detail data; failed detail cells show Unavailable; null settlement shows Not available; notes shown");

  // ---- 2b. Tooltips (AG Grid 36.2 `tooltip` callback + header tooltips) ----------------------
  const callsBeforeClientSide = apiCalls.length;
  assert.equal(await hoverTooltip(await rowCell("Demo hidden workshop", "visibility")), "Hidden since 8 Nov 2026, 11:24:40 GMT");
  assert.equal(await hoverTooltip(await rowCell("Pottery evening 05", "visibility")), null, "listed row has no tooltip");
  assert.equal(await hoverTooltip(await rowCell("Broken detail workshop", "visibility")), null, "failed-detail listed row has no tooltip");
  for (const col of ["status", "bookings", "settlement"]) {
    assert.equal(await hoverTooltip(await rowCell("Broken detail workshop", col)), null, `Unavailable ${col} cell has no fabricated tooltip`);
  }
  assert.equal(await hoverTooltip(header("seatsAvailable")), "Derived; excludes in-progress reservation holds.");
  assert.equal(await hoverTooltip(header("settlement")), "Settlement outcome; not the work-queue state.");
  assert.equal(await hoverTooltip(header("bookings")), "Admitted bookings");
  await cdp("Input.dispatchMouseEvent", { type: "mouseMoved", x: 2, y: 2 });
  passed("tooltips: hidden-since on hidden rows; none for listed, failed-detail or Unavailable cells; header notes shown");

  // ---- 2c. Horizontal reach at desktop width ------------------------------------------------
  const desktopReach = await horizontalReach();
  assert.ok(desktopReach.maxScroll > 0, `grid scrolls horizontally inside itself: ${JSON.stringify(desktopReach)}`);
  assert.equal(desktopReach.displayed.length, 10, "all ten columns displayed on desktop");
  assert.deepEqual(desktopReach.pinned, ["title"], "title pinned on desktop");
  assert.deepEqual(desktopReach.unreachable, [], `every column fully reachable: ${JSON.stringify(desktopReach)}`);
  assert.ok(desktopReach.settlementCellAtEnd, "settlement cells visible at full scroll");
  assert.equal(desktopReach.pageScrollX, 0);
  assert.ok(desktopReach.pageWidth <= desktopReach.viewport + 1, `page does not scroll horizontally: ${JSON.stringify(desktopReach)}`);
  passed("desktop: right-side columns reachable by scrolling inside the grid; title stays pinned; page has no horizontal scroll");

  // ---- 3. Sorting --------------------------------------------------------------------------
  // Keyboard sort: focus the column header and press Enter (header may be scrolled off-screen inside the grid).
  const sortBy = async (colId) => {
    await evaluate(`document.querySelector('${header(colId)}').focus()`);
    await key("Enter", "Enter", 13);
    await sleep(150);
  };
  await sortBy("price");
  assert.equal(await evaluate(`document.querySelector('${header("price")}').getAttribute('aria-sort')`), "ascending");
  const asc = await columnValues("price");
  assert.equal(asc[0], "Price not set", "£0 first ascending");
  assert.equal(asc[1], "£15.00");
  await sortBy("price");
  assert.equal((await titles())[0], "Demo hidden workshop", "£45 first descending");
  assert.equal(await evaluate(`document.querySelector('${header("price")}').getAttribute('aria-sort')`), "descending");
  await sortBy("seatsAvailable");
  await sortBy("seatsAvailable");
  const seatsDesc = await columnValues("seatsAvailable");
  assert.ok(!["Unavailable", "Not available", "Not published"].includes(seatsDesc[0]), `non-values sort last when descending: ${seatsDesc}`);
  await sortBy("title");
  assert.equal((await titles())[0], "Broken detail workshop");
  passed("sorting by price, derived seats (missing values last) and title; aria-sort reflects order");

  // ---- 4. Filtering ------------------------------------------------------------------------
  const titleFilter = ".console-grid .ag-floating-filter[col-id=title] input";
  await evaluate(`document.querySelector(${JSON.stringify(titleFilter)}).focus()`);
  await cdp("Input.insertText", { text: "pottery" });
  await until(async () => (await pagingText())?.includes("of 8"), "title filter applied");
  assert.ok((await titles()).every((t) => t.startsWith("Pottery evening")));
  await evaluate(`(() => { const i = document.querySelector(${JSON.stringify(titleFilter)}); i.focus(); i.select(); })()`);
  await key("Backspace", "Backspace", 8);
  await until(async () => (await pagingText())?.includes("of 12"), "filter cleared");
  passed("floating text filter narrows rows and clears");

  // ---- 5. Paging ---------------------------------------------------------------------------
  await clickAt(".console-grid .ag-paging-button[aria-label='Next Page']");
  await until(async () => /11 to 12 of 12/.test(await pagingText()), "page 2");
  assert.equal((await titles()).length, 2);
  await clickAt(".console-grid .ag-paging-button[aria-label='Previous Page']");
  await until(async () => /1 to 10 of 12/.test(await pagingText()), "page 1");
  assert.equal(apiCalls.length, callsBeforeClientSide, "sorting, filtering, paging and tooltips make no network requests");
  passed("pagination moves between pages of 10");

  // ---- 6. Keyboard access -----------------------------------------------------------------
  assert.equal(await evaluate("document.querySelector('.console-grid [role=treegrid], .console-grid [role=grid]') !== null"), true, "grid role exposed");
  await clickAt(`${ROWS}[row-index='0'] [col-id=status]`);
  await key("ArrowLeft", "ArrowLeft", 37);
  assert.equal(await evaluate("document.activeElement.getAttribute('col-id')"), "title", "arrow keys move focus to the title cell");
  const firstTitle = (await titles())[0];
  const target = workshops.find((w) => w.title === firstTitle).workshop_id;
  await key("Enter", "Enter", 13);
  await until(async () => (await pathname()) === `/host/workshops/${target}`, "keyboard opens workbench");
  passed("keyboard: arrow navigation reaches the title cell and Enter opens its workbench");

  // ---- 7. Row link navigation ------------------------------------------------------------
  await visit("/host/console");
  await gridReady();
  const href = await evaluate("document.querySelector('.console-grid .console-title-link').getAttribute('href')");
  assert.match(href, /^\/host\/workshops\/[0-9a-f-]{36}$/);
  await evaluate("document.querySelector('.console-grid .console-title-link').click()");
  await until(async () => (await pathname()) === href, "link opens workbench");
  await until(() => evaluate("!!document.querySelector('.workbench, .host-panel')"), "workbench rendered");
  passed("title link opens the existing workbench via in-app navigation");

  // ---- 8. Visibility toggle ----------------------------------------------------------------
  await visit("/host/console");
  await gridReady();
  await evaluate("[...document.querySelectorAll('.host-filter button')].find(b => b.innerText === 'Hidden from discovery').click()");
  await until(async () => (await pagingText())?.includes("of 1"), "hidden filter");
  assert.deepEqual(await titles(), ["Demo hidden workshop"]);
  assert.equal(apiCalls.filter((c) => c.path === "/api/merchant/workshops").at(-1).search, "?visibility=hidden");
  await evaluate("[...document.querySelectorAll('.host-filter button')].find(b => b.innerText === 'Listed').click()");
  await until(async () => (await pagingText())?.includes("of 11"), "listed filter");
  passed("Listed and Hidden toggles are preserved and request the matching visibility");

  // ---- 9. Mobile layout --------------------------------------------------------------------
  await viewport(390, 844);
  await visit("/host/console");
  await gridReady();
  await sleep(300);
  await noOverflow("mobile console");
  const hidden = await evaluate(`['opensAt','capacity'].map(c => !!document.querySelector('.console-grid .ag-header-row-column .ag-header-cell[col-id=' + c + ']'))`);
  assert.deepEqual(hidden, [false, false], "less critical columns hidden on narrow screens");
  assert.equal(await evaluate(`!!document.querySelector('${header("settlement")}')`), true);
  await screenshot("console-390.png");
  const mobileReach = await horizontalReach();
  assert.deepEqual(mobileReach.displayed, ["title", "status", "visibility", "cutoff", "bookings", "seatsAvailable", "price", "settlement"]);
  assert.deepEqual(mobileReach.pinned, [], "title scrolls with the other columns on phones");
  assert.deepEqual(mobileReach.unreachable, [], `mobile: every displayed column fully reachable in-grid: ${JSON.stringify(mobileReach)}`);
  assert.ok(mobileReach.settlementCellAtEnd, "mobile: settlement cells visible at full scroll");
  assert.ok(mobileReach.pageWidth <= mobileReach.viewport + 1 && mobileReach.pageScrollX === 0, `mobile page has no horizontal scroll: ${JSON.stringify(mobileReach)}`);
  await viewport(1440);
  await sleep(300);
  assert.equal(await evaluate(`!!document.querySelector('${header("opensAt")}')`), true, "columns return at desktop width");
  passed("mobile: no page-level horizontal overflow; right-side columns reachable in-grid; narrow layout hides opens/capacity and restores them on resize");

  // ---- 10. Empty, error, retry ------------------------------------------------------------
  listMode = "empty";
  await visit("/host/console");
  await until(() => evaluate("!!document.querySelector('.console-empty')"), "empty state");
  assert.match(await text(".console-empty h2"), /There are no owned workshops yet/);
  await evaluate("[...document.querySelectorAll('.host-filter button')].find(b => b.innerText === 'Hidden from discovery').click()");
  await until(async () => /No workshops are hidden from discovery/.test(await text(".console-empty h2") ?? ""), "hidden empty");
  passed("empty state per toggle");
  listMode = "error";
  await visit("/host/console");
  await until(() => evaluate("!!document.querySelector('.console-error [role=alert]')"), "error state");
  assert.match(await text(".console-error"), /could not be loaded/);
  await screenshot("console-error-1440.png");
  listMode = "ok";
  await evaluate("document.querySelector('.console-error button').click()");
  await gridReady();
  passed("error state is announced and Try again recovers");

  // ---- 11. Unauthorised -------------------------------------------------------------------
  listMode = "unauthorized";
  await visit("/host/console");
  await until(async () => (await pathname()) === "/host/login?returnTo=%2Fhost%2Fconsole", "401 redirect from list");
  listMode = "ok"; detailUnauthorized = true;
  await visit("/host/console");
  await until(async () => (await pathname()) === "/host/login?returnTo=%2Fhost%2Fconsole", "401 redirect from detail");
  detailUnauthorized = false;
  authMode = "anonymous";
  await visit("/host/console");
  await until(async () => (await pathname()) === "/host/login?returnTo=%2Fhost%2Fconsole", "anonymous redirect");
  await until(() => evaluate("!!document.querySelector('#host-identifier')"), "login form");
  await evaluate("document.querySelector('#host-identifier').focus()");
  await cdp("Input.insertText", { text: "fixture-host" });
  await evaluate("document.querySelector('#host-password').focus()");
  await cdp("Input.insertText", { text: "fixture-password" });
  await evaluate("document.querySelector('.login-card form').requestSubmit()");
  await until(async () => (await pathname()) === "/host/console", "return to console after login");
  await gridReady();
  passed("401 from list or detail, and anonymous access, redirect to login and return to /host/console");

  // ---- 12. Read-only guarantees -----------------------------------------------------------
  assert.deepEqual(mutatingCalls(), [], `no mutating requests: ${JSON.stringify(mutatingCalls())}`);
  assert.ok(consoleCalls().every((c) => c.method === "GET"));
  assert.ok(!apiCalls.some((c) => /hide-from-discovery|restore-visibility|publish|preview|materials|bookings|paypal/.test(c.path)));
  assert.equal(await evaluate("document.querySelectorAll('.merchant-console .hide-from-discovery, .merchant-console .restore-visibility, .merchant-console form').length"), 0);
  passed(`read-only: ${consoleCalls().length} merchant workshop requests, all GET; no hide/restore/publish/preview/payment calls`);

  assert.deepEqual(errors, []);
  const gridWarnings = allConsole.filter((m) => /AG Grid/i.test(m));
  assert.deepEqual(gridWarnings, [], "no AG Grid errors, warnings or deprecations");
  assert.equal(overlaySeen, false, "AG Grid diagnostics overlay never appeared");
  passed(`no uncaught exceptions and no AG Grid console diagnostics${devMode ? " (dev validation: errors, warnings, deprecations, overlay)" : " (production: e.g. #200 missing module)"}`);
  console.log(`${checks} console browser checks passed (${devMode ? "Vite dev server with AG Grid ValidationModule" : "production build"}). All API traffic was intercepted fixtures.`);
  console.log(`Screenshots: ${artifacts}`);
} finally {
  socket?.close();
  chrome?.kill("SIGTERM");
  server.kill("SIGTERM");
}
