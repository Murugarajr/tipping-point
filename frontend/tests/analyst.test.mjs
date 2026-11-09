import assert from "node:assert/strict";
import test from "node:test";
import {
  PRESET_LABELS, SUGGESTED_QUESTIONS, analystErrorText, analystWidgetId, answerParagraphs, applyVisualizations, boundedHistory,
  connectionLabel, presetWidget, safeTitle, statusText,
} from "../src/host/intelligence/analystModel.ts";

const page = (widgets = {}, widgetLayout = {}) => ({ id: "intelligence", widgets, widgetLayout });
const report = (p = page({ meter: { type: "tipping-meter" } }, { meter: { xTrack: 0, yTrack: 0, xSpan: 8, ySpan: 18 }, materials: { xTrack: 0, yTrack: 38, xSpan: 24, ySpan: 12 } })) =>
  ({ selectedPageId: "intelligence", pages: [p, page()].map((x, i) => i ? { ...x, id: "other" } : x), panels: { data: { collapsed: true } } });

test("suggested questions are the approved four", () => {
  assert.deepEqual([...SUGGESTED_QUESTIONS], [
    "Explain this workshop's tipping point.", "Why can attendance five be non-viable when four is viable?",
    "Show revenue versus total costs.", "Which materials drive the budget?",
  ]);
});

test("history is bounded to the server's limits and always ends with the user's question", () => {
  const long = Array.from({ length: 20 }, (_, i) => ({ role: i % 2 ? "assistant" : "user", content: `m${i}` }));
  const out = boundedHistory(long, "now?");
  assert.ok(out.length <= 12);
  assert.deepEqual(out.at(-1), { role: "user", content: "now?" });
  assert.equal(out[0].role, "user", "never starts with an assistant turn");
  const big = boundedHistory([{ role: "user", content: "x".repeat(5000) }, { role: "assistant", content: "y".repeat(5000) }], "z".repeat(5000));
  assert.ok(big.every((m) => m.content.length <= 2000));
  assert.ok(big.reduce((n, m) => n + m.content.length, 0) <= 12000);
  assert.deepEqual(boundedHistory([], "  q  "), [{ role: "user", content: "  q  " }]);
});

test("status and connection labels; not-configured copy names no secret", () => {
  assert.equal(connectionLabel({ provider: "OpenRouter", model: "vendor/m" }), "OpenRouter · vendor/m");
  assert.equal(connectionLabel({ provider: "OpenRouter", model: null }), "OpenRouter");
  for (const s of ["disabled", "missing_key", "missing_model"]) assert.match(statusText({ status: s }), /^Analyst not configured/);
});

test("errors map to fixed copy; unknown provider text never reaches the page", () => {
  assert.match(analystErrorText(429, { detail: { code: "PROVIDER_RATE_LIMITED", message: "upstream said sk-123" } }), /rate limiting/);
  assert.match(analystErrorText(503, { detail: { code: "ANALYST_NOT_CONFIGURED" } }), /dashboard is unaffected/);
  const unknown = analystErrorText(500, { detail: { code: "WEIRD", message: "<script>alert(1)</script> sk-secret" } });
  assert.doesNotMatch(unknown, /script|sk-secret/);
  assert.match(analystErrorText(422, { detail: [{ msg: "too long" }] }), /Shorten it/);
});

test("answers become plain-text paragraphs (rendered as text, never HTML)", () => {
  assert.deepEqual(answerParagraphs("One.\n\nTwo <b>bold</b>\u0007.\n\n\n"), ["One.", "Two <b>bold</b>."]);
});

test("presets reference only the page's own data-source fields", () => {
  const known = {
    attendance_curve: ["attendance", "revenue_gbp", "total_costs_gbp", "estimated_surplus_gbp", "viability"],
    material_costs: ["attendance", "cost_gbp", "material"],
    materials: ["material", "source", "pack_size", "pack_price_gbp", "packs_at_capacity", "cost_at_capacity_gbp"],
  };
  for (const preset of Object.keys(PRESET_LABELS)) {
    const widget = presetWidget(preset, "t");
    for (const refs of Object.values(widget.dataMapping)) for (const { id } of refs) {
      const [table, field] = id.split(".");
      assert.ok(known[table]?.includes(field), `${preset}: ${id}`);
    }
  }
});

test("visualizations are added once per preset on the selected page and updated in place", () => {
  const first = applyVisualizations(report(), [{ preset: "revenue_vs_costs", title: null }]);
  const p1 = first.state.pages[0];
  assert.deepEqual(first.applied, ["Analyst: Revenue, total costs (incl. est. payment fees) and estimated surplus"]);
  assert.equal(p1.widgets[analystWidgetId("revenue_vs_costs")].type, "line-chart");
  assert.deepEqual(p1.widgetLayout["analyst-revenue_vs_costs"], { xTrack: 0, yTrack: 50, xSpan: 24, ySpan: 16 }, "below existing content");
  assert.ok(p1.widgets.meter, "existing widgets kept");
  assert.deepEqual(first.state.pages[1], { ...page(), id: "other" }, "other pages untouched");
  const moved = { ...p1, widgetLayout: { ...p1.widgetLayout, "analyst-revenue_vs_costs": { xTrack: 8, yTrack: 3, xSpan: 10, ySpan: 9 } } };
  const second = applyVisualizations({ ...first.state, pages: [moved, first.state.pages[1]] }, [{ preset: "revenue_vs_costs", title: "Updated <script>" }]);
  const p2 = second.state.pages[0];
  assert.equal(Object.keys(p2.widgets).filter((k) => k.startsWith("analyst-")).length, 1, "updated, not duplicated");
  assert.equal(p2.widgets["analyst-revenue_vs_costs"].format.title.text, "Analyst: Updated script");
  assert.deepEqual(p2.widgetLayout["analyst-revenue_vs_costs"], { xTrack: 8, yTrack: 3, xSpan: 10, ySpan: 9 }, "user's position kept");
  const ignored = applyVisualizations(report(), [{ preset: "execute_sql", title: "x" }]);
  assert.deepEqual(ignored.applied, []);
  assert.equal(safeTitle("materials_table", "  a\nb  ".repeat(40)).length <= 90, true);
});
