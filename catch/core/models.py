from __future__ import annotations

from datetime import date as date_, datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel, UniqueConstraint


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DailyWellness(SQLModel, table=True):
    __tablename__ = "daily_wellness"

    date: date_ = Field(primary_key=True)
    source: str = Field(default="garmin")
    resting_hr: Optional[int] = None
    hrv_rmssd: Optional[float] = None
    sleep_seconds: Optional[int] = None
    deep_sleep_seconds: Optional[int] = None
    light_sleep_seconds: Optional[int] = None
    rem_sleep_seconds: Optional[int] = None
    awake_sleep_seconds: Optional[int] = None
    sleep_score: Optional[int] = None
    stress: Optional[int] = None
    body_battery: Optional[int] = None
    spo2: Optional[float] = None
    respiration: Optional[float] = None
    # Session 15 (see PLAN.md Part B): sleep-period respiration (`DailySleepDTO.
    # averageRespirationValue`), distinct from `respiration` above, which is the whole-day
    # `v2/dailysummaries` figure already in use elsewhere — the illness early-warning signal
    # specifically wants the overnight value. No skin-temperature field exists anywhere in
    # Garmin's Personal API (checked docs/garmin-openapi.json — the only "skin"/"temp" hit is
    # an unrelated menstrual-cycle-tracking boolean), so that planned signal was dropped
    # rather than given a column with nothing to fill it.
    sleep_respiration_avg: Optional[float] = None
    # Session 13 (see PLAN.md Part A): `v2/dailysummaries`' `movement`/`calories`/
    # `intensityMinutes` nested objects — already present in the recorded fixture
    # (`tests/fixtures/garmin/usersummary_range.json`) but unused until now. `active_kcal`
    # and `bmr_kcal` are disjoint (Garmin's own split), `total_kcal` is their sum plus any
    # other contributors Garmin tracks, not derived here.
    steps: Optional[int] = None
    active_kcal: Optional[int] = None
    total_kcal: Optional[int] = None
    bmr_kcal: Optional[int] = None
    moderate_intensity_minutes: Optional[int] = None
    vigorous_intensity_minutes: Optional[int] = None
    floors_climbed: Optional[int] = None
    floors_descended: Optional[int] = None
    updated_at: datetime = Field(default_factory=_utcnow)


class Activity(SQLModel, table=True):
    """A single source record (one sync, one external id). Session 8/12 (see PLAN.md)
    generalised the old Garmin<->Concept2-only `linked_activity_id` dedup into the matching
    engine in `catch/analytics/matching.py`: every source record now belongs to exactly one
    `CanonicalActivity` (`canonical_id`), and totals/strain/load/charts read canonical
    activities only (`catch/sync/canonical.py`'s `resolve_canonical`). `linked_activity_id`
    is kept only so a pre-session-12 DB's existing Garmin<->Concept2 pairs can be migrated
    into canonicals once (`catch/core/db.py`'s `_migrate_linked_activities_to_canonical`) —
    no code after that migration reads it."""

    __tablename__ = "activities"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_activity_source_external_id"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    source: str
    external_id: str
    type: Optional[str] = None
    start: Optional[datetime] = None
    duration: Optional[float] = None
    distance: Optional[float] = None
    avg_hr: Optional[float] = None
    max_hr: Optional[float] = None
    avg_power: Optional[float] = None
    avg_cadence: Optional[float] = None
    calories: Optional[float] = None
    # "chest_strap" | "wrist" | None (unknown) — from FIT device_info's local_device_type
    # ("heart_rate" ANT+ strap vs "whr" wrist-optical) for Garmin, or "chest_strap" assumed
    # for any Concept2 result with HR (a PM5 only logs HR from a paired ANT+ strap, never a
    # wrist sensor — documented assumption, no PM5-side wrist-HR capability exists to confuse
    # it with). Drives the HR field-priority rule (task Part A.3).
    hr_source_type: Optional[str] = None
    # [{"offset_s", "duration_s"}, ...] from FIT lap messages (Part E.8's lap markers) —
    # symmetric with intervals_json, which is Concept2's equivalent.
    laps_json: Optional[str] = None
    # The source's own native title, where one exists — Garmin's `activityName` (set at
    # upsert time from the summary JSON, since raw_json isn't parsed again later). Used as
    # the canonical's title only when it isn't Garmin's generic per-type label (e.g. "Indoor
    # Cycling") — task Part B.2's "keep the class name ... as the default title" needs a real
    # Peloton class name, not Garmin's own generic fallback text, to actually be useful.
    title_hint: Optional[str] = None
    # Session 13 (see PLAN.md Part A): Garmin's `SummarizedActivityDTO.steps`/`bmrCalories` —
    # used to subtract this activity's own steps/active-kcal out of the day's Garmin wellness
    # totals so non-exercise daily-activity strain never double-counts a logged workout.
    # `calories` (already stored) is the activity's total including BMR; active kcal for this
    # purpose is `calories - bmr_kcal`. Backfilled for pre-session-13 rows from `raw_json`
    # (`catch/core/db.py`'s `_migrate_garmin_activity_fields`) rather than a re-download.
    steps: Optional[int] = None
    bmr_kcal: Optional[float] = None
    raw_json: Optional[str] = None
    fit_path: Optional[str] = None
    # Concept2-specific, left NULL for other sources.
    workout_type: Optional[str] = None
    drag_factor: Optional[int] = None
    stroke_rate: Optional[float] = None
    intervals_json: Optional[str] = None
    # Deprecated (session 2) — see the class docstring. Superseded by canonical_id.
    linked_activity_id: Optional[int] = Field(default=None, foreign_key="activities.id")
    # "cycling" | "rowing" | "running" | "strength" | "other" — the matching engine's broad
    # sport family, computed at upsert time (catch/analytics/matching.py's sport_family()).
    sport_family: Optional[str] = None
    # Device/app origin, where detectable — "watch" (default assumption for a Garmin record
    # with no contrary device_info) or "peloton" (see docs/peloton.md: a Peloton-pushed
    # Garmin activity's device_info.manufacturer is not "garmin"). None = not yet classified
    # (e.g. Concept2, which has no device_info concept at all).
    origin: Optional[str] = None
    canonical_id: Optional[int] = Field(default=None, foreign_key="canonical_activities.id")
    updated_at: datetime = Field(default_factory=_utcnow)


class CanonicalActivity(SQLModel, table=True):
    """The one thing Trends/Today/PBs/volume/coach/MCP ever read for "an activity" — owns
    1..n `Activity` source records (`Activity.canonical_id`). Resolved fields are cached here
    by `catch/sync/canonical.py`'s `resolve_canonical` (field-priority merge across sources,
    user overrides layered on top) rather than recomputed per request — matches
    `daily_scores`' existing cache-after-write pattern (`catch/sync/scoring.py`) rather than
    introducing a second caching strategy."""

    __tablename__ = "canonical_activities"

    id: Optional[int] = Field(default=None, primary_key=True)
    sport_family: Optional[str] = None
    start: Optional[datetime] = None
    duration: Optional[float] = None
    distance: Optional[float] = None
    avg_hr: Optional[float] = None
    max_hr: Optional[float] = None
    avg_power: Optional[float] = None
    avg_cadence: Optional[float] = None
    calories: Optional[float] = None
    # Resolved display title — either a Catch-side override or an auto-title (part C.3).
    title: Optional[str] = None
    # "erg" | "on_water" | "other" (catch/analytics/matching.py's category_for_canonical) —
    # persisted, not recomputed per request, specifically so GET /api/activities' category
    # filter can run entirely in SQL. It used to be computed in Python after the page's LIMIT
    # had already applied to a SQL-level sport_family filter (erg and on_water share
    # sport_family=="rowing"), which could silently return short or empty pages — this
    # account's real backfill has 166 on_water vs. 118 erg sessions, so a page of 30
    # "rowing"-family rows landing mostly on the wrong side of that split was a real risk,
    # not a theoretical one. See PLAN.md's session 12 bug log.
    category: Optional[str] = None
    # {"power": "peloton:123", "cadence": "peloton:123", "hr": "garmin:456", ...} — which
    # source record each resolved metric came from, keyed by (source, external_id) as
    # "source:external_id". Shown next to each metric in workout detail.
    field_sources_json: Optional[str] = None
    # User (Catch-side) overrides, layered over the resolved source values and surviving
    # every re-sync — {"title": "...", "sport_family": "...", "notes": "...", "rpe": 7,
    # "exclude_from_totals": true, "tags": [...]}. A key's absence means "use source value."
    overrides_json: Optional[str] = None
    # Cached training-load / strain inputs for this one canonical activity (part E) — reused
    # by catch/sync/scoring.py's day_strain instead of recomputing per request.
    zones_json: Optional[str] = None
    strain_trimp: Optional[float] = None
    # "trimp_samples" | "cycling_tss" | "cycling_tss_estimated_ftp" | None — which strain
    # method produced strain_trimp (Part B.3's power-vs-HR branch), surfaced in the UI so an
    # estimated FTP shows a visible "estimated" flag rather than a silently approximate number.
    strain_method: Optional[str] = None
    session_label: Optional[str] = None
    auto_trimmed_tail_s: Optional[float] = None
    # Session 14 (see PLAN.md Part C): raw muscular-load AU (not 0-21 — see
    # catch/analytics/strength.py) for a strength session's working sets, or an erg/bike's
    # small above-threshold-power contribution; `by_muscle_json` is {"quadriceps": au, ...}
    # for the muscle-readiness view and the day-level strain normalization in
    # catch/sync/scoring.py. Cached here at resolve time, same pattern as strain_trimp.
    muscular_load_au: Optional[float] = None
    muscular_by_muscle_json: Optional[str] = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class MatchDecision(SQLModel, table=True):
    """Keyed on the natural (source, external_id) pair, not row ids, so a manual "not a
    duplicate" or a split survives a resync untouched (ids never change on upsert, but a
    row-id key would still be fragile if a DB were ever rebuilt from source). The pair is
    always stored with the lexicographically-smaller (source, external_id) first so a lookup
    doesn't have to try both orders."""

    __tablename__ = "match_decisions"
    __table_args__ = (
        UniqueConstraint(
            "source_a", "external_id_a", "source_b", "external_id_b", name="uq_match_decision_pair"
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    source_a: str
    external_id_a: str
    source_b: str
    external_id_b: str
    decision: str  # "not_duplicate" | "merged" | "split"
    created_at: datetime = Field(default_factory=_utcnow)


class MergeLog(SQLModel, table=True):
    """One row per merge (auto or manual) and per split, for the backfill report and a
    future audit screen — "log every auto-merge" (task Part A.4)."""

    __tablename__ = "merge_log"

    id: Optional[int] = Field(default=None, primary_key=True)
    canonical_id: int
    source: str
    external_id: str
    action: str  # "auto_merge" | "manual_merge" | "split" | "not_duplicate"
    score: Optional[float] = None
    reason: Optional[str] = None
    created_at: datetime = Field(default_factory=_utcnow)


class ActivitySamples(SQLModel, table=True):
    """Part E: per-second (post-downsample) HR/power/cadence arrays for one *source* record
    (keyed on activity_id, not canonical — merging activities never touches sample bytes).
    One row per activity, not one row per second — a 90-minute session at 1 Hz is ~5.4K
    samples; packed+zlib'd that's a few KB, vs. tens of thousands of SQLite rows the task's
    own Pi-memory rule (CLAUDE.md) says to avoid. Values are struct-packed arrays (uint16,
    0xFFFF = missing/dropped) compressed with zlib — see catch/analytics/fit_samples.py."""

    __tablename__ = "activity_samples"

    activity_id: int = Field(foreign_key="activities.id", primary_key=True)
    start: datetime
    n_samples: int
    hr_blob: Optional[bytes] = None
    power_blob: Optional[bytes] = None
    cadence_blob: Optional[bytes] = None
    updated_at: datetime = Field(default_factory=_utcnow)


class Stroke(SQLModel, table=True):
    __tablename__ = "strokes"

    id: Optional[int] = Field(default=None, primary_key=True)
    activity_id: int = Field(foreign_key="activities.id")
    seq: int = 0
    interval_index: Optional[int] = None
    # Concept2's own t/d are cumulative *within the current interval* and reset to 0 at each
    # new interval/split — t stays in those units (seconds here, converted from tenths).
    t: float
    distance: Optional[float] = None
    pace_500m: Optional[float] = None
    watts: Optional[float] = None
    stroke_rate: Optional[float] = None
    hr: Optional[float] = None


class AppSettings(SQLModel, table=True):
    __tablename__ = "settings"

    id: int = Field(default=1, primary_key=True)
    data_json: str = "{}"
    updated_at: datetime = Field(default_factory=_utcnow)


class DailyScore(SQLModel, table=True):
    __tablename__ = "daily_scores"

    date: date_ = Field(primary_key=True)
    recovery_json: Optional[str] = None
    strain_json: Optional[str] = None
    load_json: Optional[str] = None
    # Rowing-only training load (task Part B.3), parallel to load_json's all-sport number —
    # see catch/sync/scoring.py's recompute_scores.
    rowing_load_json: Optional[str] = None
    # Session 15 (see PLAN.md Part B) — illness early-warning output, rewritten on every
    # recompute like every *_json column here (user-owned state lives in illness_acks).
    illness_json: Optional[str] = None
    updated_at: datetime = Field(default_factory=_utcnow)


class BodyComp(SQLModel, table=True):
    __tablename__ = "body_comp"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_bodycomp_source_external_id"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    source: str = Field(default="withings")
    external_id: str
    ts: datetime
    weight_kg: Optional[float] = None
    fat_pct: Optional[float] = None
    fat_kg: Optional[float] = None
    muscle_kg: Optional[float] = None
    bone_kg: Optional[float] = None
    hydration_kg: Optional[float] = None


class SyncState(SQLModel, table=True):
    __tablename__ = "sync_state"

    source: str = Field(primary_key=True)
    cursor: Optional[str] = None
    last_attempt_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    last_error: Optional[str] = None


class OAuthToken(SQLModel, table=True):
    __tablename__ = "oauth_tokens"

    source: str = Field(primary_key=True)
    access_token_enc: str
    refresh_token_enc: Optional[str] = None
    expires_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=_utcnow)


class Note(SQLModel, table=True):
    __tablename__ = "notes"

    id: Optional[int] = Field(default=None, primary_key=True)
    date: date_
    text: str
    rpe: Optional[int] = None
    created_at: datetime = Field(default_factory=_utcnow)


class ApiToken(SQLModel, table=True):
    """Per-device bearer tokens (catch/cli.py's `token create`) so the MCP server can run on
    a laptop/elsewhere while Catch runs on the Pi. Only the sha256 hash is stored — the raw
    token is shown exactly once, at creation, matching `.env`'s secrets ever being printed."""

    __tablename__ = "api_tokens"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    token_hash: str
    created_at: datetime = Field(default_factory=_utcnow)
    last_used_at: Optional[datetime] = None


class CoachCredential(SQLModel, table=True):
    """Fernet-encrypted provider API keys, mirroring OAuthToken's pattern — kept out of the
    plain-JSON `settings` table on purpose (a key must never round-trip through GET /api/
    settings or a PUT patch diff)."""

    __tablename__ = "coach_credentials"

    provider: str = Field(primary_key=True)
    api_key_enc: str
    last4: str
    updated_at: datetime = Field(default_factory=_utcnow)


class CoachSettings(SQLModel, table=True):
    """Coach-only preferences, deliberately a separate table from `settings`: a per-model
    price dict would trip settings_store's unknown-nested-key validation, and PUT /api/
    settings triggers a full recompute_scores that has nothing to do with the coach."""

    __tablename__ = "coach_settings"

    id: int = Field(default=1, primary_key=True)
    provider: str = Field(default="anthropic")  # "anthropic" | "ollama"
    anthropic_model: Optional[str] = None  # None -> default to the newest "sonnet" model
    ollama_base_url: Optional[str] = None
    ollama_model: Optional[str] = None
    daily_cap_usd: Optional[float] = None
    # {model_id: {"input": $/1M, "output": $/1M, "cache_write": $/1M, "cache_read": $/1M}} —
    # prices are set here by the user, never hardcoded (Anthropic repricing, Ollama = $0).
    prices_json: str = "{}"
    updated_at: datetime = Field(default_factory=_utcnow)


class CoachConversation(SQLModel, table=True):
    __tablename__ = "coach_conversations"

    id: Optional[int] = Field(default=None, primary_key=True)
    title: Optional[str] = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class CoachMessage(SQLModel, table=True):
    """`blocks_json` is a provider-neutral list of {type: text|tool_call|tool_result, ...}
    dicts (see catch/coach/chat.py), not either provider's own wire format — needed so a
    conversation can switch providers mid-stream (Ollama laptop asleep -> Anthropic) without
    the stored history being tied to one provider's content-block shape."""

    __tablename__ = "coach_messages"

    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: int = Field(foreign_key="coach_conversations.id")
    role: str  # "user" | "assistant"
    blocks_json: str
    provider: Optional[str] = None
    model: Optional[str] = None
    usage_json: Optional[str] = None
    cost_usd: Optional[float] = None
    created_at: datetime = Field(default_factory=_utcnow)


class Event(SQLModel, table=True):
    __tablename__ = "events"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    date: date_
    type: str  # race | 2k_test | camp | selection
    distance: Optional[str] = None
    boat_class: Optional[str] = None
    priority: Optional[str] = None  # A | B | C
    goal_time: Optional[str] = None
    result: Optional[str] = None
    # Session 15 (see PLAN.md Part C.3): a generated pacing plan (per-500m targets + rate
    # plan), saved here by make_pacing_plan so the test-detail screen can show "plan vs.
    # actual" once this event's test happens. Not exposed as an update_event tool param —
    # only make_pacing_plan writes it, to keep that tool's surface a plain time/style request.
    plan_json: Optional[str] = None
    created_at: datetime = Field(default_factory=_utcnow)


class Goal(SQLModel, table=True):
    __tablename__ = "goals"

    id: Optional[int] = Field(default=None, primary_key=True)
    text: str
    target_date: Optional[date_] = None
    status: str = "active"  # active | done | abandoned
    created_at: datetime = Field(default_factory=_utcnow)


class AthleteFact(SQLModel, table=True):
    __tablename__ = "athlete_facts"

    id: Optional[int] = Field(default=None, primary_key=True)
    category: str  # injury | schedule | equipment | preference | other
    text: str
    valid_until: Optional[date_] = None
    created_at: datetime = Field(default_factory=_utcnow)
    source_conversation: Optional[int] = None


# --- Session 13 (see PLAN.md Part B): nutrition ------------------------------------------


class Food(SQLModel, table=True):
    """Every macro field is per 100g, regardless of `source` — the single canonical basis a
    `FoodLog` scales from, so quantity math never has to branch on where a food came from.
    `source="off"`/`"usda"` rows are a local cache of an external lookup (re-fetched only
    when stale is acceptable to the task's "cache every hit" ask — never re-fetched at all
    here, since branded-food nutrition data essentially never changes); `source="manual"` is
    a user-entered food, which also becomes the first local-cache hit for that barcode on a
    future scan."""

    __tablename__ = "foods"

    id: Optional[int] = Field(default=None, primary_key=True)
    source: str  # "off" | "usda" | "manual"
    barcode: Optional[str] = Field(default=None, index=True)
    name: str
    brand: Optional[str] = None
    serving_size: Optional[float] = None
    serving_unit: Optional[str] = None
    kcal_100g: Optional[float] = None
    protein_100g: Optional[float] = None
    carbs_100g: Optional[float] = None
    fat_100g: Optional[float] = None
    fiber_100g: Optional[float] = None
    sugar_100g: Optional[float] = None
    sodium_100g: Optional[float] = None
    verified: bool = False
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class FoodLog(SQLModel, table=True):
    """Macros are computed and stored at log time (`quantity`/`unit` against the food's
    per-100g basis at that moment), not re-derived from the live `Food` row on every read —
    a later correction to a food's data (or a re-verified OFF value) must never silently
    change the athlete's past daily totals."""

    __tablename__ = "food_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    ts: datetime
    meal: str  # breakfast | lunch | dinner | snack | pre_workout | post_workout
    food_id: int = Field(foreign_key="foods.id")
    quantity: float
    unit: str  # "g" | "serving"
    kcal: Optional[float] = None
    protein: Optional[float] = None
    carbs: Optional[float] = None
    fat: Optional[float] = None
    fiber: Optional[float] = None
    sugar: Optional[float] = None
    sodium: Optional[float] = None
    # Set only on a coach/MCP `log_food` write or a saved photo-estimate item — distinguishes
    # an AI-assisted log from a manually-entered one without a separate table.
    estimated: bool = False
    created_at: datetime = Field(default_factory=_utcnow)


class MyFood(SQLModel, table=True):
    """A starred quick-access shortcut to a `Food` row — distinct from the `foods` cache
    itself, which holds every food ever looked up/logged, most of which the athlete will
    never want to see again in a "my foods" quick-add list."""

    __tablename__ = "my_foods"
    __table_args__ = (UniqueConstraint("food_id", name="uq_my_foods_food_id"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    food_id: int = Field(foreign_key="foods.id")
    label: Optional[str] = None
    created_at: datetime = Field(default_factory=_utcnow)


class SavedMeal(SQLModel, table=True):
    __tablename__ = "saved_meals"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    # [{"food_id", "quantity", "unit"}, ...] — same shape as a FoodLog's own quantity/unit,
    # kept as JSON rather than a join table since a saved meal is small and always read/
    # written whole (never queried per-item).
    items_json: str
    created_at: datetime = Field(default_factory=_utcnow)


class NutritionTarget(SQLModel, table=True):
    """Singleton (id=1), same pattern as `AppSettings`/`CoachSettings` — kept out of the
    shared `settings` JSON blob deliberately: every `PUT /api/settings` triggers a full
    `recompute_scores`, which has nothing to do with nutrition targets (session 5's
    precedent for `coach_settings`). Every number here is a "starting point, adjust with a
    coach or dietitian" default — task Part B.5 — never a validated prescription."""

    __tablename__ = "nutrition_targets"

    id: int = Field(default=1, primary_key=True)
    protein_g_per_kg: float = 1.6
    carb_g_per_kg_rest: float = 3.0
    carb_g_per_kg_moderate: float = 5.0
    carb_g_per_kg_double_day: float = 7.0
    carb_g_per_kg_pre_race: float = 8.0
    kcal_target_source: str = "garmin_total"  # "garmin_total" | "manual"
    manual_kcal_target: Optional[int] = None
    updated_at: datetime = Field(default_factory=_utcnow)


class AiUsageEvent(SQLModel, table=True):
    """Anthropic spend that isn't a coach chat turn (so far: the nutrition photo-estimate
    vision call) — `CoachMessage.cost_usd` only covers conversation turns, but the daily
    spend cap (`coach_settings.daily_cap_usd`) must cover *every* Anthropic call this app
    makes, or a feature outside the chat loop could silently blow straight through it.
    `catch.coach.cost.today_spend_usd` sums both tables."""

    __tablename__ = "ai_usage_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    kind: str  # "nutrition_photo_estimate"
    usage_json: Optional[str] = None
    cost_usd: Optional[float] = None
    created_at: datetime = Field(default_factory=_utcnow)


# --- Session 14 (see PLAN.md): gym logger, Garmin-strength merge, cardio/muscular strain ----


class Exercise(SQLModel, table=True):
    """Seeded from `catch/seed/exercises.json` (yuhonas/free-exercise-db, Unlicense/
    public domain — vendored JSON only, no images, at build time) plus any user-added custom
    exercise (`custom=True`, `external_id=None`). `movement_pattern`/`unilateral` are a
    documented heuristic derived from the source dataset's name/force/category (it has no such
    fields itself — see the seed-build note in PLAN.md's session 14 section), always
    user-editable afterward rather than treated as authoritative."""

    __tablename__ = "exercises"

    id: Optional[int] = Field(default=None, primary_key=True)
    external_id: Optional[str] = Field(default=None, index=True)  # free-exercise-db's own id; None for custom.
    name: str
    default_equipment_type: str  # one of EQUIPMENT_TYPES below — just a UI pre-select, never load math.
    movement_pattern: str  # squat | hinge | lunge | push_horizontal | push_vertical | pull_horizontal | pull_vertical | carry | core | other
    unilateral: bool = False
    primary_muscles_json: str = "[]"
    secondary_muscles_json: str = "[]"
    custom: bool = False
    created_at: datetime = Field(default_factory=_utcnow)


class Gym(SQLModel, table=True):
    __tablename__ = "gyms"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    created_at: datetime = Field(default_factory=_utcnow)


class GymStation(SQLModel, table=True):
    """A saved per-gym equipment setup (task Part A.3's "save stations per gym ... one tap
    next time") — e.g. "Uni gym cable 2: dual stack, 2:1". `config_json` holds whichever of
    `bar_weight_kg`/`base_weight_kg`/`stack_kg_per_increment`/`pulley_multiplier`/
    `dual_stack`/`default_attachment` apply to `equipment_type` (catch/analytics/equipment.py's
    functions each take a subset); irrelevant keys are just absent rather than every equipment
    type sharing one rigid column set."""

    __tablename__ = "gym_stations"

    id: Optional[int] = Field(default=None, primary_key=True)
    gym_id: int = Field(foreign_key="gyms.id")
    name: str
    equipment_type: str
    config_json: str = "{}"
    created_at: datetime = Field(default_factory=_utcnow)


class StrengthSet(SQLModel, table=True):
    """One logged set. `client_id` (a UUID the phone generates offline) is the idempotent
    upsert key — matching CLAUDE.md's "(source, external_id)" convention, generalized to a
    child row: a dropped-response retry from a flaky gym signal must never duplicate a set.
    `activity_id` points at the `Activity` row that *is* this lifting session
    (`source="catch_strength"`, `external_id=`the client-generated session UUID) — the
    matching engine, canonical resolution, and every existing "an activity" reader all work on
    it unchanged (task Part B.1).

    Every equipment-math input is snapshotted here at log time (`bar_weight_kg`,
    `pulley_multiplier`, `bodyweight_kg_used`, ...), not re-derived later from the station or
    current bodyweight — a later change to either must never silently rewrite a past session's
    numbers."""

    __tablename__ = "strength_sets"

    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: str = Field(index=True, unique=True)
    activity_id: int = Field(foreign_key="activities.id")
    # Nullable only for an unmatched "garmin_draft" import (task Part B.2) — the raw Garmin
    # exercise-category enum has no reliable mapping onto this app's exercise library, so an
    # unmatched draft is surfaced with exercise_id=None rather than guessed, and excluded from
    # muscular-load math until the athlete picks the real exercise and confirms it.
    exercise_id: Optional[int] = Field(default=None, foreign_key="exercises.id")
    gym_station_id: Optional[int] = Field(default=None, foreign_key="gym_stations.id")
    seq: int = 0  # logging order within the session — the display/edit order.
    superset_group: Optional[int] = None
    set_type: str = "working"  # warmup | working | drop | failure | amrap
    reps: int = 0
    side: Optional[str] = None  # left | right | None (bilateral)
    tempo: Optional[str] = None
    rir: Optional[float] = None
    rpe: Optional[float] = None
    equipment_type: str = "other"
    load_kg: Optional[float] = None  # the raw number the lifter entered/read off the equipment.
    bar_weight_kg: Optional[float] = None
    pulley_multiplier: Optional[float] = None
    bodyweight_kg_used: Optional[float] = None
    added_weight_kg: Optional[float] = None
    assistance_kg: Optional[float] = None
    effective_load_kg: Optional[float] = None
    load_is_estimated: bool = False
    muscular_au: Optional[float] = None
    is_rep_pr: bool = False
    is_e1rm_pr: bool = False
    # "catch" (logged by the athlete) | "garmin_draft" (imported from a Garmin FIT `set`
    # message when nothing was logged in Catch — task Part B.2, confirmed before it counts
    # toward anything by `is_confirmed`).
    source: str = "catch"
    is_confirmed: bool = True
    deleted: bool = False  # tombstone, for an offline delete to survive a sync retry.
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class StrengthTemplate(SQLModel, table=True):
    """A reusable routine (task Part A.5) — `items_json` is
    `[{"exercise_id", "target_sets", "target_reps", "gym_station_id"}, ...]`, same
    read/written-whole pattern as `SavedMeal.items_json`."""

    __tablename__ = "strength_templates"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    items_json: str = "[]"
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


# --- Session 15 (see PLAN.md): morning check-in, illness early warning, erg test center ----


class CheckIn(SQLModel, table=True):
    """One per day (date is the primary key — editable later the same day, per the task's
    "editable later that day", by just POSTing again). Sliders are 1-5; 1 = none/low/poor for
    soreness/stress/sleep_quality, 1 = low for mood — see catch/analytics/checkin.py for the
    exact scoring direction of each. A niggle is purely informational (task Part A.2: "never
    changes the number silently") — it's stored here so Today/the coach can see it, but never
    read by checkin_recovery_score."""

    __tablename__ = "checkins"

    date: date_ = Field(primary_key=True)
    soreness: Optional[int] = None
    stress: Optional[int] = None
    mood: Optional[int] = None
    sleep_quality: Optional[int] = None
    niggle_area: Optional[str] = None
    niggle_severity: Optional[int] = None  # 1-3
    note: Optional[str] = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class IllnessAck(SQLModel, table=True):
    """User-owned state for a flagged day, kept out of `daily_scores.illness_json` on purpose
    — that column is fully rewritten by every `recompute_scores` run (see catch/sync/
    scoring.py's docstring), so anything that must survive a recompute (a dismissal, its
    reason, a backtest right/wrong mark) needs its own table that recompute only ever inserts
    into, never overwrites (task Part B.3/B.4). `first_flagged_at` is set once, the first time
    a date reaches "likely", for a future notifier (task's own "Session 12" — this repo's
    numbering continues past the already-used session 11/12, so whichever session adds
    notifications) to know what it hasn't already surfaced."""

    __tablename__ = "illness_acks"

    date: date_ = Field(primary_key=True)
    first_flagged_at: Optional[datetime] = None
    dismissed: bool = False
    dismiss_reason: Optional[str] = None  # alcohol | travel | late_night | vaccine | other
    backtest_mark: Optional[str] = None  # "correct" | "incorrect" — task Part B.4
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
