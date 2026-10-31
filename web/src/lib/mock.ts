import type { SparklinePoint, SyncSourceStatus, Today } from "./types";

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
  return SYNC_STATUS;
}
