// Mirrors catch/api/routes_analytics.py, routes_sync.py, routes_auth.py response shapes —
// dumped against the live DB/tests while building this, not guessed. Keep in sync by hand;
// there's no OpenAPI client generation step on this stack.

export type Band = "green" | "yellow" | "red" | "calibrating" | "insufficient_data";
export type StrainBand = "light" | "moderate" | "high" | "all_out" | "insufficient_data";
export type LoadBand = "undertraining" | "optimal" | "caution" | "high_risk" | "insufficient_data";

export interface ScoreComponent {
  metric?: string;
  [key: string]: unknown;
}

export interface Recovery {
  value: number | null;
  band: Band;
  components: ScoreComponent[];
  explanation: string;
}

export interface Strain {
  value: number | null;
  band: StrainBand;
  trimp_like?: number;
  components: ScoreComponent[];
  explanation: string;
}

export interface Load {
  value: number | null; // acute:chronic ratio
  band: LoadBand;
  components: { acute_7d: number; chronic_42d: number; form: number }[];
  explanation: string;
}

export interface SleepLastNight {
  seconds: number | null;
  score: number | null;
  need_seconds: number;
  deep_seconds: number | null;
  light_seconds: number | null;
  rem_seconds: number | null;
  awake_seconds: number | null;
}

export interface SparklinePoint {
  date: string;
  value: number | null;
}

export interface BaselineBand {
  baseline: number;
  low: number;
  high: number;
}

export interface VitalTrend {
  today: number | null;
  sparkline_14d: SparklinePoint[];
  baseline_band: BaselineBand | null;
}

export interface ErgPiece {
  id: number;
  source: string;
  external_id: string;
  type: string | null;
  start: string | null;
  duration: number | null;
  distance: number | null;
  avg_hr: number | null;
  max_hr: number | null;
  avg_power: number | null;
  calories: number | null;
  workout_type: string | null;
  drag_factor: number | null;
  stroke_rate: number | null;
  linked_activity_id: number | null;
  weight_kg: number | null;
  w_per_kg: number | null;
}

export interface Predicted2k {
  value: number | null; // predicted pace, seconds per 500m
  range?: [number, number];
  predicted_time_s?: number;
  band: "high" | "moderate" | "low" | "insufficient_data";
  components: unknown[];
  explanation: string;
}

export interface Today {
  date: string;
  recovery: Recovery | null;
  sleep_last_night: SleepLastNight | null;
  strain_today: Strain | null;
  strain_target_range: [number, number];
  load: Load | null;
  hrv: VitalTrend;
  resting_hr: VitalTrend;
  latest_erg: ErgPiece | null;
  predicted_2k: Predicted2k;
  recommendation: string;
}

export interface SyncSourceStatus {
  source: string;
  cursor?: string | null;
  last_attempt_at?: string | null;
  last_success_at: string | null;
  last_error: string | null;
}

export interface SyncResult {
  source: string;
  error?: string;
  skipped?: string;
  [key: string]: unknown;
}
