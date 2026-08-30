import type { Connection, DineInSession, Menu, RestaurantTable, WaiterUser } from "@/lib/kashir-types";

export function normalizeBaseUrl(value: string) {
  const trimmed = value.trim().replace(/\/+$/, "");
  if (!trimmed) return "";
  return /^https?:\/\//i.test(trimmed) ? trimmed : `http://${trimmed}`;
}

async function readResponse(response: Response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) throw new Error(data.error || "تعذر الاتصال بالكاشير");
  return data;
}

export async function waiterLogin(baseUrl: string, username: string, password: string) {
  const response = await fetch(`${normalizeBaseUrl(baseUrl)}/api/mobile/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  return (await readResponse(response)) as { ok: true; token: string; expires_at: string; user: WaiterUser };
}

export async function waiterRequest<T>(connection: Connection, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${connection.baseUrl}${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${connection.token}`, "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  return (await readResponse(response)) as T;
}

export const waiterApi = {
  bootstrap: (connection: Connection) => waiterRequest<{ ok: true; restaurant: { name?: string; phone?: string; address?: string }; waiter: WaiterUser; tables: RestaurantTable[]; menu: Menu }>(connection, "/api/mobile/bootstrap"),
  tables: (connection: Connection) => waiterRequest<{ ok: true; tables: RestaurantTable[] }>(connection, "/api/mobile/tables"),
  session: (connection: Connection, sessionId: string) => waiterRequest<{ ok: true; session: DineInSession }>(connection, `/api/mobile/dine-in/sessions/${encodeURIComponent(sessionId)}`),
  createSession: (connection: Connection, body: object) => waiterRequest<{ ok: true; session: DineInSession }>(connection, "/api/mobile/dine-in/sessions", { method: "POST", body: JSON.stringify(body) }),
  updateSession: (connection: Connection, sessionId: string, body: object) => waiterRequest<{ ok: true; session: DineInSession }>(connection, `/api/mobile/dine-in/sessions/${encodeURIComponent(sessionId)}`, { method: "PUT", body: JSON.stringify(body) }),
  markServed: (connection: Connection, sessionId: string) => waiterRequest<{ ok: true; session: DineInSession }>(connection, `/api/mobile/dine-in/sessions/${encodeURIComponent(sessionId)}/served`, { method: "POST" }),
  logout: (connection: Connection) => waiterRequest<{ ok: true }>(connection, "/api/mobile/auth/logout", { method: "POST" }),
};
