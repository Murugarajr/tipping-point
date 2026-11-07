import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";

// Invoked only by the PostgreSQL pytest integration fixture. APIs are real;
// PayPal is mocked inside that fixture. No external URL may be requested.
const [base, workshopId] = process.argv.slice(2);
assert.equal(new URL(base).hostname, "127.0.0.1");
const root = fileURLToPath(new URL("../", import.meta.url));
const artifacts = resolve(root, "node_modules/.tmp/guest-api-browser");
await mkdir(artifacts, { recursive: true });
const profile = await mkdtemp(resolve(artifacts, "profile-"));
const control = createInterface({ input: process.stdin, crlfDelay: Infinity });
const input = control[Symbol.asyncIterator]();
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
async function until(check, label) {
  for (let attempt = 0; attempt < 150; attempt++) {
    if (await check()) return;
    await sleep(100);
  }
  throw new Error(`Timed out: ${label}`);
}
const chrome = spawn(process.env.CHROME_PATH ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", [
  "--headless", "--disable-gpu", "--disable-background-networking", "--disable-sync",
  "--disable-component-update", "--no-first-run", "--no-default-browser-check",
  "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank",
], { stdio: ["ignore", "ignore", "pipe"] });
let socket;
try {
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
  await new Promise((done, reject) => {
    socket.addEventListener("open", done, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });
  let sequence = 0;
  const pending = new Map(), listeners = new Set();
  socket.addEventListener("message", ({ data }) => {
    const message = JSON.parse(data);
    if (!message.id) { for (const listener of listeners) listener(message); return; }
    const waiter = pending.get(message.id);
    if (!waiter) return;
    pending.delete(message.id); clearTimeout(waiter.timeout);
    if (message.error) waiter.reject(new Error(message.error.message)); else waiter.done(message.result);
  });
  const send = (method, params = {}, sessionId) => new Promise((done, reject) => {
    const id = ++sequence;
    const timeout = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 30000);
    pending.set(id, { done, reject, timeout });
    socket.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
  });
  const { targetInfos } = await send("Target.getTargets");
  const { sessionId } = await send("Target.attachToTarget", {
    targetId: targetInfos.find((target) => target.type === "page").targetId, flatten: true,
  });
  const cdp = (method, params) => send(method, params, sessionId);
  await cdp("Page.enable"); await cdp("Runtime.enable");
  const external = [], errors = [], mutations = [];
  listeners.add((event) => {
    if (event.method === "Runtime.exceptionThrown") errors.push(event.params.exceptionDetails.text);
    if (event.method !== "Fetch.requestPaused") return;
    const { request, requestId } = event.params;
    if (new URL(request.url).origin !== base) {
      external.push(request.url);
      void cdp("Fetch.failRequest", { requestId, errorReason: "BlockedByClient" });
    } else {
      if (request.method !== "GET") mutations.push(new URL(request.url).pathname);
      void cdp("Fetch.continueRequest", { requestId });
    }
  });
  await cdp("Fetch.enable", { patterns: [{ urlPattern: "*" }] });
  const evaluate = async (expression) => {
    const result = await cdp("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description ?? result.exceptionDetails.text);
    return result.result.value;
  };
  const text = () => evaluate("document.querySelector('main')?.innerText ?? ''");
  const click = async (caption) => {
    assert.ok(await evaluate(`(() => {
      const control = [...document.querySelectorAll('main button, main a')].find(item => item.textContent === ${JSON.stringify(caption)});
      if (!control || control.disabled) return false;
      control.click(); return true;
    })()`), `Missing or disabled action: ${caption}`);
  };
  const screenshot = async (name) => {
    const result = await cdp("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    await writeFile(resolve(artifacts, name), Buffer.from(result.data, "base64"));
  };
  await cdp("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await cdp("Page.navigate", { url: `${base}/continue?workshop=${workshopId}` });
  await until(() => evaluate("!!document.querySelector('#guest-email')"), "real guest contact form");
  assert.equal(mutations.length, 0);
  await evaluate("document.querySelector('#guest-email').focus()");
  await cdp("Input.insertText", { text: "browser-integration@example.invalid" });
  await click("Continue — reserve one temporary seat");
  await until(() => evaluate("location.pathname.startsWith('/bookings/') && document.querySelector('main h1')?.innerText === 'Seat held temporarily'"), "persisted seat");
  const bookingPath = await evaluate("location.pathname");
  const bookingId = bookingPath.split("/")[2];
  await click("Create PayPal Sandbox order");
  await until(() => evaluate("document.querySelector('main h1')?.innerText === 'Awaiting buyer approval'"), "persisted provider order");
  assert.ok(await evaluate("document.querySelector('a[href^=\"https://www.sandbox.paypal.com/checkoutnow?token=\"]') !== null"));
  console.log(JSON.stringify({ phase: "APPROVE_FIXTURE", booking_id: bookingId }));
  assert.equal((await input.next()).value, "APPROVED");
  const beforeReturn = mutations.length;
  await cdp("Page.navigate", { url: `${base}${bookingPath}/paypal/return?token=not-proof&PayerID=not-proof` });
  await until(() => evaluate("document.querySelector('main h1')?.innerText === 'Awaiting buyer approval'"), "GET-only return route");
  assert.equal(mutations.length, beforeReturn);
  await click("Check approval and authorize");
  await until(() => evaluate("document.querySelector('main h1')?.innerText === 'Authorized reservation'"), "persisted authorization");
  assert.match(await text(), /not a completed charge|not collected/);
  await screenshot("guest-durable-api-authorized-1440.png");
  await click("Request cancellation");
  await until(() => evaluate("document.querySelector('main h1')?.innerText === 'Authorization release pending'"), "persisted release queue");
  console.log(JSON.stringify({ phase: "RELEASE_FIXTURE", booking_id: bookingId }));
  assert.equal((await input.next()).value, "VOIDED");
  await click("Refresh saved status");
  await until(() => evaluate("document.querySelector('main h1')?.innerText === 'Authorization voided'"), "verified persisted void");
  await cdp("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: false });
  await screenshot("guest-durable-api-voided-390.png");
  assert.ok(await evaluate("document.documentElement.scrollWidth <= innerWidth + 1"));
  assert.deepEqual(external, []);
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ phase: "DONE", booking_id: bookingId, api_mutations: mutations.length, external_requests: external.length }));
} finally {
  control.close();
  process.stdin.destroy();
  socket?.close();
  chrome.kill("SIGTERM");
}
