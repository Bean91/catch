import type {
  BodyCompReading,
  ErgStrokesResponse,
  ErgTechnique,
  IntervalSummary,
  Note,
  PersonalBests,
  Settings,
  SparklinePoint,
  Stroke,
  SyncSourceStatus,
  Today,
  TrendMetric,
  TrendPoint,
  VolumeWeek,
  WorkoutCategory,
  WorkoutDetail,
  WorkoutListItem,
  WorkoutsPage,
  ZoneRow,
} from "./types";
import { ZONE_NAMES } from "./types";

export type MockScenario = "full" | "calibrating" | "empty" | "error" | "loading";

export function mockScenarioFromQuery(): MockScenario | null {
  const params = new URLSearchParams(window.location.search);
  if (!params.has("mock")) return null;
  const value = params.get("mock");
  if (value === "" || value === "1" || value === "true") return "full";
  if (value === "calibrating" || value === "empty" || value === "error" || value === "loading") return value;
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
    value: 8.2,
    band: "light",
    trimp_like: 48,
    components: [],
    explanation: "1 session today, Banister TRIMP from heart rate.",
  },
  strain_target_range: [10, 16],
  load: {
    value: 1.08,
    band: "optimal",
    components: [{ acute_7d: 71.2, chronic_42d: 66.0, form: -5.2 }],
    explanation: "Acute (7d EWMA)=71.2, chronic (42d EWMA)=66.0, acute:chronic=1.08.",
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
  recovery: null,
  sleep_last_night: null,
  strain_today: null,
  strain_target_range: [0, 21],
  load: null,
  hrv: { today: null, sparkline_14d: [], baseline_band: null },
  resting_hr: { today: null, sparkline_14d: [], baseline_band: null },
  latest_erg: null,
  predicted_2k: { value: null, band: "insufficient_data", components: [], explanation: "No usable pieces yet." },
  recommendation: "Not enough data yet to make a recommendation — keep syncing.",
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

function mockWorkout(i: number): WorkoutListItem {
  const bucket = i % 5;
  const daysAgo = Math.round(i * 1.6);
  const start = shiftDate(TODAY, -daysAgo) + "T07:30:00.000Z";

  let category: WorkoutListItem["category"];
  let source: string;
  let type: string;
  if (bucket === 0) {
    category = "on_water";
    source = "garmin";
    type = "rowing_v2";
  } else if (bucket === 3) {
    category = "other";
    source = "garmin";
    type = "strength_training";
  } else {
    category = "erg";
    source = i % 2 === 0 ? "concept2" : "garmin";
    type = source === "concept2" ? "rower" : "indoor_rowing";
  }

  const distance = category === "other" ? null : category === "on_water" ? 8000 + (i % 5) * 600 : 5000 + (i % 4) * 1000;
  const paceS500 = category === "on_water" ? 118 + (i % 6) : 108 + (i % 5) * 2;
  const duration = category === "other" ? 2700 + (i % 3) * 300 : distance ? (distance / 500) * paceS500 : null;
  const avgHr = category === "other" ? 128 + (i % 4) * 3 : 150 + (i % 6) * 3;
  const strainValue = 4 + (i % 8) * 1.6;

  return {
    id: i + 1,
    source,
    external_id: `mock-${i}`,
    type,
    start,
    duration,
    distance,
    avg_hr: avgHr,
    max_hr: avgHr + 18,
    avg_power: category === "erg" ? 180 + (i % 5) * 15 : null,
    calories: duration ? Math.round(duration * 0.17) : null,
    workout_type: category === "erg" ? "JustRow" : null,
    drag_factor: category === "erg" && source === "concept2" ? 118 + (i % 6) : null,
    stroke_rate: category !== "other" ? 22 + (i % 5) : null,
    linked_activity_id: null,
    category,
    strain: i < 2 ? null : { activity_id: i + 1, value: strainValue, band: strainValue < 10 ? "light" : strainValue < 14 ? "moderate" : "high" },
  };
}

const MOCK_WORKOUTS: WorkoutListItem[] = Array.from({ length: MOCK_WORKOUT_COUNT }, (_, i) => mockWorkout(i));

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

export function mockWorkoutDetail(id: number): WorkoutDetail {
  const base = MOCK_WORKOUTS.find((w) => w.id === id) ?? MOCK_WORKOUTS[0];
  const localDate = (base.start ?? TODAY).slice(0, 10);
  return {
    ...base,
    intervals: base.category === "erg" ? { type: "JustRow" } : null,
    local_date: localDate,
    zones: { zones: MOCK_ZONES, note: "Zone boundaries are defaults — confirm with your coach before training off them." },
    hr_zone: base.avg_hr ? "UT1" : null,
    note:
      id % 3 === 0
        ? { id: 1, date: localDate, text: "Felt strong on the back half.", rpe: 6, created_at: new Date().toISOString() }
        : null,
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

export function mockErgStrokes(id: number): ErgStrokesResponse {
  const strokesPerInterval = 48;
  const interval0 = Array.from({ length: strokesPerInterval }, (_, i) => mockStroke(i, 0, 0, 0, 108));
  const rep0End = interval0[interval0.length - 1];
  const interval1 = Array.from({ length: strokesPerInterval }, (_, i) =>
    mockStroke(i, 1, rep0End.distance_cum ?? 0, rep0End.t_cum, 112),
  );
  const strokes = [...interval0, ...interval1].map((s) => ({ ...s, activity_id: id }));

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

  return {
    activity_id: id,
    strokes,
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

export function mockTrend(metric: TrendMetric): TrendPoint[] {
  const days = metric === "weight" || metric === "w_per_kg" ? 40 : 84;
  const step = metric === "weight" || metric === "w_per_kg" ? 3 : 1;
  const points: TrendPoint[] = [];
  for (let i = days; i >= 0; i -= step) {
    const d = shiftDate(TODAY, -i);
    let value: number | null;
    switch (metric) {
      case "recovery":
        value = 55 + 20 * Math.sin(i / 6);
        break;
      case "hrv_rmssd":
        value = 60 + 6 * Math.sin(i / 5);
        break;
      case "resting_hr":
        value = 49 - Math.sin(i / 7) * 2;
        break;
      case "sleep_score":
        value = 80 + 10 * Math.sin(i / 4);
        break;
      case "strain":
        value = 8 + 6 * Math.abs(Math.sin(i / 3));
        break;
      case "load_acr":
        value = 1.0 + 0.25 * Math.sin(i / 10);
        break;
      case "weight":
        value = 79 + Math.sin(i / 9) * 0.8;
        break;
      case "w_per_kg":
        value = 2.6 + Math.sin(i / 11) * 0.15;
        break;
      case "predicted_2k":
        value = 400 - i * 0.05;
        break;
      default:
        value = null;
    }
    const point: TrendPoint = { date: d, value };
    if (metric === "load_acr") {
      point.acute_7d = 60 + 8 * Math.sin(i / 10);
      point.chronic_42d = 58;
      point.form = point.chronic_42d - point.acute_7d;
    }
    if (metric === "weight") {
      point.smoothed = 79 + Math.sin((i - step) / 9) * 0.6;
    }
    points.push(point);
  }
  return points;
}

export function mockBody(): BodyCompReading[] {
  const days = 60;
  const out: BodyCompReading[] = [];
  for (let i = days; i >= 0; i -= 3) {
    const d = shiftDate(TODAY, -i);
    out.push({
      id: days - i,
      source: "withings",
      external_id: `mock-body-${i}`,
      ts: d + "T07:00:00.000Z",
      weight_kg: 79 + Math.sin(i / 9) * 0.8,
      fat_pct: 14.5 + Math.sin(i / 14) * 0.6,
      fat_kg: 11.4,
      muscle_kg: 36.2 + Math.sin(i / 20) * 0.3,
      bone_kg: 3.2,
      hydration_kg: 44.0,
    });
  }
  return out;
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
};

export function mockSettings(): Settings {
  return MOCK_SETTINGS;
}

export function saveMockSettings(patch: Partial<Settings>): Settings {
  MOCK_SETTINGS = { ...MOCK_SETTINGS, ...patch };
  return MOCK_SETTINGS;
}
