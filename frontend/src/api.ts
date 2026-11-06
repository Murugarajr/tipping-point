import type { Campaign, DraftPayload, SessionInfo, ViabilityPreview, Workshop } from "./types";

export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly detail: unknown) {
    super(message);
    this.name = "ApiError";
  }
}

let csrfToken: string | null = null;

function csrfTokenFromCookie(): string | null {
  const prefix = "tipping_csrf=";
  const entry = document.cookie.split(";").map((value) => value.trim()).find((value) => value.startsWith(prefix));
  return entry ? decodeURIComponent(entry.slice(prefix.length)) : null;
}

function errorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "detail" in detail) {
    return errorMessage((detail as { detail: unknown }).detail, fallback);
  }
  if (Array.isArray(detail)) {
    return detail.map((entry) => typeof entry === "object" && entry && "msg" in entry ? String(entry.msg) : String(entry)).join("; ");
  }
  return fallback;
}

async function request<T>(path: string, init: RequestInit = {}, csrf = false): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  if (csrf && csrfToken) headers.set("X-CSRF-Token", csrfToken);
  const response = await fetch(path, { ...init, headers, credentials: "same-origin" });
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
export function publishWorkshop(workshopId: string): Promise<Campaign> {
  return request<Campaign>(`/api/merchant/workshops/${workshopId}/publish`, { method: "POST" }, true);
}