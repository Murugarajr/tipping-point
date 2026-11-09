import { useEffect, useMemo } from "react";
import { AgStudio, AgStudioProvider, createWidgets } from "ag-studio-react";
import type { AgRegistry, AgWidgetDefinition } from "ag-studio-react";
import { enableStudioDevValidations } from "ag-studio";
import type { AgDataSourcesDefinition, AgDefaultWidgetDefinition, AgFieldDefinition, AgReportState, AgStudioApi, AgStudioMode, AgStudioProperties, AgWidgetFormParams } from "ag-studio";
import TippingMeter from "./TippingMeter";
import type { TippingMeterState } from "./TippingMeter";
import type { IntelligenceData } from "./intelligenceModel";

if (import.meta.env.DEV) enableStudioDevValidations();

/**
 * Licence: applied exactly as AG Studio documents, via `<AgStudioProvider licenseKey>`.
 * The key is read from a Vite env var (frontend/.env.local, git-ignored), so it is never committed.
 * Without it AG Studio runs with the vendor's watermark and console warning (documented local testing).
 */
const LICENSE_KEY: string | undefined = import.meta.env.VITE_AG_STUDIO_LICENSE_KEY || undefined;
export const studioLicensed = Boolean(LICENSE_KEY);

type MeterDefinition = AgWidgetDefinition<"tipping-meter", TippingMeterState>;
interface IntelligenceRegistry extends AgRegistry {
  widgets: readonly (AgDefaultWidgetDefinition | MeterDefinition)[];
}

const gbp = { format: new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP" }) };
const NA = "Not available";
type Field = AgFieldDefinition<IntelligenceRegistry>;
const text = (id: string, name: string, description?: string): Field => ({ id, name, description, format: "textFormat", blankValue: NA });
const int = (id: string, name: string, description?: string): Field => ({ id, name, description, format: "integerFormat", blankValue: NA });
const money = (id: string, name: string, description?: string): Field => ({ id, name, description, format: "currencyFormat", formatOptions: gbp, blankValue: NA });

const meterDefinition: MeterDefinition = {
  id: "tipping-meter",
  label: "Tipping Meter",
  icon: { className: "tp-meter-icon" },
  dataMapping: {
    capacity: { type: "field", supportedRoles: ["numeric"], requires: { cardinality: "one" }, required: true, aiDescription: "Campaign capacity (places)." },
    threshold: { type: "field", supportedRoles: ["numeric"], requires: { cardinality: "one" }, required: true, aiDescription: "Backend-viable target attendance." },
    admitted: { type: "field", supportedRoles: ["numeric"], requires: { cardinality: "one" }, aiDescription: "Admitted bookings; blank when unavailable." },
    authorized: { type: "field", supportedRoles: ["numeric"], requires: { cardinality: "one" }, aiDescription: "Authorised amount, not collected." },
    collected: { type: "field", supportedRoles: ["numeric"], requires: { cardinality: "one" }, aiDescription: "Collected amount." },
    state: { type: "field", supportedRoles: ["category"], aiDescription: "Tipping state label." },
  },
  form: (params: AgWidgetFormParams<TippingMeterState>) => params.createDefaults({
    dataMappingItems: [
      { key: "capacity", label: "Capacity" }, { key: "threshold", label: "Target attendance" },
      { key: "admitted", label: "Admitted bookings" }, { key: "authorized", label: "Authorised (not collected)" },
      { key: "collected", label: "Collected" }, { key: "state", label: "Tipping state" },
    ],
  }),
  comp: TippingMeter,
  defaultSize: { width: 420, height: 300 },
  minSize: { width: 280, height: 220 },
  ai: {
    label: "Tipping Meter",
    description: "Shows admitted bookings against the backend-viable target attendance and capacity, with authorised and collected amounts kept separate.",
  },
};

const widgets: AgStudioProperties<IntelligenceRegistry>["widgets"] = (defaults) => createWidgets<IntelligenceRegistry>({
  additionalTypes: [meterDefinition],
  menu: [...defaults.menu, { label: "Tipping Point", widgetIds: ["tipping-meter"] }],
});

export function dataSources(data: IntelligenceData): AgDataSourcesDefinition<IntelligenceRegistry> {
  return {
    description: "Sanitised Tipping Point campaign data from the authenticated merchant API and the backend calculator. Money in GBP.",
    sources: [
      {
        id: "campaign_health", name: "Campaign health", description: "One row: current tipping position. Bookings and payment fields are blank when unavailable.",
        data: [{ ...data.health }],
        fields: [
          text("workshop", "Workshop"), int("terms_version", "Terms version"), text("publication", "Publication status"),
          text("tipping_state", "Tipping state"), int("capacity", "Capacity"), int("minimum_operating_attendance", "Minimum operating attendance"),
          int("first_viable_attendance", "First viable attendance"), text("viable_at_capacity", "Viable at capacity"),
          int("admitted_attendance", "Admitted bookings", "From the settlement projection; blank when not published or unavailable."),
          int("next_viable_attendance", "Next viable attendance"), int("target_attendance", "Target attendance"),
          int("places_still_required", "Places still required"), text("viable_at_current_attendance", "Viable at current attendance"),
          money("estimated_surplus_at_current_gbp", "Estimated surplus at current attendance"),
          money("authorized_gbp", "Authorised (not collected)"), money("collected_gbp", "Collected"), text("cutoff_at", "Cutoff (UTC)"),
          text("booking_window", "Booking window", "Time-based: new bookings stop at the cutoff. Separate from financial viability."),
        ],
      },
      {
        id: "attendance_curve", name: "Attendance curve", description: "Backend calculator output per attendance. Viability is per point; pack-cost steps can make higher attendance non-viable.",
        data: data.attendance.map((row) => ({ ...row })),
        fields: [
          int("attendance", "Attendance"), money("revenue_gbp", "Revenue"), money("fees_gbp", "Estimated fees"), money("net_revenue_gbp", "Net revenue"),
          money("material_cost_gbp", "Material cost"), money("fixed_and_other_costs_gbp", "Fixed, shipping & contingency"),
          money("approved_budget_gbp", "Approved budget (excl. est. payment fees)"),
          money("total_costs_gbp", "Total costs (incl. est. payment fees)"), money("estimated_surplus_gbp", "Estimated surplus"), text("viability", "Viability"),
        ],
      },
      {
        id: "materials", name: "Materials", description: "Saved material lines. Source states whether each is a merchant assumption or a reviewed Channel3 snapshot.",
        data: data.materials.map((row) => ({ ...row })),
        fields: [
          text("material", "Material"), text("kind", "Kind"), text("source", "Source"), int("pack_size", "Pack size"),
          money("pack_price_gbp", "Pack price"), int("shared_units", "Shared units"), int("per_attendee_units", "Units per attendee"),
          int("packs_at_capacity", "Packs at capacity"), money("cost_at_capacity_gbp", "Cost at capacity"),
        ],
      },
      {
        id: "material_costs", name: "Material cost by attendance", description: "Backend pack counts × saved pack price, per material and attendance.",
        data: data.materialCosts.map((row) => ({ ...row })),
        fields: [int("attendance", "Attendance"), text("material", "Material"), int("packs", "Packs"), money("cost_gbp", "Cost")],
      },
    ],
  };
}

const f = (id: string, aggregation?: "sum" | "max") => aggregation ? { id, aggregation } : { id };
const title = (text: string) => ({ title: { text, enabled: true } });

export function defaultReport(): AgReportState<IntelligenceRegistry> {
  return {
    selectedPageId: "intelligence",
    panels: { filters: { collapsed: true }, data: { collapsed: true } },
    pages: [{
      id: "intelligence",
      widgets: {
        meter: {
          type: "tipping-meter",
          dataMapping: {
            capacity: [f("campaign_health.capacity", "max")], threshold: [f("campaign_health.target_attendance", "max")],
            admitted: [f("campaign_health.admitted_attendance", "max")], authorized: [f("campaign_health.authorized_gbp", "max")],
            collected: [f("campaign_health.collected_gbp", "max")], state: [f("campaign_health.tipping_state")],
          },
        },
        curve: {
          type: "line-chart", format: title("Revenue, total costs (incl. est. payment fees) and estimated surplus by attendance"),
          dataMapping: {
            categoryKey: [f("attendance_curve.attendance")],
            valueKey: [f("attendance_curve.revenue_gbp", "sum"), f("attendance_curve.total_costs_gbp", "sum"), f("attendance_curve.estimated_surplus_gbp", "sum")],
          },
        },
        curveTable: {
          type: "grid", format: title("Attendance curve (backend viability per point)"),
          dataMapping: { cols: [f("attendance_curve.attendance"), f("attendance_curve.viability"), f("attendance_curve.revenue_gbp"), f("attendance_curve.total_costs_gbp"), f("attendance_curve.estimated_surplus_gbp")] },
        },
        materialCost: {
          type: "column-chart-stacked", format: title("Material cost by attendance"),
          dataMapping: { categoryKey: [f("material_costs.attendance")], valueKey: [f("material_costs.cost_gbp", "sum")], legendKey: [f("material_costs.material")] },
        },
        materials: {
          type: "grid", format: title("Materials breakdown"),
          dataMapping: { cols: [f("materials.material"), f("materials.source"), f("materials.pack_size"), f("materials.pack_price_gbp"), f("materials.packs_at_capacity"), f("materials.cost_at_capacity_gbp")] },
        },
      },
      widgetLayout: {
        meter: { xTrack: 0, yTrack: 0, xSpan: 8, ySpan: 18 },
        curve: { xTrack: 8, yTrack: 0, xSpan: 16, ySpan: 18 },
        curveTable: { xTrack: 0, yTrack: 18, xSpan: 12, ySpan: 20 },
        materialCost: { xTrack: 12, yTrack: 18, xSpan: 12, ySpan: 20 },
        materials: { xTrack: 0, yTrack: 38, xSpan: 24, ySpan: 12 },
      },
    }],
  } as AgReportState<IntelligenceRegistry>;
}

/** Studio's public API, handed to the page so analyst presets can be applied with getState/setState. */
export type IntelligenceStudioApi = AgStudioApi<IntelligenceRegistry>;

export default function StudioDashboard({ data, mode, onApi }: { data: IntelligenceData; mode: AgStudioMode; onApi?: (api: IntelligenceStudioApi | null) => void }) {
  const sources = useMemo(() => dataSources(data), [data]);
  const initialState = useMemo(() => defaultReport(), []);
  useEffect(() => () => onApi?.(null), []);
  return <AgStudioProvider licenseKey={LICENSE_KEY}>
    <AgStudio<IntelligenceRegistry>
      className="tp-studio"
      style={{ width: "100%", height: "100%" }}
      data={sources}
      initialState={initialState}
      widgets={widgets}
      mode={mode}
      onApiReady={(event) => onApi?.(event.api as IntelligenceStudioApi)}
    />
  </AgStudioProvider>;
}
