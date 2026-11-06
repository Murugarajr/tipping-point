import assert from "node:assert/strict";
import { test } from "node:test";
import { categories, exampleWorkshops, filterWorkshops, findWorkshop, formatPrice, faqs } from "../src/public/content.ts";
import * as api from "../src/api.ts";

test("all editorial workshops have explicit example provenance and unique IDs", () => {
  assert.equal(new Set(exampleWorkshops.map((item) => item.id)).size, exampleWorkshops.length);
  for (const item of exampleWorkshops) {
    assert.equal(item.source, "illustrative-example");
    assert.ok(Number.isSafeInteger(item.priceMinor) && item.priceMinor > 0);
    assert.ok(categories.includes(item.category));
    assert.match(item.location, /^Example studio/);
  }
});

test("filters return only the selected category and reset to all examples", () => {
  for (const category of categories.slice(1)) {
    assert.ok(filterWorkshops(category).every((item) => item.category === category));
  }
  assert.equal(filterWorkshops("Clay").length, 1);
  assert.equal(filterWorkshops("All workshops").length, 3);
});

test("the empty category is intentional and does not fabricate inventory", () => {
  assert.deepEqual(filterWorkshops("Print"), []);
});

test("workshop lookup accepts only known editorial identifiers", () => {
  assert.equal(findWorkshop("a-little-clay")?.craft, "clay");
  for (const id of [null, "", "../host", "unknown", "<script>"]) assert.equal(findWorkshop(id), undefined);
});

test("GBP formatting preserves pence", () => {
  assert.equal(formatPrice(4800), "£48");
  assert.equal(formatPrice(4805), "£48.05");
});

test("FAQs distinguish discovery, prototype payments and actual confirmation checks", () => {
  assert.equal(faqs.length, 6);
  assert.match(faqs.map(([, answer]) => answer).join(" "), /not an active booking service/);
  assert.match(faqs.map(([, answer]) => answer).join(" "), /authorization is not collection/);
  assert.match(faqs.map(([, answer]) => answer).join(" "), /not bookable inventory/);
});

test("real API wrapper preserves same-origin credentials, CSRF rotation and logout", async (t) => {
  const originalFetch = globalThis.fetch;
  const originalDocument = globalThis.document;
  t.after(() => { globalThis.fetch = originalFetch; globalThis.document = originalDocument; api.clearCsrfToken(); });
  globalThis.document = { cookie: "tipping_csrf=cookie-fixture" };
  const calls = [];
  const session = { merchant: { merchant_id: "fixture", name: "Test host" }, csrf_token: "bound-fixture", session_id: "fixture-session", expires_at: "2099-01-01T00:00:00Z" };
  globalThis.fetch = async (path, init) => {
    calls.push({ path, init });
    const body = path === "/api/auth/csrf" ? { csrf_token: "bootstrap-fixture" }
      : path === "/api/merchant/logout" ? { status: "logged out" }
        : path === "/api/me" ? { ...session, csrf_token: "" } : session;
    return new Response(JSON.stringify(body), { status: 200 });
  };
  await api.login("fixture-host", "fixture-password");
  assert.equal(calls[0].path, "/api/auth/csrf");
  assert.equal(calls[1].init.headers.get("X-CSRF-Token"), "bootstrap-fixture");
  assert.deepEqual(JSON.parse(calls[1].init.body), { login_identifier: "fixture-host", password: "fixture-password" });
  await api.logout();
  assert.equal(calls[2].init.headers.get("X-CSRF-Token"), "bound-fixture");
  await api.restoreSession();
  await api.logout();
  assert.equal(calls[4].init.headers.get("X-CSRF-Token"), "cookie-fixture");
  assert.ok(calls.every(({ init }) => init.credentials === "same-origin"));
});

test("API errors remain errors instead of falling back to sample success", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: "invalid login credentials" }), { status: 401 });
  await assert.rejects(api.restoreSession(), (error) => error instanceof api.ApiError && error.status === 401);
});

test("merchant-only listing contract stays merchant-only", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = async (path) => {
    assert.equal(path, "/api/merchant/workshops");
    return new Response("[]", { status: 200 });
  };
  assert.deepEqual(await api.listWorkshops(), []);
});

test("brand text and accent combinations meet WCAG AA normal text contrast", async () => {
  const { readFile } = await import("node:fs/promises");
  const css = await readFile(new URL("../src/public/public.css", import.meta.url), "utf8");
  const token = (name) => css.match(new RegExp(`--tp-${name}: (#[a-f0-9]{6})`))[1];
  const luminance = (hex) => {
    const rgb = hex.slice(1).match(/../g).map((part) => parseInt(part, 16) / 255)
      .map((part) => part <= .04045 ? part / 12.92 : ((part + .055) / 1.055) ** 2.4);
    return .2126 * rgb[0] + .7152 * rgb[1] + .0722 * rgb[2];
  };
  const contrast = (a, b) => {
    const pair = [luminance(a), luminance(b)].sort((x, y) => y - x);
    return (pair[0] + .05) / (pair[1] + .05);
  };
  for (const [a, b] of [[token("red"), "#ffffff"], [token("blue"), "#ffffff"], [token("red-ink"), "#ffffff"], [token("muted"), token("soft")], [token("ink"), "#ffffff"]]) {
    assert.ok(contrast(a, b) >= 4.5, `${a} / ${b} contrast is ${contrast(a, b).toFixed(2)}`);
  }
});
