import type { DraftPayload, MaterialInput, ViabilityPreview, WorkshopDetail } from "../types";

export const sections = ["basics", "materials", "economics", "review"] as const;
export type Section = typeof sections[number];
export const workshopRoute = /^\/host\/workshops\/(new|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i;

export function safeHostReturn(value: string | null): string {
  if (!value || !/^\/host(?:\/|$)/.test(value) || value.includes("\\") || value.startsWith("//")) return "/host";
  const url = new URL(value, "http://internal.invalid");
  if (url.origin !== "http://internal.invalid" || url.search || (url.pathname !== "/host" && !workshopRoute.test(url.pathname))) return "/host";
  return url.pathname + (sections.includes(url.hash.slice(1) as Section) ? url.hash : "");
}
export function poundsToMinor(raw: string): number | null {
  if (!/^\d+(?:\.\d{1,2})?$/.test(raw)) return null;
  const [whole, fraction = ""] = raw.split(".");
  const minor = Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
  return Number.isSafeInteger(minor) ? minor : null;
}
export const minorToPounds = (minor: number) => `${Math.floor(minor / 100)}.${String(minor % 100).padStart(2, "0")}`;
export const money = (minor: number) => new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP" }).format(minor / 100);
export const displayDate = (value: string | null) => value ? new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/London", year: "numeric", month: "short", day: "numeric",
  hour: "2-digit", minute: "2-digit", second: "2-digit", timeZoneName: "short",
}).format(new Date(value)) : "Not set";
export function localDate(value: string | Date): string {
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 23);
}
export function defaultDraft(): DraftPayload {
  return {
    title: "", description: "",
    financials: {
      currency: "GBP", ticket_price_minor: 0, capacity: 8, minimum_operating_attendance: 1,
      fixed_costs_minor: 0, materials: [], shipping_allowance_minor: 0,
      shipping_allowance_source: "merchant-entered estimate", contingency_minor: 0,
      fee_estimate: { percent_basis_points: 249, fixed_minor: 30, label: "merchant-entered-conservative-estimate" },
    },
    schedule: { opens_at: localDate(new Date(Date.now() + 3600000)), closes_at: localDate(new Date(Date.now() + 90000000)) },
  };
}
export function draftFromDetail(detail: WorkshopDetail): DraftPayload {
  return {
    title: detail.title, description: detail.description ?? "",
    financials: {
      ...detail.financials,
      materials: detail.financials.materials.map(({ offer_provenance, ...line }) => ({
        ...line, ...(offer_provenance ? { selected_offer_snapshot_id: offer_provenance.offer_snapshot_id } : {}),
      })),
    },
    schedule: { opens_at: detail.opens_at ? localDate(detail.opens_at) : "", closes_at: detail.closes_at ? localDate(detail.closes_at) : "" },
  };
}
export function payloadForSave(draft: DraftPayload): DraftPayload {
  return { ...draft, title: draft.title.trim(), schedule: {
    opens_at: new Date(draft.schedule.opens_at).toISOString(), closes_at: new Date(draft.schedule.closes_at).toISOString(),
  } };
}

export const firstViableLabel = (preview: ViabilityPreview | null) =>
  preview ? preview.first_viable_attendance ?? "None" : "Not calculated";

// Advisory completeness only; the backend is the publication authority.
export function publicationSetupIssues(detail: WorkshopDetail | null): string[] {
  if (!detail) return ["Save the draft before publishing."];
  const issues: string[] = [];
  if (!detail.title.trim()) issues.push("Add a workshop title in Basics.");
  if (detail.financials.ticket_price_minor <= 0) issues.push("Set a ticket price above £0.00 in Basics.");
  if (!detail.financials.fee_estimate) issues.push("Add and review explicit fee assumptions in Economics.");
  if (!detail.opens_at || !detail.closes_at) issues.push("Add booking dates in Basics.");
  return issues;
}
export function savedTermsKey(detail: WorkshopDetail | null): string | null {
  return detail?.terms_snapshot_hash ? `${detail.workshop_id}:${detail.terms_version}:${detail.terms_snapshot_hash}` : null;
}
export function previewMatchesSaved(detail: WorkshopDetail | null, preview: ViabilityPreview | null): boolean {
  return Boolean(savedTermsKey(detail) && preview
    && preview.terms_version === detail!.terms_version
    && preview.terms_snapshot_hash === detail!.terms_snapshot_hash);
}
export function materialIsSaved(line: MaterialInput, detail: WorkshopDetail | null): boolean {
  const saved = detail ? draftFromDetail(detail).financials.materials.find((item) => item.name === line.name) : null;
  return Boolean(saved && JSON.stringify(saved) === JSON.stringify(line));
}
export function draftDateLabel(value: string): string {
  return value && Number.isFinite(new Date(value).getTime()) ? displayDate(new Date(value).toISOString()) : "Not set";
}
