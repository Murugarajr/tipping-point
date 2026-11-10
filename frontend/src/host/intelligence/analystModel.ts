/**
 * Rescue Analyst browser-side model. Pure: no AG Studio or DOM imports, so it is unit-tested directly.
 *
 * The model/tool loop runs on the server. The browser only:
 *  - sends bounded, untrusted conversation text;
 *  - applies server-validated visualization presets to the Studio report via the public
 *    getState()/setState() API, building widget state from the fixed templates below.
 * Nothing the browser does is sent back to the model, and widget data always comes from the
 * page's own sanitised data sources (never from model output).
 */

export type VisualizationPreset = "revenue_vs_costs" | "surplus_by_attendance" | "material_cost_by_attendance" | "attendance_table" | "materials_table";

export interface AnalystStatus {
  available: boolean;
  status: "ready" | "disabled" | "missing_key" | "missing_model" | "misconfigured";
  provider: string | null;
  model: string | null;
}
export interface AnalystActivity { tool: string; status: "ok" | "rejected" | "limit"; summary: string }
export interface AnalystVisualization { preset: VisualizationPreset; title: string | null }
export interface AnalystAnswer {
  status: "answered" | "limit_reached";
  answer: string;
  activity: AnalystActivity[];
  visualizations: AnalystVisualization[];
  provider: string;
  model: string;
  rounds: number;
  tool_calls: number;
}
export interface ChatMessage { role: "user" | "assistant"; content: string }

export const SUGGESTED_QUESTIONS = [
  "Explain this workshop's tipping point.",
  "Why can attendance five be non-viable when four is viable?",
  "Show revenue versus total costs.",
  "Which materials drive the budget?",
] as const;

export const MAX_MESSAGE_CHARS = 2000;
const MAX_MESSAGES = 12;
const MAX_HISTORY_CHARS = 12000;

/** Most recent turns only, within the server's limits; the newest message is always the user's question. */
export function boundedHistory(turns: ChatMessage[], question: string): ChatMessage[] {
  const next: ChatMessage[] = [...turns, { role: "user" as const, content: question.slice(0, MAX_MESSAGE_CHARS) }]
    .map((m): ChatMessage => ({ role: m.role, content: m.content.slice(0, MAX_MESSAGE_CHARS) }))
    .filter((m) => m.content.trim().length > 0);
  let kept = next.slice(-MAX_MESSAGES);
  while (kept.length > 1 && kept.reduce((n, m) => n + m.content.length, 0) > MAX_HISTORY_CHARS) kept = kept.slice(1);
  while (kept.length > 1 && kept[0].role !== "user") kept = kept.slice(1);
  return kept;
}

const STATUS_COPY: Record<AnalystStatus["status"], string> = {
  ready: "Ready.",
  disabled: "Analyst not configured: an operator has not enabled it on the server.",
  missing_key: "Analyst not configured: the server has no credential for the selected provider.",
  missing_model: "Analyst not configured: the server has no model selected.",
  misconfigured: "Analyst not configured: a server setting is invalid; an operator must correct it.",
};
export const statusText = (status: AnalystStatus) => STATUS_COPY[status.status];
export const connectionLabel = (status: Pick<AnalystStatus, "provider" | "model">) =>
  status.provider && status.model ? `${status.provider} · ${status.model}` : status.provider ?? "Not configured";

const ERROR_COPY: Record<string, string> = {
  ANALYST_NOT_CONFIGURED: "Analyst not configured on this server. The dashboard is unaffected.",
  ANALYST_BUSY: "An analyst request is already running for your account. Wait for it to finish.",
  ANALYST_RATE_LIMITED: "Too many analyst requests. Try again in a few minutes.",
  PROVIDER_RATE_LIMITED: "The model provider is rate limiting requests. Try again shortly.",
  PROVIDER_TIMEOUT: "The model provider did not answer in time. Nothing was changed.",
  PROVIDER_AUTH: "The model provider rejected the server's credentials. An operator must check the configuration.",
  MODEL_UNSUPPORTED: "The configured model is not available with tool calling. An operator must choose another model.",
  MODEL_MISMATCH: "The provider reported a model other than the configured one, so the answer was discarded.",
  PROVIDER_NO_ENDPOINT: "No provider endpoint for the configured model accepted this request. Nothing was changed; an operator must check the analyst request settings.",
  PROVIDER_BAD_RESPONSE: "The model provider returned an unusable response. Nothing was changed.",
  PROVIDER_ERROR: "The model provider returned an error. Nothing was changed.",
};

/** Maps a sanitised server error to fixed copy; unknown or malformed details never reach the page. */
export function analystErrorText(status: number | null, detail: unknown): string {
  const code = detail && typeof detail === "object" && "detail" in detail && (detail as { detail: unknown }).detail
    && typeof (detail as { detail: { code?: unknown } }).detail === "object" ? (detail as { detail: { code?: unknown } }).detail.code : null;
  if (typeof code === "string" && code in ERROR_COPY) return ERROR_COPY[code];
  if (status === 422) return "That question could not be sent. Shorten it and try again.";
  if (status === 404) return "This workshop is not available in your workspace.";
  if (status === 403) return "The request was refused. Reload the page and try again.";
  return "The analyst could not answer right now. The dashboard is unaffected.";
}

/** Plain-text paragraphs; rendered as React text (no HTML, no links). Control characters are removed. */
export function answerParagraphs(answer: string): string[] {
  return answer.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, "").split(/\n{2,}/).map((p) => p.trim()).filter(Boolean);
}

export const PRESET_LABELS: Record<VisualizationPreset, string> = {
  revenue_vs_costs: "Revenue, total costs (incl. est. payment fees) and estimated surplus",
  surplus_by_attendance: "Estimated surplus by attendance",
  material_cost_by_attendance: "Material cost by attendance",
  attendance_table: "Attendance curve (backend viability per point)",
  materials_table: "Materials breakdown",
};

const f = (id: string, aggregation?: "sum") => aggregation ? { id, aggregation } : { id };

/** Fixed Studio widget templates over the page's own data sources. */
export function presetWidget(preset: VisualizationPreset, title: string) {
  const format = { title: { text: title, enabled: true } };
  switch (preset) {
    case "revenue_vs_costs": return { type: "line-chart", format, dataMapping: {
      categoryKey: [f("attendance_curve.attendance")],
      valueKey: [f("attendance_curve.revenue_gbp", "sum"), f("attendance_curve.total_costs_gbp", "sum"), f("attendance_curve.estimated_surplus_gbp", "sum")] } };
    case "surplus_by_attendance": return { type: "column-chart-grouped", format, dataMapping: {
      categoryKey: [f("attendance_curve.attendance")], valueKey: [f("attendance_curve.estimated_surplus_gbp", "sum")] } };
    case "material_cost_by_attendance": return { type: "column-chart-stacked", format, dataMapping: {
      categoryKey: [f("material_costs.attendance")], valueKey: [f("material_costs.cost_gbp", "sum")], legendKey: [f("material_costs.material")] } };
    case "attendance_table": return { type: "grid", format, dataMapping: {
      cols: [f("attendance_curve.attendance"), f("attendance_curve.viability"), f("attendance_curve.revenue_gbp"), f("attendance_curve.total_costs_gbp"), f("attendance_curve.estimated_surplus_gbp")] } };
    case "materials_table": return { type: "grid", format, dataMapping: {
      cols: [f("materials.material"), f("materials.source"), f("materials.pack_size"), f("materials.pack_price_gbp"), f("materials.packs_at_capacity"), f("materials.cost_at_capacity_gbp")] } };
  }
}

export const analystWidgetId = (preset: VisualizationPreset) => `analyst-${preset}`;
const PRESETS = new Set<string>(Object.keys(PRESET_LABELS));

export function safeTitle(preset: VisualizationPreset, title: string | null): string {
  const clean = (title ?? "").replace(/[\u0000-\u001f\u007f<>]/g, "").replace(/\s+/g, " ").trim().slice(0, 80);
  return clean ? `Analyst: ${clean}` : `Analyst: ${PRESET_LABELS[preset]}`;
}

interface Layout { xTrack: number; yTrack: number; xSpan: number; ySpan: number }
interface PageLike { id: string; widgets?: Record<string, unknown>; widgetLayout?: Record<string, Layout | undefined> }
interface ReportLike { selectedPageId: string; pages: PageLike[] }

/**
 * Adds or updates analyst widgets (stable id per preset) on the selected page. Unknown presets are
 * ignored. Existing analyst widgets keep their position; new ones are appended below the content.
 */
export function applyVisualizations<T extends ReportLike>(state: T, visualizations: AnalystVisualization[]): { state: T; applied: string[] } {
  const applied: string[] = [];
  const pages = state.pages.map((page) => {
    if (page.id !== state.selectedPageId) return page;
    const widgets = { ...(page.widgets ?? {}) };
    const layout = { ...(page.widgetLayout ?? {}) };
    for (const viz of visualizations) {
      if (!PRESETS.has(viz.preset)) continue;
      const id = analystWidgetId(viz.preset);
      const title = safeTitle(viz.preset, viz.title);
      widgets[id] = presetWidget(viz.preset, title);
      if (!layout[id]) {
        const bottom = Object.values(layout).reduce((max, l) => l ? Math.max(max, l.yTrack + l.ySpan) : max, 0);
        layout[id] = { xTrack: 0, yTrack: bottom, xSpan: 24, ySpan: 16 };
      }
      applied.push(title);
    }
    return { ...page, widgets, widgetLayout: layout };
  });
  return { state: { ...state, pages }, applied };
}
