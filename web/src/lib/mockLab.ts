// ?mock=1 fixtures for records and the Performance Lab. Fixed figures: the browser holds none of the rules (tolerances, bands,
// thresholds) — the mock only answers in the server's shape.
import { addDays, todayISO, weekStart } from "./dates";
import type { ErgAlignment, ErgAlignmentSuggestion, LoadHistory, DuplicateMergePreview, HrAtWorkload, LabProgression, PowerCurve, Predicted2k, RecordEntry, RecordsPayload, SplitByRate } from "./types";

const t = () => todayISO();

function entry(daysAgo: number, distance: number, duration: number, label: RecordEntry["label"], watts: number | null, extra: Partial<RecordEntry> = {}): RecordEntry {
  return {
    distance_m: distance, duration_s: duration, pace_s: (duration / distance) * 500, split_m: 500, avg_watts: watts, watts_basis: watts == null ? null : label === "piece" ? "derived" : "measured",
    date: addDays(t(), -daysAgo), canonical_id: 1, piece_id: label === "piece" ? 1 : null, ref: label === "piece" ? "/tests/piece/1" : "/workouts/1", label, verified: label === "test", ...extra,
  };
}

export function mockRecords(modality: "rowing_erg" | "bike" = "rowing_erg"): RecordsPayload {
  if (modality === "bike") {
    const e = { ...entry(20, 10000, 1180, "training", 238), pace_s: 118, split_m: 1000, watts_basis: "measured" as const, verified: false };
    return {
      modality, from: null, to: null,
      distance: [1000, 5000, 10000, 20000].map((m) => ({ key: `${m}m`, target_m: m, count: m === 10000 ? 1 : 0, best: m === 10000 ? e : null, history: m === 10000 ? [e] : [] })),
      duration: [{ key: "30min", target_s: 1800, count: 0, best: null, history: [] }, { key: "60min", target_s: 3600, count: 0, best: null, history: [] }],
      power: [60, 300, 1200, 1800, 3600].map((s) => ({ key: `${s / 60}min_power`, min_duration_s: s, count: s <= 1200 ? 1 : 0, best: s <= 1200 ? e : null, history: s <= 1200 ? [e] : [] })),
    };
  }
  const twoKOld = entry(160, 2000, 418.4, "test", 296);
  const twoK = entry(12, 2000, 412.3, "test", 312);
  const fiveK = entry(45, 5000, 1098.0, "training", 268, { verified: true });
  const piece500 = entry(30, 500, 92.1, "piece", 449);
  const sixty = entry(70, 14820, 3600, "training", 205);
  return {
    modality, from: null, to: null,
    distance: [
      { key: "500m", target_m: 500, count: 3, best: piece500, history: [piece500] },
      { key: "1000m", target_m: 1000, count: 0, best: null, history: [] },
      { key: "2000m", target_m: 2000, count: 4, best: twoK, history: [twoKOld, twoK] },
      { key: "5000m", target_m: 5000, count: 2, best: fiveK, history: [fiveK] },
      { key: "6000m", target_m: 6000, count: 0, best: null, history: [] },
      { key: "10000m", target_m: 10000, count: 0, best: null, history: [] },
    ],
    duration: [
      { key: "30min", target_s: 1800, count: 0, best: null, history: [] },
      { key: "60min", target_s: 3600, count: 1, best: sixty, history: [sixty] },
    ],
    power: [
      { key: "1min_power", min_duration_s: 60, count: 6, best: piece500, history: [piece500] },
      { key: "5min_power", min_duration_s: 300, count: 4, best: twoK, history: [twoKOld, twoK] },
      { key: "20min_power", min_duration_s: 1200, count: 2, best: sixty, history: [sixty] },
      { key: "30min_power", min_duration_s: 1800, count: 1, best: sixty, history: [sixty] },
      { key: "60min_power", min_duration_s: 3600, count: 1, best: sixty, history: [sixty] },
    ],
  };
}

export function mockProgression(modality: "rowing_erg" | "bike" = "rowing_erg"): LabProgression {
  const pts = [
    [160, 418.4, 296, "test", true], [120, 421.0, 291, "training", false], [80, 416.0, 301, "training", true], [40, 414.9, 304, "piece", true], [12, 412.3, 312, "test", true],
  ] as const;
  return {
    from: addDays(t(), -365), to: t(), modality, split_m: modality === "bike" ? 1000 : 500,
    series: modality === "bike" ? [] : [
      { key: "2000m", points: pts.map(([d, dur, w, label, best]) => ({ date: addDays(t(), -d), distance_m: 2000, duration_s: dur, pace_s: dur / 4, avg_watts: w, watts_basis: label === "piece" ? "derived" : "measured", label, new_best: best, ref: "/workouts/1" })) },
    ],
  };
}

export function mockHrAtWorkload(): HrAtWorkload {
  return {
    from: addDays(t(), -365), to: t(), split_date: addDays(t(), -182), sessions: 22, min_sessions: 2,
    bands: [
      { band_w: [220, 240], earlier: { sessions: 3, median_hr: 158, median_watts: 228, refs: [] }, recent: { sessions: 4, median_hr: 154, median_watts: 231, refs: [] }, hr_change_bpm: -4 },
      { band_w: [200, 220], earlier: { sessions: 6, median_hr: 151, median_watts: 208, refs: [] }, recent: { sessions: 5, median_hr: 147, median_watts: 210, refs: [] }, hr_change_bpm: -4 },
      { band_w: [180, 200], earlier: { sessions: 1, median_hr: null, median_watts: null, refs: [] }, recent: { sessions: 3, median_hr: 139, median_watts: 191, refs: [] }, hr_change_bpm: null },
    ],
  };
}

export function mockSplitByRate(): SplitByRate {
  return {
    from: addDays(t(), -365), to: t(), split_date: addDays(t(), -182), min_strokes: 60, min_sessions: 2,
    bands: [
      { band_spm: [18, 20], earlier: { strokes: 4200, sessions: 9, split_s: 128.4 }, recent: { strokes: 5100, sessions: 11, split_s: 126.9 }, split_change_s: -1.5 },
      { band_spm: [20, 22], earlier: { strokes: 3100, sessions: 7, split_s: 123.2 }, recent: { strokes: 2900, sessions: 6, split_s: 122.1 }, split_change_s: -1.1 },
      { band_spm: [28, 30], earlier: { strokes: 40, sessions: 1, split_s: null }, recent: { strokes: 380, sessions: 3, split_s: 103.6 }, split_change_s: null },
    ],
  };
}

export function mockPowerCurve(): PowerCurve {
  const pt = (watts: number, days: number, id = 1) => ({ watts, date: addDays(t(), -days), ref: `/workouts/${id}` });
  return {
    from: addDays(t(), -365), to: t(), split_date: addDays(t(), -182), recordings: 38, watts_basis: "derived_from_pace", max_gap_s: 10,
    durations: [
      { duration_s: 10, best: pt(612.4, 20), earlier: pt(590.1, 240, 6), recent: pt(612.4, 20) },
      { duration_s: 60, best: pt(455.0, 12), earlier: pt(441.2, 210, 6), recent: pt(455.0, 12) },
      { duration_s: 300, best: pt(322.8, 12), earlier: pt(318.0, 200, 6), recent: pt(322.8, 12) },
      { duration_s: 1200, best: pt(251.3, 230, 6), earlier: pt(251.3, 230, 6), recent: null },
      { duration_s: 3600, best: null, earlier: null, recent: null },
    ],
  };
}

export function mockPredict2k(): Predicted2k {
  return {
    kind: "estimate", value: 102.8, range: [101.9, 103.8], predicted_time_s: 411.2, range_s: [407.6, 415.2], band: "moderate", confidence: "moderate",
    components: [
      { distance_m: 2000, duration_s: 412.3, date: addDays(t(), -12), age_days: 12, effort: "declared", label: "2k test", canonical_id: 1, implied_2k_s: 412.3, weight: 0.87 },
      { distance_m: 5000, duration_s: 1098.0, date: addDays(t(), -45), age_days: 45, effort: "hr_verified", label: null, canonical_id: 1, implied_2k_s: 410.1, weight: 0.42 },
    ],
    excluded_count: 1,
    explanation: "From 2 recent hard efforts, weighted by how recent and how certain the effort was. An estimate, not a result.",
    measured_2k: null,
  };
}

export function mockDuplicateMergePreview(a: number, b: number): DuplicateMergePreview {
  const start = new Date(Date.now() - 2 * 86400000).toISOString();
  return {
    a: { activity_id: a, source: "garmin", external_id: "mock-g", type: "indoor_rowing", sport_family: "rowing", start, duration: 1800, distance: 7600, avg_hr: 148, max_hr: 171, avg_power: null, avg_cadence: 22, calories: 410 },
    b: { activity_id: b, source: "concept2", external_id: "mock-c", type: "rower", sport_family: "rowing", start, duration: 1740, distance: 7520, avg_hr: null, max_hr: null, avg_power: 205, avg_cadence: 22, calories: 395 },
    score: 0.64,
    reasons: ["overlap 97%", "duration ratio 0.97", "same sport"],
    hard_block: false,
    overlap_s: 1740,
    already_merged: false,
    blocked_reason: null,
    merged: {
      values: { start, duration: 1740, distance: 7520, avg_hr: 148, max_hr: 171, avg_power: 205, avg_cadence: 22, calories: 395 },
      from: { start: "concept2:mock-c", duration: "concept2:mock-c", distance: "concept2:mock-c", avg_hr: "garmin:mock-g", max_hr: "garmin:mock-g", avg_power: "concept2:mock-c", avg_cadence: "concept2:mock-c", calories: "concept2:mock-c" },
      recordings: 2,
      kept_workout_id: 1,
      moves: {},
    },
  };
}

export function mockLoadHistory(weeks: number): LoadHistory {
  const mon = weekStart(t());
  const rows = Array.from({ length: weeks }, (_, i) => {
    const ws = addDays(mon, -7 * (weeks - 1 - i));
    const complete = i < weeks - 1;
    const minutes = 240 + ((i * 37) % 160);
    return {
      week_start: ws, complete, load: minutes * 1.6, monotony: complete ? 1.1 + ((i * 13) % 9) / 10 : null, strain: complete ? minutes * 1.6 * 1.4 : null,
      monotony_reason: complete ? null : "week in progress", days_scored: 7, sessions: 4 + (i % 3), minutes, distance_m: minutes * 220,
      training_days: 4 + (i % 3), days_without_training: 3 - (i % 3), rest_weekdays: [0, 4, 6].slice(0, 3 - (i % 3)), avg_recovery: 55 + (i % 5) * 4,
    };
  });
  return {
    from: rows[0].week_start, to: t(), weeks: rows,
    months: [{ month: t().slice(0, 7), sessions: 14, minutes: 980, distance_m: 212000 }],
    comparison: { recent_weeks: 4, baseline_weeks: 12, rows: [
      { metric: "minutes", recent: 330, baseline: 295, change_pct: 11.9 },
      { metric: "sessions", recent: 5.25, baseline: 4.9, change_pct: 7.1 },
      { metric: "distance_m", recent: 72500, baseline: 64000, change_pct: 13.3 },
      { metric: "load", recent: 528, baseline: 470, change_pct: 12.3 },
    ] },
    rest_by_weekday: [9, 1, 2, 1, 7, 2, 6],
    complete_weeks: weeks - 1,
  };
}

// --- Session 36 follow-up: erg/heart-rate chart alignment across two devices. Workout 13's heart-rate chart is a watch's recording and
// its strokes a PM5's, so the two share a cursor only at an offset confirmed here.
export const MOCK_CROSS_DEVICE_WORKOUT = 13;
const mockAlignmentOffsets = new Map<number, number>();

export function mockErgAlignment(canonicalId: number): ErgAlignment {
  if (canonicalId !== MOCK_CROSS_DEVICE_WORKOUT) return { state: "same_recording", erg_activity_id: null, watch_activity_id: null, offset_s: 0 };
  const offset = mockAlignmentOffsets.get(canonicalId);
  return { state: offset != null ? "confirmed" : "not_linked", erg_activity_id: 9013, watch_activity_id: 7013, offset_s: offset ?? null, wall_time_known: true };
}

export function mockSuggestErgAlignment(): ErgAlignmentSuggestion {
  return { offset_s: 42, r: 0.962, overlap_s: 1710, signal: "heart_rate" };
}

export function mockSetErgAlignment(canonicalId: number, offset: number | null): ErgAlignment {
  if (offset == null) mockAlignmentOffsets.delete(canonicalId);
  else mockAlignmentOffsets.set(canonicalId, offset);
  return mockErgAlignment(canonicalId);
}
