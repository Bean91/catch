// Session 20 mock data for ?mock=1 — GPS track, on-water metrics, weather and routes. Kept out
// of mock.ts (already 2.6K lines). The browser holds no analytics math (matching Session 19's
// rule): these are canned *server responses*, not calculations the app would do itself.
//
// Mock on-water workouts (canonical ids 1, 6, 11, 16, 21, ...) rotate through states so every
// fallback is reachable: id 1 = full data, 6 = partial weather, 11 = weather not fetched yet,
// 16 = on-water with no GPS recorded, then it repeats.
import type {
  OnWaterResponse,
  RouteDetailData,
  RouteHistory,
  RouteRef,
  RouteSession,
  SplitRow,
  TrackData,
  TrackPoint,
  TrackResponse,
  WeatherResponse,
  WeatherSummary,
} from "./types";
import { mockWorkoutDetail } from "./mock";

const CENTER = { lat: 45.0, lon: -73.0 };
const TOTAL_S = 2500;
const TOTAL_M = 7700;

function kOf(id: number): number {
  return Math.floor((id - 1) / 5) % 4;
}

function hasGps(id: number): boolean {
  const w = mockWorkoutDetail(id);
  return w.category === "on_water" && kOf(id) !== 3;
}

function loop(n: number, scale = 1): TrackPoint[] {
  const pts: TrackPoint[] = [];
  for (let i = 0; i < n; i++) {
    const t = i / (n - 1);
    const a = t * 2 * Math.PI;
    const speed = 3.1 + 0.5 * Math.sin(t * 8 * Math.PI);
    pts.push({
      elapsed_s: Math.round(t * TOTAL_S),
      lat: CENTER.lat + 0.009 * scale * Math.sin(a),
      lon: CENTER.lon + 0.02 * scale * Math.cos(a) - 0.02 * scale,
      distance_m: t * TOTAL_M,
      speed_mps: speed,
      provider_speed_mps: speed + 0.05,
      pace_unit: "s_per_500m",
      pace: 500 / speed,
      hr: Math.round(146 + 12 * Math.sin(t * 6 * Math.PI) + t * 8),
      elevation_m: null,
      segment: 0,
    });
  }
  return pts;
}

export function mockTrack(id: number, points = 600): TrackResponse {
  const w = mockWorkoutDetail(id);
  if (w.category !== "on_water") return { has_track: false, reason: "no_gps_recorded", message: "No GPS track was recorded for this activity." };
  if (!hasGps(id)) return { has_track: false, reason: "not_processed", message: "No GPS data has been read for this activity (no FIT file synced yet)." };
  const pts = loop(Math.min(Math.max(points, 50), 600), 1 + (kOf(id) === 1 ? 0.04 : 0));
  const lats = pts.map((p) => p.lat);
  const lons = pts.map((p) => p.lon);
  const data: TrackData = {
    has_track: true,
    activity_id: 1000 + id,
    sport_family: "rowing",
    pace_unit: "s_per_500m",
    points: pts,
    returned_count: pts.length,
    accepted_count: 740,
    bounds: { min_lat: Math.min(...lats), max_lat: Math.max(...lats), min_lon: Math.min(...lons), max_lon: Math.max(...lons) },
    start: { lat: pts[0].lat, lon: pts[0].lon },
    end: { lat: pts[pts.length - 1].lat, lon: pts[pts.length - 1].lon },
    has_elevation: false,
    has_hr: true,
    filter_report: {
      points_in: 745, dropped_no_fix: 3, dropped_duplicate_time: 1, dropped_out_of_order: 0, dropped_jump: 1,
      reanchored: 0, gaps: 0, gap_seconds: 0, ceiling_mps: 10, gap_threshold_s: 35, records_total: 748, records_without_fix: 3, accuracy_reported: false,
    },
    provenance: {
      track: "Garmin FIT position fixes, stored as recorded",
      speed_pace_distance: "gps_derived",
      elevation_hr: "provider",
    },
  };
  return data;
}

function fig(value: number | null, source: "gps_derived" | "provider", method: string) {
  return { value, source, method };
}

export function mockOnWater(id: number, splitM = 500): OnWaterResponse {
  const w = mockWorkoutDetail(id);
  const detection = { kind: w.category === "on_water" ? ("on_water" as const) : ("erg" as const), basis: "garmin_type", category: w.category };
  if (!hasGps(id)) {
    return {
      has_track: false,
      reason: w.category === "on_water" ? "not_processed" : "no_gps_recorded",
      message: w.category === "on_water" ? "No GPS data has been read for this activity (no FIT file synced yet)." : "No GPS track was recorded for this activity.",
      detection,
    };
  }
  const n = Math.ceil(TOTAL_M / splitM);
  const splits: SplitRow[] = Array.from({ length: n }, (_, i) => {
    const partial = i === n - 1 && TOTAL_M % splitM !== 0;
    const dist = partial ? TOTAL_M - i * splitM : splitM;
    const speed = 3.1 + 0.35 * Math.sin(i * 0.9);
    return {
      index: i + 1, start_distance_m: i * splitM, distance_m: dist, start_s: (i * splitM) / 3.1,
      time_s: dist / speed, speed_mps: speed, avg_hr: 146 + (i % 5) * 3, partial, has_gap: false,
      pace: { unit: "s_per_500m", value: 500 / speed }, source: "gps_derived",
    };
  });
  return {
    has_track: true,
    activity_id: 1000 + id,
    sport_family: "rowing",
    detection,
    metrics: {
      distance_m: fig(7712, "gps_derived", "haversine sum over every in-segment pair; gaps excluded"),
      moving_distance_m: fig(7580, "gps_derived", "pairs at >= 0.5 m/s"),
      elapsed_s: fig(2510, "gps_derived", "last accepted fix minus first"),
      moving_s: fig(2438, "gps_derived", "sum of dt where pair speed >= 0.5 m/s"),
      stopped_s: fig(72, "gps_derived", "in-segment dt where pair speed below moving threshold"),
      gap_s: fig(0, "gps_derived", "time inside gaps, not counted anywhere"),
      avg_speed_mps: fig(3.109, "gps_derived", "moving distance / moving time"),
      avg_speed_elapsed_mps: fig(3.073, "gps_derived", "distance / elapsed time (the basis Garmin's own averageSpeed uses)"),
      peak_speed_mps: fig(3.9, "gps_derived", "best chord speed over >= 10 s"),
      provider: {
        distance_m: fig(7700, "provider", "garmin"),
        moving_s: fig(2501, "provider", "garmin"),
        elapsed_s: fig(2512, "provider", "garmin"),
        avg_speed_mps: fig(3.065, "provider", "garmin"),
        max_speed_mps: fig(4.1, "provider", "garmin"),
      },
      distance_delta_vs_provider_pct: 0.16,
      filter_report: mockTrack(id).has_track ? (mockTrack(id) as TrackData).filter_report : ({} as never),
    },
    pace: { unit: "s_per_500m", value: 500 / 3.109, source: "gps_derived", method: "from average moving speed" },
    splits: {
      split_m: splitM,
      splits,
      consistency: { cv_pct: 6.4, split_time_sd_s: 7.9, n_splits: Math.max(n - 1, 0), source: "gps_derived", method: "population CV of full, gap-free split speeds" },
      source: "gps_derived",
      method: "boundary time interpolated between fixes at each multiple of split_m",
    },
    laps: { usable: false, count: 1, rows: [], note: "Only one lap recorded — no lap or interval breakdown to show." },
    route: routeRefFor(id),
    weather: weatherBrief(id),
    environment_corrected: false,
    environment_note: "Speed and pace are raw GPS figures. They are not corrected for wind, current or water conditions.",
  };
}

const ATTRIBUTION =
  "Weather data by Open-Meteo.com (CC BY 4.0), based on ECMWF ERA5 / IFS reanalysis (contains modified Copernicus Climate Change Service information).";

function weatherSummary(partial: boolean): WeatherSummary {
  return {
    window_start: "2026-10-30T11:30:00+00:00",
    window_end: "2026-10-30T12:12:00+00:00",
    duration_s: 2520,
    temperature_c: { avg: partial ? null : 14.2, min: partial ? null : 13.9, max: partial ? null : 14.6 },
    humidity_pct: 58,
    wind: { speed_kmh: 18.4, speed_mps: 5.1, gust_max_kmh: 31.2, direction_from_deg: 292, direction_from_label: "WNW" },
    pressure_hpa: 1013.2,
    precipitation_mm: 0.0,
    condition: { code: 2, text: "Partly cloudy", codes_in_window: [{ code: 2, text: "Partly cloudy" }, { code: 3, text: "Overcast" }] },
    coverage: partial ? 0.67 : 1,
    core_coverage_min: partial ? 0 : 1,
    variable_coverage: { temperature: partial ? 0 : 1, wind_speed: 1, precipitation: 1 },
    provisional: partial,
    location_rounded: { lat: 45.0, lon: -73.0 },
    grid: [{ utc_date: "2026-10-30", lat: 45.04, lon: -73.04, elevation_m: 2 }],
  };
}

function weatherBrief(id: number) {
  const k = kOf(id);
  if (!hasGps(id) || k === 2) return null;
  const s = weatherSummary(k === 1);
  return {
    status: k === 1 ? "partial" : "ok",
    temperature_avg_c: s.temperature_c.avg,
    wind_speed_kmh: s.wind.speed_kmh,
    wind_direction_from_label: s.wind.direction_from_label,
    precipitation_mm: s.precipitation_mm,
    condition: s.condition.text,
  };
}

export function mockWeather(id: number): WeatherResponse {
  const base = { attribution: ATTRIBUTION, attribution_url: "https://open-meteo.com/" };
  if (!hasGps(id)) return { ...base, status: "no_gps", weather: null, reason: "not_processed", message: "No GPS data has been read for this activity (no FIT file synced yet)." };
  const k = kOf(id);
  if (k === 2) return { ...base, status: "not_fetched", weather: null, source: "provider_reanalysis", disclaimer: DISCLAIMER };
  return { ...base, status: k === 1 ? "partial" : "ok", weather: weatherSummary(k === 1), source: "provider_reanalysis", disclaimer: DISCLAIMER, fetched_at: "2026-11-10T09:00:00+00:00" };
}

const DISCLAIMER =
  "Gridded model/reanalysis data for the area (roughly 9-25 km cells), not a measurement taken at the water. Shown as context only — never as a performance correction.";

export function refreshMockWeather(id: number): WeatherResponse {
  const base = { attribution: ATTRIBUTION, attribution_url: "https://open-meteo.com/" };
  if (!hasGps(id)) return mockWeather(id);
  return { ...base, status: "ok", weather: weatherSummary(false), source: "provider_reanalysis", disclaimer: DISCLAIMER, fetched_at: new Date().toISOString() };
}

// --- routes ---------------------------------------------------------------------------------

const ROUTE_SESSION_IDS = [1, 6, 11, 21];
const routeState: { name: string | null; tags: string[] } = { name: null, tags: [] };
let pinnedOut = new Set<number>();

function routeRef(): RouteRef {
  return {
    id: 1,
    name: routeState.name,
    auto_label: "Westport · 7.7 km",
    display_name: routeState.name ?? "Westport · 7.7 km",
    name_is_manual: routeState.name != null,
    tags: routeState.tags,
    sport_family: "rowing",
    length_m: 7700,
    length_source: "gps_derived",
    n_sessions: ROUTE_SESSION_IDS.filter((i) => !pinnedOut.has(i)).length,
  };
}

function routeRefFor(id: number): RouteRef | null {
  return ROUTE_SESSION_IDS.includes(id) && !pinnedOut.has(id) ? { ...routeRef(), pinned: false } : null;
}

export function mockRoutes(): RouteRef[] {
  return [{ ...routeRef(), last_session: "2026-10-30T11:30:00+00:00" }];
}

export function mockRouteDetail(id: number): RouteDetailData {
  if (id !== 1) throw new Error("not found");
  const ref = loop(64).map((p) => [p.lat, p.lon] as [number, number]);
  return { ...routeRef(), reference: ref };
}

export function patchMockRoute(id: number, patch: { name?: string | null; tags?: string[] }): RouteDetailData {
  if (patch.name !== undefined) routeState.name = patch.name && patch.name.trim() ? patch.name.trim() : null;
  if (patch.tags !== undefined) routeState.tags = patch.tags;
  return mockRouteDetail(id);
}

export function putMockActivityRoute(id: number, body: { route_id?: number | null; unpin?: boolean; new_route?: boolean }): { route: RouteRef | null } {
  if (body.unpin) pinnedOut.delete(id);
  else if (body.route_id === null) pinnedOut = new Set([...pinnedOut, id]);
  return { route: routeRefFor(id) };
}

export function mockRouteHistory(routeId: number): RouteHistory {
  if (routeId !== 1) throw new Error("not found");
  const speeds = [3.02, 3.109, 3.24, 3.15];
  const sessions: RouteSession[] = ROUTE_SESSION_IDS.filter((i) => !pinnedOut.has(i)).map((cid, idx) => ({
    date: `2026-10-${String(30 - idx * 7).padStart(2, "0")}T11:30:00+00:00`,
    canonical_id: cid,
    activity_id: 1000 + cid,
    distance_m: 7700 + idx * 12,
    moving_s: 7700 / speeds[idx],
    elapsed_s: 7700 / speeds[idx] + 60,
    avg_speed_mps: speeds[idx],
    peak_speed_mps: speeds[idx] + 0.8,
    avg_hr: idx === 2 ? null : 148 + idx * 2,
    weather: weatherBrief(cid),
    pinned: false,
  }));
  const speedVals = sessions.map((s) => s.avg_speed_mps as number);
  const best = sessions.reduce((a, b) => ((b.avg_speed_mps ?? 0) > (a.avg_speed_mps ?? 0) ? b : a));
  const sorted = [...speedVals].sort((a, b) => a - b);
  const median = sorted.length % 2 ? sorted[(sorted.length - 1) / 2] : (sorted[sorted.length / 2 - 1] + sorted[sorted.length / 2]) / 2;
  const lo = sorted[0];
  const hi = sorted[sorted.length - 1];
  const bins = 5;
  const histogram = Array.from({ length: bins }, (_, i) => ({
    from: lo + ((hi - lo) / bins) * i,
    to: lo + ((hi - lo) / bins) * (i + 1),
    count: speedVals.filter((v) => (i === bins - 1 ? v >= lo + ((hi - lo) / bins) * i : v >= lo + ((hi - lo) / bins) * i && v < lo + ((hi - lo) / bins) * (i + 1))).length,
  }));
  return {
    route: { ...routeRef(), n_sessions: sessions.length },
    sessions,
    stats: {
      n_sessions: sessions.length,
      best,
      typical_avg_speed_mps: median,
      recent: sessions[0],
      recent_vs_typical_pct: ((sessions[0].avg_speed_mps as number) - median) / median * 100,
      speed_distribution: { min: lo, p25: sorted[0] + (sorted[1] - sorted[0]) * 0.75, median, p75: sorted[2] + (sorted[3] - sorted[2]) * 0.25, max: hi, n: sessions.length, histogram, basis: "each session's average moving speed" },
      hr: { n: 3, mean: 150, min: 148, max: 154 },
      weather_differences: [
        { metric: "wind speed (km/h)", best_session: 12.0, other_sessions_median: 18.4, difference: -6.4, kind: "observed_difference", note: "Observed provider data, not a correction. Wind direction relative to the course is not factored in, so this cannot say whether the wind helped or hurt." },
      ],
      caveats: [
        "Times are moving time on the same recorded course. They are not wind-, current- or water-corrected, and a session's structure (steady row, intervals, warm-up) is included.",
        "Weather beside each session is provider data for the area, shown for context only; it is not used to adjust any figure here.",
      ],
      source: "gps_derived",
    },
    confidence: "low",
    note: null,
    comparison: "Compared only because each session's track aligned with this route's reference course (matching start, end, length and coverage).",
  };
}
