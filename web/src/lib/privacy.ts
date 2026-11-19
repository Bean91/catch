import { authedFetch } from "./authedFetch";
import { ApiError, isMock } from "./api";
import { mockPrivacy } from "./mockPrivacy";

export type PrivacyCategory = { key: string; label: string; note: string; rows: number };
export type PrivacySummary = {
  categories: PrivacyCategory[];
  totals: { workouts: number; tables_exported: number };
  public: { leaderboard_profile: { active: boolean; display_mode: string } | null; published_results: number; club_memberships: number } | null;
};
export type SharingCategory = { key: string; label: string; description: string; health: boolean; enabled: boolean };
export type SharingState = {
  consent_version: number;
  consented: boolean;
  consented_at: string | null;
  age_band: string | null;
  guardian_ack: boolean;
  categories: SharingCategory[];
};
export type SharingUpdate = { acknowledge?: boolean; categories?: Record<string, boolean>; age_band?: string | null; guardian_ack?: boolean };
export type ToolCallRow = { tool: string; via: string; as: string; write: boolean; confirmed: boolean; outcome: string; at: string };
export type DeviceToken = { id: number; name: string; role: string; scope: string; created_at: string; last_used_at: string | null; expires_at: string | null };
export type Restriction = {
  id: number;
  scope: string;
  scope_text: string;
  active: boolean;
  reason: string;
  decided_by: string;
  created_at: string;
  expires_at: string | null;
  appeal: { status: string; text: string | null; resolution: string | null } | null;
};

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await authedFetch(path, init);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, typeof body.detail === "string" ? body.detail : res.statusText);
  }
  return res.json() as Promise<T>;
}

const json = (method: string, body: unknown): RequestInit => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const fetchPrivacySummary = (): Promise<PrivacySummary> => (isMock ? mockPrivacy.summary() : call("/api/privacy/summary"));
export const fetchSharing = (): Promise<SharingState> => (isMock ? mockPrivacy.sharing() : call("/api/ai/sharing"));
export const updateSharing = (body: SharingUpdate): Promise<SharingState> => (isMock ? mockPrivacy.updateSharing(body) : call("/api/ai/sharing", json("PUT", body)));
export const withdrawSharing = (): Promise<SharingState> => (isMock ? mockPrivacy.withdraw() : call("/api/ai/sharing", { method: "DELETE" }));
export const fetchToolCalls = (): Promise<ToolCallRow[]> => (isMock ? mockPrivacy.toolCalls() : call("/api/privacy/tool-calls"));
export const fetchDeviceTokens = (): Promise<DeviceToken[]> => (isMock ? mockPrivacy.tokens() : call("/api/coach/tokens"));
export const revokeDeviceToken = (id: number): Promise<{ ok: boolean }> => (isMock ? mockPrivacy.revoke(id) : call(`/api/coach/tokens/${id}`, { method: "DELETE" }));
export const revokeAllDeviceTokens = (): Promise<{ revoked: number }> => (isMock ? mockPrivacy.revokeAll() : call("/api/coach/tokens", { method: "DELETE" }));
export const deleteCategory = (key: string): Promise<{ category: string; rows_removed: number; files_removed: number }> =>
  isMock ? mockPrivacy.deleteCategory(key) : call(`/api/privacy/data/${key}`, json("DELETE", { confirm: true }));
export const fetchRestrictions = (): Promise<{ restrictions: Restriction[] }> => (isMock ? mockPrivacy.restrictions() : call("/api/account/restrictions"));
export const appealRestriction = (id: number, text: string): Promise<Restriction> =>
  isMock ? mockPrivacy.appeal(id, text) : call(`/api/account/restrictions/${id}/appeal`, json("POST", { text }));

/** The export is a download that needs the bearer header, so it is fetched, then handed to the browser as a file. */
export async function downloadExport(): Promise<void> {
  if (isMock) return mockPrivacy.download();
  const res = await authedFetch("/api/privacy/export");
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, typeof body.detail === "string" ? body.detail : res.statusText);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const day = new Date().toISOString().slice(0, 10).replaceAll("-", "");
  a.href = url;
  a.download = `catch-export-${day}.ndjson.gz`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

export const YOUTH_BANDS = ["u19", "u18", "u17", "u16", "u15", "u14"];
