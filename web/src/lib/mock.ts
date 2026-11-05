import type {
  ActivityOverrides,
  ActivitySamplesResponse,
  ActivitySourceSummary,
  BarcodeLookupResult,
  BodyCompReading,
  CoachConversation,
  CoachConversationDetail,
  CoachEvent,
  CoachMessageRow,
  CoachModel,
  CoachSettings,
  DaySummary,
  DeviceToken,
  DuplicatePair,
  ErgStrokesResponse,
  ErgTechnique,
  Food,
  FoodLogRow,
  IntervalSummary,
  Meal,
  MemoryEvent,
  MemoryFact,
  MemoryGoal,
  MemoryListing,
  MyFoodRow,
  Note,
  NutritionTargetSettings,
  NutritionTargetsResponse,
  PersonalBests,
  PhotoEstimateResult,
  SavedMealItem,
  SavedMealRow,
  Settings,
  SeriesForMetric,
  SeriesResponse,
  SparklinePoint,
  Stroke,
  SyncSourceStatus,
  Today,
  TrendMetric,
  TrendPoint,
  UnderFuelling,
  VolumeWeek,
  WeekSummary,
  WorkoutCategory,
  WorkoutDetail,
  WorkoutListItem,
  WorkoutsPage,
  ZoneRow,
  Exercise,
  GymRow,
  GymStation,
  MuscleReadiness,
  RepeatWorkoutPlanItem,
  StrengthSetRow,
  StrengthTemplate,
  StrengthTemplateItem,
} from "./types";
import { ZONE_NAMES } from "./types";
import { localDateString } from "./format";

export type MockScenario = "full" | "calibrating" | "empty" | "error" | "loading" | "offline";

export function mockScenarioFromQuery(): MockScenario | null {
  const params = new URLSearchParams(window.location.search);
  if (!params.has("mock")) return null;
  const value = params.get("mock");
  if (value === "" || value === "1" || value === "true") return "full";
  if (value === "calibrating" || value === "empty" || value === "error" || value === "loading" || value === "offline") return value;
  return "full";
}

function sparkline(values: (number | null)[], startDate: string): SparklinePoint[] {
  const start = new Date(startDate + "T00:00:00");
  return values.map((value, i) => {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    return { date: d.toISOString().slice(0, 10), value };
  });
}

const TODAY = new Date().toISOString().slice(0, 10);

const FULL: Today = {
  date: TODAY,
  generated_at: new Date().toISOString(),
  recovery: {
    value: 78.4,
    band: "green",
    components: [
      { metric: "hrv", baseline_7d_ln: Math.log(62), spread_60d: 0.07, value: 82 },
      { metric: "resting_hr", baseline_7d: 49, spread_60d: 2.1, value: 74 },
      { metric: "sleep", need_seconds: 28800, value: 88 },
      { metric: "prior_strain", value: 65 },
    ],
    explanation:
      "Weighted blend of HRV-vs-7d-baseline (normalised by 60d spread), resting HR deviation, sleep-vs-need, and prior-day strain.",
  },
  sleep_last_night: {
    seconds: 27300,
    score: 88,
    need_seconds: 28800,
    deep_seconds: 6200,
    light_seconds: 15100,
    rem_seconds: 5400,
    awake_seconds: 600,
  },
  strain_today: {
    value: 8.9,
    band: "light",
    trimp_like: 48,
    components: [{ canonical_id: 1, title: "Morning row", value: 8.2, band: "light", muscular_au: 0 }],
    daily_activity: { value: 0.7, steps: 6400, active_kcal: 210 },
    cardio: { value: 8.2, trimp_like: 48 },
    muscular: { value: 0, total_normalized_au: 0, explanation: "No muscular load logged." },
    explanation: "1 session today, Banister TRIMP from heart rate -> 8.2, plus daily activity 0.7 = 8.9.",
  },
  strain_target_range: [10, 16],
  daily_activity: { steps: 9800, active_kcal: 340 },
  load: {
    value: 1.08,
    band: "optimal",
    components: [{ acute_7d: 71.2, chronic_42d: 66.0, form: -5.2 }],
    explanation: "Acute (7d EWMA)=71.2, chronic (42d EWMA)=66.0, acute:chronic=1.08.",
  },
  rowing_load: {
    value: 1.02,
    band: "optimal",
    components: [{ acute_7d: 58.0, chronic_42d: 56.9, form: -1.1 }],
    explanation: "Acute (7d EWMA)=58.0, chronic (42d EWMA)=56.9, acute:chronic=1.02.",
  },
  hrv: {
    today: 64,
    sparkline_14d: sparkline([58, 60, 61, 59, 63, 62, 60, 64, 61, 63, 62, 65, 61, 64], shiftDate(TODAY, -13)),
    baseline_band: { baseline: 61.5, low: 57.8, high: 65.4 },
  },
  resting_hr: {
    today: 47,
    sparkline_14d: sparkline([50, 49, 51, 49, 48, 50, 49, 48, 47, 49, 48, 47, 48, 47], shiftDate(TODAY, -13)),
    baseline_band: { baseline: 48.8, low: 46.9, high: 50.7 },
  },
  latest_erg: {
    id: 1,
    canonical_id: 1,
    source: "concept2",
    external_id: "mock-1",
    type: "rower",
    start: new Date(Date.now() - 18 * 3600 * 1000).toISOString(),
    duration: 1860,
    distance: 8000,
    avg_hr: 158,
    max_hr: 174,
    avg_power: 214,
    calories: 410,
    workout_type: "JustRow",
    drag_factor: 128,
    stroke_rate: 24,
    linked_activity_id: null,
    weight_kg: 79,
    w_per_kg: 2.71,
  },
  predicted_2k: {
    value: 98.4,
    range: [97.1, 99.6],
    predicted_time_s: 393.6,
    band: "high",
    components: [],
    explanation: "Paul's law extrapolated from 4 recent pieces.",
  },
  recommendation: "Recovery is green — you're clear for a harder session if it's on the plan.",
  next_a_race: { name: "Head of the Charles", date: shiftDate(TODAY, 9), days_to_go: 9, taper: true },
  under_fuelling: { flag: false, logged_days: 6, explanation: "Intake has kept pace with expenditure over the last logged days." },
};

const CALIBRATING: Today = {
  ...FULL,
  recovery: {
    value: null,
    band: "calibrating",
    components: [],
    explanation: "Need 7 nights of HRV history before a baseline exists; have 3.",
  },
  strain_target_range: [0, 21],
  hrv: { today: 61, sparkline_14d: sparkline([null, null, null, null, 59, 61, 60], shiftDate(TODAY, -6)), baseline_band: null },
  resting_hr: {
    today: 49,
    sparkline_14d: sparkline([null, null, null, null, 50, 49, 49], shiftDate(TODAY, -6)),
    baseline_band: null,
  },
  recommendation: "Still calibrating your recovery baseline (need 7+ nights of HRV) — no number yet.",
};

const EMPTY: Today = {
  date: TODAY,
  generated_at: new Date().toISOString(),
  recovery: null,
  sleep_last_night: null,
  strain_today: null,
  strain_target_range: [0, 21],
  daily_activity: null,
  load: null,
  rowing_load: null,
  hrv: { today: null, sparkline_14d: [], baseline_band: null },
  resting_hr: { today: null, sparkline_14d: [], baseline_band: null },
  latest_erg: null,
  predicted_2k: { value: null, band: "insufficient_data", components: [], explanation: "No usable pieces yet." },
  recommendation: "Not enough data yet to make a recommendation — keep syncing.",
  next_a_race: null,
  under_fuelling: { flag: false, logged_days: 0, explanation: "Not enough logged days yet to assess fuelling." },
};

function shiftDate(iso: string, days: number): string {
  const d = new Date(iso + "T00:00:00");
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

const SYNC_STATUS: SyncSourceStatus[] = [
  { source: "garmin", last_success_at: new Date(Date.now() - 35 * 60 * 1000).toISOString(), last_error: null },
  { source: "withings", last_success_at: null, last_error: "No Withings tokens stored — visit /auth/withings/start first" },
  { source: "concept2", last_success_at: new Date(Date.now() - 35 * 60 * 1000).toISOString(), last_error: null },
];

export function mockToday(scenario: MockScenario): Today {
  if (scenario === "calibrating") return CALIBRATING;
  if (scenario === "empty") return EMPTY;
  // Real device data, just hours old — the offline banner should show real data age here,
  // not the data itself looking any different from "full".
  if (scenario === "offline") return { ...FULL, generated_at: new Date(Date.now() - 3 * 3600 * 1000).toISOString() };
  return FULL;
}

export function mockSyncStatus(): SyncSourceStatus[] {
  return SYNC_STATUS.map((s) => ({
    ...s,
    token_expires_at: s.source === "garmin" ? new Date(Date.now() + 20 * 3600 * 1000).toISOString() : null,
  }));
}

// --- Workouts ----------------------------------------------------------

const MOCK_PAGE_SIZE = 20;
const MOCK_WORKOUT_COUNT = 56;

// Raw source-record ids are deliberately offset far from canonical ids (1..MOCK_WORKOUT_COUNT)
// — a real id-confusion bug (e.g. a merge/split action resolving the wrong record) would be
// invisible in mock data if canonical and raw ids always happened to match, the exact gap an
// advisor review flagged in the real backend's test suite before this session's canonical-id
// rewrite. 1000+ never collides with a canonical id at this mock dataset's size.
let nextRawActivityId = 1000;

function mockSource(
  source: string,
  type: string,
  provenance: string,
  origin: string | null,
  overrides: Partial<ActivitySourceSummary> = {},
): ActivitySourceSummary {
  return {
    activity_id: nextRawActivityId++,
    source,
    external_id: `mock-${source}-${nextRawActivityId}`,
    provenance,
    type,
    origin,
    hr_source_type: null,
    has_fit: source === "garmin",
    has_strokes: source === "concept2",
    ...overrides,
  };
}

function mockWorkout(i: number): WorkoutListItem {
  const bucket = i % 5;
  const daysAgo = Math.round(i * 1.6);
  const start = shiftDate(TODAY, -daysAgo) + "T07:30:00.000Z";

  let category: WorkoutListItem["category"];
  let sportFamily: WorkoutListItem["sport_family"];
  let source: string;
  let type: string;
  if (bucket === 0) {
    category = "on_water";
    sportFamily = "rowing";
    source = "garmin";
    type = "rowing_v2";
  } else if (bucket === 3) {
    category = "strength";
    sportFamily = "strength";
    source = "garmin";
    type = "strength_training";
  } else {
    category = "erg";
    sportFamily = "rowing";
    source = i % 2 === 0 ? "concept2" : "garmin";
    type = source === "concept2" ? "rower" : "indoor_rowing";
  }

  const distance = category === "strength" ? null : category === "on_water" ? 8000 + (i % 5) * 600 : 5000 + (i % 4) * 1000;
  const paceS500 = category === "on_water" ? 118 + (i % 6) : 108 + (i % 5) * 2;
  const duration = category === "strength" ? 2700 + (i % 3) * 300 : distance ? (distance / 500) * paceS500 : null;
  const avgHr = category === "strength" ? 128 + (i % 4) * 3 : 150 + (i % 6) * 3;
  const strainValue = 4 + (i % 8) * 1.6;
  const sourceRow = mockSource(source, type, source === "concept2" ? "concept2" : "garmin", source === "garmin" ? "watch" : null);
  const canonicalId = i + 1;
  const title = category === "strength" ? "Strength" : category === "on_water" ? "Row" : source === "concept2" ? "Erg 60'" : "Steady state 60'";

  return {
    id: canonicalId,
    sport_family: sportFamily,
    start,
    duration,
    distance,
    avg_hr: avgHr,
    max_hr: avgHr + 18,
    avg_power: category === "erg" ? 180 + (i % 5) * 15 : null,
    avg_cadence: category !== "strength" ? 22 + (i % 5) : null,
    calories: duration ? Math.round(duration * 0.17) : null,
    title,
    strain_method: "trimp_samples",
    session_label: category === "strength" ? null : i % 7 === 0 ? "AN (9 min) + UT2" : "UT2 (52 min)",
    auto_trimmed_tail_s: i % 11 === 0 ? 95 : null,
    category,
    field_sources: { start: `${sourceRow.source}:${sourceRow.external_id}`, avg_hr: `${sourceRow.source}:${sourceRow.external_id}` },
    zones:
      category === "strength"
        ? null
        : { hr: { UT2: 3120, UT1: 540, AT: 0, TR: 0, AN: i % 7 === 0 ? 540 : 0 }, power: null },
    notes: null,
    rpe: null,
    exclude_from_totals: false,
    tags: [],
    overrides: {},
    sources: [sourceRow],
    editable_fields: ["title", "sport_family", "notes", "rpe", "exclude_from_totals", "tags"],
    edits_push_back_to_source: false,
    strain: i < 2 ? null : { canonical_id: canonicalId, title, value: strainValue, band: strainValue < 10 ? "light" : strainValue < 14 ? "moderate" : "high" },
  };
}

const MOCK_WORKOUTS: WorkoutListItem[] = Array.from({ length: MOCK_WORKOUT_COUNT }, (_, i) => mockWorkout(i));

// A Peloton-pushed Garmin ride that hasn't been merged with its watch counterpart yet, plus
// the watch's own recording — the Duplicates review screen's worked example (task Part A.5).
const PELOTON_PUSH = mockSource("garmin", "indoor_cycling", "peloton", "peloton", { has_fit: true });
const PELOTON_WATCH = mockSource("garmin", "indoor_cycling", "garmin", "watch", { has_fit: true });
const MOCK_DUPLICATE_PAIRS: DuplicatePair[] = [
  {
    a: { activity_id: PELOTON_PUSH.activity_id, source: PELOTON_PUSH.source, external_id: PELOTON_PUSH.external_id, start: shiftDate(TODAY, -2) + "T17:00:10.000Z", duration: 2700 },
    b: { activity_id: PELOTON_WATCH.activity_id, source: PELOTON_WATCH.source, external_id: PELOTON_WATCH.external_id, start: shiftDate(TODAY, -2) + "T17:00:00.000Z", duration: 2700 },
    score: 0.94,
    hard_block: false,
    reasons: ["same sport family, within time/duration window"],
  },
];

export function mockWorkoutsPage(category: WorkoutCategory | undefined, cursor: string | null): WorkoutsPage {
  const all = category ? MOCK_WORKOUTS.filter((w) => w.category === category) : MOCK_WORKOUTS;
  const startIndex = cursor ? Number(cursor) : 0;
  const items = all.slice(startIndex, startIndex + MOCK_PAGE_SIZE);
  const nextIndex = startIndex + MOCK_PAGE_SIZE;
  return { items, next_cursor: nextIndex < all.length ? String(nextIndex) : null };
}

const MOCK_ZONES: ZoneRow[] = [
  { zone: "UT2", hr_pct_lo: 60, hr_pct_hi: 70, hr_lo: 114, hr_hi: 133, power_pct_lo: 55, power_pct_hi: 65, power_lo: 143, power_hi: 169 },
  { zone: "UT1", hr_pct_lo: 70, hr_pct_hi: 80, hr_lo: 133, hr_hi: 152, power_pct_lo: 65, power_pct_hi: 75, power_lo: 169, power_hi: 195 },
  { zone: "AT", hr_pct_lo: 80, hr_pct_hi: 87, hr_lo: 152, hr_hi: 165, power_pct_lo: 75, power_pct_hi: 85, power_lo: 195, power_hi: 221 },
  { zone: "TR", hr_pct_lo: 87, hr_pct_hi: 93, hr_lo: 165, hr_hi: 177, power_pct_lo: 85, power_pct_hi: 95, power_lo: 221, power_hi: 247 },
  { zone: "AN", hr_pct_lo: 93, hr_pct_hi: null, hr_lo: 177, hr_hi: null, power_pct_lo: 95, power_pct_hi: null, power_lo: 247, power_hi: null },
];

const MOCK_STRENGTH_MUSCULAR_BY_MUSCLE: Record<string, number> = { quadriceps: 1800, glutes: 1600, hamstrings: 900, chest: 1100, triceps: 650, abdominals: 300 };

function mockStrengthSets(canonicalId: number): StrengthSetRow[] {
  return [
    { client_id: `mock-wd-${canonicalId}-1`, exercise_id: 1, seq: 0, set_type: "working", reps: 5, equipment_type: "barbell", load_kg: 100, bar_weight_kg: 20, effective_load_kg: 120, load_is_estimated: false, bodyweight_kg_used: null, is_rep_pr: true, is_e1rm_pr: false, muscular_au: 500, source: "catch", is_confirmed: true, created_at: new Date().toISOString() },
    { client_id: `mock-wd-${canonicalId}-2`, exercise_id: 2, seq: 1, set_type: "working", reps: 8, equipment_type: "barbell", load_kg: 60, bar_weight_kg: 20, effective_load_kg: 80, load_is_estimated: false, bodyweight_kg_used: null, is_rep_pr: false, is_e1rm_pr: false, muscular_au: 350, source: "catch", is_confirmed: true, created_at: new Date().toISOString() },
  ];
}

export function mockWorkoutDetail(id: number): WorkoutDetail {
  const base = MOCK_WORKOUTS.find((w) => w.id === id) ?? MOCK_WORKOUTS[0];
  const localDate = (base.start ?? TODAY).slice(0, 10);
  return {
    ...base,
    local_date: localDate,
    zones_config: { zones: MOCK_ZONES, note: "Zone boundaries are defaults — confirm with your coach before training off them." },
    hr_zone: base.avg_hr ? "UT1" : null,
    day_note:
      id % 3 === 0
        ? { id: 1, date: localDate, text: "Felt strong on the back half.", rpe: 6, created_at: new Date().toISOString() }
        : null,
    has_samples: base.category !== "other" && base.category !== "strength",
    strength_sets: base.category === "strength" ? mockStrengthSets(id) : undefined,
    muscular_by_muscle: base.category === "strength" ? MOCK_STRENGTH_MUSCULAR_BY_MUSCLE : null,
  };
}

// --- Activity editing (task Part C) -----------------------------------------

export function patchMockActivity(id: number, patch: ActivityOverrides): WorkoutDetail {
  const workout = MOCK_WORKOUTS.find((w) => w.id === id);
  if (!workout) throw new Error("not found");
  workout.overrides = { ...workout.overrides, ...patch };
  if (patch.title !== undefined) workout.title = patch.title;
  if (patch.sport_family !== undefined) workout.sport_family = patch.sport_family;
  if (patch.notes !== undefined) workout.notes = patch.notes;
  if (patch.rpe !== undefined) workout.rpe = patch.rpe;
  if (patch.exclude_from_totals !== undefined) workout.exclude_from_totals = patch.exclude_from_totals;
  if (patch.tags !== undefined) workout.tags = patch.tags;
  return mockWorkoutDetail(id);
}

export function revertMockActivityField(id: number, field: keyof ActivityOverrides): WorkoutDetail {
  const workout = MOCK_WORKOUTS.find((w) => w.id === id);
  if (!workout) throw new Error("not found");
  const { [field]: _removed, ...rest } = workout.overrides;
  workout.overrides = rest;
  if (field === "title") workout.title = "Steady state 60'";
  if (field === "notes") workout.notes = null;
  if (field === "rpe") workout.rpe = null;
  if (field === "exclude_from_totals") workout.exclude_from_totals = false;
  if (field === "tags") workout.tags = [];
  return mockWorkoutDetail(id);
}

// --- Duplicates review (task Part A.5) --------------------------------------

export function mockDuplicates(): DuplicatePair[] {
  return MOCK_DUPLICATE_PAIRS;
}

function findSourceOwner(activityId: number): WorkoutListItem | undefined {
  return MOCK_WORKOUTS.find((w) => w.sources.some((s) => s.activity_id === activityId));
}

export function mergeMockActivities(activityIdA: number, activityIdB: number): WorkoutDetail {
  // A flagged-pair merge never corresponds to a real pre-existing MOCK_WORKOUTS entry (the
  // whole point of the Peloton-push demo pair is that it isn't attached to one yet) — always
  // drop the pair from the flagged list first, regardless of which merge path below applies.
  const pairIdx = MOCK_DUPLICATE_PAIRS.findIndex(
    (p) =>
      (p.a.activity_id === activityIdA && p.b.activity_id === activityIdB) ||
      (p.a.activity_id === activityIdB && p.b.activity_id === activityIdA),
  );
  if (pairIdx >= 0) MOCK_DUPLICATE_PAIRS.splice(pairIdx, 1);

  const ownerA = findSourceOwner(activityIdA);
  const sourceB = [PELOTON_PUSH, PELOTON_WATCH].find((s) => s.activity_id === activityIdB);
  if (ownerA && sourceB) {
    ownerA.sources = [...ownerA.sources, sourceB];
    return mockWorkoutDetail(ownerA.id);
  }
  if (!ownerA && (activityIdA === PELOTON_PUSH.activity_id || activityIdA === PELOTON_WATCH.activity_id)) {
    // Neither side was already attached to a real workout — synthesize a new merged one so
    // the demo pair has somewhere to land (a real backend always has at least one side
    // belonging to a real, already-synced canonical; this mock pair deliberately doesn't).
    const newId = Math.max(...MOCK_WORKOUTS.map((w) => w.id)) + 1;
    const merged: WorkoutListItem = { ...mockWorkout(0), id: newId, sources: [PELOTON_PUSH, PELOTON_WATCH], strain: null };
    MOCK_WORKOUTS.push(merged);
    return mockWorkoutDetail(newId);
  }

  // Generic fallback: merge two canonicals in MOCK_WORKOUTS by their first source id.
  const a = MOCK_WORKOUTS.find((w) => w.sources[0]?.activity_id === activityIdA) ?? MOCK_WORKOUTS[0];
  const b = MOCK_WORKOUTS.find((w) => w.sources[0]?.activity_id === activityIdB);
  if (b && b.id !== a.id) {
    a.sources = [...a.sources, ...b.sources];
    const idx = MOCK_WORKOUTS.findIndex((w) => w.id === b.id);
    if (idx >= 0) MOCK_WORKOUTS.splice(idx, 1);
  }
  return mockWorkoutDetail(a.id);
}

export function splitMockActivity(activityId: number): WorkoutDetail {
  const owner = findSourceOwner(activityId);
  if (!owner || owner.sources.length < 2) return mockWorkoutDetail(owner?.id ?? MOCK_WORKOUTS[0].id);
  const leaving = owner.sources.find((s) => s.activity_id === activityId)!;
  owner.sources = owner.sources.filter((s) => s.activity_id !== activityId);
  const newCanonicalId = Math.max(...MOCK_WORKOUTS.map((w) => w.id)) + 1;
  const split: WorkoutListItem = {
    ...owner,
    id: newCanonicalId,
    sources: [leaving],
    strain: null,
    title: leaving.provenance === "peloton" ? "Peloton ride" : "Row",
  };
  MOCK_WORKOUTS.push(split);
  return mockWorkoutDetail(newCanonicalId);
}

export function markMockNotDuplicate(activityIdA: number, activityIdB: number): void {
  const idx = MOCK_DUPLICATE_PAIRS.findIndex(
    (p) => (p.a.activity_id === activityIdA && p.b.activity_id === activityIdB) || (p.a.activity_id === activityIdB && p.b.activity_id === activityIdA),
  );
  if (idx >= 0) MOCK_DUPLICATE_PAIRS.splice(idx, 1);
}

// --- Per-activity HR/power/cadence samples (task Part E.8) ------------------

export function mockActivitySamples(id: number): ActivitySamplesResponse {
  const workout = MOCK_WORKOUTS.find((w) => w.id === id);
  if (!workout || workout.category === "other") {
    return { has_data: false, reason: workout ? "no heart-rate data" : "no per-sample data for this activity" };
  }
  const n = Math.round(workout.duration ?? 3600);
  const baseHr = workout.avg_hr ?? 140;
  const points = Array.from({ length: Math.min(n, 3600) }, (_, t) => {
    const trimmed = workout.auto_trimmed_tail_s && t > n - workout.auto_trimmed_tail_s;
    const hr = trimmed ? 72 + Math.sin(t / 20) * 2 : baseHr + Math.sin(t / 45) * 10 + (t % 900 < 120 ? 20 : 0);
    return { elapsed_s: t, hr: Math.round(hr), power: workout.avg_power ? Math.round(workout.avg_power + Math.sin(t / 30) * 15) : null, cadence: workout.avg_cadence ? Math.round(workout.avg_cadence + Math.sin(t / 15) * 3) : null };
  });
  return {
    has_data: true,
    canonical_id: id,
    n_samples: n,
    usable_n_samples: n - (workout.auto_trimmed_tail_s ?? 0),
    trimmed_tail_s: workout.auto_trimmed_tail_s ?? 0,
    max_hr_setting: MOCK_SETTINGS.max_hr,
    avg_hr: baseHr,
    max_hr_observed: baseHr + 22,
    min_hr_observed: baseHr - 18,
    zones: workout.zones,
    zones_config: { zones: MOCK_ZONES, note: "Zone boundaries are defaults — confirm with your coach before training off them." },
    session_label: workout.session_label,
    laps: [{ offset_s: 0, duration_s: n }],
    hr_recovery: { session_end: 22, per_lap: [{ offset_s: 0, recovery_bpm: 22 }] },
    points,
    returned_count: points.length,
    raw_count: points.length,
  };
}

function mockStroke(seq: number, intervalIndex: number, offsetDistance: number, offsetT: number, baseSplit: number): Stroke {
  const t = seq * 2.1;
  const distance = seq * 10.5;
  return {
    id: seq,
    activity_id: 0,
    seq,
    interval_index: intervalIndex,
    t,
    distance,
    pace_500m: baseSplit + Math.sin(seq / 6) * 1.5,
    watts: 190 + Math.round(Math.sin(seq / 6) * 12),
    stroke_rate: 24 + Math.round(Math.sin(seq / 9)),
    hr: 148 + Math.round(seq / 8),
    distance_cum: offsetDistance + distance,
    t_cum: offsetT + t,
  };
}

function mockTechnique(rep: number): ErgTechnique {
  const metric = (value: number, band: string, explanation: string) => ({ value, band, components: [], explanation });
  // Varies a little by rep so two reps don't render as suspiciously identical stat tiles —
  // real per-interval technique naturally drifts rep to rep.
  const drift = rep * 0.6;
  return {
    split_consistency: metric(2.1 + drift, drift > 0.5 ? "moderate" : "consistent", "Coefficient of variation across 500m splits."),
    watts_per_stroke: metric(480 - rep * 15, "n/a", "Mean work per stroke."),
    rate_power_slope: metric(9.2 - drift, "efficient", "Watts gained per unit of rate increase."),
    fade: metric(1.4 + drift, "mild_fade", "% slower pace in the last quarter vs the first."),
  };
}

export function mockErgStrokes(
  id: number,
  opts?: { points?: number; distanceMin?: number; distanceMax?: number },
): ErgStrokesResponse {
  // 850 strokes/rep x 2 reps, ~2.1s/stroke -> ~60 minutes total — long enough to exercise
  // real per-zoom-level stroke downsampling (interaction spec #8), not just a short demo piece.
  const strokesPerInterval = 850;
  const interval0 = Array.from({ length: strokesPerInterval }, (_, i) => mockStroke(i, 0, 0, 0, 108));
  const rep0End = interval0[interval0.length - 1];
  const interval1 = Array.from({ length: strokesPerInterval }, (_, i) =>
    mockStroke(i, 1, rep0End.distance_cum ?? 0, rep0End.t_cum, 112),
  );
  const allStrokes = [...interval0, ...interval1].map((s) => ({ ...s, activity_id: id }));

  const summary = (strokesForRep: Stroke[], rep: number): IntervalSummary => {
    const last = strokesForRep[strokesForRep.length - 1];
    const avgSplit = (last.t / (last.distance ?? 1)) * 500;
    return {
      distance_m: last.distance,
      duration_s: last.t,
      avg_split_500m: avgSplit,
      avg_stroke_rate: 24 - rep,
      avg_watts: 190 - rep * 8,
      avg_hr: 150 + rep * 6,
      drift_vs_rep1_pct: 0,
    };
  };
  const rep0Summary = summary(interval0, 0);
  const rep1Summary = summary(interval1, 1);
  rep1Summary.drift_vs_rep1_pct = ((rep1Summary.avg_split_500m! - rep0Summary.avg_split_500m!) / rep0Summary.avg_split_500m!) * 100;

  const windowed = allStrokes.filter(
    (s) =>
      (opts?.distanceMin == null || (s.distance_cum ?? 0) >= opts.distanceMin) &&
      (opts?.distanceMax == null || (s.distance_cum ?? 0) <= opts.distanceMax),
  );
  const returnedStrokes = opts?.points && windowed.length > opts.points ? lttbLikeDownsample(windowed, opts.points) : windowed;

  return {
    activity_id: id,
    strokes: returnedStrokes,
    stroke_count: allStrokes.length,
    returned_stroke_count: returnedStrokes.length,
    technique_by_interval: { "0": mockTechnique(0), "1": mockTechnique(1) },
    interval_summary: { "0": rep0Summary, "1": rep1Summary },
    time_in_zone_by_interval: {
      "0": { UT2: 20, UT1: 180, AT: 60, TR: 0, AN: 0 },
      "1": { UT2: 0, UT1: 90, AT: 150, TR: 20, AN: 0 },
    },
  };
}

// --- Notes ---------------------------------------------------------------

const MOCK_NOTES = new Map<string, Note>();

export function mockNote(date: string): Note | null {
  return MOCK_NOTES.get(date) ?? null;
}

export function saveMockNote(date: string, text: string, rpe: number | null): Note {
  const note: Note = { id: 1, date, text, rpe, created_at: new Date().toISOString() };
  MOCK_NOTES.set(date, note);
  return note;
}

// --- Trends / Body -------------------------------------------------------

// `i` is days-ago from today; every formula is a plain periodic/linear function of it, so it
// generalizes to any range for free — used by mockSeries()'s multi-year synthetic history
// (session 8: interactive charts need enough history to actually test pan/zoom/downsampling
// against, which the live account doesn't have yet — same situation PLAN.md's session 2/3
// notes for Concept2/Withings fixtures).
function metricValueAt(metric: TrendMetric, i: number): number | null {
  switch (metric) {
    case "recovery":
      return 55 + 20 * Math.sin(i / 6) + 3 * Math.sin(i / 97);
    case "hrv_rmssd":
      return 60 + 6 * Math.sin(i / 5) + 2 * Math.sin(i / 131);
    case "resting_hr":
      return 49 - Math.sin(i / 7) * 2 - Math.sin(i / 211) * 1.5;
    case "sleep_score":
      return 80 + 10 * Math.sin(i / 4);
    case "strain":
      return 8 + 6 * Math.abs(Math.sin(i / 3));
    case "load_acr":
      return 1.0 + 0.25 * Math.sin(i / 10);
    case "weight":
      return 79 + Math.sin(i / 9) * 0.8 - (i / 1000) * 1.2; // a slow year-over-year drift
    case "w_per_kg":
      return 2.6 + Math.sin(i / 11) * 0.15 + (i / 1000) * 0.08;
    case "predicted_2k":
      return 400 - i * 0.02 + Math.sin(i / 17) * 3;
    default:
      return null;
  }
}

function metricExtrasAt(metric: TrendMetric, i: number, step: number): Partial<TrendPoint> {
  if (metric === "load_acr") {
    const acute_7d = 60 + 8 * Math.sin(i / 10);
    const chronic_42d = 58;
    return { acute_7d, chronic_42d, form: chronic_42d - acute_7d };
  }
  if (metric === "weight") {
    return { smoothed: (metricValueAt("weight", i - step) ?? 0) - 0.2 };
  }
  if (metric === "w_per_kg" || metric === "predicted_2k") {
    // A deterministic fake id — mockWorkoutDetail(id) happily generates a plausible workout
    // for any id, so tapping one of these points in mock mode (spec #4) opens something real.
    return { activity_id: 1000 + (i % 400) };
  }
  return {};
}

// ~4 years of daily history — enough to exercise "all" range, the navigator brush, and the
// server's real LTTB downsampling contract (points-budget in, exactly that many points out)
// against mock data without a live account's actual (much shorter) history.
const MOCK_SERIES_HISTORY_DAYS = 1460;

function lttbLikeDownsample<T>(points: T[], n: number): T[] {
  // Approximate stride-sampling, not the real LTTB — good enough for mock-mode visuals and
  // for exercising the frontend's points-budget plumbing; the exact algorithm only needs to
  // be right once, server-side (catch/analytics/downsample.py), and is unit-tested there.
  if (points.length <= n || n < 3) return points;
  const out: T[] = [points[0]];
  const step = (points.length - 2) / (n - 2);
  for (let i = 1; i < n - 1; i++) out.push(points[Math.min(points.length - 2, Math.round(i * step))]);
  out.push(points[points.length - 1]);
  return out;
}

export function mockSeries(metrics: TrendMetric[], from: string, to: string, points: number): SeriesResponse {
  const series: Record<string, SeriesForMetric> = {};
  for (const metric of metrics) {
    const all: TrendPoint[] = [];
    for (let i = MOCK_SERIES_HISTORY_DAYS; i >= 0; i--) {
      all.push({ date: shiftDate(TODAY, -i), value: metricValueAt(metric, i), ...metricExtrasAt(metric, i, 1) });
    }
    const windowed = all.filter((p) => p.date >= from && p.date <= to && p.value != null);
    const sampled = lttbLikeDownsample(windowed, points);
    series[metric] = {
      points: sampled.map((p) => ({ ...p, value: p.value as number, value_min: p.value as number, value_max: p.value as number })),
      raw_count: windowed.length,
      returned_count: sampled.length,
    };
  }
  return { series };
}

const MOCK_BODY: BodyCompReading[] = (() => {
  const days = 60;
  const out: BodyCompReading[] = [];
  for (let i = days; i >= 0; i -= 3) {
    const d = shiftDate(TODAY, -i);
    out.push({
      date: d,
      weight: 79 + Math.sin(i / 9) * 0.8,
      weight_source: "withings",
      fat_pct: 14.5 + Math.sin(i / 14) * 0.6,
      fat_pct_source: "withings",
      muscle_kg: 36.2 + Math.sin(i / 20) * 0.3,
      muscle_kg_source: "withings",
      bone_kg: 3.2,
      hydration_kg: 44.0,
      sources: ["withings"],
    });
  }
  return out;
})();

export function mockBody(): BodyCompReading[] {
  return MOCK_BODY;
}

export function postMockManualWeight(date: string, weightKg: number): void {
  const existing = MOCK_BODY.find((r) => r.date === date);
  if (existing) {
    existing.weight = weightKg;
    existing.weight_source = "manual";
    if (!existing.sources.includes("manual")) existing.sources.push("manual");
  } else {
    MOCK_BODY.push({
      date,
      weight: weightKg,
      weight_source: "manual",
      fat_pct: null,
      fat_pct_source: null,
      muscle_kg: null,
      muscle_kg_source: null,
      bone_kg: null,
      hydration_kg: null,
      sources: ["manual"],
    });
    MOCK_BODY.sort((a, b) => a.date.localeCompare(b.date));
  }
}

export function mockVolume(weeks: number): VolumeWeek[] {
  const out: VolumeWeek[] = [];
  const today = new Date();
  const monday = new Date(today);
  monday.setDate(today.getDate() - ((today.getDay() + 6) % 7));
  for (let i = weeks - 1; i >= 0; i--) {
    const weekStart = new Date(monday);
    weekStart.setDate(monday.getDate() - i * 7);
    const zones = {} as VolumeWeek["zones"];
    ZONE_NAMES.forEach((z, idx) => {
      zones[z] = Math.max(0, 1200 * (5 - idx) * (0.6 + 0.4 * Math.sin(i + idx)));
    });
    out.push({ week_start: weekStart.toISOString().slice(0, 10), zones, estimated: i % 4 === 0 });
  }
  return out;
}

export function mockPbs(): PersonalBests {
  const entry = (distance: number, pace: number, daysAgo: number): PbEntryLike => ({
    activity_id: 1,
    date: shiftDate(TODAY, -daysAgo),
    distance_m: distance,
    duration_s: (distance / 500) * pace,
    pace_s_per_500: pace,
  });
  return {
    "500m": entry(500, 92.0, 40),
    "1000m": entry(1000, 95.5, 120),
    "2000m": entry(2000, 98.4, 10),
    "5000m": entry(5000, 104.2, 60),
    "6000m": null,
    "30min": { activity_id: 1, date: shiftDate(TODAY, -200), distance_m: 8300, duration_s: 1800, pace_s_per_500: null },
    "60min": null,
  };
}

type PbEntryLike = NonNullable<PersonalBests[string]>;

// --- Settings --------------------------------------------------------------

let MOCK_SETTINGS: Settings = {
  zones: {
    hr_pct: { UT2: 60, UT1: 70, AT: 80, TR: 87, AN: 93 },
    power_pct: { UT2: 55, UT1: 65, AT: 75, TR: 85, AN: 95 },
  },
  trimp_exponent: 1.92,
  srpe_to_trimp_scale: 50 / 300,
  strain_log_a: 2.54,
  load_acute_days: 7,
  load_chronic_days: 42,
  acr_bands: { undertraining: 0.8, optimal_high: 1.3, caution_high: 1.5 },
  max_hr: 190,
  recovery_weights: { hrv: 0.4, resting_hr: 0.25, sleep: 0.2, prior_strain: 0.15 },
  recovery_green: 67,
  recovery_yellow: 34,
  sleep_need_seconds: 8 * 3600,
  min_hrv_nights_for_baseline: 7,
  predict_lookback_days: 180,
  strain_targets: { calibrating: [0, 21], green: [10, 16], yellow: [6, 12], red: [0, 8] },
  zone_mode: "hr",
  units: "metric",
  garmin_key_expires_on: null,
  field_priority: {
    power: ["peloton", "concept2", "garmin"],
    cadence: ["peloton", "concept2", "garmin"],
    title: ["peloton", "concept2", "garmin"],
    distance_indoor_bike: ["peloton", "garmin"],
  },
  ftp_watts: null,
  body_comp_priority: { weight: ["withings", "garmin"], fat_pct: ["withings", "garmin"], muscle_kg: ["withings", "garmin"] },
  min_zone_minutes: 3,
  min_zone_pct: 0.1,
  auto_trim_enabled: true,
  auto_trim_min_idle_s: 120,
  daily_activity_strain_cap: 1.5,
  daily_activity_strain_weight: 1.0,
};

export function mockSettings(): Settings {
  return MOCK_SETTINGS;
}

export function saveMockSettings(patch: Partial<Settings>): Settings {
  MOCK_SETTINGS = { ...MOCK_SETTINGS, ...patch };
  return MOCK_SETTINGS;
}

// --- Coach (session 5) -------------------------------------------------------

let MOCK_COACH_SETTINGS: CoachSettings = {
  provider: "anthropic",
  anthropic_model: "claude-sonnet-5",
  ollama_base_url: null,
  ollama_model: null,
  daily_cap_usd: 2,
  prices: { "claude-sonnet-5": { input: 2.0, output: 10.0, cache_write: 2.5, cache_read: 0.2 } },
  anthropic_key: { configured: true, last4: "wxyz" },
};

export function mockCoachSettings(): CoachSettings {
  return MOCK_COACH_SETTINGS;
}

export function saveMockCoachSettings(patch: Partial<CoachSettings>): CoachSettings {
  MOCK_COACH_SETTINGS = { ...MOCK_COACH_SETTINGS, ...patch, prices: { ...MOCK_COACH_SETTINGS.prices, ...patch.prices } };
  return MOCK_COACH_SETTINGS;
}

export function setMockAnthropicKey(key: string): CoachSettings["anthropic_key"] {
  MOCK_COACH_SETTINGS.anthropic_key = { configured: true, last4: key.slice(-4) };
  return MOCK_COACH_SETTINGS.anthropic_key;
}

export function deleteMockAnthropicKey(): void {
  MOCK_COACH_SETTINGS.anthropic_key = { configured: false, last4: null };
}

export function mockCoachModels(provider: "anthropic" | "ollama"): CoachModel[] {
  if (provider === "ollama") {
    return [{ id: "llama3.1:70b", display_name: "llama3.1:70b" }, { id: "qwen2.5:32b", display_name: "qwen2.5:32b" }];
  }
  return [
    { id: "claude-opus-5", display_name: "Claude Opus 5" },
    { id: "claude-sonnet-5", display_name: "Claude Sonnet 5" },
    { id: "claude-haiku-4-5", display_name: "Claude Haiku 4.5" },
  ];
}

export function mockTestConnection(): { ok: boolean; error?: string; model_count?: number } {
  return { ok: true, model_count: 3 };
}

export function mockDailyUsage(): { spend_usd: number; cap_usd: number | null } {
  return { spend_usd: 0.42, cap_usd: MOCK_COACH_SETTINGS.daily_cap_usd };
}

let MOCK_TOKENS: DeviceToken[] = [
  { id: 1, name: "laptop", created_at: new Date(Date.now() - 20 * 86400000).toISOString(), last_used_at: new Date(Date.now() - 2 * 3600000).toISOString() },
];
let nextTokenId = 2;

export function mockTokens(): DeviceToken[] {
  return MOCK_TOKENS;
}

export function createMockToken(name: string): DeviceToken & { token: string } {
  const row = { id: nextTokenId++, name, created_at: new Date().toISOString(), last_used_at: null };
  MOCK_TOKENS = [...MOCK_TOKENS, row];
  return { ...row, token: "mock-token-" + row.id };
}

export function deleteMockToken(id: number): void {
  MOCK_TOKENS = MOCK_TOKENS.filter((t) => t.id !== id);
}

let MOCK_FACTS: MemoryFact[] = [
  { ref: "fact:1", kind: "fact", category: "injury", text: "Tight left hamstring, easing back into volume", valid_until: shiftDate(TODAY, 20), created_at: shiftDate(TODAY, -3) + "T08:00:00Z", expired: false },
  { ref: "fact:2", kind: "fact", category: "preference", text: "Prefers short warmups, dislikes long steady-state", valid_until: null, created_at: shiftDate(TODAY, -40) + "T08:00:00Z", expired: false },
];
let MOCK_EVENTS: MemoryEvent[] = [
  { ref: "event:1", kind: "event", name: "Head of the Charles", date: shiftDate(TODAY, 9), type: "race", distance: "5000m", boat_class: "1x", priority: "A", goal_time: "19:30", result: null, days_to_go: 9 },
  { ref: "event:2", kind: "event", name: "Club 2k test", date: shiftDate(TODAY, -14), type: "2k_test", distance: null, boat_class: null, priority: null, goal_time: null, result: "6:42.1", days_to_go: -14 },
];
let MOCK_GOALS: MemoryGoal[] = [{ ref: "goal:1", kind: "goal", text: "Break 6:40 for 2k", target_date: shiftDate(TODAY, 60), status: "active" }];
let nextFactId = 3;
let nextEventId = 3;
let nextGoalId = 2;

export function mockMemory(): MemoryListing {
  return { facts: MOCK_FACTS, events: MOCK_EVENTS, goals: MOCK_GOALS };
}

export function createMockFact(category: string, text: string, valid_until: string | null): MemoryFact {
  const row: MemoryFact = { ref: `fact:${nextFactId++}`, kind: "fact", category, text, valid_until, created_at: new Date().toISOString(), expired: false };
  MOCK_FACTS = [...MOCK_FACTS, row];
  return row;
}

export function createMockEvent(fields: Omit<MemoryEvent, "ref" | "kind" | "days_to_go">): MemoryEvent {
  const daysToGo = Math.round((new Date(fields.date).getTime() - new Date(TODAY).getTime()) / 86400000);
  const row: MemoryEvent = { ...fields, ref: `event:${nextEventId++}`, kind: "event", days_to_go: daysToGo };
  MOCK_EVENTS = [...MOCK_EVENTS, row];
  return row;
}

export function createMockGoal(text: string, target_date: string | null): MemoryGoal {
  const row: MemoryGoal = { ref: `goal:${nextGoalId++}`, kind: "goal", text, target_date, status: "active" };
  MOCK_GOALS = [...MOCK_GOALS, row];
  return row;
}

export function updateMockFact(ref: string, patch: Partial<Omit<MemoryFact, "ref" | "kind">>): MemoryFact {
  const row = MOCK_FACTS.find((f) => f.ref === ref);
  if (!row) throw new Error("not found");
  Object.assign(row, patch);
  return row;
}

export function updateMockEvent(ref: string, patch: Partial<Omit<MemoryEvent, "ref" | "kind" | "days_to_go">>): MemoryEvent {
  const row = MOCK_EVENTS.find((e) => e.ref === ref);
  if (!row) throw new Error("not found");
  Object.assign(row, patch);
  if (patch.date) row.days_to_go = Math.round((new Date(patch.date).getTime() - new Date(TODAY).getTime()) / 86400000);
  return row;
}

export function updateMockGoal(ref: string, patch: Partial<Omit<MemoryGoal, "ref" | "kind">>): MemoryGoal {
  const row = MOCK_GOALS.find((g) => g.ref === ref);
  if (!row) throw new Error("not found");
  Object.assign(row, patch);
  return row;
}

export function deleteMockMemory(ref: string): void {
  MOCK_FACTS = MOCK_FACTS.filter((f) => f.ref !== ref);
  MOCK_EVENTS = MOCK_EVENTS.filter((e) => e.ref !== ref);
  MOCK_GOALS = MOCK_GOALS.filter((g) => g.ref !== ref);
}

const MOCK_CONVERSATION_MESSAGES = new Map<number, CoachMessageRow[]>([
  [
    1,
    [
      { id: 1, role: "user", blocks: [{ type: "text", text: "How should I train today?" }], provider: null, model: null, usage: null, cost_usd: null, created_at: new Date(Date.now() - 3600000).toISOString() },
      {
        id: 2,
        role: "assistant",
        blocks: [
          { type: "tool_call", id: "t1", name: "get_today", input: {} },
        ],
        provider: "anthropic",
        model: "claude-sonnet-5",
        usage: null,
        cost_usd: null,
        created_at: new Date(Date.now() - 3598000).toISOString(),
      },
      {
        id: 3,
        role: "user",
        blocks: [{ type: "tool_result", id: "t1", output: { recovery: { value: 78, band: "green" } }, is_error: false }],
        provider: null,
        model: null,
        usage: null,
        cost_usd: null,
        created_at: new Date(Date.now() - 3597000).toISOString(),
      },
      {
        id: 4,
        role: "assistant",
        blocks: [
          {
            type: "text",
            text: "Your recovery is 78% (green), mostly thanks to HRV sitting right at your 7-day baseline. You're clear for a harder session today — your strain target is 10-16, so a solid AT/TR piece fits well.",
          },
        ],
        provider: "anthropic",
        model: "claude-sonnet-5",
        usage: { input_tokens: 1800, output_tokens: 95, cache_creation_input_tokens: 1200, cache_read_input_tokens: 0 },
        cost_usd: 0.0062,
        created_at: new Date(Date.now() - 3595000).toISOString(),
      },
    ],
  ],
]);

let MOCK_CONVERSATIONS: CoachConversation[] = [
  {
    id: 1,
    title: "How should I train today?",
    created_at: new Date(Date.now() - 3600000).toISOString(),
    updated_at: new Date(Date.now() - 3595000).toISOString(),
    usage: { input_tokens: 1800, output_tokens: 95, cache_creation_input_tokens: 1200, cache_read_input_tokens: 0, cost_usd: 0.0062 },
  },
];
let nextConversationId = 2;

export function mockConversations(): CoachConversation[] {
  return [...MOCK_CONVERSATIONS].sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1));
}

export function createMockConversation(): CoachConversation {
  const row: CoachConversation = {
    id: nextConversationId++,
    title: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    usage: { input_tokens: 0, output_tokens: 0, cache_creation_input_tokens: 0, cache_read_input_tokens: 0, cost_usd: 0 },
  };
  MOCK_CONVERSATIONS = [...MOCK_CONVERSATIONS, row];
  MOCK_CONVERSATION_MESSAGES.set(row.id, []);
  return row;
}

export function mockConversationDetail(id: number): CoachConversationDetail | null {
  const conv = MOCK_CONVERSATIONS.find((c) => c.id === id);
  if (!conv) return null;
  return { ...conv, messages: MOCK_CONVERSATION_MESSAGES.get(id) ?? [] };
}

export function deleteMockConversation(id: number): void {
  MOCK_CONVERSATIONS = MOCK_CONVERSATIONS.filter((c) => c.id !== id);
  MOCK_CONVERSATION_MESSAGES.delete(id);
}

function delayed<T>(value: T, ms: number): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), ms));
}

// Scripted, illustrative demo of a full turn (tool call -> tool result -> streamed text ->
// usage -> done) so the Coach screen is fully reviewable under `?mock=1` with no backend.
export async function* streamMockMessage(conversationId: number, text: string): AsyncGenerator<CoachEvent> {
  const conv = MOCK_CONVERSATIONS.find((c) => c.id === conversationId);
  const messages = MOCK_CONVERSATION_MESSAGES.get(conversationId) ?? [];
  const nextId = () => messages.length + 1 + Math.floor(Math.random() * 1000);

  messages.push({ id: nextId(), role: "user", blocks: [{ type: "text", text }], provider: null, model: null, usage: null, cost_usd: null, created_at: new Date().toISOString() });
  if (conv && conv.title === null) conv.title = text.slice(0, 60);

  await delayed(undefined, 350);
  yield { type: "tool_call", id: "mock-1", name: "get_today", input: {}, label: "Read today's recovery and strain" };
  messages.push({ id: nextId(), role: "assistant", blocks: [{ type: "tool_call", id: "mock-1", name: "get_today", input: {} }], provider: "anthropic", model: "claude-sonnet-5", usage: null, cost_usd: null, created_at: new Date().toISOString() });

  await delayed(undefined, 400);
  const toolOutput = { recovery: { value: 78.4, band: "green" }, strain_today: { value: 8.2, band: "light" } };
  yield { type: "tool_result", id: "mock-1", output: toolOutput, is_error: false };
  messages.push({ id: nextId(), role: "user", blocks: [{ type: "tool_result", id: "mock-1", output: toolOutput, is_error: false }], provider: null, model: null, usage: null, cost_usd: null, created_at: new Date().toISOString() });

  const reply =
    "Recovery is 78% (green) and strain so far today is light — you're clear for a harder session. " +
    "Given you've got Head of the Charles in 9 days, I'd keep today purposeful but not maximal: a TR-zone piece " +
    "with full recovery between reps, then ease into the taper from here.";
  const words = reply.split(" ");
  for (const word of words) {
    await delayed(undefined, 18);
    yield { type: "text", text: word + " " };
  }

  const usage = { input_tokens: 2100, output_tokens: 78, cache_creation_input_tokens: 0, cache_read_input_tokens: 1600 };
  const cost_usd = 0.0041;
  yield { type: "usage", usage, cost_usd, daily_spend_usd: 0.46, daily_cap_usd: MOCK_COACH_SETTINGS.daily_cap_usd };
  messages.push({ id: nextId(), role: "assistant", blocks: [{ type: "text", text: reply }], provider: "anthropic", model: "claude-sonnet-5", usage, cost_usd, created_at: new Date().toISOString() });
  if (conv) conv.updated_at = new Date().toISOString();

  yield { type: "done", stop_reason: "end_turn" };
}

// --- Nutrition (session 13) --------------------------------------------------

function localDateFromIso(ts: string): string {
  return localDateString(new Date(ts));
}

function isoAtLocalTime(dateStr: string, hour: number, minute = 0): string {
  const d = new Date(dateStr + "T00:00:00");
  d.setHours(hour, minute, 0, 0);
  return d.toISOString();
}

let nextMockFoodId = 100;
let nextMockFoodLogId = 1000;
let nextMockMyFoodId = 1;
let nextMockSavedMealId = 1;

const MOCK_FOODS: Food[] = [
  {
    id: 1, source: "manual", barcode: null, name: "Oats", brand: null, serving_size: 40, serving_unit: "g",
    kcal_100g: 375, protein_100g: 13, carbs_100g: 61, fat_100g: 7, fiber_100g: 10, sugar_100g: 1, sodium_100g: 2, verified: true,
  },
  {
    id: 2, source: "off", barcode: "5000112548167", name: "Banana", brand: null, serving_size: 118, serving_unit: "g",
    kcal_100g: 89, protein_100g: 1.1, carbs_100g: 23, fat_100g: 0.3, fiber_100g: 2.6, sugar_100g: 12, sodium_100g: 1, verified: false,
  },
  {
    id: 3, source: "usda", barcode: null, name: "Chicken breast, grilled", brand: null, serving_size: 172, serving_unit: "g",
    kcal_100g: 165, protein_100g: 31, carbs_100g: 0, fat_100g: 3.6, fiber_100g: 0, sugar_100g: 0, sodium_100g: 74, verified: false,
  },
  {
    id: 4, source: "usda", barcode: null, name: "White rice, cooked", brand: null, serving_size: 158, serving_unit: "g",
    kcal_100g: 130, protein_100g: 2.7, carbs_100g: 28, fat_100g: 0.3, fiber_100g: 0.4, sugar_100g: 0.1, sodium_100g: 1, verified: false,
  },
  {
    id: 5, source: "off", barcode: "3760020505701", name: "Greek yoghurt", brand: "Fage", serving_size: 170, serving_unit: "g",
    kcal_100g: 59, protein_100g: 10, carbs_100g: 3.6, fat_100g: 0.4, fiber_100g: 0, sugar_100g: 3.6, sodium_100g: 36, verified: false,
  },
  {
    id: 6, source: "off", barcode: "0810010300047", name: "Chocolate Chip Protein Bar", brand: "Clif", serving_size: 68, serving_unit: "g",
    kcal_100g: 370, protein_100g: 20, carbs_100g: 40, fat_100g: 12, fiber_100g: 7, sugar_100g: 20, sodium_100g: 260, verified: false,
  },
];

// Only returned when a search opts into OFF (`includeOff`) — lets the mock UI actually
// demonstrate the "Also search Open Food Facts" flow finding something the local cache/USDA
// mocks above don't have, the same way the real OFF fallthrough surfaces results local/USDA
// didn't.
const MOCK_OFF_ONLY_FOODS: Food[] = [
  {
    id: 7, source: "off", barcode: "7622210449283", name: "Oreo Cookies", brand: "Nabisco", serving_size: 29, serving_unit: "g",
    kcal_100g: 480, protein_100g: 5, carbs_100g: 68, fat_100g: 20, fiber_100g: 3, sugar_100g: 38, sodium_100g: 420, verified: false,
  },
];

function findMockFood(id: number): Food | undefined {
  return MOCK_FOODS.find((f) => f.id === id);
}

function gramsForMockQuantity(quantity: number, unit: "g" | "serving", servingSize: number | null): number | null {
  if (quantity <= 0) return null;
  if (unit === "g") return quantity;
  return servingSize ? quantity * servingSize : null;
}

function scaleMockMacros(food: Food, grams: number) {
  const factor = grams / 100;
  const scale = (v: number | null) => (v != null ? v * factor : null);
  return {
    kcal: scale(food.kcal_100g),
    protein: scale(food.protein_100g),
    carbs: scale(food.carbs_100g),
    fat: scale(food.fat_100g),
    fiber: scale(food.fiber_100g),
    sugar: scale(food.sugar_100g),
    sodium: scale(food.sodium_100g),
  };
}

let MOCK_FOOD_LOGS: FoodLogRow[] = (() => {
  const today = localDateString();
  const yesterday = shiftDate(today, -1);
  const seed: { date: string; hour: number; meal: Meal; foodId: number; quantity: number; unit: "g" | "serving" }[] = [
    { date: yesterday, hour: 7, meal: "breakfast", foodId: 1, quantity: 1, unit: "serving" },
    { date: yesterday, hour: 12, meal: "lunch", foodId: 3, quantity: 1, unit: "serving" },
    { date: yesterday, hour: 12, meal: "lunch", foodId: 4, quantity: 1, unit: "serving" },
    { date: yesterday, hour: 19, meal: "dinner", foodId: 5, quantity: 1, unit: "serving" },
    { date: today, hour: 7, meal: "breakfast", foodId: 1, quantity: 1, unit: "serving" },
    { date: today, hour: 10, meal: "snack", foodId: 2, quantity: 1, unit: "serving" },
  ];
  return seed.map((s) => {
    const food = findMockFood(s.foodId)!;
    const grams = gramsForMockQuantity(s.quantity, s.unit, food.serving_size)!;
    return {
      id: nextMockFoodLogId++,
      ts: isoAtLocalTime(s.date, s.hour),
      meal: s.meal,
      food_id: food.id,
      food_name: food.name,
      food_brand: food.brand,
      quantity: s.quantity,
      unit: s.unit,
      estimated: false,
      ...scaleMockMacros(food, grams),
    };
  });
})();

// A plausible trailing-30-day Garmin total-burn curve, so the day/week views and the targets
// card have something believable to show without a real Garmin connection in mock mode.
function mockExpenditureKcal(dateStr: string): number | null {
  const today = localDateString();
  const daysAgo = Math.round((new Date(today + "T00:00:00").getTime() - new Date(dateStr + "T00:00:00").getTime()) / 86_400_000);
  if (daysAgo < 0 || daysAgo > 30) return null;
  return Math.round(2750 + 220 * Math.sin(daysAgo / 3));
}

export function mockBarcodeLookup(barcode: string): BarcodeLookupResult {
  const food = MOCK_FOODS.find((f) => f.barcode === barcode);
  if (!food) return { found: false, barcode };
  return { found: true, ...food };
}

export function mockFoodSearch(query: string, includeOff = false): Food[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const matches = (f: Food) => f.name.toLowerCase().includes(q) || f.brand?.toLowerCase().includes(q);
  const local = MOCK_FOODS.filter(matches);
  if (!includeOff) return local.slice(0, 20);
  // Mirrors the real `search_foods`'s `_get_or_create_cached_food`: an OFF hit is cached into
  // the same store everything else logs against, so a food found through the opt-in button
  // has a real, loggable id — never a detached result that fails at log time. Skips any OFF
  // hit already in `local` (same mirroring as the backend's `seen_barcodes` dedup), since once
  // cached into MOCK_FOODS on a prior search it would otherwise show up twice.
  const localIds = new Set(local.map((f) => f.id));
  const offHits = MOCK_OFF_ONLY_FOODS.filter((f) => matches(f) && !localIds.has(f.id)).map((f) => {
    const cached = findMockFood(f.id);
    if (cached) return cached;
    MOCK_FOODS.push(f);
    return f;
  });
  return [...local, ...offHits].slice(0, 20);
}

export function createMockManualFood(fields: Omit<Food, "id" | "source" | "verified" | "barcode"> & { barcode?: string | null }): Food {
  const food: Food = { id: nextMockFoodId++, source: "manual", verified: true, barcode: fields.barcode ?? null, ...fields };
  MOCK_FOODS.push(food);
  return food;
}

let MOCK_MY_FOODS: { my_food_id: number; food_id: number; label: string | null }[] = [
  { my_food_id: nextMockMyFoodId++, food_id: 1, label: "Morning oats" },
  { my_food_id: nextMockMyFoodId++, food_id: 5, label: null },
];

export function mockMyFoods(): MyFoodRow[] {
  return MOCK_MY_FOODS.map((m) => ({ my_food_id: m.my_food_id, label: m.label, ...findMockFood(m.food_id)! }));
}

export function starMockFood(foodId: number, label: string | null): MyFoodRow {
  const existing = MOCK_MY_FOODS.find((m) => m.food_id === foodId);
  const row = existing ?? { my_food_id: nextMockMyFoodId++, food_id: foodId, label };
  if (!existing) MOCK_MY_FOODS = [...MOCK_MY_FOODS, row];
  return { my_food_id: row.my_food_id, label: row.label, ...findMockFood(foodId)! };
}

export function unstarMockFood(myFoodId: number): boolean {
  const before = MOCK_MY_FOODS.length;
  MOCK_MY_FOODS = MOCK_MY_FOODS.filter((m) => m.my_food_id !== myFoodId);
  return MOCK_MY_FOODS.length < before;
}

let MOCK_SAVED_MEALS: SavedMealRow[] = [
  {
    id: nextMockSavedMealId++,
    name: "Post-workout shake",
    items: [{ food_id: 5, quantity: 1, unit: "serving" }, { food_id: 2, quantity: 1, unit: "serving" }],
    created_at: new Date().toISOString(),
  },
];

export function mockSavedMeals(): SavedMealRow[] {
  return MOCK_SAVED_MEALS;
}

export function saveMockMeal(name: string, items: SavedMealItem[]): SavedMealRow {
  const row: SavedMealRow = { id: nextMockSavedMealId++, name, items, created_at: new Date().toISOString() };
  MOCK_SAVED_MEALS = [...MOCK_SAVED_MEALS, row];
  return row;
}

export function deleteMockSavedMeal(id: number): boolean {
  const before = MOCK_SAVED_MEALS.length;
  MOCK_SAVED_MEALS = MOCK_SAVED_MEALS.filter((m) => m.id !== id);
  return MOCK_SAVED_MEALS.length < before;
}

function pushMockFoodLog(ts: string, meal: Meal, foodId: number, quantity: number, unit: "g" | "serving", estimated = false): FoodLogRow {
  const food = findMockFood(foodId);
  if (!food) throw new Error("Food not found");
  const grams = gramsForMockQuantity(quantity, unit, food.serving_size);
  if (grams == null) throw new Error(`Can't log ${food.name} by serving — no known serving size.`);
  const row: FoodLogRow = {
    id: nextMockFoodLogId++,
    ts,
    meal,
    food_id: food.id,
    food_name: food.name,
    food_brand: food.brand,
    quantity,
    unit,
    estimated,
    ...scaleMockMacros(food, grams),
  };
  MOCK_FOOD_LOGS = [...MOCK_FOOD_LOGS, row];
  return row;
}

export function createMockFoodLog(ts: string | undefined, meal: Meal, foodId: number, quantity: number, unit: "g" | "serving"): FoodLogRow {
  return pushMockFoodLog(ts ?? new Date().toISOString(), meal, foodId, quantity, unit);
}

export function updateMockFoodLog(logId: number, patch: { meal?: Meal; quantity?: number; unit?: "g" | "serving" }): FoodLogRow {
  const idx = MOCK_FOOD_LOGS.findIndex((l) => l.id === logId);
  if (idx === -1) throw new Error("Log not found");
  const row = MOCK_FOOD_LOGS[idx];
  const food = findMockFood(row.food_id)!;
  const quantity = patch.quantity ?? row.quantity;
  const unit = patch.unit ?? row.unit;
  const grams = gramsForMockQuantity(quantity, unit, food.serving_size);
  if (grams == null) throw new Error(`Can't log ${food.name} by serving — no known serving size.`);
  const updated: FoodLogRow = { ...row, meal: patch.meal ?? row.meal, quantity, unit, ...scaleMockMacros(food, grams) };
  MOCK_FOOD_LOGS = [...MOCK_FOOD_LOGS.slice(0, idx), updated, ...MOCK_FOOD_LOGS.slice(idx + 1)];
  return updated;
}

export function deleteMockFoodLog(logId: number): boolean {
  const before = MOCK_FOOD_LOGS.length;
  MOCK_FOOD_LOGS = MOCK_FOOD_LOGS.filter((l) => l.id !== logId);
  return MOCK_FOOD_LOGS.length < before;
}

export function listMockFoodLogs(from?: string, to?: string): FoodLogRow[] {
  return MOCK_FOOD_LOGS.filter((l) => {
    const d = localDateFromIso(l.ts);
    if (from && d < from) return false;
    if (to && d > to) return false;
    return true;
  }).sort((a, b) => (a.ts < b.ts ? -1 : 1));
}

export function copyMockDayLogs(fromDate: string, toDate: string, meal?: Meal): FoodLogRow[] {
  const dayDeltaMs = new Date(toDate + "T00:00:00").getTime() - new Date(fromDate + "T00:00:00").getTime();
  const source = listMockFoodLogs(fromDate, fromDate).filter((l) => !meal || l.meal === meal);
  return source.map((l) => pushMockFoodLog(new Date(new Date(l.ts).getTime() + dayDeltaMs).toISOString(), l.meal, l.food_id, l.quantity, l.unit));
}

export function logMockSavedMeal(savedMealId: number, meal: Meal, ts?: string): FoodLogRow[] {
  const saved = MOCK_SAVED_MEALS.find((m) => m.id === savedMealId);
  if (!saved) throw new Error("Saved meal not found");
  const at = ts ?? new Date().toISOString();
  return saved.items.map((item) => pushMockFoodLog(at, meal, item.food_id, item.quantity, item.unit));
}

let MOCK_NUTRITION_TARGET_SETTINGS: NutritionTargetSettings = {
  protein_g_per_kg: 1.6,
  carb_g_per_kg_rest: 3,
  carb_g_per_kg_moderate: 5,
  carb_g_per_kg_double_day: 7,
  carb_g_per_kg_pre_race: 8,
  kcal_target_source: "garmin_total",
  manual_kcal_target: null,
};

const MOCK_WEIGHT_KG = 79;

function computeMockTargets(dateStr: string): NutritionTargetsResponse["today"] {
  const s = MOCK_NUTRITION_TARGET_SETTINGS;
  // The real backend's tier comes from the day's *workouts* (today_training_tier), never food
  // logs — one erg session in FULL's mock Today fixture is a plausible single-session day.
  const tier: NutritionTargetsResponse["today"]["tier"] = "moderate";
  const carbPerKg = { rest: s.carb_g_per_kg_rest, moderate: s.carb_g_per_kg_moderate, double_day: s.carb_g_per_kg_double_day, pre_race: s.carb_g_per_kg_pre_race }[tier];
  const proteinG = s.protein_g_per_kg * MOCK_WEIGHT_KG;
  const carbG = carbPerKg * MOCK_WEIGHT_KG;
  const kcalTarget = s.kcal_target_source === "manual" ? s.manual_kcal_target : mockExpenditureKcal(shiftDate(dateStr, -1));
  let fatG: number | null = null;
  let explanation = `Protein ${s.protein_g_per_kg}g/kg x ${MOCK_WEIGHT_KG}kg = ${proteinG.toFixed(0)}g. Carbs ${carbPerKg}g/kg (${tier.replace("_", " ")}) x ${MOCK_WEIGHT_KG}kg = ${carbG.toFixed(0)}g.`;
  if (kcalTarget) {
    const fatKcal = Math.max(0, kcalTarget - proteinG * 4 - carbG * 4);
    fatG = fatKcal / 9;
    explanation += ` Fat is the kcal remainder: (${kcalTarget.toFixed(0)} - ${(proteinG * 4).toFixed(0)} - ${(carbG * 4).toFixed(0)}) / 9 = ${fatG.toFixed(0)}g.`;
  } else {
    explanation += " No kcal target yet (no recent Garmin total-burn data), so no fat target either.";
  }
  return { protein_g: proteinG, carb_g: carbG, fat_g: fatG, kcal_target: kcalTarget, tier, explanation, weight_source: "withings" };
}

export function mockNutritionTargets(): NutritionTargetsResponse {
  return { settings: { ...MOCK_NUTRITION_TARGET_SETTINGS }, today: computeMockTargets(localDateString()) };
}

export function saveMockNutritionTargets(patch: Partial<NutritionTargetSettings>): NutritionTargetsResponse {
  MOCK_NUTRITION_TARGET_SETTINGS = { ...MOCK_NUTRITION_TARGET_SETTINGS, ...patch };
  return mockNutritionTargets();
}

function sumMockDay(dateStr: string) {
  const logs = listMockFoodLogs(dateStr, dateStr);
  const totals = { kcal: 0, protein: 0, carbs: 0, fat: 0, fiber: 0, sugar: 0, sodium: 0 };
  for (const l of logs) {
    totals.kcal += l.kcal ?? 0;
    totals.protein += l.protein ?? 0;
    totals.carbs += l.carbs ?? 0;
    totals.fat += l.fat ?? 0;
    totals.fiber += l.fiber ?? 0;
    totals.sugar += l.sugar ?? 0;
    totals.sodium += l.sodium ?? 0;
  }
  return { totals, logs };
}

export function mockDaySummary(dateStr: string): DaySummary {
  const { totals, logs } = sumMockDay(dateStr);
  return { date: dateStr, intake: totals, targets: computeMockTargets(dateStr), expenditure_kcal: mockExpenditureKcal(dateStr), logs };
}

function computeMockUnderFuelling(balances: { intake_kcal: number; expenditure_kcal: number | null; has_log: boolean }[]): UnderFuelling {
  const logged = balances.filter((b) => b.has_log && b.expenditure_kcal);
  if (logged.length < 3) return { flag: false, logged_days: logged.length, explanation: "Not enough logged days yet to assess fuelling." };
  const recent = logged.slice(-3);
  const deficitPcts = recent.map((b) => (b.expenditure_kcal! - b.intake_kcal) / b.expenditure_kcal!);
  const flagged = deficitPcts.every((p) => p >= 0.25);
  const avgDeficit = recent.reduce((sum, b) => sum + (b.expenditure_kcal! - b.intake_kcal), 0) / recent.length;
  return {
    flag: flagged,
    logged_days: logged.length,
    avg_deficit_kcal: avgDeficit,
    explanation: flagged
      ? `The last ${recent.length} logged days each ran 25%+ below expenditure (avg ${avgDeficit.toFixed(0)} kcal/day short) — worth a look at fuelling, not a reason to worry alone.`
      : "Intake has kept pace with expenditure over the last logged days.",
  };
}

export function mockWeekSummary(from: string, to: string): WeekSummary {
  const days = [];
  let cursor = from;
  while (cursor <= to) {
    const { totals, logs } = sumMockDay(cursor);
    days.push({ date: cursor, intake_kcal: totals.kcal, protein: totals.protein, expenditure_kcal: mockExpenditureKcal(cursor), has_log: logs.length > 0 });
    cursor = shiftDate(cursor, 1);
  }
  return { days, under_fuelling: computeMockUnderFuelling(days) };
}

const MOCK_PHOTO_ESTIMATE: PhotoEstimateResult = {
  items: [
    { name: "Grilled chicken breast", quantity_description: "~150g", kcal: 248, protein_g: 46, carbs_g: 0, fat_g: 5 },
    { name: "White rice", quantity_description: "~1 cup cooked", kcal: 205, protein_g: 4, carbs_g: 44, fat_g: 0.5 },
    { name: "Steamed broccoli", quantity_description: "~1 cup", kcal: 55, protein_g: 4, carbs_g: 11, fat_g: 0.5 },
  ],
  notes: "Estimate — portion sizes are a guess from a single photo angle, and any oil or sauce used in cooking isn't visible.",
  cost_usd: 0.012,
};

export function mockPhotoEstimate(): PhotoEstimateResult {
  return MOCK_PHOTO_ESTIMATE;
}

export function savePhotoEstimateMock(items: PhotoEstimateResult["items"], meal: Meal, ts?: string): number[] {
  const at = ts ?? new Date().toISOString();
  return items.map((item) => {
    const food = createMockManualFood({
      name: item.name,
      brand: null,
      serving_size: 100,
      serving_unit: item.quantity_description || "serving",
      kcal_100g: item.kcal,
      protein_100g: item.protein_g,
      carbs_100g: item.carbs_g,
      fat_100g: item.fat_g,
      fiber_100g: null,
      sugar_100g: null,
      sodium_100g: null,
    });
    food.source = "estimate";
    food.verified = false;
    return pushMockFoodLog(at, meal, food.id, 1, "serving", true).id;
  });
}

// --- Session 14 (see PLAN.md): gym logger --------------------------------------------------
//
// The active-logging screen reads/writes IndexedDB directly (gymDb.ts/gymSync.ts), real in a
// real browser even under ?mock=1 — only the library/history/readiness reads below go through
// this mock switch, same as every other page.

let nextMockExerciseId = 1;
let MOCK_EXERCISES: Exercise[] = [
  { id: nextMockExerciseId++, external_id: "Barbell_Squat", name: "Barbell Squat", default_equipment_type: "barbell", movement_pattern: "squat", unilateral: false, primary_muscles: ["quadriceps", "glutes"], secondary_muscles: ["hamstrings"], custom: false },
  { id: nextMockExerciseId++, external_id: "Barbell_Bench_Press", name: "Barbell Bench Press", default_equipment_type: "barbell", movement_pattern: "push_horizontal", unilateral: false, primary_muscles: ["chest"], secondary_muscles: ["triceps", "shoulders"], custom: false },
  { id: nextMockExerciseId++, external_id: "Conventional_Deadlift", name: "Conventional Deadlift", default_equipment_type: "barbell", movement_pattern: "hinge", unilateral: false, primary_muscles: ["hamstrings", "lower back"], secondary_muscles: ["glutes", "traps"], custom: false },
  { id: nextMockExerciseId++, external_id: "Seated_Cable_Row", name: "Seated Cable Row", default_equipment_type: "cable", movement_pattern: "pull_horizontal", unilateral: false, primary_muscles: ["lats", "middle back"], secondary_muscles: ["biceps"], custom: false },
  { id: nextMockExerciseId++, external_id: "Dumbbell_Shoulder_Press", name: "Dumbbell Shoulder Press", default_equipment_type: "dumbbell", movement_pattern: "push_vertical", unilateral: false, primary_muscles: ["shoulders"], secondary_muscles: ["triceps"], custom: false },
  { id: nextMockExerciseId++, external_id: "Pull-up", name: "Pull-up", default_equipment_type: "bodyweight", movement_pattern: "pull_vertical", unilateral: false, primary_muscles: ["lats"], secondary_muscles: ["biceps", "middle back"], custom: false },
  { id: nextMockExerciseId++, external_id: "Walking_Lunge", name: "Walking Lunge", default_equipment_type: "dumbbell", movement_pattern: "lunge", unilateral: true, primary_muscles: ["quadriceps", "glutes"], secondary_muscles: ["hamstrings"], custom: false },
];

export function mockExercises(query?: string): Exercise[] {
  if (!query) return MOCK_EXERCISES;
  const q = query.trim().toLowerCase();
  return MOCK_EXERCISES.filter((e) => e.name.toLowerCase().includes(q));
}

export function createMockExercise(fields: Omit<Exercise, "id" | "external_id" | "custom">): Exercise {
  const row: Exercise = { id: nextMockExerciseId++, external_id: null, custom: true, ...fields };
  MOCK_EXERCISES = [...MOCK_EXERCISES, row];
  return row;
}

export function updateMockExercise(id: number, patch: Partial<Exercise>): Exercise {
  MOCK_EXERCISES = MOCK_EXERCISES.map((e) => (e.id === id ? { ...e, ...patch } : e));
  return MOCK_EXERCISES.find((e) => e.id === id)!;
}

let nextMockGymId = 1;
let nextMockStationId = 1;
let MOCK_GYMS: GymRow[] = [{ id: nextMockGymId++, name: "Home gym" }];
let MOCK_STATIONS: GymStation[] = [
  { id: nextMockStationId++, gym_id: 1, name: "Cable station 2", equipment_type: "cable", config: { dual_stack: true, pulley_multiplier: 0.5 } },
];

export function mockGyms(): GymRow[] {
  return MOCK_GYMS;
}

export function createMockGym(name: string): GymRow {
  const row: GymRow = { id: nextMockGymId++, name };
  MOCK_GYMS = [...MOCK_GYMS, row];
  return row;
}

export function mockStations(gymId: number): GymStation[] {
  return MOCK_STATIONS.filter((s) => s.gym_id === gymId);
}

export function upsertMockStation(
  gymId: number,
  fields: { name: string; equipment_type: GymStation["equipment_type"]; config: GymStation["config"] },
  stationId?: number,
): GymStation {
  if (stationId) {
    MOCK_STATIONS = MOCK_STATIONS.map((s) => (s.id === stationId ? { ...s, gym_id: gymId, ...fields } : s));
    return MOCK_STATIONS.find((s) => s.id === stationId)!;
  }
  const row: GymStation = { id: nextMockStationId++, gym_id: gymId, ...fields };
  MOCK_STATIONS = [...MOCK_STATIONS, row];
  return row;
}

let nextMockTemplateId = 1;
let MOCK_TEMPLATES: StrengthTemplate[] = [
  {
    id: nextMockTemplateId++,
    name: "Push day",
    items: [
      { exercise_id: 2, target_sets: 4, target_reps: 6 },
      { exercise_id: 5, target_sets: 3, target_reps: 10 },
    ],
  },
];

export function mockTemplates(): StrengthTemplate[] {
  return MOCK_TEMPLATES;
}

export function saveMockTemplate(name: string, items: StrengthTemplateItem[], templateId?: number): StrengthTemplate {
  if (templateId) {
    MOCK_TEMPLATES = MOCK_TEMPLATES.map((t) => (t.id === templateId ? { id: templateId, name, items } : t));
    return MOCK_TEMPLATES.find((t) => t.id === templateId)!;
  }
  const row: StrengthTemplate = { id: nextMockTemplateId++, name, items };
  MOCK_TEMPLATES = [...MOCK_TEMPLATES, row];
  return row;
}

export function deleteMockTemplate(id: number): void {
  MOCK_TEMPLATES = MOCK_TEMPLATES.filter((t) => t.id !== id);
}

export function mockRepeatLastWorkout(): RepeatWorkoutPlanItem[] {
  return [
    { exercise_id: 1, gym_station_id: null, equipment_type: "barbell", set_type: "working", target_reps: 5 },
    { exercise_id: 3, gym_station_id: null, equipment_type: "barbell", set_type: "working", target_reps: 5 },
  ];
}

export function mockLastSetsForExercise(exerciseId: number): StrengthSetRow[] {
  if (exerciseId !== 1) return [];
  const createdAt = new Date(Date.now() - 4 * 86_400_000).toISOString();
  return [0, 1, 2].map((i) => ({
    client_id: `mock-last-${exerciseId}-${i}`,
    exercise_id: exerciseId,
    seq: i,
    set_type: "working",
    reps: 5,
    equipment_type: "barbell",
    load_kg: 100,
    bar_weight_kg: 20,
    effective_load_kg: 120,
    load_is_estimated: false,
    bodyweight_kg_used: null,
    is_rep_pr: false,
    is_e1rm_pr: false,
    muscular_au: 500,
    source: "catch",
    is_confirmed: true,
    created_at: createdAt,
  }));
}

export function mockMuscleReadiness(): MuscleReadiness {
  return {
    window_hours: 72,
    by_muscle: {
      quadriceps: 1800,
      glutes: 1600,
      hamstrings: 900,
      chest: 1100,
      shoulders: 700,
      triceps: 650,
      lats: 950,
      "middle back": 500,
      biceps: 300,
      "lower back": 800,
      abdominals: 200,
      calves: 0,
      traps: 400,
      forearms: 100,
      adductors: 0,
      abductors: 0,
      neck: 0,
    },
  };
}
