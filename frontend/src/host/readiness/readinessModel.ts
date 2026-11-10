/**
 * Readiness timeline model. Pure: no Bryntum or DOM imports, so it is unit-tested directly.
 *
 * Every date shown comes from the owned-workshop API response. Rows are classified as:
 *  - saved:       an authoritative date or outcome persisted by the backend;
 *  - proposed:    an operational task with no authoritative date ("No saved date");
 *  - unavailable: information the backend does not have for this workshop.
 * Confirmation is taken only from the persisted campaign status, never from scenario viability.
 */
import type { Campaign, SettlementStatus, WorkshopDetail } from "../../types";

export type ReadinessTone = "scheduled" | "open" | "settled" | "pending" | "unavailable";
export type ReadinessKind = "saved" | "proposed" | "unavailable";

export interface ReadinessRow {
  id: string;
  name: string;
  tone: ReadinessTone;
  status: string;
  kind: ReadinessKind;
  /** ISO instants from the API; null when no authoritative date exists. */
  start: string | null;
  /** Null for a milestone (single instant) or an unscheduled row. */
  end: string | null;
  detail: string;
}

export interface Readiness {
  workshop: ReadinessRow;
  rows: ReadinessRow[];
  /** Span of saved dates (null when nothing is dated). */
  range: { start: string; end: string } | null;
}

export const NO_SAVED_DATE = "No saved date";
/**
 * The one zone every readiness date is presented in: list, text summary, timeline headers and task dates.
 * Saved values stay UTC instants; only presentation uses this IANA zone (GMT and BST handled by the zone rules).
 */
export const READINESS_TIME_ZONE = "Europe/London";

const time = (value: string | null | undefined) => {
  if (!value) return null;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? ms : null;
};

const WORKING_STATES = new Set(["DECIDING", "SETTLING", "RELEASING", "ABORTING", "COMPENSATING"]);

function workshopRow(detail: WorkshopDetail, campaign: Campaign | null): ReadinessRow {
  const base = { id: "workshop", name: detail.title || "Untitled workshop", kind: "saved" as const, start: null, end: null };
  if (!campaign) return { ...base, tone: "pending", status: "Draft", detail: "Not published. No bookings or payments exist." };
  if (campaign.status === "OPEN") return { ...base, tone: "open", status: "Open", detail: "Published. OPEN is publication status, not workshop or payment confirmation." };
  if (campaign.status === "CONFIRMED") return { ...base, tone: "settled", status: "Confirmed", detail: "Backend confirmed after required collections completed." };
  if (campaign.status === "CANCELLED") return { ...base, tone: "settled", status: "Cancelled", detail: "Backend cancelled the campaign." };
  return { ...base, tone: "pending", status: campaign.status, detail: "Backend settlement is in progress." };
}

function bookingWindow(detail: WorkshopDetail, campaign: Campaign | null, now: number): ReadinessRow {
  const base = { id: "booking-window", name: "Booking window", kind: "saved" as const };
  const opens = time(detail.opens_at), closes = time(detail.closes_at);
  if (opens === null || closes === null) {
    return { ...base, kind: "unavailable", tone: "unavailable", status: "Not set", start: null, end: null, detail: NO_SAVED_DATE };
  }
  const row = { ...base, start: detail.opens_at, end: detail.closes_at };
  if (!campaign) return { ...row, tone: "scheduled", status: "Draft dates", detail: "Saved in draft terms; not published." };
  const stop = Math.min(closes, time(campaign.cutoff_at) ?? closes);
  if (now < opens) return { ...row, tone: "scheduled", status: "Scheduled", detail: "Bookings have not opened yet." };
  if (now < stop && campaign.status === "OPEN") return { ...row, tone: "open", status: "Open", detail: "Accepting bookings until the cutoff." };
  return { ...row, tone: "pending", status: "Closed", detail: "No new bookings: the booking window has ended." };
}

function bookingCutoff(detail: WorkshopDetail, campaign: Campaign | null, now: number): ReadinessRow {
  const base = { id: "booking-cutoff", name: "Booking cutoff", kind: "saved" as const, end: null };
  const at = campaign?.cutoff_at ?? detail.closes_at;
  const ms = time(at);
  if (ms === null) return { ...base, kind: "unavailable", tone: "unavailable", status: "Not set", start: null, detail: NO_SAVED_DATE };
  if (!campaign) return { ...base, start: at, tone: "scheduled", status: "Draft", detail: "Draft cutoff; becomes binding only when published." };
  if (now < ms) return { ...base, start: at, tone: "scheduled", status: "Scheduled", detail: "New bookings stop at this time." };
  if (campaign.status === "OPEN" && !campaign.settlement?.decision_result) {
    return { ...base, start: at, tone: "pending", status: "Passed", detail: "Cutoff passed. Stored status is still OPEN; no deadline decision is recorded yet." };
  }
  return { ...base, start: at, tone: "settled", status: "Passed", detail: "Cutoff passed." };
}

function publication(campaign: Campaign | null): ReadinessRow {
  const base = { id: "publication", name: "Campaign publication", end: null };
  if (!campaign) return { ...base, kind: "unavailable", tone: "unavailable", status: "Not published", start: null, detail: NO_SAVED_DATE };
  if (!time(campaign.published_at)) return { ...base, kind: "unavailable", tone: "unavailable", status: "Unavailable", start: null, detail: NO_SAVED_DATE };
  return { ...base, kind: "saved", tone: "settled", status: "Published", start: campaign.published_at!, detail: "Terms frozen at publication." };
}

const DECISION_LABEL: Record<NonNullable<SettlementStatus["decision_result"]>, string> = {
  COLLECT: "Decided · collect", RELEASE: "Decided · release", REVIEW_REQUIRED: "Review required",
};

function decision(campaign: Campaign | null): ReadinessRow {
  const base = { id: "decision", name: "Deadline decision", end: null };
  if (!campaign) return { ...base, kind: "unavailable", tone: "unavailable", status: "Not published", start: null, detail: NO_SAVED_DATE };
  const settlement = campaign.settlement;
  if (!settlement) return { ...base, kind: "unavailable", tone: "unavailable", status: "Unavailable", start: null, detail: "Settlement data unavailable." };
  if (!settlement.decision_result) return { ...base, kind: "saved", tone: "pending", status: "Awaiting decision", start: null, detail: "No deadline decision recorded yet." };
  const reason = settlement.decision_reason ? settlement.decision_reason.toLowerCase().replace(/_/g, " ") : "no reason recorded";
  const attendance = settlement.frozen_attendance === null ? "" : ` · frozen attendance ${settlement.frozen_attendance}`;
  return {
    ...base, kind: "saved", start: time(settlement.decided_at) ? settlement.decided_at! : null,
    tone: settlement.decision_result === "REVIEW_REQUIRED" ? "pending" : "settled",
    status: DECISION_LABEL[settlement.decision_result],
    detail: `${reason}${attendance}`,
  };
}

function paymentSettlement(campaign: Campaign | null): ReadinessRow {
  const base = { id: "settlement", name: "Payment settlement", end: null };
  if (!campaign) return { ...base, kind: "unavailable", tone: "unavailable", status: "Not published", start: null, detail: NO_SAVED_DATE };
  const s = campaign.settlement;
  if (!s) return { ...base, kind: "unavailable", tone: "unavailable", status: "Unavailable", start: null, detail: "Settlement data unavailable." };
  const counts = `Capture pending ${s.capture_pending} · release pending ${s.release_pending} · refund pending ${s.refund_pending}`;
  const detail = s.review_required ? `${counts} · review required` : counts;
  const start = time(s.settlement_deadline) ? s.settlement_deadline : null;
  if (s.review_required) return { ...base, kind: "saved", start, tone: "pending", status: "Review required", detail };
  if (campaign.status === "CONFIRMED") return { ...base, kind: "saved", start, tone: "settled", status: "Collected", detail };
  if (campaign.status === "CANCELLED") return { ...base, kind: "saved", start, tone: "settled", status: "Released / refunded", detail };
  if (WORKING_STATES.has(campaign.status)) return { ...base, kind: "saved", start, tone: "pending", status: "In progress", detail };
  return { ...base, kind: "saved", start, tone: "pending", status: "Not started", detail };
}

const proposed = (id: string, name: string, note: string): ReadinessRow => ({
  id, name, kind: "proposed", tone: "unavailable", status: "Proposed", start: null, end: null, detail: note,
});

export function buildReadiness(detail: WorkshopDetail, now: Date = new Date()): Readiness {
  const campaign = detail.campaign ?? null;
  const at = now.getTime();
  const rows = [
    bookingWindow(detail, campaign, at),
    publication(campaign),
    bookingCutoff(detail, campaign, at),
    decision(campaign),
    paymentSettlement(campaign),
    proposed("materials", "Materials purchase readiness", "Proposed operational task; no purchasing date is stored."),
    proposed("preparation", "Preparation", "Proposed operational task; no preparation date is stored."),
    proposed("delivery", "Workshop delivery", "The workshop delivery date is not stored by the backend."),
  ];
  const instants = rows.flatMap((r) => [r.start, r.end]).map(time).filter((v): v is number => v !== null);
  const range = instants.length ? { start: new Date(Math.min(...instants)).toISOString(), end: new Date(Math.max(...instants)).toISOString() } : null;
  // The workshop row spans its saved dates (it has no date of its own).
  const workshop = { ...workshopRow(detail, campaign), start: range?.start ?? null, end: range?.end ?? null };
  return { workshop, rows, range };
}

/** Timeline window with padding; hour resolution for short campaigns (booking windows are at most 48 hours). */
export function timelineWindow(range: Readiness["range"], now: Date = new Date()) {
  const start = range ? Date.parse(range.start) : now.getTime();
  const end = range ? Date.parse(range.end) : now.getTime();
  const span = Math.max(end - start, 3600_000);
  const pad = Math.max(span * 0.15, 3600_000);
  return {
    startDate: new Date(start - pad),
    endDate: new Date(end + pad),
    viewPreset: span + 2 * pad <= 2.5 * 86400_000 ? "hourAndDay" : "weekAndDay",
  };
}

export interface GanttTaskData {
  id: string;
  name: string;
  manuallyScheduled: true;
  readOnly: true;
  cls: string;
  startDate?: string;
  endDate?: string;
  duration?: number;
  unscheduled?: true;
  expanded?: true;
  children?: GanttTaskData[];
}

/**
 * Bryntum project config: task data plus the IANA zone. Bryntum 8's default (Temporal-based) zone mode displays
 * and computes in that zone without mutating records, so task dates remain the saved UTC instants.
 */
export function ganttProject(readiness: Readiness) {
  return { timeZone: READINESS_TIME_ZONE, tasks: ganttTasks(readiness) };
}

/** Read-only Bryntum task data. No dependencies: the backend stores none between these steps. */
export function ganttTasks(readiness: Readiness): GanttTaskData[] {
  const toTask = (row: ReadinessRow): GanttTaskData => {
    const base = { id: row.id, name: row.name, manuallyScheduled: true as const, readOnly: true as const, cls: `tp-tone-${row.tone} tp-kind-${row.kind}` };
    if (!row.start) return { ...base, unscheduled: true };
    if (!row.end) return { ...base, startDate: row.start, duration: 0 };
    return { ...base, startDate: row.start, endDate: row.end };
  };
  const children = readiness.rows.map(toTask);
  const { workshop, range } = readiness;
  const parentBase = { id: workshop.id, name: workshop.name, manuallyScheduled: true as const, readOnly: true as const,
    cls: `tp-tone-${workshop.tone} tp-kind-${workshop.kind}`, expanded: true as const, children };
  return [range ? { ...parentBase, startDate: range.start, endDate: range.end } : { ...parentBase, unscheduled: true as const }];
}

const SHORT = new Intl.DateTimeFormat("en-GB", { timeZone: READINESS_TIME_ZONE, day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const DAY = new Intl.DateTimeFormat("en-GB", { timeZone: READINESS_TIME_ZONE, year: "numeric", month: "numeric", day: "numeric" });
const TIME = new Intl.DateTimeFormat("en-GB", { timeZone: READINESS_TIME_ZONE, hour: "2-digit", minute: "2-digit" });
/** Compact Europe/London label for the grid ("7 Nov, 09:30"); full timestamps are in the text summary. */
export function shortDateText(row: Pick<ReadinessRow, "start" | "end">): string | null {
  if (!row.start) return null;
  const from = new Date(row.start), start = SHORT.format(from);
  if (!row.end) return start;
  const to = new Date(row.end);
  return `${start} → ${DAY.format(from) === DAY.format(to) ? TIME.format(to) : SHORT.format(to)}`;
}

export const readinessPath = (workshopId: string) => `/host/workshops/${encodeURIComponent(workshopId)}/readiness`;
