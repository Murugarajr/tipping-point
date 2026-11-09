import type { DraftPayload, MaterialInput, SettlementStatus, ViabilityPreview, WorkshopDetail } from "../types";

export const sections = ["basics", "materials", "economics", "review"] as const;
export type Section = typeof sections[number];
export const workshopRoute = /^\/host\/workshops\/(new|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i;
/** Read-only AG Studio Campaign Intelligence page for one saved workshop. */
export const intelligenceRoute = /^\/host\/workshops\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\/intelligence$/i;
/** Read-only Bryntum readiness timeline for one saved workshop. */
export const readinessRoute = /^\/host\/workshops\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\/readiness$/i;

export function safeHostReturn(value: string | null): string {
  if (!value || !/^\/host(?:\/|$)/.test(value) || value.includes("\\") || value.startsWith("//")) return "/host";
  const url = new URL(value, "http://internal.invalid");
  if (url.origin !== "http://internal.invalid" || url.search
    || (url.pathname !== "/host" && url.pathname !== "/host/console" && !workshopRoute.test(url.pathname) && !intelligenceRoute.test(url.pathname) && !readinessRoute.test(url.pathname))) return "/host";
  if (url.pathname === "/host/console" || intelligenceRoute.test(url.pathname) || readinessRoute.test(url.pathname)) return url.pathname;
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
/**
 * datetime-local values carry no UTC offset. During a clock change a wall time can be
 * repeated (two instants) or skipped (no instant); either would be saved as a silently
 * shifted instant. Detect both so the editor can refuse to save instead of guessing.
 */
export function clockChangeIssue(value: string): "ambiguous" | "nonexistent" | null {
  const instant = new Date(value).getTime();
  if (!value || !Number.isFinite(instant)) return null;
  const normalized = value.length === 16 ? `${value}:00.000` : value.length === 19 ? `${value}.000` : value;
  if (localDate(new Date(instant)) !== normalized) return "nonexistent";
  for (const shift of [-3_600_000, -1_800_000, 1_800_000, 3_600_000]) {
    if (localDate(new Date(instant + shift)) === normalized) return "ambiguous";
  }
  return null;
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

/** Local Sandbox test preset. Computed from the click instant (never module load); fills draft inputs only. */
export function sandboxShortWindow(clickedAt: Date): DraftPayload["schedule"] {
  const instant = clickedAt.getTime();
  if (!Number.isFinite(instant)) throw new Error("invalid preset instant");
  return { opens_at: localDate(new Date(instant - 60_000)), closes_at: localDate(new Date(instant + 15 * 60_000)) };
}

const londonDay = (value: Date) => new Intl.DateTimeFormat("en-CA", {
  timeZone: "Europe/London", year: "numeric", month: "2-digit", day: "2-digit",
}).format(value);
const londonTime = (value: Date) => new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/London", hour: "2-digit", minute: "2-digit", second: "2-digit", timeZoneName: "short",
}).format(value);
const shiftDay = (day: string, days: number) => {
  const date = new Date(`${day}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
};

export function formatDuration(ms: number): string {
  const total = Math.round(Math.abs(ms) / 1000);
  const days = Math.floor(total / 86400), hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60), seconds = total % 60;
  const parts = [days && `${days} day${days === 1 ? "" : "s"}`, hours && `${hours} h`, minutes && `${minutes} min`,
    !days && !hours && seconds && `${seconds} s`].filter(Boolean);
  return parts.length ? parts.join(" ") : "0 s";
}

/** "today", "tomorrow", "yesterday", or an explicit date, by London calendar day. */
export function relativeDay(target: Date, now: Date): string {
  const day = londonDay(target), today = londonDay(now);
  if (day === today) return "today";
  if (day === shiftDay(today, 1)) return "tomorrow";
  if (day === shiftDay(today, -1)) return "yesterday";
  return `on ${new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/London", weekday: "short", day: "numeric", month: "short", year: "numeric" }).format(target)}`;
}

export interface ScheduleSummary { opens: string; closes: string; opensPhrase: string; closesPhrase: string; duration: string; remaining: string }

/** Human-readable cross-check of the exact instants the draft will send; null when either field is not a valid date. */
export function scheduleSummary(schedule: DraftPayload["schedule"], now: Date): ScheduleSummary | null {
  const opens = new Date(schedule.opens_at), closes = new Date(schedule.closes_at);
  if (!schedule.opens_at || !schedule.closes_at || !Number.isFinite(opens.getTime()) || !Number.isFinite(closes.getTime())) return null;
  const left = closes.getTime() - now.getTime();
  return {
    opens: displayDate(opens.toISOString()), closes: displayDate(closes.toISOString()),
    opensPhrase: `${opens.getTime() <= now.getTime() ? "Opened" : "Opens"} ${relativeDay(opens, now)} at ${londonTime(opens)}`,
    closesPhrase: `${left <= 0 ? "Closed" : "Closes"} ${relativeDay(closes, now)} at ${londonTime(closes)}`,
    duration: closes.getTime() > opens.getTime() ? formatDuration(closes.getTime() - opens.getTime()) : "Invalid: cutoff is not after opening",
    remaining: left > 0 ? `${formatDuration(left)} until cutoff` : "Cutoff has passed",
  };
}

/** Headline never shows completed cleanup or confirmation that the saved state does not support. */
export function settlementHeadline(status: SettlementStatus): string {
  const cleanup = status.sandbox_cleanup;
  if (cleanup) {
    if (cleanup.status === "REFUNDED" && status.state === "CANCELLED") return "Test campaign cancelled; full Sandbox refund verified";
    if (cleanup.status === "REVIEW_REQUIRED") return "Test campaign cancelled; refund requires operator review";
    return "Test campaign cancelled; refund processing";
  }
  if (status.state === "CONFIRMED") return "Workshop financially confirmed";
  if (status.state === "CANCELLED") return "Campaign cancelled after cleanup";
  return `Campaign ${status.state.toLowerCase()}`;
}

/** Exact confirmation copy for Hide from discovery (listing metadata only). */
export const HIDE_FROM_DISCOVERY_EXPLANATION =
  "Hides this workshop from browsing. Existing links and bookings remain valid. This does not cancel the workshop or its payments.";
export const VISIBILITY_NOT_ACCESS_CONTROL = "Visibility is not a privacy or access-control setting: anyone with the link can still open it.";

export function visibilityLabel(hiddenAt: string | null | undefined): string {
  return hiddenAt ? `Hidden from discovery since ${displayDate(hiddenAt)}` : "Listed in public browsing";
}
