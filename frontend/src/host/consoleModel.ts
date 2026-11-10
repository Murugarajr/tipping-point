// Explicit .ts paths let Node's type-stripping test runner load this module directly.
import * as api from "../api.ts";
import type { HostVisibilityFilter, Workshop, WorkshopDetail } from "../types";
import { displayDate, money } from "./model.ts";

/**
 * Read-only merchant console model. Only GET helpers are referenced here:
 * listWorkshops and getWorkshop. Nothing in this module may call a mutating endpoint.
 */

export const CONSOLE_FILTERS: { value: HostVisibilityFilter; label: string }[] = [
  { value: "all", label: "All" }, { value: "listed", label: "Listed" }, { value: "hidden", label: "Hidden from discovery" },
];
export const DEFAULT_CONSOLE_FILTER: HostVisibilityFilter = "all";
export const DETAIL_CONCURRENCY = 4;

export const SEATS_NOTE = "Derived; excludes in-progress reservation holds.";
export const SETTLEMENT_NOTE = "Settlement outcome; not the work-queue state.";
export const UNAVAILABLE = "Unavailable";
export const NOT_AVAILABLE = "Not available";
export const NOT_PUBLISHED = "Not published";

/**
 * Per-cell value. "unavailable" = the detail request failed (never guessed);
 * "not_available" = the backend returned no settlement projection;
 * "not_published" = draft, no campaign exists.
 */
export type Cell<T> =
  | { kind: "value"; value: T }
  | { kind: "unavailable" }
  | { kind: "not_available" }
  | { kind: "not_published" };

export interface ConsoleRow {
  workshopId: string;
  title: string;
  workbenchHref: string;
  detail: "not_needed" | "loaded" | "failed";
  status: Cell<string>;
  hiddenSince: string | null;
  opensAt: string | null;
  cutoff: Cell<{ at: string | null; planned: boolean }>;
  capacity: Cell<number>;
  bookings: Cell<number>;
  seatsAvailable: Cell<number>;
  settlement: Cell<{ decision: string | null; deadline: string | null }>;
  priceMinor: number;
}

const value = <T>(v: T): Cell<T> => ({ kind: "value", value: v });
const unavailable = { kind: "unavailable" } as const;
const notAvailable = { kind: "not_available" } as const;
const notPublished = { kind: "not_published" } as const;

export const workbenchHref = (workshopId: string) => `/host/workshops/${encodeURIComponent(workshopId)}`;
export const needsDetail = (workshop: Workshop) => Boolean(workshop.campaign_id);

/** Map the list row plus its (optional) detail. `detail` undefined = not requested; null = request failed. */
export function toConsoleRow(workshop: Workshop, detail?: WorkshopDetail | null): ConsoleRow {
  const base = {
    workshopId: workshop.workshop_id,
    title: workshop.title,
    workbenchHref: workbenchHref(workshop.workshop_id),
    hiddenSince: workshop.hidden_from_discovery_at ?? null,
    opensAt: workshop.opens_at,
    priceMinor: workshop.ticket_price_minor,
  };
  if (!needsDetail(workshop)) {
    return {
      ...base, detail: "not_needed",
      status: value(workshop.is_frozen ? "Published · no campaign" : "Draft"),
      cutoff: value({ at: workshop.closes_at, planned: true }),
      capacity: value(workshop.capacity),
      bookings: notPublished, seatsAvailable: notPublished, settlement: notPublished,
    };
  }
  if (detail === undefined || detail === null) {
    return {
      ...base, detail: "failed",
      status: unavailable, cutoff: unavailable, capacity: unavailable,
      bookings: unavailable, seatsAvailable: unavailable, settlement: unavailable,
    };
  }
  const campaign = detail.campaign;
  if (!campaign) {
    return {
      ...base, detail: "loaded",
      status: value(workshop.is_frozen ? "Published · no campaign" : "Draft"),
      cutoff: value({ at: detail.closes_at, planned: true }),
      capacity: value(detail.capacity),
      bookings: notPublished, seatsAvailable: notPublished, settlement: notPublished,
    };
  }
  const settlement = campaign.settlement;
  return {
    ...base, detail: "loaded",
    status: value(campaign.status),
    cutoff: value({ at: campaign.cutoff_at, planned: false }),
    capacity: value(campaign.capacity),
    bookings: settlement ? value(settlement.admitted_attendance) : notAvailable,
    // Derived; never clamped, so an anomaly stays visible rather than hidden.
    seatsAvailable: settlement ? value(campaign.capacity - settlement.admitted_attendance) : notAvailable,
    settlement: settlement
      ? value({ decision: settlement.decision_result, deadline: settlement.settlement_deadline })
      : notAvailable,
  };
}

function cellText<T>(cell: Cell<T>, format: (v: T) => string): string {
  switch (cell.kind) {
    case "value": return format(cell.value);
    case "unavailable": return UNAVAILABLE;
    case "not_available": return NOT_AVAILABLE;
    case "not_published": return NOT_PUBLISHED;
  }
}

export const visibilityText = (row: ConsoleRow) => row.hiddenSince ? "Hidden from discovery" : "Listed";
/** Visibility cell tooltip: the hide timestamp for hidden rows; undefined (no tooltip) for listed or missing rows. */
export const visibilityTooltip = (row: ConsoleRow | undefined): string | undefined =>
  row?.hiddenSince ? `Hidden since ${displayDate(row.hiddenSince)}` : undefined;
export const statusText = (row: ConsoleRow) => cellText(row.status, (s) => s);
export const cutoffText = (row: ConsoleRow) =>
  cellText(row.cutoff, ({ at, planned }) => `${displayDate(at)}${planned && at ? " (planned)" : ""}`);
export const countText = (cell: Cell<number>) => cellText(cell, (n) => String(n));
export const priceText = (row: ConsoleRow) => row.priceMinor > 0 ? money(row.priceMinor) : "Price not set";
export const settlementText = (row: ConsoleRow) => cellText(row.settlement, ({ decision, deadline }) =>
  `${decision ?? "No decision yet"} · ${deadline ? `deadline ${displayDate(deadline)}` : "no deadline set"}`);

/** Numeric value for sorting/filtering; null for any non-value cell. */
export const cellNumber = (cell: Cell<number>): number | null => cell.kind === "value" ? cell.value : null;
export const cutoffInstant = (row: ConsoleRow): Date | null =>
  row.cutoff.kind === "value" && row.cutoff.value.at ? new Date(row.cutoff.value.at) : null;
export const opensInstant = (row: ConsoleRow): Date | null => row.opensAt ? new Date(row.opensAt) : null;

type Sortable = number | string | Date | null | undefined;
const key = (v: Sortable) => v instanceof Date ? v.getTime() : v;

/**
 * Null-safe comparator for AG Grid: missing values sort last in both directions.
 * AG Grid inverts the comparator result when descending, so we pre-invert the null placement.
 */
export function nullsLast(a: Sortable, b: Sortable, _nodeA?: unknown, _nodeB?: unknown, isDescending = false): number {
  const left = key(a), right = key(b);
  const missingLeft = left === null || left === undefined || (typeof left === "number" && Number.isNaN(left));
  const missingRight = right === null || right === undefined || (typeof right === "number" && Number.isNaN(right));
  if (missingLeft && missingRight) return 0;
  if (missingLeft) return isDescending ? -1 : 1;
  if (missingRight) return isDescending ? 1 : -1;
  if (typeof left === "string" && typeof right === "string") return left.localeCompare(right, "en-GB", { sensitivity: "base" });
  return left! < right! ? -1 : left! > right! ? 1 : 0;
}

/** AG Grid date-filter comparator: compares the cell's local calendar day to the chosen day. */
export function dateFilterComparator(filterLocalDateAtMidnight: Date, cellValue: Date | null): number {
  if (!cellValue) return -1;
  const day = new Date(cellValue.getFullYear(), cellValue.getMonth(), cellValue.getDate()).getTime();
  const chosen = filterLocalDateAtMidnight.getTime();
  return day < chosen ? -1 : day > chosen ? 1 : 0;
}

/** Run `task` over `items` with at most `limit` in flight; results keep input order. */
export async function mapSettledWithLimit<T, R>(items: readonly T[], limit: number, task: (item: T) => Promise<R>): Promise<PromiseSettledResult<R>[]> {
  const results: PromiseSettledResult<R>[] = new Array(items.length);
  let next = 0;
  const worker = async () => {
    while (next < items.length) {
      const index = next++;
      try { results[index] = { status: "fulfilled", value: await task(items[index]) }; }
      catch (reason) { results[index] = { status: "rejected", reason }; }
    }
  };
  await Promise.all(Array.from({ length: Math.min(Math.max(1, limit), items.length) }, worker));
  return results;
}

export interface ConsoleLoad { rows: ConsoleRow[]; failedDetails: number }
export interface ConsoleApi {
  listWorkshops: (visibility: HostVisibilityFilter) => Promise<Workshop[]>;
  getWorkshop: (id: string) => Promise<WorkshopDetail>;
}
const defaultApi: ConsoleApi = { listWorkshops: api.listWorkshops, getWorkshop: api.getWorkshop };

/**
 * GET-only loader. A 401 from the list or any detail request is rethrown (session expired);
 * any other detail failure marks only that row's detail cells "Unavailable".
 */
export async function loadConsoleRows(visibility: HostVisibilityFilter, deps: ConsoleApi = defaultApi, limit = DETAIL_CONCURRENCY): Promise<ConsoleLoad> {
  const workshops = await deps.listWorkshops(visibility);
  const targets = workshops.filter(needsDetail);
  const settled = await mapSettledWithLimit(targets, limit, (workshop) => deps.getWorkshop(workshop.workshop_id));
  const expired = settled.find((result) => result.status === "rejected"
    && result.reason instanceof api.ApiError && result.reason.status === 401);
  if (expired && expired.status === "rejected") throw expired.reason;
  const details = new Map<string, WorkshopDetail | null>();
  targets.forEach((workshop, index) => {
    const result = settled[index];
    details.set(workshop.workshop_id, result.status === "fulfilled" ? result.value : null);
  });
  const rows = workshops.map((workshop) => toConsoleRow(workshop, needsDetail(workshop) ? details.get(workshop.workshop_id) : undefined));
  return { rows, failedDetails: [...details.values()].filter((detail) => detail === null).length };
}

/** Columns hidden on narrow layouts; data stays reachable at wider widths. */
export const NARROW_HIDDEN_COLUMNS = ["opensAt", "capacity"] as const;
export const NARROW_BREAKPOINT = 800;
/** Below this grid width the pinned title would leave too little room to see wide columns, so it scrolls with them. */
export const PIN_TITLE_MIN_WIDTH = 520;
