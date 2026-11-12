import {
  mockAiModels,
  mockAiProviders,
  mockAiUsage,
  mockDeleteAiKey,
  mockPutAiKey,
  mockSetActive,
  mockTestAiProvider,
} from "./mockAi";
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
  dismissMockRecommendation,
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
  mockPerformanceTrends,
  mockPhotoEstimate,
  mockPieces,
  mockIntervalTemplate,
  replaceMockIntervals,
  reorderMockIntervals,
  importMockConcept2Intervals,
  mockIntervalComparisons,
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
  mockRecommendations,
  mockRepeatLastWorkout,
  mockSavedMeals,
  mockScenarioFromQuery,
  mockSeries,
  mockSettings,
  mockStations,
  mockSyncStatus,
  mockTemplates,
  mockTrainingConsistency,
  mockTrainingDistribution,
  mockTrainingInsights,
  mockTrainingProfile,
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
  rateMockRecommendation,
  revertMockActivityField,
  saveMockCheckin,
  saveMockRecommendation,
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
import {
  mockOnWater,
  mockRouteDetail,
  mockRouteHistory,
  mockRoutes,
  mockTrack,
  mockWeather,
  patchMockRoute,
  putMockActivityRoute,
  refreshMockWeather,
} from "./mockGps";
import type {
  OnWaterResponse,
  RouteDetailData,
  RouteHistory,
  RouteRef,
  TrackResponse,
  WeatherResponse,
  IntervalComparisonBucket,
  IntervalRepeatSpec,
  IntervalsResult,
  PieceInterval,
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
  Recommendation,
  RecommendationRating,
  RecommendationStatus,
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
  TrainingConsistency,
  TrainingDistribution,
  TrainingInsight,
  TrainingProfile,
  PerformanceTrends,
  TrendMetric,
  VolumeWeek,
  WeekSummary,
  WorkoutCategory,
  WorkoutDetail,
  WorkoutsPage,
  PushSubscriptionRow,
  AppStatus,
} from "./types";
import type {
  FeedbackEntry,
  FeedbackFilters,
  FeedbackInput,
  FeedbackRevision,
  ScheduleInput,
  TechniqueNote,
  TechniqueNoteInput,
  TemplateInput,
  TemplatePreview,
  TemplateScope,
  WorkoutTemplate,
} from "./types";
import type { AiModelsResponse, AiProviderCard, AiProvidersResponse, AiTestResult, AiUsage, CoachProviderName, WhoopTestResult } from "./types";
import type { CalendarPayload, EventInput, EventOverview, EventProjection, PhaseInput, PlanWeekSummary, PlannedInput, PlannedWorkout, PlanPhase, UpcomingEvent } from "./types";
import * as mockCal from "./mockCalendar";
import * as mockCoach from "./mockCoaching";
import * as mockLib from "./mockLibrary";

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
  /** Session 19: present => an interval piece; splits are ignored server-side. */
  intervals?: PieceInterval[];
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

// --- Intervals within a piece (session 19 — see PLAN.md) ---------------------------------

/** "4 x 500m r1:00" -> rows. The server owns this (catch.analytics.piece_intervals.expand_repeat)
 * so the UI, the API and the coach can't disagree. */
export async function fetchIntervalTemplate(canonicalId: number, spec: IntervalRepeatSpec): Promise<PieceInterval[]> {
  if (isMock) return delay(mockIntervalTemplate(spec), 80);
  const search = new URLSearchParams({ count: String(spec.count) });
  if (spec.distance_m) search.set("distance_m", String(spec.distance_m));
  if (spec.duration_s) search.set("duration_s", String(spec.duration_s));
  if (spec.rest_s) search.set("rest_s", String(spec.rest_s));
  const { intervals } = await request<{ intervals: PieceInterval[] }>(`/api/activities/${canonicalId}/pieces/interval-template?${search.toString()}`);
  return intervals;
}

/** Replaces the piece's whole ordered interval set (rows that carry an `id` keep it). Soft
 * validation like splits: `saved: false` + issues unless `force`. */
export async function replaceIntervals(pieceId: number, intervals: PieceInterval[], force = false): Promise<IntervalsResult> {
  if (isMock) return delay(replaceMockIntervals(pieceId, intervals, force), 200);
  return request<IntervalsResult>(`/api/pieces/${pieceId}/intervals`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ replace: intervals, force }),
  });
}

export async function reorderIntervals(pieceId: number, ids: number[]): Promise<IntervalsResult> {
  if (isMock) {
    return delay(reorderMockIntervals(pieceId, ids), 150);
  }
  return request<IntervalsResult>(`/api/pieces/${pieceId}/intervals/order`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  });
}

export async function importConcept2Intervals(canonicalId: number, activityId: number): Promise<Piece> {
  if (isMock) return delay(importMockConcept2Intervals(canonicalId), 300);
  const { piece } = await request<{ piece: Piece }>(`/api/activities/${canonicalId}/pieces/from-concept2`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ activity_id: activityId }),
  });
  return piece;
}

export async function fetchIntervalComparisons(): Promise<{ buckets: IntervalComparisonBucket[] }> {
  if (isMock) return delay(mockIntervalComparisons());
  return request<{ buckets: IntervalComparisonBucket[] }>("/api/training-intelligence/intervals");
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

// --- AI providers (session 23) -----------------------------------------------

export async function fetchAiProviders(): Promise<AiProvidersResponse> {
  if (isMock) return delay(mockAiProviders());
  return request<AiProvidersResponse>("/api/ai/providers");
}

export async function putAiKey(provider: CoachProviderName, apiKey: string): Promise<AiProviderCard & { validated: boolean }> {
  if (isMock) return delay({ ...mockPutAiKey(provider, apiKey), validated: true }, 500);
  return request(`/api/ai/providers/${provider}/key`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: apiKey }),
  });
}

export async function deleteAiKey(provider: CoachProviderName): Promise<AiProvidersResponse> {
  if (isMock) return delay(mockDeleteAiKey(provider), 150);
  return request(`/api/ai/providers/${provider}/key`, { method: "DELETE" });
}

export async function testAiProvider(provider: CoachProviderName): Promise<AiTestResult> {
  if (isMock) return delay(mockTestAiProvider(provider), 500);
  return request(`/api/ai/providers/${provider}/test`, { method: "POST" });
}

export async function fetchAiModels(provider: CoachProviderName): Promise<AiModelsResponse> {
  if (isMock) return delay(mockAiModels(provider), 150);
  return request(`/api/ai/providers/${provider}/models`);
}

export async function setActiveAi(provider: CoachProviderName, model?: string): Promise<AiProvidersResponse> {
  if (isMock) return delay(mockSetActive(provider, model), 150);
  return request("/api/ai/active", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider, model: model ?? null }),
  });
}

export async function fetchAiUsage(): Promise<AiUsage> {
  if (isMock) return delay(mockAiUsage());
  return request<AiUsage>("/api/ai/usage");
}

// --- Whoop (session 23) --------------------------------------------------------

export async function disconnectWhoop(): Promise<{ revoked: boolean; was_connected: boolean }> {
  if (isMock) return delay({ revoked: true, was_connected: true }, 200);
  return request("/auth/whoop/disconnect", { method: "POST" });
}

export async function testWhoop(): Promise<WhoopTestResult> {
  if (isMock) return delay({ connected: true, recovery: { ok: true, has_records: true }, sleep: { ok: true, has_records: true }, workout: { ok: true, has_records: true }, token_expires_at: null }, 600);
  return request("/api/whoop/test");
}

// --- Coach: device tokens -----------------------------------------------------

export async function fetchTokens(): Promise<DeviceToken[]> {
  if (isMock) return delay(mockTokens());
  return request<DeviceToken[]>("/api/coach/tokens");
}

export async function createToken(name: string, role: "athlete" | "coach" = "athlete", displayName?: string): Promise<DeviceToken & { token: string }> {
  if (isMock) return delay(createMockToken(name, role, displayName), 150);
  return request("/api/coach/tokens", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, role, display_name: displayName || null }),
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

// --- Training intelligence (session 18) ---------------------------------------------------

export async function fetchTrainingProfile(): Promise<TrainingProfile> {
  if (isMock) return delay(mockTrainingProfile(MOCK_SCENARIO!));
  return request<TrainingProfile>("/api/training-intelligence/profile");
}

export async function fetchPerformanceTrends(pieceType?: ErgTestType): Promise<PerformanceTrends> {
  if (isMock) return delay(mockPerformanceTrends(MOCK_SCENARIO!));
  const search = new URLSearchParams();
  if (pieceType) search.set("piece_type", pieceType);
  return request<PerformanceTrends>(`/api/training-intelligence/trends?${search.toString()}`);
}

export async function fetchTrainingDistribution(weeks = 12): Promise<TrainingDistribution> {
  if (isMock) return delay(mockTrainingDistribution(MOCK_SCENARIO!, weeks));
  return request<TrainingDistribution>(`/api/training-intelligence/distribution?weeks=${weeks}`);
}

export async function fetchTrainingConsistency(weeks?: number): Promise<TrainingConsistency> {
  if (isMock) return delay(mockTrainingConsistency(MOCK_SCENARIO!, weeks ?? 8));
  const search = new URLSearchParams();
  if (weeks) search.set("weeks", String(weeks));
  return request<TrainingConsistency>(`/api/training-intelligence/consistency?${search.toString()}`);
}

export async function fetchTrainingInsights(): Promise<TrainingInsight[]> {
  if (isMock) return delay(mockTrainingInsights(MOCK_SCENARIO!));
  const { insights } = await request<{ insights: TrainingInsight[] }>("/api/training-intelligence/insights");
  return insights;
}

export async function fetchRecommendations(status: RecommendationStatus = "active", type?: string): Promise<Recommendation[]> {
  if (isMock) return delay(mockRecommendations(MOCK_SCENARIO!, status, type));
  const search = new URLSearchParams({ status });
  if (type) search.set("type", type);
  const { recommendations } = await request<{ recommendations: Recommendation[] }>(`/api/training-intelligence/recommendations?${search.toString()}`);
  return recommendations;
}

export async function dismissRecommendation(id: number): Promise<Recommendation> {
  if (isMock) return delay(dismissMockRecommendation(id), 150);
  return request<Recommendation>(`/api/training-intelligence/recommendations/${id}/dismiss`, { method: "POST" });
}

export async function saveRecommendation(id: number, saved: boolean): Promise<Recommendation> {
  if (isMock) return delay(saveMockRecommendation(id, saved), 150);
  return request<Recommendation>(`/api/training-intelligence/recommendations/${id}/save`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ saved }),
  });
}

export async function rateRecommendation(id: number, rating: RecommendationRating): Promise<Recommendation> {
  if (isMock) return delay(rateMockRecommendation(id, rating), 150);
  return request<Recommendation>(`/api/training-intelligence/recommendations/${id}/rate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rating }),
  });
}


// --- Session 20: GPS track, on-water metrics, weather, routes -----------------------------------

export async function fetchTrack(canonicalId: number, points = 600): Promise<TrackResponse> {
  if (isMock) return delay(mockTrack(canonicalId, points));
  return request<TrackResponse>(`/api/activities/${canonicalId}/track?points=${points}`);
}

export async function fetchOnWater(canonicalId: number, splitM?: number): Promise<OnWaterResponse> {
  if (isMock) return delay(mockOnWater(canonicalId, splitM));
  return request<OnWaterResponse>(`/api/activities/${canonicalId}/on-water${splitM ? `?split_m=${splitM}` : ""}`);
}

export async function fetchWorkoutWeather(canonicalId: number): Promise<WeatherResponse> {
  if (isMock) return delay(mockWeather(canonicalId));
  return request<WeatherResponse>(`/api/activities/${canonicalId}/weather`);
}

export async function refreshWorkoutWeather(canonicalId: number): Promise<WeatherResponse> {
  if (isMock) return delay(refreshMockWeather(canonicalId), 500);
  return request<WeatherResponse>(`/api/activities/${canonicalId}/weather/refresh`, { method: "POST" });
}

export async function setActivityRoute(
  canonicalId: number,
  body: { route_id?: number | null; unpin?: boolean; new_route?: boolean; name?: string },
): Promise<{ route: RouteRef | null }> {
  if (isMock) return delay(putMockActivityRoute(canonicalId, body));
  return request<{ route: RouteRef | null }>(`/api/activities/${canonicalId}/route`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function fetchRoutes(): Promise<RouteRef[]> {
  if (isMock) return delay(mockRoutes());
  return (await request<{ routes: RouteRef[] }>("/api/routes")).routes;
}

export async function fetchRoute(id: number): Promise<RouteDetailData> {
  if (isMock) return delay(mockRouteDetail(id));
  return request<RouteDetailData>(`/api/routes/${id}`);
}

export async function patchRoute(id: number, patch: { name?: string | null; tags?: string[] }): Promise<RouteDetailData> {
  if (isMock) return delay(patchMockRoute(id, patch), 200);
  return request<RouteDetailData>(`/api/routes/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export async function fetchRouteHistory(id: number): Promise<RouteHistory> {
  if (isMock) return delay(mockRouteHistory(id));
  return request<RouteHistory>(`/api/routes/${id}/history`);
}


// --- Session 21: calendar, race planning, periodization ----------------------------------------

const JSON_HEADERS = { "Content-Type": "application/json" };

function send<T>(path: string, method: string, body?: unknown): Promise<T> {
  return request<T>(path, { method, headers: JSON_HEADERS, body: body === undefined ? undefined : JSON.stringify(body) });
}

// The mock layer throws plain Errors for the 404/422 cases the server would return; surface them
// the same way the real client does so a form shows the message either way.
function mocked<T>(fn: () => T, ms = 150): Promise<T> {
  try {
    return delay(fn(), ms);
  } catch (e) {
    return Promise.reject(new ApiError(422, e instanceof Error ? e.message : "Request failed"));
  }
}

export async function fetchCalendar(from: string, to: string): Promise<CalendarPayload> {
  if (isMock) {
    if (MOCK_SCENARIO === "error") throw new ApiError(500, "Mock server error");
    return delay(mockCal.mockCalendar(from, to), 120);
  }
  return request<CalendarPayload>(`/api/calendar?from=${from}&to=${to}`);
}

export async function fetchPlanWeekSummary(weekStart: string): Promise<PlanWeekSummary> {
  if (isMock) return delay(mockCal.mockPlanWeekSummary(weekStart), 120);
  return request<PlanWeekSummary>(`/api/calendar/week-summary?week_start=${weekStart}`);
}

export async function createPlanned(body: PlannedInput): Promise<{ planned: PlannedWorkout[] }> {
  if (isMock) return mocked(() => ({ planned: mockCal.createMockPlanned(body) }));
  return send("/api/planned", "POST", body);
}

export async function updatePlanned(id: number, patch: Partial<PlannedInput>, scope: "this" | "this_and_following" = "this"): Promise<{ planned: PlannedWorkout[] }> {
  if (isMock) return mocked(() => ({ planned: mockCal.updateMockPlanned(id, patch, scope) }));
  return send(`/api/planned/${id}?scope=${scope}`, "PATCH", patch);
}

export async function movePlanned(id: number, date: string): Promise<PlannedWorkout> {
  if (isMock) return mocked(() => mockCal.updateMockPlanned(id, { date }, "this")[0]);
  return send(`/api/planned/${id}/move`, "POST", { date });
}

export async function deletePlanned(id: number, scope: "this" | "this_and_following" = "this"): Promise<{ deleted: number }> {
  if (isMock) return mocked(() => ({ deleted: mockCal.deleteMockPlanned(id, scope) }));
  return request<{ deleted: number }>(`/api/planned/${id}?scope=${scope}`, { method: "DELETE" });
}

export async function linkPlanned(id: number, canonicalId: number): Promise<PlannedWorkout> {
  if (isMock) return mocked(() => mockCal.linkMockPlanned(id, canonicalId));
  return send(`/api/planned/${id}/link`, "POST", { canonical_id: canonicalId });
}

export async function unlinkPlanned(id: number): Promise<PlannedWorkout> {
  if (isMock) return mocked(() => mockCal.unlinkMockPlanned(id));
  return send(`/api/planned/${id}/unlink`, "POST");
}

export async function declineMatch(id: number, canonicalId: number): Promise<{ ok: boolean }> {
  if (isMock) return mocked(() => {
    mockCal.declineMockMatch(id, canonicalId);
    return { ok: true };
  });
  return send(`/api/planned/${id}/decline`, "POST", { canonical_id: canonicalId });
}

export async function setPlannedSkipped(id: number, skipped: boolean): Promise<PlannedWorkout> {
  if (isMock) return mocked(() => mockCal.skipMockPlanned(id, skipped));
  return send(`/api/planned/${id}/${skipped ? "skip" : "unskip"}`, "POST");
}

export async function fetchUpcomingEvents(limit = 5): Promise<{ events: UpcomingEvent[] }> {
  if (isMock) return delay({ events: mockCal.mockUpcomingEvents(limit) }, 150);
  return request<{ events: UpcomingEvent[] }>(`/api/events/upcoming?limit=${limit}`);
}

export async function fetchEvents(): Promise<{ events: UpcomingEvent[] }> {
  if (isMock) return delay({ events: mockCal.mockEvents() }, 120);
  return request<{ events: UpcomingEvent[] }>("/api/events");
}

export async function fetchEventOverview(id: number): Promise<EventOverview> {
  if (isMock) return mocked(() => mockCal.mockEventOverview(id), 150);
  return request<EventOverview>(`/api/events/${id}`);
}

export async function fetchEventProjection(id: number): Promise<EventProjection> {
  if (isMock) return mocked(() => mockCal.mockEventProjection(id), 200);
  return request<EventProjection>(`/api/events/${id}/projection`);
}

export async function createEvent(body: EventInput): Promise<UpcomingEvent> {
  if (isMock) return mocked(() => mockCal.createMockEvent(body));
  return send("/api/events", "POST", body);
}

export async function updateEvent(id: number, patch: Partial<EventInput>): Promise<UpcomingEvent> {
  if (isMock) return mocked(() => mockCal.updateMockEvent(id, patch));
  return send(`/api/events/${id}`, "PATCH", patch);
}

export async function deleteEvent(id: number): Promise<{ ok: boolean }> {
  if (isMock) return mocked(() => {
    mockCal.deleteMockEvent(id);
    return { ok: true };
  });
  return request<{ ok: boolean }>(`/api/events/${id}`, { method: "DELETE" });
}

export async function fetchPhases(): Promise<{ phases: PlanPhase[] }> {
  if (isMock) return delay({ phases: mockCal.mockPhases() }, 120);
  return request<{ phases: PlanPhase[] }>("/api/phases");
}

export async function createPhase(body: PhaseInput): Promise<PlanPhase> {
  if (isMock) return mocked(() => mockCal.createMockPhase(body));
  return send("/api/phases", "POST", body);
}

export async function updatePhase(id: number, patch: Partial<PhaseInput>): Promise<PlanPhase> {
  if (isMock) return mocked(() => mockCal.updateMockPhase(id, patch));
  return send(`/api/phases/${id}`, "PATCH", patch);
}

export async function deletePhase(id: number): Promise<{ ok: boolean }> {
  if (isMock) return mocked(() => {
    mockCal.deleteMockPhase(id);
    return { ok: true };
  });
  return request<{ ok: boolean }>(`/api/phases/${id}`, { method: "DELETE" });
}

export async function approvePhase(id: number, approvedBy: string | null, note: string | null): Promise<PlanPhase> {
  if (isMock) return mocked(() => mockCal.approveMockPhase(id, approvedBy, note));
  return send(`/api/phases/${id}/approve`, "POST", { approved_by: approvedBy, note });
}

export async function unapprovePhase(id: number): Promise<PlanPhase> {
  if (isMock) return mocked(() => mockCal.unapproveMockPhase(id));
  return send(`/api/phases/${id}/unapprove`, "POST");
}


// --- Session 22: workout library, technique notes, coach feedback ---------------------------------

export async function fetchLibraryTemplates(opts: { scope?: TemplateScope; q?: string; workout_type?: string; difficulty?: string } = {}): Promise<{ templates: WorkoutTemplate[] }> {
  if (isMock) {
    if (MOCK_SCENARIO === "error") throw new ApiError(500, "Mock server error");
    return delay({ templates: mockLib.mockTemplates(opts) }, 120);
  }
  const qs = new URLSearchParams({ scope: opts.scope ?? "mine" });
  if (opts.q) qs.set("q", opts.q);
  if (opts.workout_type) qs.set("workout_type", opts.workout_type);
  if (opts.difficulty) qs.set("difficulty", opts.difficulty);
  return request<{ templates: WorkoutTemplate[] }>(`/api/library/templates?${qs}`);
}

export async function fetchLibraryTemplate(id: number): Promise<WorkoutTemplate> {
  if (isMock) return mocked(() => mockLib.mockTemplate(id), 120);
  return request<WorkoutTemplate>(`/api/library/templates/${id}`);
}

export async function previewLibraryTemplate(body: TemplateInput): Promise<TemplatePreview> {
  if (isMock) return mocked(() => mockLib.mockPreview(body), 60);
  return send("/api/library/templates/preview", "POST", body);
}

export async function createLibraryTemplate(body: TemplateInput): Promise<WorkoutTemplate> {
  if (isMock) return mocked(() => mockLib.createMockTemplate(body));
  return send("/api/library/templates", "POST", body);
}

export async function updateLibraryTemplate(id: number, body: Partial<TemplateInput>): Promise<WorkoutTemplate> {
  if (isMock) return mocked(() => mockLib.updateMockTemplate(id, body));
  return send(`/api/library/templates/${id}`, "PATCH", body);
}

export async function duplicateLibraryTemplate(id: number, name?: string): Promise<WorkoutTemplate> {
  if (isMock) return mocked(() => mockLib.duplicateMockTemplate(id, name));
  return send(`/api/library/templates/${id}/duplicate`, "POST", name ? { name } : {});
}

export async function setLibraryTemplateArchived(id: number, archived: boolean): Promise<WorkoutTemplate> {
  if (isMock) return mocked(() => mockLib.archiveMockTemplate(id, archived));
  return send(`/api/library/templates/${id}/${archived ? "archive" : "unarchive"}`, "POST");
}

export async function scheduleLibraryTemplate(id: number, body: ScheduleInput): Promise<{ planned: PlannedWorkout[] }> {
  if (isMock) return mocked(() => ({ planned: mockLib.scheduleMockTemplate(id, body) }));
  return send(`/api/library/templates/${id}/schedule`, "POST", body);
}

export async function fetchTechniqueNotes(q: { workout_id?: number; piece_id?: number; date?: string; category?: string } = {}): Promise<{ notes: TechniqueNote[]; note: string }> {
  if (isMock) {
    if (MOCK_SCENARIO === "error") throw new ApiError(500, "Mock server error");
    return delay({ notes: mockCoach.mockNotes(q), note: "" }, 120);
  }
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) if (v !== undefined && v !== "") qs.set(k, String(v));
  return request<{ notes: TechniqueNote[]; note: string }>(`/api/technique-notes?${qs}`);
}

export async function createTechniqueNote(body: TechniqueNoteInput): Promise<TechniqueNote> {
  if (isMock) return mocked(() => mockCoach.createMockNote(body));
  return send("/api/technique-notes", "POST", body);
}

export async function updateTechniqueNote(id: number, body: Partial<TechniqueNoteInput>): Promise<TechniqueNote> {
  if (isMock) return mocked(() => mockCoach.updateMockNote(id, body));
  return send(`/api/technique-notes/${id}`, "PATCH", body);
}

export async function deleteTechniqueNote(id: number): Promise<{ ok: boolean }> {
  if (isMock) return mocked(() => {
    mockCoach.deleteMockNote(id);
    return { ok: true };
  });
  return request<{ ok: boolean }>(`/api/technique-notes/${id}`, { method: "DELETE" });
}

export async function fetchFeedback(f: FeedbackFilters = {}): Promise<{ feedback: FeedbackEntry[]; coaches: string[] }> {
  if (isMock) {
    if (MOCK_SCENARIO === "error") throw new ApiError(500, "Mock server error");
    return delay(mockCoach.mockFeedback(f), 120);
  }
  const qs = new URLSearchParams();
  if (f.coach) qs.set("coach", f.coach);
  if (f.category) qs.set("category", f.category);
  if (f.from) qs.set("from", f.from);
  if (f.to) qs.set("to", f.to);
  return request<{ feedback: FeedbackEntry[]; coaches: string[] }>(`/api/coach-feedback?${qs}`);
}

export async function createFeedback(body: FeedbackInput): Promise<FeedbackEntry> {
  if (isMock) return mocked(() => mockCoach.createMockFeedback(body));
  return send("/api/coach-feedback", "POST", body);
}

export async function updateFeedback(id: number, body: Partial<FeedbackInput>): Promise<FeedbackEntry> {
  if (isMock) return mocked(() => mockCoach.updateMockFeedback(id, body));
  return send(`/api/coach-feedback/${id}`, "PATCH", body);
}

export async function respondToFeedback(id: number, response: string | null): Promise<FeedbackEntry> {
  if (isMock) return mocked(() => mockCoach.respondMockFeedback(id, response));
  return send(`/api/coach-feedback/${id}/response`, "POST", { response });
}

export async function deleteFeedback(id: number): Promise<{ ok: boolean }> {
  if (isMock) return mocked(() => {
    mockCoach.deleteMockFeedback(id);
    return { ok: true };
  });
  return request<{ ok: boolean }>(`/api/coach-feedback/${id}`, { method: "DELETE" });
}

export async function fetchFeedbackHistory(id: number): Promise<{ history: FeedbackRevision[] }> {
  if (isMock) return mocked(() => ({ history: mockCoach.mockHistory(id) }), 100);
  return request<{ history: FeedbackRevision[] }>(`/api/coach-feedback/${id}/history`);
}
