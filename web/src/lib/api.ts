import {
  createMockConversation,
  createMockEvent,
  createMockFact,
  createMockGoal,
  createMockToken,
  deleteMockAnthropicKey,
  deleteMockConversation,
  deleteMockMemory,
  deleteMockToken,
  mockActivitySamples,
  mockBody,
  mockCoachModels,
  mockCoachSettings,
  mockConversationDetail,
  mockConversations,
  mockDailyUsage,
  mockDuplicates,
  mockErgStrokes,
  mockMemory,
  mockNote,
  mockPbs,
  mockScenarioFromQuery,
  mockSeries,
  mockSettings,
  mockSyncStatus,
  mockTestConnection,
  mockToday,
  mockTokens,
  mockVolume,
  mockWorkoutDetail,
  mockWorkoutsPage,
  mergeMockActivities,
  markMockNotDuplicate,
  patchMockActivity,
  postMockManualWeight,
  revertMockActivityField,
  saveMockCoachSettings,
  saveMockNote,
  saveMockSettings,
  setMockAnthropicKey,
  splitMockActivity,
  streamMockMessage,
  updateMockEvent,
  updateMockFact,
  updateMockGoal,
} from "./mock";
import type {
  ActivityOverrides,
  ActivitySamplesResponse,
  BodyCompReading,
  CoachConversation,
  CoachConversationDetail,
  CoachEvent,
  CoachModel,
  CoachSettings,
  DeviceToken,
  DuplicatePair,
  ErgStrokesResponse,
  MemoryEvent,
  MemoryFact,
  MemoryGoal,
  MemoryListing,
  Note,
  PersonalBests,
  Settings,
  SeriesResponse,
  SyncResult,
  SyncSourceStatus,
  Today,
  TrendMetric,
  VolumeWeek,
  WorkoutCategory,
  WorkoutDetail,
  WorkoutsPage,
} from "./types";

export const MOCK_SCENARIO = mockScenarioFromQuery();
export const isMock = MOCK_SCENARIO !== null;

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// A session cookie can expire mid-visit (30-day max age, but still). AuthProvider listens
// for this so a stale session drops the user back to the login screen instead of leaving
// every card stuck on "Couldn't load" with a Retry button that will never succeed.
export const UNAUTHORIZED_EVENT = "catch:unauthorized";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { credentials: "include", ...init });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    if (res.status === 401) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
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

// --- Workouts ----------------------------------------------------------

export async function fetchWorkouts(params: {
  category?: WorkoutCategory;
  cursor?: string | null;
}): Promise<WorkoutsPage> {
  if (isMock) return delay(mockWorkoutsPage(params.category, params.cursor ?? null));
  const search = new URLSearchParams();
  if (params.category) search.set("category", params.category);
  if (params.cursor) search.set("cursor", params.cursor);
  return request<WorkoutsPage>(`/api/activities?${search.toString()}`);
}

export async function fetchWorkoutDetail(id: number): Promise<WorkoutDetail> {
  if (isMock) return delay(mockWorkoutDetail(id));
  return request<WorkoutDetail>(`/api/activities/${id}`);
}

export async function fetchErgStrokes(
  id: number,
  opts?: { points?: number; distanceMin?: number; distanceMax?: number },
): Promise<ErgStrokesResponse> {
  if (isMock) return delay(mockErgStrokes(id, opts));
  const search = new URLSearchParams();
  if (opts?.points) search.set("points", String(opts.points));
  if (opts?.distanceMin != null) search.set("distance_min", String(opts.distanceMin));
  if (opts?.distanceMax != null) search.set("distance_max", String(opts.distanceMax));
  const qs = search.toString();
  return request<ErgStrokesResponse>(`/api/erg/${id}/strokes${qs ? `?${qs}` : ""}`);
}

// --- Activity editing (task Part C) -----------------------------------------

export async function patchActivity(id: number, patch: ActivityOverrides): Promise<WorkoutDetail> {
  if (isMock) return delay(patchMockActivity(id, patch), 200);
  return request<WorkoutDetail>(`/api/activities/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export async function revertActivityField(id: number, field: keyof ActivityOverrides): Promise<WorkoutDetail> {
  if (isMock) return delay(revertMockActivityField(id, field), 200);
  return request<WorkoutDetail>(`/api/activities/${id}/revert`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ field }),
  });
}

export async function bulkEditActivities(ids: number[], patch: ActivityOverrides): Promise<{ updated: number[] }> {
  if (isMock) {
    ids.forEach((id) => patchMockActivity(id, patch));
    return delay({ updated: ids }, 300);
  }
  return request("/api/activities/bulk", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ canonical_ids: ids, patch }),
  });
}

export async function fetchActivitySamples(
  id: number,
  opts?: { points?: number; startS?: number; endS?: number },
): Promise<ActivitySamplesResponse> {
  if (isMock) return delay(mockActivitySamples(id));
  const search = new URLSearchParams();
  if (opts?.points) search.set("points", String(opts.points));
  if (opts?.startS != null) search.set("start_s", String(opts.startS));
  if (opts?.endS != null) search.set("end_s", String(opts.endS));
  const qs = search.toString();
  return request<ActivitySamplesResponse>(`/api/activities/${id}/samples${qs ? `?${qs}` : ""}`);
}

// --- Duplicates review (task Part A.5) --------------------------------------

export async function fetchDuplicates(): Promise<DuplicatePair[]> {
  if (isMock) return delay(mockDuplicates());
  const { pairs } = await request<{ pairs: DuplicatePair[] }>("/api/activities/duplicates");
  return pairs;
}

export async function mergeActivities(activityIdA: number, activityIdB: number): Promise<WorkoutDetail> {
  if (isMock) return delay(mergeMockActivities(activityIdA, activityIdB), 300);
  return request<WorkoutDetail>("/api/activities/merge", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ activity_id_a: activityIdA, activity_id_b: activityIdB }),
  });
}

export async function splitActivity(activityId: number): Promise<WorkoutDetail> {
  if (isMock) return delay(splitMockActivity(activityId), 300);
  return request<WorkoutDetail>("/api/activities/split", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ activity_id: activityId }),
  });
}

export async function markNotDuplicate(activityIdA: number, activityIdB: number): Promise<void> {
  if (isMock) return delay(markMockNotDuplicate(activityIdA, activityIdB), 150);
  await request("/api/activities/not-duplicate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ activity_id_a: activityIdA, activity_id_b: activityIdB }),
  });
}

// --- Notes ---------------------------------------------------------------

export async function fetchNote(date: string): Promise<Note | null> {
  if (isMock) return delay(mockNote(date));
  return request<Note | null>(`/api/notes?date=${date}`);
}

export async function saveNote(date: string, text: string, rpe: number | null): Promise<Note> {
  if (isMock) return delay(saveMockNote(date, text, rpe), 200);
  return request<Note>("/api/notes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ date, text, rpe }),
  });
}

// --- Trends / Body -------------------------------------------------------

export async function fetchVolume(weeks: number): Promise<VolumeWeek[]> {
  if (isMock) return delay(mockVolume(weeks));
  return request<VolumeWeek[]>(`/api/trends/volume?weeks=${weeks}`);
}

// Interactive charts (session 8): one or more metrics, a visible-range window plus a point
// budget — the backend LTTB-downsamples anything longer than `points`. Every Trends/Body/
// Today chart uses this now; the plain, undownsampled GET /api/trends still exists
// server-side (catch/coach/tools.py's get_trends tool calls it directly), it's just no
// longer fetched from the frontend.
export async function fetchSeries(metrics: TrendMetric[], from: string, to: string, points: number): Promise<SeriesResponse> {
  if (isMock) return delay(mockSeries(metrics, from, to, points));
  const search = new URLSearchParams({ metrics: metrics.join(","), from, to, points: String(points) });
  return request<SeriesResponse>(`/api/series?${search.toString()}`);
}

export async function fetchBody(from?: string, to?: string): Promise<BodyCompReading[]> {
  if (isMock) return delay(mockBody());
  const search = new URLSearchParams();
  if (from) search.set("from", from);
  if (to) search.set("to", to);
  return request<BodyCompReading[]>(`/api/body?${search.toString()}`);
}

export async function postManualWeight(date: string, weightKg: number): Promise<void> {
  if (isMock) return delay(postMockManualWeight(date, weightKg), 200);
  await request("/api/body/manual", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ date, weight_kg: weightKg }),
  });
}

export async function fetchPbs(): Promise<PersonalBests> {
  if (isMock) return delay(mockPbs());
  return request<PersonalBests>("/api/pbs");
}

// --- Settings --------------------------------------------------------------

export async function fetchSettings(): Promise<Settings> {
  if (isMock) return delay(mockSettings());
  return request<Settings>("/api/settings");
}

export async function saveSettings(patch: Partial<Settings>): Promise<Settings> {
  if (isMock) return delay(saveMockSettings(patch), 200);
  return request<Settings>("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

// --- Coach: conversations ---------------------------------------------------

export async function fetchConversations(): Promise<CoachConversation[]> {
  if (isMock) return delay(mockConversations());
  return request<CoachConversation[]>("/api/coach/conversations");
}

export async function createConversation(): Promise<CoachConversation> {
  if (isMock) return delay(createMockConversation(), 100);
  return request<CoachConversation>("/api/coach/conversations", { method: "POST" });
}

export async function fetchConversation(id: number): Promise<CoachConversationDetail> {
  if (isMock) {
    const detail = mockConversationDetail(id);
    if (!detail) throw new ApiError(404, "Conversation not found");
    return delay(detail);
  }
  return request<CoachConversationDetail>(`/api/coach/conversations/${id}`);
}

export async function deleteConversation(id: number): Promise<void> {
  if (isMock) return delay(deleteMockConversation(id), 100);
  await request<{ ok: true }>(`/api/coach/conversations/${id}`, { method: "DELETE" });
}

// EventSource can't send a POST body, so streaming goes over a plain fetch + a hand-rolled
// SSE line parser instead — each `data: {...}\n\n` chunk becomes one yielded CoachEvent.
export async function* streamMessage(conversationId: number, text: string): AsyncGenerator<CoachEvent> {
  if (isMock) {
    yield* streamMockMessage(conversationId, text);
    return;
  }
  const res = await fetch(`/api/coach/conversations/${conversationId}/messages`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!res.ok || !res.body) {
    if (res.status === 401) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    throw new ApiError(res.status, "Failed to send message");
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary: number;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const chunk = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const line = chunk.split("\n").find((l) => l.startsWith("data: "));
      if (line) yield JSON.parse(line.slice("data: ".length)) as CoachEvent;
    }
  }
}

// --- Coach: settings / models / credentials / usage --------------------------

export async function fetchCoachSettings(): Promise<CoachSettings> {
  if (isMock) return delay(mockCoachSettings());
  return request<CoachSettings>("/api/coach/settings");
}

export async function saveCoachSettings(patch: Partial<CoachSettings>): Promise<CoachSettings> {
  if (isMock) return delay(saveMockCoachSettings(patch), 150);
  return request<CoachSettings>("/api/coach/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export async function setAnthropicKey(apiKey: string): Promise<CoachSettings["anthropic_key"]> {
  if (isMock) return delay(setMockAnthropicKey(apiKey), 300);
  return request<CoachSettings["anthropic_key"]>("/api/coach/key", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: apiKey }),
  });
}

export async function deleteAnthropicKey(): Promise<void> {
  if (isMock) return delay(deleteMockAnthropicKey(), 100);
  await request<{ ok: true }>("/api/coach/key", { method: "DELETE" });
}

export async function testCoachConnection(): Promise<{ ok: boolean; error?: string; model_count?: number }> {
  if (isMock) return delay(mockTestConnection(), 500);
  return request("/api/coach/test-connection", { method: "POST" });
}

export async function fetchCoachModels(provider?: "anthropic" | "ollama"): Promise<CoachModel[]> {
  if (isMock) return delay(mockCoachModels(provider ?? "anthropic"));
  const search = provider ? `?provider=${provider}` : "";
  return request<CoachModel[]>(`/api/coach/models${search}`);
}

export async function fetchDailyUsage(): Promise<{ spend_usd: number; cap_usd: number | null }> {
  if (isMock) return delay(mockDailyUsage());
  return request("/api/coach/usage/daily");
}

// --- Coach: device tokens -----------------------------------------------------

export async function fetchTokens(): Promise<DeviceToken[]> {
  if (isMock) return delay(mockTokens());
  return request<DeviceToken[]>("/api/coach/tokens");
}

export async function createToken(name: string): Promise<DeviceToken & { token: string }> {
  if (isMock) return delay(createMockToken(name), 150);
  return request("/api/coach/tokens", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export async function deleteToken(id: number): Promise<void> {
  if (isMock) return delay(deleteMockToken(id), 100);
  await request<{ ok: true }>(`/api/coach/tokens/${id}`, { method: "DELETE" });
}

// --- Coach: memory -------------------------------------------------------------

export async function fetchMemory(): Promise<MemoryListing> {
  if (isMock) return delay(mockMemory());
  return request<MemoryListing>("/api/coach/memory");
}

export async function addMemoryFact(category: string, text: string, valid_until: string | null): Promise<MemoryFact> {
  if (isMock) return delay(createMockFact(category, text, valid_until), 150);
  return request<MemoryFact>("/api/coach/memory/facts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ category, text, valid_until }),
  });
}

export async function addMemoryEvent(fields: Omit<MemoryEvent, "ref" | "kind" | "days_to_go">): Promise<MemoryEvent> {
  if (isMock) return delay(createMockEvent(fields), 150);
  return request<MemoryEvent>("/api/coach/memory/events", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  });
}

export async function addMemoryGoal(text: string, target_date: string | null): Promise<MemoryGoal> {
  if (isMock) return delay(createMockGoal(text, target_date), 150);
  return request<MemoryGoal>("/api/coach/memory/goals", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, target_date }),
  });
}

export async function deleteMemoryItem(ref: string): Promise<void> {
  if (isMock) return delay(deleteMockMemory(ref), 100);
  await request<{ ok: true }>(`/api/coach/memory/${ref}`, { method: "DELETE" });
}

function memoryId(ref: string): number {
  return Number(ref.split(":")[1]);
}

export async function updateMemoryFact(ref: string, patch: Partial<Pick<MemoryFact, "category" | "text" | "valid_until">>): Promise<MemoryFact> {
  if (isMock) return delay(updateMockFact(ref, patch), 150);
  return request<MemoryFact>(`/api/coach/memory/facts/${memoryId(ref)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export async function updateMemoryEvent(
  ref: string,
  patch: Partial<Pick<MemoryEvent, "name" | "date" | "type" | "distance" | "boat_class" | "priority" | "goal_time" | "result">>,
): Promise<MemoryEvent> {
  if (isMock) return delay(updateMockEvent(ref, patch), 150);
  return request<MemoryEvent>(`/api/coach/memory/events/${memoryId(ref)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export async function updateMemoryGoal(ref: string, text: string, target_date: string | null, status: MemoryGoal["status"]): Promise<MemoryGoal> {
  if (isMock) return delay(updateMockGoal(ref, { text, target_date, status }), 150);
  return request<MemoryGoal>(`/api/coach/memory/goals/${memoryId(ref)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, target_date, status }),
  });
}
