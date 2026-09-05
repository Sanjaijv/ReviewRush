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

/**
 * Calls the FastAPI dashboard API (proxied same-origin via next.config.ts
 * rewrites, so the existing GitHub-OAuth session cookie is sent
 * automatically - no token handling needed on this side).
 */
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...init,
  });
  if (res.status === 401) {
    throw new UnauthorizedError();
  }
  if (!res.ok) {
    const text = await res.text();
    throw new ApiError(res.status, text || res.statusText);
  }
  if (res.status === 204) {
    return null as T;
  }
  return (await res.json()) as T;
}

export function apiJson<T>(
  path: string,
  method: "POST" | "PUT",
  body: unknown,
): Promise<T> {
  return api<T>(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export const loginUrl = `${API_BASE}/auth/login`;

export async function logout(): Promise<void> {
  await fetch(`${API_BASE}/auth/logout`, {
    method: "POST",
    credentials: "include",
  });
}
