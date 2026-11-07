import type { Campaign, DraftPayload, SessionInfo, ViabilityPreview, Workshop, WorkshopDetail, MaterialSearchResult, MaterialSelection, PublicWorkshop } from "./types";

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

export function listWorkshops(): Promise<Workshop[]> { return request<Workshop[]>("/api/merchant/workshops"); }
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
