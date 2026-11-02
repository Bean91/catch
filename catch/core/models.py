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
    session_label: Optional[str] = None
    auto_trimmed_tail_s: Optional[float] = None
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
