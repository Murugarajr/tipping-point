import assert from "node:assert/strict";
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
    if (path === "/api/merchant/workshops") { code = expireListing ? 401 : 200; body = code === 200 ? [] : { detail: "expired" }; }
    if (path === "/api/merchant/logout") { code = 200; body = { status: "logged out" }; authMode = "anonymous"; }
    void cdp("Fetch.fulfillRequest", { requestId, responseCode: code, responseHeaders: [{ name: "Content-Type", value: "application/json" }], body: Buffer.from(JSON.stringify(body)).toString("base64") }).catch((error) => errors.push(error.message));
  });
  await cdp("Fetch.enable", { patterns: [{ urlPattern: `${base}/api/*` }] });
  async function evaluate(expression) {
    const response = await cdp("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (response.exceptionDetails) throw new Error(response.exceptionDetails.text);
    return response.result.value;
  }
  async function viewport(width, height = 900) {
    await cdp("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
  }
  async function visit(path) {
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
  await until(() => evaluate("!!document.querySelector('.merchant-menu')"), "authenticated host");
  const login = apiCalls.filter((item) => item.path === "/api/merchant/login").at(-1);
  assert.equal(new Headers(login.headers).get("X-CSRF-Token"), "bootstrap-test-csrf");
  assert.deepEqual(JSON.parse(login.body), { login_identifier: "fixture-host", password: "fixture-password" });
  await noOverflow("authenticated mobile host");
  await click(".merchant-menu button");
  await until(() => evaluate("!!document.querySelector('#host-password')"), "logout");
  const logout = apiCalls.find((item) => item.path === "/api/merchant/logout");
  assert.equal(new Headers(logout.headers).get("X-CSRF-Token"), "bound-test-csrf");
  passed("host login bootstrap, bound logout CSRF and workspace access (mocked API)");
  authMode = "authenticated"; expireListing = true;
  await visit("/host");
  await until(() => evaluate("!!document.querySelector('.notice.warning')"), "expired host session");
  assert.match(await evaluate("document.querySelector('.notice.warning').innerText"), /expired/);
  assert.equal(await evaluate("!!document.querySelector('.merchant-menu')"), false);
  passed("session expiry hides merchant data and returns to sign-in (mocked API)");
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
