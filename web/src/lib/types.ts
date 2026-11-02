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

export interface NextARace {
  name: string;
  date: string;
  days_to_go: number;
  taper: boolean;
}

export interface Today {
  date: string;
  generated_at: string;
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
  next_a_race: NextARace | null;
}

export interface SyncSourceStatus {
  source: string;
  cursor?: string | null;
  last_attempt_at?: string | null;
  last_success_at: string | null;
  last_error: string | null;
  token_expires_at?: string | null;
}

export interface SyncResult {
  source: string;
  error?: string;
  skipped?: string;
  [key: string]: unknown;
}

// --- Workouts (session 4) ---------------------------------------------------

export type WorkoutCategory = "erg" | "on_water" | "other";

export interface ActivityStrain {
  activity_id: number;
  value: number | null;
  band: StrainBand;
  components?: unknown[];
  explanation?: string;
}

export interface WorkoutListItem {
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
  category: WorkoutCategory;
  strain: ActivityStrain | null;
}

export interface WorkoutsPage {
  items: WorkoutListItem[];
  next_cursor: string | null;
}

export interface ZoneRow {
  zone: string;
  hr_pct_lo: number;
  hr_pct_hi: number | null;
  hr_lo: number | null;
  hr_hi: number | null;
  power_pct_lo: number;
  power_pct_hi: number | null;
  power_lo: number | null;
  power_hi: number | null;
}

export interface TrainingZones {
  zones: ZoneRow[];
  note: string;
}

export interface Note {
  id: number;
  date: string;
  text: string;
  rpe: number | null;
  created_at: string;
}

export interface WorkoutDetail extends WorkoutListItem {
  intervals: unknown | null;
  local_date: string | null;
  zones: TrainingZones;
  hr_zone: string | null;
  note: Note | null;
}

export interface Stroke {
  id: number;
  activity_id: number;
  seq: number;
  interval_index: number | null;
  t: number;
  distance: number | null;
  pace_500m: number | null;
  watts: number | null;
  stroke_rate: number | null;
  hr: number | null;
  distance_cum: number | null;
  t_cum: number;
}

export interface TechniqueMetric {
  value: number | null;
  band: string;
  components: unknown[];
  explanation: string;
}

export interface ErgTechnique {
  split_consistency: TechniqueMetric;
  watts_per_stroke: TechniqueMetric;
  rate_power_slope: TechniqueMetric;
  fade: TechniqueMetric;
}

export interface IntervalSummary {
  distance_m: number | null;
  duration_s: number | null;
  avg_split_500m: number | null;
  avg_stroke_rate: number | null;
  avg_watts: number | null;
  avg_hr: number | null;
  drift_vs_rep1_pct: number | null;
}

export interface ErgStrokesResponse {
  activity_id: number;
  strokes: Stroke[];
  stroke_count: number;
  returned_stroke_count: number;
  technique_by_interval: Record<string, ErgTechnique>;
  interval_summary: Record<string, IntervalSummary>;
  time_in_zone_by_interval: Record<string, Record<string, number> | null>;
}

// --- Trends / Body (session 4) ----------------------------------------------

export type TrendMetric =
  | "recovery"
  | "hrv_rmssd"
  | "resting_hr"
  | "sleep_score"
  | "strain"
  | "load_acr"
  | "weight"
  | "w_per_kg"
  | "predicted_2k";

export interface TrendPoint {
  date: string;
  value: number | null;
  acute_7d?: number;
  chronic_42d?: number;
  form?: number;
  smoothed?: number | null;
  activity_id?: number;
}

// --- Interactive series (session 8) -----------------------------------------

export interface SeriesPoint {
  date: string;
  value: number;
  value_min: number;
  value_max: number;
  acute_7d?: number;
  chronic_42d?: number;
  form?: number;
  smoothed?: number | null;
  /** Only on w_per_kg/predicted_2k — lets tapping a point open that workout (spec #4). */
  activity_id?: number;
}

export interface SeriesForMetric {
  points: SeriesPoint[];
  raw_count: number;
  returned_count: number;
}

export interface SeriesResponse {
  series: Record<string, SeriesForMetric>;
}

export const ZONE_NAMES = ["UT2", "UT1", "AT", "TR", "AN"] as const;
export type ZoneName = (typeof ZONE_NAMES)[number];

export interface VolumeWeek {
  week_start: string;
  zones: Record<ZoneName, number>;
  estimated: boolean;
}

export interface BodyCompReading {
  id: number;
  source: string;
  external_id: string;
  ts: string;
  weight_kg: number | null;
  fat_pct: number | null;
  fat_kg: number | null;
  muscle_kg: number | null;
  bone_kg: number | null;
  hydration_kg: number | null;
}

export interface PbEntry {
  activity_id: number;
  date: string | null;
  distance_m: number | null;
  duration_s: number | null;
  pace_s_per_500: number | null;
}

export type PersonalBests = Record<string, PbEntry | null>;

// --- Settings (session 4) ---------------------------------------------------

export interface Settings {
  zones: { hr_pct: Record<string, number>; power_pct: Record<string, number> };
  trimp_exponent: number;
  srpe_to_trimp_scale: number;
  strain_log_a: number;
  load_acute_days: number;
  load_chronic_days: number;
  acr_bands: { undertraining: number; optimal_high: number; caution_high: number };
  max_hr: number | null;
  recovery_weights: Record<string, number>;
  recovery_green: number;
  recovery_yellow: number;
  sleep_need_seconds: number;
  min_hrv_nights_for_baseline: number;
  predict_lookback_days: number;
  strain_targets: Record<string, [number, number]>;
  zone_mode: "hr" | "power";
  units: "metric" | "imperial";
  garmin_key_expires_on: string | null;
}

// --- Coach (session 5) -------------------------------------------------------

export type MessageBlock =
  | { type: "text"; text: string }
  | { type: "tool_call"; id: string; name: string; input: Record<string, unknown> }
  | { type: "tool_result"; id: string; output: unknown; is_error: boolean };

export interface UsageTokens {
  input_tokens: number;
  output_tokens: number;
  cache_creation_input_tokens: number;
  cache_read_input_tokens: number;
}

export interface CoachMessageRow {
  id: number;
  role: "user" | "assistant";
  blocks: MessageBlock[];
  provider: string | null;
  model: string | null;
  usage: UsageTokens | null;
  cost_usd: number | null;
  created_at: string;
}

export interface ConversationUsage extends UsageTokens {
  cost_usd: number;
}

export interface CoachConversation {
  id: number;
  title: string | null;
  created_at: string;
  updated_at: string;
  usage: ConversationUsage;
}

export interface CoachConversationDetail extends CoachConversation {
  messages: CoachMessageRow[];
}

// SSE events as emitted by POST /api/coach/conversations/{id}/messages — one per `data:` line.
export type CoachEvent =
  | { type: "text"; text: string }
  | { type: "tool_call"; id: string; name: string; input: Record<string, unknown>; label: string }
  | { type: "tool_result"; id: string; output: unknown; is_error: boolean }
  | { type: "usage"; usage: UsageTokens; cost_usd: number | null; daily_spend_usd: number; daily_cap_usd: number | null }
  | { type: "done"; stop_reason: string | null }
  | { type: "error"; message: string }
  | { type: "provider_unavailable"; message: string; can_switch_to: string }
  | { type: "cap_reached"; daily_spend_usd: number; daily_cap_usd: number };

export type CoachProviderName = "anthropic" | "ollama";

export interface ModelPrice {
  input?: number;
  output?: number;
  cache_write?: number;
  cache_read?: number;
}

export interface CoachSettings {
  provider: CoachProviderName;
  anthropic_model: string | null;
  ollama_base_url: string | null;
  ollama_model: string | null;
  daily_cap_usd: number | null;
  prices: Record<string, ModelPrice>;
  anthropic_key: { configured: boolean; last4: string | null };
}

export interface CoachModel {
  id: string;
  display_name: string;
}

export interface DeviceToken {
  id: number;
  name: string;
  created_at: string;
  last_used_at: string | null;
}

export interface MemoryFact {
  ref: string;
  kind: "fact";
  category: string;
  text: string;
  valid_until: string | null;
  created_at: string;
  expired: boolean;
}

export interface MemoryEvent {
  ref: string;
  kind: "event";
  name: string;
  date: string;
  type: string;
  distance: string | null;
  boat_class: string | null;
  priority: string | null;
  goal_time: string | null;
  result: string | null;
  days_to_go: number;
}

export interface MemoryGoal {
  ref: string;
  kind: "goal";
  text: string;
  target_date: string | null;
  status: "active" | "done" | "abandoned";
}

export interface MemoryListing {
  facts: MemoryFact[];
  events: MemoryEvent[];
  goals: MemoryGoal[];
}
