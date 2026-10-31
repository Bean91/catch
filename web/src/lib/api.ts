import { mockScenarioFromQuery, mockSyncStatus, mockToday } from "./mock";
import type { SyncResult, SyncSourceStatus, Today } from "./types";

export const MOCK_SCENARIO = mockScenarioFromQuery();
export const isMock = MOCK_SCENARIO !== null;

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { credentials: "include", ...init });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.detail ?? res.statusText);
  }
  return res.json() as Promise<T>;
}

function delay<T>(value: T, ms = 300): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), ms));
}

export async function fetchToday(): Promise<Today> {
  if (isMock) {
    if (MOCK_SCENARIO === "error") throw new ApiError(500, "Mock server error");
    if (MOCK_SCENARIO === "loading") return new Promise<Today>(() => {});
    return delay(mockToday(MOCK_SCENARIO!));
  }
  return request<Today>("/api/today");
}

export async function fetchSyncStatus(): Promise<SyncSourceStatus[]> {
  if (isMock) return delay(mockSyncStatus());
  return request<SyncSourceStatus[]>("/api/sync/status");
}

export async function triggerSync(source: string): Promise<SyncResult> {
  if (isMock) return delay({ source, measures: 3 }, 600);
  return request<SyncResult>(`/api/sync/${source}`, { method: "POST" });
}

export async function login(password: string): Promise<void> {
  if (isMock) return delay(undefined, 200);
  await request<{ ok: true }>("/api/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
}

export async function logout(): Promise<void> {
  if (isMock) return delay(undefined, 100);
  await request<{ ok: true }>("/api/logout", { method: "POST" });
}
