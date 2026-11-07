import {
  copyMockDayLogs,
  createMockConversation,
  createMockEvent,
  createMockExercise,
  createMockFact,
  createMockGoal,
  createMockGym,
  createMockManualFood,
  createMockFoodLog,
  createMockToken,
  deleteMockTemplate,
  deleteMockAnthropicKey,
  deleteMockConversation,
  deleteMockFoodLog,
  deleteMockMemory,
  deleteMockSavedMeal,
  deleteMockToken,
  dismissMockIllness,
  listMockFoodLogs,
  logMockSavedMeal,
  mockActivitySamples,
  mockBarcodeLookup,
  mockBody,
  mockCoachModels,
  mockCoachSettings,
  mockConversationDetail,
  mockConversations,
  mockDailyUsage,
  mockDaySummary,
  mockDuplicates,
  mockErgStrokes,
  mockExercises,
  mockFoodSearch,
  mockGyms,
  mockIllnessBacktest,
  mockLastSetsForExercise,
  mockMemory,
  mockMuscleReadiness,
  mockMyFoods,
  mockNote,
  mockNutritionTargets,
  mockPacingPlan,
  mockPbs,
  mockPhotoEstimate,
  mockPieces,
  mockPieceTemplate,
  mockPiecePhotoEstimate,
  mockPieceTestDetail,
  createMockPiece,
  updateMockPiece,
  deleteMockPiece,
  alignMockPiece,
  uploadMockPiecePhoto,
  deleteMockPiecePhoto,
  mockProjection,
  mockRepeatLastWorkout,
  mockSavedMeals,
  mockScenarioFromQuery,
  mockSeries,
  mockSettings,
  mockStations,
  mockSyncStatus,
  mockTemplates,
  mockTestCandidates,
  mockTestConnection,
  mockTestDetail,
  mockTests,
  mockToday,
  mockTodayCheckin,
  mockTokens,
  mockVolume,
  mockWeekSummary,
  mockWorkoutDetail,
  mockWorkoutsPage,
  markMockIllnessBacktest,
  mergeMockActivities,
  markMockNotDuplicate,
  patchMockActivity,
  postMockManualWeight,
  revertMockActivityField,
  saveMockCheckin,
  saveMockCoachSettings,
  saveMockMeal,
  saveMockNote,
  saveMockNutritionTargets,
  saveMockSettings,
  saveMockTemplate,
  savePhotoEstimateMock,
  setMockAnthropicKey,
  splitMockActivity,
  starMockFood,
  streamMockMessage,
  unstarMockFood,
  updateMockEvent,
  updateMockExercise,
  updateMockFact,
  updateMockFoodLog,
  updateMockGoal,
  upsertMockStation,
  mockSubscribePush,
  mockUnsubscribePush,
  mockPushSubscriptions,
  mockStatus,
} from "./mock";
import type {
  ActivityOverrides,
  ActivitySamplesResponse,
  BarcodeLookupResult,
  BodyCompReading,
  CheckIn,
  CoachConversation,
  CoachConversationDetail,
  CoachEvent,
  CoachModel,
  CoachSettings,
  DaySummary,
  DeviceToken,
  DismissReason,
  DuplicatePair,
  ErgStrokesResponse,
  ErgTestCandidate,
  ErgTestDetail,
  ErgTestSummary,
  ErgTestType,
  Exercise,
  Food,
  FoodLogRow,
  GymRow,
  GymStation,
  IllnessBacktestResponse,
  Meal,
  MemoryEvent,
  MemoryFact,
  MemoryGoal,
  MemoryListing,
  MuscleReadiness,
  MyFoodRow,
  Note,
  NutritionTargetSettings,
  NutritionTargetsResponse,
  PacingPlan,
  PacingStyle,
  PersonalBests,
  PhotoEstimateItem,
  PhotoEstimateResult,
  CreatePieceResult,
  Piece,
  PiecePhotoEstimate,
  PieceSplitRow,
  PieceTestDetail,
  ProjectionResult,
  RepeatWorkoutPlanItem,
  SavedMealItem,
  SavedMealRow,
  Settings,
  SeriesResponse,
  StrengthSetRow,
  StrengthTemplate,
  StrengthTemplateItem,
  SyncResult,
  SyncSourceStatus,
  Today,
  TodayCheckinStatus,
  TrendMetric,
  VolumeWeek,
  WeekSummary,
  WorkoutCategory,
  WorkoutDetail,
  WorkoutsPage,
  PushSubscriptionRow,
  AppStatus,
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

// --- Morning check-in (session 15 Part A) -----------------------------------

export async function fetchTodayCheckin(): Promise<TodayCheckinStatus> {
  if (isMock) return delay(mockTodayCheckin());
  return request<TodayCheckinStatus>("/api/checkins/today");
}

export async function postCheckin(body: Partial<Omit<CheckIn, "date">> & { date?: string }): Promise<CheckIn> {
  if (isMock) return delay(saveMockCheckin(body), 200);
  return request<CheckIn>("/api/checkins", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// --- Illness early warning (session 15 Part B) -------------------------------

export async function dismissIllness(day: string, reason: DismissReason): Promise<void> {
  if (isMock) return delay(dismissMockIllness(day, reason), 200);
  await request(`/api/illness/${day}/dismiss`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
}

export async function markIllnessBacktest(day: string, correct: boolean): Promise<void> {
  if (isMock) return delay(markMockIllnessBacktest(day, correct), 200);
  await request(`/api/illness/${day}/mark`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ correct }),
  });
}

export async function fetchIllnessBacktest(): Promise<IllnessBacktestResponse> {
  if (isMock) return delay(mockIllnessBacktest());
  return request<IllnessBacktestResponse>("/api/illness/backtest");
}

// --- Erg test center (session 15 Part C) -------------------------------------

export async function fetchTestCandidates(): Promise<ErgTestCandidate[]> {
  if (isMock) return delay(mockTestCandidates());
  const { candidates } = await request<{ candidates: ErgTestCandidate[] }>("/api/tests/candidates");
  return candidates;
}

export async function fetchTests(type?: ErgTestType): Promise<ErgTestSummary[]> {
  if (isMock) return delay(mockTests(type));
  const search = new URLSearchParams();
  if (type) search.set("type", type);
  const { tests } = await request<{ tests: ErgTestSummary[] }>(`/api/tests?${search.toString()}`);
  return tests;
}

export async function fetchTestDetail(id: number): Promise<ErgTestDetail> {
  if (isMock) return delay(mockTestDetail(id));
  return request<ErgTestDetail>(`/api/tests/${id}`);
}

// Confirming a candidate is just the existing activity-edit PATCH with tags + test_type —
// no separate endpoint, same free-form overrides_json every other edit already uses.
export async function confirmTest(canonicalId: number, testType: ErgTestType, existingTags: string[] = []): Promise<WorkoutDetail> {
  const tags = existingTags.includes("test") ? existingTags : [...existingTags, "test"];
  return patchActivity(canonicalId, { tags, test_type: testType });
}

export async function makePacingPlan(body: {
  test_type: ErgTestType;
  goal_time_s: number;
  style: PacingStyle;
  distance_m?: number;
  save_to_next_event?: boolean;
}): Promise<{ plan: PacingPlan; saved_to_event: { id: number; name: string; date: string } | null }> {
  if (isMock) return delay(mockPacingPlan(body), 300);
  return request("/api/tests/pacing-plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function fetchProjection(type: ErgTestType): Promise<ProjectionResult> {
  if (isMock) return delay(mockProjection(type));
  return request<ProjectionResult>(`/api/tests/projection?type=${encodeURIComponent(type)}`);
}

// --- Pieces (session 17 — see PLAN.md, the task called itself "session 13") -------------

export async function fetchPieces(canonicalId: number): Promise<Piece[]> {
  if (isMock) return delay(mockPieces(canonicalId));
  const { pieces } = await request<{ pieces: Piece[] }>(`/api/activities/${canonicalId}/pieces`);
  return pieces;
}

export async function fetchPieceTemplate(canonicalId: number, pieceType: ErgTestType, distanceM?: number, durationS?: number): Promise<PieceSplitRow[]> {
  if (isMock) return delay(mockPieceTemplate(pieceType, distanceM, durationS));
  const search = new URLSearchParams({ type: pieceType });
  if (distanceM) search.set("distance_m", String(distanceM));
  if (durationS) search.set("duration_s", String(durationS));
  const { splits } = await request<{ splits: PieceSplitRow[] }>(`/api/activities/${canonicalId}/pieces/template?${search.toString()}`);
  return splits;
}

export interface CreatePieceBody {
  piece_type: ErgTestType;
  splits: PieceSplitRow[];
  distance_m?: number | null;
  duration_s?: number | null;
  drag_factor?: number | null;
  source?: "manual" | "photo";
  notes?: string | null;
  force?: boolean;
}

export async function createPiece(canonicalId: number, body: CreatePieceBody): Promise<CreatePieceResult> {
  if (isMock) return delay(createMockPiece(canonicalId, body), 200);
  return request<CreatePieceResult>(`/api/activities/${canonicalId}/pieces`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// Multipart, like the nutrition photo-estimate — the only other upload this app does.
export async function estimatePiecePhoto(canonicalId: number, photo: Blob): Promise<PiecePhotoEstimate> {
  if (isMock) return delay(mockPiecePhotoEstimate(), 1200);
  const form = new FormData();
  form.append("photo", photo, "pm5.jpg");
  const res = await fetch(`/api/activities/${canonicalId}/pieces/photo-estimate`, { method: "POST", credentials: "include", body: form });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    if (res.status === 401) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    throw new ApiError(res.status, body.detail ?? res.statusText);
  }
  return res.json() as Promise<PiecePhotoEstimate>;
}

export interface UpdatePieceBody {
  splits?: PieceSplitRow[];
  distance_m?: number | null;
  duration_s?: number | null;
  notes?: string | null;
  force?: boolean;
}

export async function updatePiece(pieceId: number, body: UpdatePieceBody): Promise<CreatePieceResult> {
  if (isMock) return delay(updateMockPiece(pieceId, body), 200);
  return request<CreatePieceResult>(`/api/pieces/${pieceId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function deletePiece(pieceId: number): Promise<void> {
  if (isMock) {
    deleteMockPiece(pieceId);
    return delay(undefined, 150);
  }
  await request(`/api/pieces/${pieceId}`, { method: "DELETE" });
}

export async function alignPiece(pieceId: number, activityId?: number, startS?: number): Promise<Piece> {
  if (isMock) return delay(alignMockPiece(pieceId, activityId, startS), 150);
  return request<Piece>(`/api/pieces/${pieceId}/align`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ activity_id: activityId, start_s: startS }),
  });
}

export async function uploadPiecePhoto(pieceId: number, photo: Blob): Promise<{ has_photo: true }> {
  if (isMock) return delay(uploadMockPiecePhoto(pieceId), 400);
  const form = new FormData();
  form.append("photo", photo, "pm5.jpg");
  const res = await fetch(`/api/pieces/${pieceId}/photo`, { method: "POST", credentials: "include", body: form });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    if (res.status === 401) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    throw new ApiError(res.status, body.detail ?? res.statusText);
  }
  return res.json() as Promise<{ has_photo: true }>;
}

export function piecePhotoUrl(pieceId: number): string {
  return `/api/pieces/${pieceId}/photo`;
}

export async function deletePiecePhoto(pieceId: number): Promise<void> {
  if (isMock) {
    deleteMockPiecePhoto(pieceId);
    return delay(undefined, 150);
  }
  await request(`/api/pieces/${pieceId}/photo`, { method: "DELETE" });
}

export async function fetchPieceTestDetail(pieceId: number): Promise<PieceTestDetail> {
  if (isMock) return delay(mockPieceTestDetail(pieceId));
  return request<PieceTestDetail>(`/api/pieces/${pieceId}/test-detail`);
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

// --- Nutrition (session 13) -----------------------------------------------------

export async function lookupBarcode(barcode: string): Promise<BarcodeLookupResult> {
  if (isMock) return delay(mockBarcodeLookup(barcode), 400);
  return request<BarcodeLookupResult>(`/api/nutrition/barcode/${encodeURIComponent(barcode)}`);
}

// `includeOff`: Open Food Facts' legacy free-text search is opt-in, never part of the plain
// debounced as-you-type call — OFF's own docs warn against exactly that pattern. Callers pass
// true only for an explicit, one-shot action (the "Also search Open Food Facts" button).
export async function searchFoods(query: string, includeOff = false): Promise<Food[]> {
  if (isMock) return delay(mockFoodSearch(query, includeOff), 250);
  const search = new URLSearchParams({ q: query });
  if (includeOff) search.set("include_off", "true");
  const { results } = await request<{ results: Food[] }>(`/api/nutrition/search?${search.toString()}`);
  return results;
}

export async function createManualFood(fields: {
  barcode?: string | null;
  name: string;
  brand?: string | null;
  serving_size?: number | null;
  serving_unit?: string | null;
  kcal_100g?: number | null;
  protein_100g?: number | null;
  carbs_100g?: number | null;
  fat_100g?: number | null;
  fiber_100g?: number | null;
  sugar_100g?: number | null;
  sodium_100g?: number | null;
}): Promise<Food> {
  if (isMock) return delay(createMockManualFood({ ...fields, barcode: fields.barcode ?? null } as Food), 200);
  return request<Food>("/api/nutrition/foods", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  });
}

export async function fetchMyFoods(): Promise<MyFoodRow[]> {
  if (isMock) return delay(mockMyFoods());
  const { my_foods } = await request<{ my_foods: MyFoodRow[] }>("/api/nutrition/my-foods");
  return my_foods;
}

export async function starFood(foodId: number, label?: string | null): Promise<MyFoodRow> {
  if (isMock) return delay(starMockFood(foodId, label ?? null), 150);
  const search = new URLSearchParams({ food_id: String(foodId) });
  if (label) search.set("label", label);
  return request<MyFoodRow>(`/api/nutrition/my-foods?${search.toString()}`, { method: "POST" });
}

export async function unstarFood(myFoodId: number): Promise<void> {
  if (isMock) {
    unstarMockFood(myFoodId);
    return delay(undefined, 100);
  }
  await request(`/api/nutrition/my-foods/${myFoodId}`, { method: "DELETE" });
}

export async function fetchSavedMeals(): Promise<SavedMealRow[]> {
  if (isMock) return delay(mockSavedMeals());
  const { saved_meals } = await request<{ saved_meals: SavedMealRow[] }>("/api/nutrition/saved-meals");
  return saved_meals;
}

export async function saveMeal(name: string, items: SavedMealItem[]): Promise<SavedMealRow> {
  if (isMock) return delay(saveMockMeal(name, items), 200);
  return request<SavedMealRow>("/api/nutrition/saved-meals", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, items }),
  });
}

export async function deleteSavedMeal(id: number): Promise<void> {
  if (isMock) {
    deleteMockSavedMeal(id);
    return delay(undefined, 100);
  }
  await request(`/api/nutrition/saved-meals/${id}`, { method: "DELETE" });
}

export async function logSavedMeal(savedMealId: number, meal: Meal, ts?: string): Promise<number[]> {
  if (isMock) return delay(logMockSavedMeal(savedMealId, meal, ts).map((r) => r.id), 200);
  const { logged } = await request<{ logged: number[] }>(`/api/nutrition/saved-meals/${savedMealId}/log`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ meal, ts }),
  });
  return logged;
}

export async function fetchFoodLogs(from: string, to: string): Promise<FoodLogRow[]> {
  if (isMock) return delay(listMockFoodLogs(from, to));
  const search = new URLSearchParams({ from, to });
  const { logs } = await request<{ logs: FoodLogRow[] }>(`/api/nutrition/logs?${search.toString()}`);
  return logs;
}

type LogMutationResult = { id: number; kcal: number | null; protein: number | null; carbs: number | null; fat: number | null };

export async function logFood(args: { ts?: string; meal: Meal; foodId: number; quantity: number; unit: "g" | "serving" }): Promise<LogMutationResult> {
  if (isMock) return delay(createMockFoodLog(args.ts, args.meal, args.foodId, args.quantity, args.unit), 200);
  return request<LogMutationResult>("/api/nutrition/logs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ts: args.ts, meal: args.meal, food_id: args.foodId, quantity: args.quantity, unit: args.unit }),
  });
}

export async function updateFoodLog(logId: number, patch: { meal?: Meal; quantity?: number; unit?: "g" | "serving" }): Promise<LogMutationResult> {
  if (isMock) return delay(updateMockFoodLog(logId, patch), 150);
  return request<LogMutationResult>(`/api/nutrition/logs/${logId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export async function deleteFoodLog(logId: number): Promise<void> {
  if (isMock) {
    deleteMockFoodLog(logId);
    return delay(undefined, 100);
  }
  await request(`/api/nutrition/logs/${logId}`, { method: "DELETE" });
}

export async function copyDayLogs(fromDate: string, toDate: string, meal?: Meal): Promise<number[]> {
  if (isMock) return delay(copyMockDayLogs(fromDate, toDate, meal).map((r) => r.id), 250);
  const { logged } = await request<{ logged: number[] }>("/api/nutrition/logs/copy-day", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ from_date: fromDate, to_date: toDate, meal }),
  });
  return logged;
}

export async function fetchNutritionTargets(): Promise<NutritionTargetsResponse> {
  if (isMock) return delay(mockNutritionTargets());
  return request<NutritionTargetsResponse>("/api/nutrition/targets");
}

export async function saveNutritionTargets(patch: Partial<NutritionTargetSettings>): Promise<NutritionTargetsResponse> {
  if (isMock) return delay(saveMockNutritionTargets(patch), 200);
  return request<NutritionTargetsResponse>("/api/nutrition/targets", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export async function fetchDaySummary(day: string): Promise<DaySummary> {
  if (isMock) return delay(mockDaySummary(day));
  return request<DaySummary>(`/api/nutrition/summary/day?day=${day}`);
}

export async function fetchWeekSummary(from: string, to: string): Promise<WeekSummary> {
  if (isMock) return delay(mockWeekSummary(from, to));
  const search = new URLSearchParams({ from, to });
  return request<WeekSummary>(`/api/nutrition/summary/week?${search.toString()}`);
}

// Multipart, not the usual JSON `request()` helper — the only upload this app does.
export async function estimateMealPhoto(photo: Blob): Promise<PhotoEstimateResult> {
  if (isMock) return delay(mockPhotoEstimate(), 1200);
  const form = new FormData();
  form.append("photo", photo, "meal.jpg");
  const res = await fetch("/api/nutrition/photo-estimate", { method: "POST", credentials: "include", body: form });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    if (res.status === 401) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    throw new ApiError(res.status, body.detail ?? res.statusText);
  }
  return res.json() as Promise<PhotoEstimateResult>;
}

export async function savePhotoEstimate(items: PhotoEstimateItem[], meal: Meal, ts?: string): Promise<number[]> {
  if (isMock) return delay(savePhotoEstimateMock(items, meal, ts), 200);
  const { logged } = await request<{ logged: number[] }>("/api/nutrition/photo-estimate/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ts, meal, items }),
  });
  return logged;
}

// --- Gym logger (session 14) ----------------------------------------------------------
//
// The active-session logging screen reads/writes IndexedDB directly (gymDb.ts/gymSync.ts) —
// these are the library/gyms/templates/history/readiness reads, mock-gated like every other
// page in the app.

export async function fetchExercises(query?: string): Promise<Exercise[]> {
  if (isMock) return delay(mockExercises(query));
  const search = query ? `?q=${encodeURIComponent(query)}` : "";
  const { exercises } = await request<{ exercises: Exercise[] }>(`/api/gym/exercises${search}`);
  return exercises;
}

export async function createExercise(fields: Omit<Exercise, "id" | "external_id" | "custom">): Promise<Exercise> {
  if (isMock) return delay(createMockExercise(fields), 200);
  return request<Exercise>("/api/gym/exercises", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  });
}

export async function updateExercise(id: number, patch: Partial<Exercise>): Promise<Exercise> {
  if (isMock) return delay(updateMockExercise(id, patch), 200);
  return request<Exercise>(`/api/gym/exercises/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export async function fetchGyms(): Promise<GymRow[]> {
  if (isMock) return delay(mockGyms());
  const { gyms } = await request<{ gyms: GymRow[] }>("/api/gym/gyms");
  return gyms;
}

export async function createGym(name: string): Promise<GymRow> {
  if (isMock) return delay(createMockGym(name), 200);
  return request<GymRow>("/api/gym/gyms", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export async function fetchStations(gymId: number): Promise<GymStation[]> {
  if (isMock) return delay(mockStations(gymId));
  const { stations } = await request<{ stations: GymStation[] }>(`/api/gym/gyms/${gymId}/stations`);
  return stations;
}

export async function upsertStation(
  gymId: number,
  fields: { name: string; equipment_type: GymStation["equipment_type"]; config: GymStation["config"] },
  stationId?: number,
): Promise<GymStation> {
  if (isMock) return delay(upsertMockStation(gymId, fields, stationId), 200);
  const path = stationId ? `/api/gym/gyms/${gymId}/stations/${stationId}` : `/api/gym/gyms/${gymId}/stations`;
  return request<GymStation>(path, {
    method: stationId ? "PUT" : "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  });
}

export async function fetchTemplates(): Promise<StrengthTemplate[]> {
  if (isMock) return delay(mockTemplates());
  const { templates } = await request<{ templates: StrengthTemplate[] }>("/api/gym/templates");
  return templates;
}

export async function saveTemplate(name: string, items: StrengthTemplateItem[], templateId?: number): Promise<StrengthTemplate> {
  if (isMock) return delay(saveMockTemplate(name, items, templateId), 200);
  const path = templateId ? `/api/gym/templates/${templateId}` : "/api/gym/templates";
  return request<StrengthTemplate>(path, {
    method: templateId ? "PUT" : "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, items }),
  });
}

export async function deleteTemplate(id: number): Promise<void> {
  if (isMock) return delay(deleteMockTemplate(id), 150);
  await request<{ deleted: true }>(`/api/gym/templates/${id}`, { method: "DELETE" });
}

export async function fetchRepeatLastWorkout(): Promise<RepeatWorkoutPlanItem[]> {
  if (isMock) return delay(mockRepeatLastWorkout());
  const { plan } = await request<{ plan: RepeatWorkoutPlanItem[] }>("/api/gym/repeat-last-workout");
  return plan;
}

export async function fetchLastSetsForExercise(exerciseId: number): Promise<StrengthSetRow[]> {
  if (isMock) return delay(mockLastSetsForExercise(exerciseId));
  const { sets } = await request<{ sets: StrengthSetRow[] }>(`/api/gym/exercises/${exerciseId}/last`);
  return sets;
}

export async function fetchMuscleReadiness(): Promise<MuscleReadiness> {
  if (isMock) return delay(mockMuscleReadiness());
  return request<MuscleReadiness>("/api/gym/muscle-readiness");
}

// --- Session 16 (see PLAN.md Part A) — push notifications ---

export async function fetchVapidPublicKey(): Promise<string> {
  if (isMock) return delay("mock-vapid-public-key");
  const { public_key } = await request<{ public_key: string }>("/api/push/vapid-public-key");
  return public_key;
}

export async function subscribePush(sub: {
  endpoint: string;
  keys: { p256dh: string; auth: string };
  label?: string;
  user_agent?: string;
}): Promise<PushSubscriptionRow> {
  if (isMock) return delay(mockSubscribePush(sub), 200);
  return request<PushSubscriptionRow>("/api/push/subscribe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(sub),
  });
}

export async function unsubscribePush(endpoint: string): Promise<void> {
  if (isMock) return delay(mockUnsubscribePush(endpoint), 150);
  await request<{ deleted: true }>("/api/push/subscribe", {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ endpoint }),
  });
}

export async function fetchPushSubscriptions(): Promise<PushSubscriptionRow[]> {
  if (isMock) return delay(mockPushSubscriptions());
  return request<PushSubscriptionRow[]>("/api/push/subscriptions");
}

export async function sendTestPush(subscriptionId: number): Promise<void> {
  if (isMock) return delay(undefined, 400);
  await request<{ sent: true }>("/api/push/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ subscription_id: subscriptionId }),
  });
}

// --- Session 16 (see PLAN.md Part B) — monitoring ---

export async function fetchStatus(): Promise<AppStatus> {
  if (isMock) return delay(mockStatus());
  return request<AppStatus>("/api/status");
}
