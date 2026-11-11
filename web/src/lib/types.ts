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
  /** Task Part A: non-exercise steps/active-kcal's own contribution to `value` — a separate
   * key, not one of `components` (those are per-canonical-workout and assume `canonical_id`
   * everywhere else they're read). */
  daily_activity?: { value: number; steps: number | null; active_kcal: number | null };
  /** Session 14 (see PLAN.md Part C): the cardio half of `value` (existing HR/power trimp,
   * log-saturated) and the muscular half (per-muscle-group AU, normalized against a 28-day
   * baseline, log-saturated) — summed together, then daily_activity added on top, to make
   * `value`. Shown as a split on the Today strain gauge. */
  cardio?: { value: number; trimp_like: number };
  muscular?: { value: number; total_normalized_au: number; explanation: string };
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
  /** The canonical id — navigate to /workouts/{canonical_id}, never {id}. */
  canonical_id: number;
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
  /** Task Part A.4: whole-day Garmin totals, for Today's small secondary steps/active-kcal
   * line — not the non-exercise-only figure inside strain_today's own `daily_activity` key. */
  daily_activity: { steps: number | null; active_kcal: number | null } | null;
  load: Load | null;
  /** Rowing-only load, parallel to `load`'s all-sport number (task Part B.3) — so cycling
   * volume never inflates the figure the athlete actually trains rowing against. */
  rowing_load: Load | null;
  hrv: VitalTrend;
  resting_hr: VitalTrend;
  latest_erg: ErgPiece | null;
  predicted_2k: Predicted2k;
  recommendation: string;
  next_a_race: NextARace | null;
  /** Session 13: calm, non-judgemental under-fuelling note (never a streak/warning) — same
   * shape as nutrition.week_summary's `under_fuelling`, over the trailing 7 days. */
  under_fuelling: UnderFuelling;
  /** Session 15 Part A: today's check-in (completed or not) + the niggle flag — riding on
   * GET /api/today rather than a separate call, so this and the coach/MCP side always agree. */
  checkin: TodayCheckin;
  /** Session 15 Part B: null only when no daily_scores row exists at all for today (e.g. a
   * fresh instance that's never synced) — otherwise always present, usually `level: "none"`. */
  illness: IllnessState | null;
}

// --- Session 15 Part A: morning check-in ------------------------------------------------

export interface CheckIn {
  date: string;
  soreness: number | null; // 1-5, 1 = none/fine
  stress: number | null; // 1-5, 1 = low
  mood: number | null; // 1-5, 1 = low
  sleep_quality: number | null; // 1-5, 1 = poor
  niggle_area: string | null;
  niggle_severity: number | null; // 1-3
  note: string | null;
}

export interface TodayCheckinStatus {
  date: string;
  completed: boolean;
  checkin: CheckIn | null;
}

export interface TodayCheckin {
  completed: boolean;
  today: CheckIn | null;
  niggle_area: string | null;
  niggle_severity: number | null;
  niggle_streak_days: number;
  niggle_flag: boolean;
}

// --- Session 15 Part B: illness early warning -------------------------------------------

export type IllnessLevel = "none" | "watch" | "likely";
export type IllnessSignalName = "resting_hr" | "hrv" | "respiration" | "checkin";

export interface IllnessSignal {
  z: number | null;
  baseline: number | null;
  deviated: boolean;
}

export interface IllnessState {
  level: IllnessLevel;
  deviated_count: number;
  signals: Record<IllnessSignalName, IllnessSignal>;
  explanation: string;
}

export type DismissReason = "alcohol" | "travel" | "late_night" | "vaccine" | "other";

export interface IllnessAck {
  date: string;
  first_flagged_at: string | null;
  dismissed: boolean;
  dismiss_reason: DismissReason | null;
  backtest_mark: "correct" | "incorrect" | null;
}

export interface IllnessBacktestEntry {
  date: string;
  level: IllnessLevel;
  deviated_count: number;
  explanation: string;
  dismissed: boolean;
  dismiss_reason: DismissReason | null;
  backtest_mark: "correct" | "incorrect" | null;
}

export interface IllnessBacktestResponse {
  flagged: IllnessBacktestEntry[];
  marked_count: number;
  precision: number | null;
}

// --- Session 15 Part C: erg test center --------------------------------------------------

export type ErgTestType = "500m" | "1000m" | "2000m" | "5000m" | "6000m" | "30min_r20" | "60min" | "custom";
export const ERG_TEST_TYPES: ErgTestType[] = ["500m", "1000m", "2000m", "5000m", "6000m", "30min_r20", "60min", "custom"];
export type PacingStyle = "even" | "fast_start_settle" | "negative_split";

export interface ErgTestSummary {
  // Session 17 (see PLAN.md — the task called itself "session 13") — "kind" distinguishes a
  // confirmed-test row (id in canonical_id) from a piece row (id in piece_id), since a
  // piece's canonical_id is the *containing* activity, not unique to the piece.
  kind: "test" | "piece";
  piece_id: number | null;
  canonical_id: number;
  activity_id: number | null;
  test_type: ErgTestType | null;
  title: string | null;
  date: string | null;
  distance_m: number | null;
  duration_s: number | null;
  avg_power: number | null;
  avg_stroke_rate: number | null;
  avg_hr: number | null;
}

// --- Session 17: pieces (a segment of a canonical activity) -----------------------------

export interface Piece {
  id: number;
  canonical_id: number;
  piece_type: ErgTestType;
  distance_m: number | null;
  duration_s: number | null;
  avg_split_s: number | null;
  avg_rate: number | null;
  avg_watts: number | null;
  drag_factor: number | null;
  splits: PieceSplitRow[];
  source: "manual" | "photo" | "concept2";
  window_activity_id: number | null;
  window_start_s: number | null;
  window_end_s: number | null;
  concept2_activity_id: number | null;
  time_in_zone: Record<ZoneName, number> | null;
  hr_recovery_bpm: number | null;
  notes: string | null;
  has_photo: boolean;
  created_at: string;
  /** Session 19: an interval piece's distance_m/duration_s are *work only*; rest is in
   * interval_summary. Totals and weighted averages always come from the server. */
  has_intervals: boolean;
  intervals: PieceInterval[];
  interval_summary: PieceIntervalSummary | null;
  interval_signature: string | null;
}

export type IntervalTarget = "distance" | "time";

export interface PieceInterval {
  /** Absent on a not-yet-saved row in the editor. */
  id?: number;
  position?: number;
  target_type: IntervalTarget;
  work_distance_m: number | null;
  work_duration_s: number | null;
  rest_duration_s: number | null;
  avg_split_s: number | null;
  avg_watts: number | null;
  avg_rate: number | null;
  avg_hr: number | null;
  max_hr: number | null;
  calories: number | null;
  notes: string | null;
  source?: "manual" | "concept2";
  /** Server-derived (stored split, or time/distance) — never computed in the browser. */
  split_s?: number | null;
}

export interface PieceIntervalSummary {
  count: number;
  complete_count: number;
  work_distance_m: number | null;
  work_duration_s: number | null;
  rest_duration_s: number | null;
  total_duration_s: number | null;
  avg_split_s: number | null;
  avg_watts: number | null;
  avg_rate: number | null;
  avg_hr: number | null;
  max_hr: number | null;
  calories: number | null;
}

export interface IntervalValidationIssue {
  index: number | null;
  field: string | null;
  message: string;
}

export interface IntervalValidation {
  ok: boolean;
  issues: IntervalValidationIssue[];
}

export interface IntervalsResult {
  saved: boolean;
  validation: IntervalValidation;
  piece: Piece;
}

export interface IntervalRepeatSpec {
  count: number;
  distance_m?: number;
  duration_s?: number;
  rest_s?: number;
}

export interface IntervalComparisonBucket {
  bucket_label: string;
  n_points: number;
  best: { date: string; value: number; avg_watts: number | null; avg_rate: number | null; avg_hr: number | null } | null;
  typical: { value: number } | null;
  recent: { date: string; value: number; avg_watts: number | null; avg_rate: number | null; avg_hr: number | null } | null;
  delta_vs_typical_pct: number | null;
  confidence: "insufficient_data" | "low" | "medium" | "high";
  note: string | null;
}

export interface PieceSplitRow {
  split_index: number;
  distance_m: number | null;
  split_s: number | null;
  rate: number | null;
  watts: number | null;
  hr: number | null;
  hr_source?: "typed" | "derived" | "concept2" | null;
}

export interface PieceValidationIssue {
  split_index: number | null;
  field: string;
  message: string;
}

export interface PieceValidation {
  ok: boolean;
  issues: PieceValidationIssue[];
}

export interface CreatePieceResult {
  piece: Piece | null;
  validation: PieceValidation;
}

export interface PiecePhotoEstimate {
  splits: PieceSplitRow[];
  distance_m: number | null;
  duration_s: number | null;
  avg_split_s: number | null;
  avg_rate: number | null;
  avg_watts: number | null;
  drag_factor: number | null;
  validation: PieceValidation;
  notes: string;
  cost_usd: number;
}

export interface PieceTestDetail {
  activity: WorkoutDetail;
  piece: Piece;
  test_type: ErgTestType;
  plan: PacingPlan | null;
  pacing_analysis: PacingAnalysis | null;
  compare_to_earlier: ErgTestSummary | null;
  w_per_kg: number | null;
}

export interface ErgTestCandidate {
  canonical_id: number;
  activity_id: number;
  suggested_test_type: ErgTestType;
  title: string | null;
  date: string | null;
  distance_m: number | null;
  duration_s: number | null;
  avg_stroke_rate: number | null;
}

export interface PacingPlanSplit {
  split_index: number;
  distance_m: number;
  target_split_s: number;
  target_cum_s: number;
}

export interface PacingPlan {
  style: PacingStyle;
  distance_m: number;
  goal_time_s: number;
  rate_hint: number | null;
  splits: PacingPlanSplit[];
  explanation: string;
  test_type?: ErgTestType;
}

export interface ActualSplit {
  split_index: number;
  distance_m: number;
  actual_split_s: number | null;
  actual_cum_s: number | null;
}

export interface PacingVsPlanRow {
  split_index: number;
  actual_s: number;
  target_s: number;
  delta_s: number;
}

export interface PacingAnalysis {
  splits: ActualSplit[];
  even_split_s: number | null;
  segments: { start: number | null; middle_1000: number | null; sprint: number | null };
  deviation_from_even_pct: number | null;
  worst_split_vs_even: { split_index: number; seconds_lost_vs_even: number } | null;
  vs_plan: PacingVsPlanRow[] | null;
}

export interface ErgTestDetail {
  activity: WorkoutDetail;
  test_type: ErgTestType | null;
  plan: PacingPlan | null;
  pacing_analysis: PacingAnalysis | null;
  compare_to_earlier: ErgTestSummary | null;
  w_per_kg: number | null;
}

export interface ProjectionResult {
  value: number | null;
  range: [number, number] | null;
  slope_s_per_day?: number;
  n_points?: number;
  explanation: string;
  inputs: { date: string; value: number }[];
  target_date: string;
  target_event: NextARace | null;
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

// --- Workouts (session 4; canonical activities + matching/editing, session 8/12) -------

export type WorkoutCategory = "erg" | "on_water" | "strength" | "other";
export type SportFamily = "cycling" | "rowing" | "running" | "strength" | "other";

export interface ActivityStrain {
  /** The canonical id this strain component belongs to (catch/sync/scoring.py keys its
   * per-session components by canonical_id, not a raw per-source activity id). */
  canonical_id: number;
  title?: string | null;
  value: number | null;
  band: StrainBand;
  components?: unknown[];
  explanation?: string;
}

/** One member source record of a canonical activity — catch/api/routes_activities.py's
 * `_source_summary`. `activity_id` here is a *raw* per-source Activity id (used by
 * GET /api/erg/{activity_id}/strokes and the Duplicates-review merge/split/not-duplicate
 * endpoints), never a canonical id. */
export interface ActivitySourceSummary {
  activity_id: number;
  source: string;
  external_id: string;
  provenance: string; // "garmin" | "peloton" | "concept2"
  type: string | null;
  origin: string | null; // "watch" | "peloton" | null
  hr_source_type: string | null; // "chest_strap" | "wrist" | null
  has_fit: boolean;
  has_strokes: boolean;
}

export interface ActivityZones {
  hr: Record<ZoneName, number> | null;
  power: Record<ZoneName, number> | null;
}

export interface ActivityOverrides {
  title?: string;
  sport_family?: SportFamily;
  notes?: string;
  rpe?: number;
  exclude_from_totals?: boolean;
  tags?: string[];
  /** Session 15 Part C — set alongside tags: ["test"] via the same PATCH, see erg_test.ts. */
  test_type?: ErgTestType;
}

export const EDITABLE_ACTIVITY_FIELDS = ["title", "sport_family", "notes", "rpe", "exclude_from_totals", "tags", "test_type"] as const;
export type EditableActivityField = (typeof EDITABLE_ACTIVITY_FIELDS)[number];

export interface WorkoutListItem {
  id: number; // canonical id
  sport_family: SportFamily;
  start: string | null;
  duration: number | null;
  distance: number | null;
  avg_hr: number | null;
  max_hr: number | null;
  avg_power: number | null;
  avg_cadence: number | null;
  calories: number | null;
  title: string | null;
  strain_method: string | null;
  session_label: string | null;
  auto_trimmed_tail_s: number | null;
  category: WorkoutCategory;
  field_sources: Record<string, string>;
  zones: ActivityZones | null;
  notes: string | null;
  rpe: number | null;
  exclude_from_totals: boolean;
  tags: string[];
  test_type: ErgTestType | null;
  overrides: ActivityOverrides;
  sources: ActivitySourceSummary[];
  editable_fields: EditableActivityField[];
  edits_push_back_to_source: false;
  strain: ActivityStrain | null;
}

export interface WorkoutsPage {
  items: WorkoutListItem[];
  next_cursor: string | null;
}

// --- Duplicates review (task Part A.5) --------------------------------------

export interface DuplicatePairSide {
  activity_id: number;
  source: string;
  external_id: string;
  start: string | null;
  duration: number | null;
}

export interface DuplicatePair {
  a: DuplicatePairSide;
  b: DuplicatePairSide;
  score: number;
  hard_block: boolean;
  reasons: string[];
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
  local_date: string | null;
  /** Zone *boundaries* (thresholds), as opposed to WorkoutListItem.zones' per-sample zone
   * *seconds* — these are two different things with similarly-named fields; don't confuse
   * them. Mirrors GET /api/activities/{id}'s split naming exactly. */
  zones_config: TrainingZones;
  hr_zone: string | null;
  day_note: Note | null;
  has_samples: boolean;
  /** Session 19: pieces ride along on the detail payload; a Concept2 member that reported
   * real intervals is flagged so the page can offer the on-demand import. */
  pieces?: Piece[];
  concept2_interval_activity_id?: number | null;
  /** Session 14 (see PLAN.md Part C.4) — present only when category === "strength": this
   * session's own logged/draft sets, and its per-muscle-group raw AU breakdown (the same
   * cache catch/sync/gym.py writes onto the canonical). */
  strength_sets?: StrengthSetRow[];
  muscular_by_muscle?: Record<string, number> | null;
}

// --- Per-activity HR/power/cadence samples (task Part E.8) -------------------

export interface LapMarker {
  offset_s: number;
  duration_s: number;
}

export interface HrRecovery {
  session_end: number | null;
  per_lap: { offset_s: number; recovery_bpm: number | null }[];
}

export interface SamplePoint {
  elapsed_s: number;
  hr: number | null;
  power: number | null;
  cadence: number | null;
}

export type ActivitySamplesResponse =
  | { has_data: false; reason: string }
  | {
      has_data: true;
      canonical_id: number;
      n_samples: number;
      usable_n_samples: number;
      trimmed_tail_s: number;
      max_hr_setting: number | null;
      avg_hr: number | null;
      max_hr_observed: number | null;
      min_hr_observed: number | null;
      zones: ActivityZones | null;
      zones_config: TrainingZones;
      session_label: string | null;
      laps: LapMarker[];
      hr_recovery: HrRecovery;
      points: SamplePoint[];
      returned_count: number;
      raw_count: number;
    };

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
  | "predicted_2k"
  // Session 15 Part A.3.
  | "checkin_soreness"
  | "checkin_stress"
  | "checkin_mood"
  | "checkin_sleep_quality";

export interface TrendPoint {
  date: string;
  value: number | null;
  acute_7d?: number;
  chronic_42d?: number;
  form?: number;
  smoothed?: number | null;
  /** A canonical id (w_per_kg/predicted_2k only) — navigate to /workouts/{activity_id}. */
  activity_id?: number;
  /** weight only — which source this day's resolved value came from (task Part D.2). */
  source?: string | null;
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
  /** Only on w_per_kg/predicted_2k — lets tapping a point open that workout (spec #4). A
   * canonical id, like TrendPoint's. */
  activity_id?: number;
  /** weight only — which source this day's resolved value came from (task Part D.2). */
  source?: string | null;
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

// Session 8/12 (see PLAN.md Part D) — GET /api/body now returns one priority-resolved row
// per calendar day (never averaged across scales) instead of raw interleaved source rows.
export interface BodyCompReading {
  date: string;
  weight: number | null;
  weight_source: string | null; // "withings" | "garmin" | "manual" | null
  fat_pct: number | null;
  fat_pct_source: string | null;
  muscle_kg: number | null;
  muscle_kg_source: string | null;
  bone_kg: number | null;
  hydration_kg: number | null;
  sources: string[];
}

export interface PbEntry {
  /** A canonical id — navigate to /workouts/{activity_id}. */
  activity_id: number;
  /** Session 17 — set when this PB came from a piece rather than a standalone Concept2
   * result; navigate to /tests/piece/{piece_id} instead of /workouts/{activity_id}. */
  piece_id: number | null;
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
  // --- Session 8/12 (see PLAN.md): matching/editing/body-comp/samples settings ---
  field_priority: {
    power: string[];
    cadence: string[];
    title: string[];
    distance_indoor_bike: string[];
  };
  ftp_watts: number | null;
  body_comp_priority: {
    weight: string[];
    fat_pct: string[];
    muscle_kg: string[];
  };
  min_zone_minutes: number;
  min_zone_pct: number;
  auto_trim_enabled: boolean;
  auto_trim_min_idle_s: number;
  // --- Session 13 (see PLAN.md Part A) ---
  daily_activity_strain_cap: number;
  daily_activity_strain_weight: number;
  // --- Session 16 (see PLAN.md Part A) — push notification prefs ---
  notifications: {
    quiet_hours_start: string;
    quiet_hours_end: string;
    types: {
      morning_brief: boolean;
      illness: boolean;
      garmin_key_expiring: boolean;
      sync_broken: boolean;
      test_reminder: boolean;
    };
  };
}

// --- Session 16 (see PLAN.md Part A/B) ---

export interface PushSubscriptionRow {
  id: number;
  endpoint: string;
  label: string | null;
  created_at: string;
  last_seen_at: string;
}

export interface NotificationLogRow {
  id: number;
  type: string;
  title: string;
  body: string;
  deep_link: string | null;
  sent_at: string;
  device_count: number;
}

export interface SourceStatus {
  source: string;
  last_success_at: string | null;
  last_attempt_at: string | null;
  last_error: string | null;
  consecutive_failures: number;
  token_expires_at: string | null;
}

export interface BackupStatus {
  last_backup_at: string | null;
  backup_size_bytes: number | null;
  integrity_ok: boolean | null;
  remote_copied_at: string | null;
  remote_ok: boolean | null;
}

export interface AppStatus {
  sources: SourceStatus[];
  garmin_key_expires_on: string | null;
  backup: BackupStatus | null;
  disk_free_bytes: number;
  disk_total_bytes: number;
  db_size_bytes: number;
  uptime_seconds: number;
  build: { build: string; commit: string } | null;
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

// --- Nutrition (session 13) --------------------------------------------------

export type Meal = "breakfast" | "lunch" | "dinner" | "snack" | "pre_workout" | "post_workout";
export const MEALS: Meal[] = ["breakfast", "lunch", "dinner", "snack", "pre_workout", "post_workout"];

export interface Food {
  id: number;
  source: string; // "off" | "usda" | "manual" | "estimate"
  barcode: string | null;
  name: string;
  brand: string | null;
  serving_size: number | null;
  serving_unit: string | null;
  kcal_100g: number | null;
  protein_100g: number | null;
  carbs_100g: number | null;
  fat_100g: number | null;
  fiber_100g: number | null;
  sugar_100g: number | null;
  sodium_100g: number | null;
  verified: boolean;
}

export type BarcodeLookupResult = ({ found: true } & Food) | { found: false; barcode: string };

export interface FoodLogRow {
  id: number;
  ts: string;
  meal: Meal;
  food_id: number;
  food_name: string | null;
  food_brand: string | null;
  quantity: number;
  unit: "g" | "serving";
  estimated: boolean;
  kcal: number | null;
  protein: number | null;
  carbs: number | null;
  fat: number | null;
  fiber: number | null;
  sugar: number | null;
  sodium: number | null;
}

export interface MyFoodRow extends Food {
  my_food_id: number;
  label: string | null;
}

export interface SavedMealItem {
  food_id: number;
  quantity: number;
  unit: "g" | "serving";
}

export interface SavedMealRow {
  id: number;
  name: string;
  items: SavedMealItem[];
  created_at: string;
}

export type TrainingTier = "rest" | "moderate" | "double_day" | "pre_race";

export interface NutritionTargetsComputed {
  protein_g: number | null;
  carb_g: number | null;
  fat_g: number | null;
  kcal_target: number | null;
  tier: TrainingTier;
  explanation: string;
  weight_source: string | null;
}

export interface NutritionTargetSettings {
  protein_g_per_kg: number;
  carb_g_per_kg_rest: number;
  carb_g_per_kg_moderate: number;
  carb_g_per_kg_double_day: number;
  carb_g_per_kg_pre_race: number;
  kcal_target_source: "garmin_total" | "manual";
  manual_kcal_target: number | null;
}

export interface NutritionTargetsResponse {
  settings: NutritionTargetSettings;
  today: NutritionTargetsComputed;
}

export interface MacroTotals {
  kcal: number;
  protein: number;
  carbs: number;
  fat: number;
  fiber: number;
  sugar: number;
  sodium: number;
}

export interface DaySummary {
  date: string;
  intake: MacroTotals;
  targets: NutritionTargetsComputed;
  expenditure_kcal: number | null;
  logs: FoodLogRow[];
}

export interface UnderFuelling {
  flag: boolean;
  logged_days: number;
  avg_deficit_kcal?: number;
  explanation: string;
}

export interface WeekDaySummary {
  date: string;
  intake_kcal: number;
  protein: number;
  expenditure_kcal: number | null;
  has_log: boolean;
}

export interface WeekSummary {
  days: WeekDaySummary[];
  under_fuelling: UnderFuelling;
}

export interface PhotoEstimateItem {
  name: string;
  quantity_description: string;
  kcal: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
}

export interface PhotoEstimateResult {
  items: PhotoEstimateItem[];
  notes: string;
  cost_usd: number;
}

// --- Session 14 (see PLAN.md): gym logger -------------------------------------------------

export type EquipmentType =
  | "barbell"
  | "dumbbell"
  | "kettlebell"
  | "machine_plate"
  | "machine_selectorized"
  | "smith"
  | "cable"
  | "bodyweight"
  | "weighted"
  | "assisted"
  | "band"
  | "other";

export type MovementPattern =
  | "squat"
  | "hinge"
  | "lunge"
  | "push_horizontal"
  | "push_vertical"
  | "pull_horizontal"
  | "pull_vertical"
  | "carry"
  | "core"
  | "other";

export type SetType = "warmup" | "working" | "drop" | "failure" | "amrap";

export interface Exercise {
  id: number;
  external_id: string | null;
  name: string;
  default_equipment_type: EquipmentType;
  movement_pattern: MovementPattern;
  unilateral: boolean;
  primary_muscles: string[];
  secondary_muscles: string[];
  custom: boolean;
}

export interface GymStation {
  id: number;
  gym_id: number;
  name: string;
  equipment_type: EquipmentType;
  config: {
    bar_weight_kg?: number;
    base_weight_kg?: number;
    stack_kg_per_increment?: number;
    pulley_multiplier?: number;
    dual_stack?: boolean;
    default_attachment?: string;
  };
}

export interface GymRow {
  id: number;
  name: string;
}

/** The shape both the local offline queue (gymDb.ts) and `POST /api/gym/sessions/sync` use —
 * every field the equipment math needs is here so a set can be computed/displayed before the
 * server has ever seen it. */
export interface StrengthSetInput {
  client_id: string;
  exercise_id: number;
  gym_station_id?: number | null;
  seq: number;
  superset_group?: number | null;
  set_type: SetType;
  reps: number;
  side?: "left" | "right" | null;
  tempo?: string | null;
  rir?: number | null;
  rpe?: number | null;
  equipment_type: EquipmentType;
  load_kg?: number | null;
  bar_weight_kg?: number | null;
  pulley_multiplier?: number | null;
  added_weight_kg?: number | null;
  assistance_kg?: number | null;
  band_tag?: string | null;
  notes?: string | null;
  created_at?: string;
}

export interface StrengthSetRow extends StrengthSetInput {
  effective_load_kg: number | null;
  load_is_estimated: boolean;
  load_note?: string | null;
  bodyweight_kg_used: number | null;
  is_rep_pr: boolean;
  is_e1rm_pr: boolean;
  muscular_au: number | null;
  source: "catch" | "garmin_draft";
  is_confirmed: boolean;
}

export interface StrengthTemplateItem {
  exercise_id: number;
  target_sets?: number;
  target_reps?: number;
  gym_station_id?: number | null;
}

export interface StrengthTemplate {
  id: number;
  name: string;
  items: StrengthTemplateItem[];
}

export interface RepeatWorkoutPlanItem {
  exercise_id: number;
  gym_station_id: number | null;
  equipment_type: EquipmentType;
  set_type: SetType;
  target_reps: number;
}

export interface MuscleReadiness {
  window_hours: number;
  by_muscle: Record<string, number>;
}

// --- Session 18: training intelligence & recommendations ---------------------------------

export type RecommendationType = "training_suggestion" | "recovery_suggestion" | "data_quality_warning" | "overload_warning";
export type ConfidenceLevel = "insufficient_data" | "low" | "medium" | "high";
export type RecommendationRating = "useful" | "not_useful";
export type RecommendationStatus = "active" | "dismissed" | "all";

export interface EvidenceItem {
  label: string;
  value: unknown;
  source: string;
}

export interface Recommendation {
  id: number;
  date: string;
  type: RecommendationType;
  confidence: ConfidenceLevel;
  title: string;
  body: string;
  evidence: EvidenceItem[];
  last_confirmed_on: string;
  dismissed: boolean;
  saved: boolean;
  rating: RecommendationRating | null;
  active: boolean;
}

export interface TrainingPhase {
  value: "base" | "build" | "taper" | null;
  inferred: boolean;
  explanation: string;
}

export interface TrainingProfile {
  phase: TrainingPhase;
  performance_trajectory: ProjectionResult;
  consistency_summary: { band: string; explanation: string } | null;
  strengths: { text: string; evidence: EvidenceItem[] }[];
  weaknesses: { text: string; evidence: EvidenceItem[] }[];
  recovery_context: { recovery: Recovery; load: Load; illness: IllnessState };
  confidence: ConfidenceLevel;
  explanation: string;
  // "When available" context — present but honestly flagged `logged: false` when the
  // athlete hasn't logged anything, never silently treated as zero.
  nutrition: { logged: false } | { logged: true; logged_days: number; under_fuelling: boolean };
  daily_activity: { logged: false } | { logged: true; steps: number; active_kcal: number | null };
  recent_note: string | null;
}

export interface PerformanceTrendPoint {
  date: string;
  value: number;
  avg_stroke_rate: number | null;
}

export interface PerformanceTrendBucket {
  bucket_label: ErgTestType;
  kind: "distance" | "duration";
  best: PerformanceTrendPoint | null;
  typical: { value: number } | null;
  recent: PerformanceTrendPoint | null;
  trend: ProjectionResult;
  rate_note: string | null;
  drag_note: string | null;
  n_points: number;
}

export interface PerformanceTrends {
  buckets: PerformanceTrendBucket[];
}

export interface TrainingDistributionWeek extends VolumeWeek {
  strength_minutes: number;
}

export interface TrainingDistribution {
  weeks: TrainingDistributionWeek[];
}

export interface TrainingConsistency {
  sessions_completed: number;
  sessions_target: number;
  minutes_completed: number;
  minutes_target: number;
  pct_of_target: number | null;
  rest_days: number;
  concentrated_block: boolean;
  distribution_pct: Record<ZoneName, number>;
  strength_sessions: number;
  band: string;
  explanation: string;
  confidence: ConfidenceLevel;
}

export interface TrainingInsight {
  id: string;
  title: string;
  body: string;
  confidence: ConfidenceLevel;
  evidence: EvidenceItem[];
  category: string;
}
