import type { Campaign, DraftPayload, HostVisibilityFilter, SessionInfo, ViabilityPreview, Workshop, WorkshopDetail, WorkshopVisibilityResult, MaterialSearchResult, MaterialSelection, PublicWorkshop, GuestSession, GuestBooking } from "./types";

export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly detail: unknown) {
    super(message);
    this.name = "ApiError";
  }
}

export class ApiContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ApiContractError";
  }
}

const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

export function requireWorkshopDetail(value: unknown): WorkshopDetail {
  if (!record(value) || !record(value.financials) || !Array.isArray(value.financials.materials)) {
    throw new ApiContractError(
      "The backend returned a workshop summary without saved financial inputs and materials. "
      + "Restart the local API with the current code, then click Try again. "
      + "Do not create another draft; this does not mean the saved workshop was lost.",
    );
  }
  if (value.financials.materials.some((line: unknown) => !record(line) || typeof line.name !== "string")) {
    throw new ApiContractError("The backend returned incomplete material details. Reload the updated API and try again; no empty material list has been substituted.");
  }
  return value as unknown as WorkshopDetail;
}

let csrfToken: string | null = null;

function csrfTokenFromCookie(): string | null {
  const prefix = "tipping_csrf=";
  const entry = document.cookie.split(";").map((value) => value.trim()).find((value) => value.startsWith(prefix));
  return entry ? decodeURIComponent(entry.slice(prefix.length)) : null;
}

function errorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail && typeof detail.message === "string") return detail.message;
  if (detail && typeof detail === "object" && "detail" in detail) {
    return errorMessage((detail as { detail: unknown }).detail, fallback);
  }
  if (Array.isArray(detail)) {
    return detail.map((entry) => {
      if (typeof entry !== "object" || !entry || !("msg" in entry)) return "Invalid request field.";
      const location = "loc" in entry && Array.isArray(entry.loc) ? entry.loc.filter((part: unknown) => part !== "body").join(".") : "";
      return `${location ? `${location}: ` : ""}${String(entry.msg)}`;
    }).join("; ");
  }
  return fallback;
}

async function request<T>(path: string, init: RequestInit = {}, csrf = false): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  if (csrf && csrfToken) headers.set("X-CSRF-Token", csrfToken);
  const response = await fetch(path, { ...init, headers, credentials: "same-origin", cache: "no-store" });
  const body = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(errorMessage(body, `Request failed (${response.status})`), response.status, body);
  return body as T;
}

export function clearCsrfToken(): void { csrfToken = null; }
export async function restoreSession(): Promise<SessionInfo> {
  const session = await request<SessionInfo>("/api/me");
  csrfToken = session.csrf_token || csrfTokenFromCookie();
  return session;
}

export async function login(loginIdentifier: string, password: string): Promise<SessionInfo> {
  const bootstrap = await request<{ csrf_token: string }>("/api/auth/csrf");
  const session = await request<SessionInfo>("/api/merchant/login", {
    method: "POST",
    headers: { "X-CSRF-Token": bootstrap.csrf_token },
    body: JSON.stringify({ login_identifier: loginIdentifier, password }),
  });
  csrfToken = session.csrf_token;
  return session;
}

export async function logout(): Promise<void> {
  await request<{ status: string }>("/api/merchant/logout", { method: "POST" }, true);
  clearCsrfToken();
}

export function listWorkshops(visibility: HostVisibilityFilter = "listed"): Promise<Workshop[]> {
  return request<Workshop[]>(`/api/merchant/workshops?visibility=${visibility}`);
}
/** Listing metadata only: never cancels the workshop, its bookings or its payments. */
export function hideFromDiscovery(workshopId: string): Promise<WorkshopVisibilityResult> {
  return request<WorkshopVisibilityResult>(`/api/merchant/workshops/${encodeURIComponent(workshopId)}/hide-from-discovery`, { method: "POST" }, true);
}
export function restoreVisibility(workshopId: string): Promise<WorkshopVisibilityResult> {
  return request<WorkshopVisibilityResult>(`/api/merchant/workshops/${encodeURIComponent(workshopId)}/restore-visibility`, { method: "POST" }, true);
}
export function createWorkshop(payload: DraftPayload): Promise<Workshop> {
  return request<Workshop>("/api/merchant/workshops", { method: "POST", body: JSON.stringify(payload) }, true);
}
export function editWorkshop(workshopId: string, payload: DraftPayload): Promise<Workshop> {
  return request<Workshop>(`/api/merchant/workshops/${workshopId}`, { method: "PATCH", body: JSON.stringify(payload) }, true);
}
export function previewWorkshop(workshopId: string): Promise<ViabilityPreview> {
  return request<ViabilityPreview>(`/api/merchant/workshops/${workshopId}/preview`, { method: "POST" }, true);
}
export function publishWorkshop(workshopId: string, review?: { expected_terms_version: number; expected_terms_snapshot_hash: string }): Promise<Campaign> {
  return request<Campaign>(`/api/merchant/workshops/${workshopId}/publish`, { method: "POST", ...(review ? { body: JSON.stringify(review) } : {}) }, true);
}
export async function getWorkshop(id: string): Promise<WorkshopDetail> {
  return requireWorkshopDetail(await request<unknown>(`/api/merchant/workshops/${encodeURIComponent(id)}`));
}
export function searchMaterials(id: string, query: string): Promise<MaterialSearchResult> {
  return request(`/api/merchant/workshops/${encodeURIComponent(id)}/materials/search`, {
    method: "POST", body: JSON.stringify({ query, limit: 10, in_stock_only: true }),
  }, true);
}
export function selectMaterial(id: string, payload: MaterialSelection): Promise<{ viability_preview: ViabilityPreview }> {
  return request(`/api/merchant/workshops/${encodeURIComponent(id)}/materials/select`, {
    method: "POST", body: JSON.stringify(payload),
  }, true);
}
export function listPublicWorkshops(): Promise<PublicWorkshop[]> { return request("/api/workshops"); }
export function getPublicWorkshop(id: string): Promise<PublicWorkshop> { return request(`/api/workshops/${encodeURIComponent(id)}`); }

// Guest CSRF is intentionally separate from merchant credentials and never persisted.
let guestCsrfToken: string | null = null;
export function clearGuestCsrfToken(): void { guestCsrfToken = null; }
function validGuestCsrf(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && !/[\s\u0000-\u001f\u007f]/.test(value);
}
function guestCsrfFromCookie(): string | null {
  const prefix = "tipping_guest_csrf=";
  const entry = document.cookie.split(";").map((value) => value.trim()).find((value) => value.startsWith(prefix));
  try {
    const value = entry ? decodeURIComponent(entry.slice(prefix.length)) : null;
    return validGuestCsrf(value) ? value : null;
  } catch { return null; }
}
function bindGuestCsrf(session: GuestSession): void {
  guestCsrfToken = validGuestCsrf(session.csrf_token) ? session.csrf_token : guestCsrfFromCookie();
  if (!guestCsrfToken) throw new ApiContractError("Guest session protection is unavailable. Restore your guest session before retrying; no mutation was sent.");
}
export function isGuestReservationValidationError(cause: unknown): boolean {
  return cause instanceof ApiError && cause.status === 422 && record(cause.detail)
    && Array.isArray(cause.detail.detail) && cause.detail.detail.length > 0
    && cause.detail.detail.every((entry: unknown) => record(entry) && Array.isArray(entry.loc) && entry.loc[0] === "body");
}
export function guestErrorCode(cause: unknown): string | null {
  if (!(cause instanceof ApiError) || !record(cause.detail) || !record(cause.detail.detail)) return null;
  return typeof cause.detail.detail.code === "string" ? cause.detail.detail.code : null;
}
export async function restoreGuestSession(): Promise<GuestSession> {
  clearGuestCsrfToken();
  const session = await request<GuestSession>("/api/guest/session");
  bindGuestCsrf(session);
  return session;
}
export async function createGuestSession(): Promise<GuestSession> {
  clearGuestCsrfToken();
  const bootstrap = await request<{ csrf_token: string }>("/api/guest/csrf");
  if (!validGuestCsrf(bootstrap.csrf_token)) throw new ApiContractError("Guest session bootstrap protection is unavailable. No guest session was created.");
  const session = await request<GuestSession>("/api/guest/session", {
    method: "POST", body: "{}", headers: { "X-CSRF-Token": bootstrap.csrf_token },
  });
  guestCsrfToken = session.csrf_token;
  return session;
}
async function guestMutation<T>(path: string, payload: object): Promise<T> {
  if (!guestCsrfToken) await restoreGuestSession();
  if (!validGuestCsrf(guestCsrfToken)) throw new ApiContractError("Guest session protection is unavailable. No mutation was sent.");
  return request<T>(path, {
    method: "POST", body: JSON.stringify(payload), headers: { "X-CSRF-Token": guestCsrfToken! },
  });
}
export function reserveGuestSeat(campaignId: string, email: string, key: string): Promise<GuestBooking> {
  return guestMutation(`/api/campaigns/${encodeURIComponent(campaignId)}/bookings`, { email, idempotency_key: key });
}
export function getGuestBooking(id: string): Promise<GuestBooking> {
  return request(`/api/bookings/${encodeURIComponent(id)}`);
}
export function createGuestOrder(id: string): Promise<GuestBooking> {
  return guestMutation(`/api/bookings/${encodeURIComponent(id)}/paypal/order`, {});
}
export function authorizeGuestBooking(id: string): Promise<GuestBooking> {
  return guestMutation(`/api/bookings/${encodeURIComponent(id)}/paypal/authorize`, {});
}
export function cancelGuestBooking(id: string): Promise<GuestBooking> {
  return guestMutation(`/api/bookings/${encodeURIComponent(id)}/cancel`, {});
}
