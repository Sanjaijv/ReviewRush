const API_BASE = "/api/v1/dashboard";

export class UnauthorizedError extends Error {
  constructor() {
    super("not authenticated");
    this.name = "UnauthorizedError";
  }
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(base: string, path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${base}${path}`, { credentials: "include", ...init });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) {
    const text = await res.text();
    throw new ApiError(res.status, text || res.statusText);
  }
  if (res.status === 204) return null as T;
  return (await res.json()) as T;
}

/** Calls the cookie-authenticated dashboard API through the same-origin proxy. */
export function api<T>(path: string, init?: RequestInit): Promise<T> {
  return request<T>(API_BASE, path, init);
}

/** Calls token-gated operator endpoints through the server-only Next proxy. */
export function adminApi<T>(path: string, init?: RequestInit): Promise<T> {
  return request<T>("/api/admin", path, init);
}

export function apiJson<T>(path: string, method: "POST" | "PUT", body: unknown): Promise<T> {
  return api<T>(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export function adminApiJson<T>(path: string, method: "POST" | "PUT", body: unknown): Promise<T> {
  return adminApi<T>(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export const loginUrl = `${API_BASE}/auth/login`;

export async function logout(): Promise<void> {
  await fetch(`${API_BASE}/auth/logout`, { method: "POST", credentials: "include" });
}
