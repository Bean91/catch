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
    calories: Optional[float] = None
    raw_json: Optional[str] = None
    fit_path: Optional[str] = None
    # Concept2-specific, left NULL for other sources.
    workout_type: Optional[str] = None
    drag_factor: Optional[int] = None
    stroke_rate: Optional[float] = None
    intervals_json: Optional[str] = None
    # Cross-source dedup: points at the paired row (Garmin<->Concept2) for the same physical
    # session, set on both sides. Scoring must only count the Concept2 side of a linked pair.
    linked_activity_id: Optional[int] = Field(default=None, foreign_key="activities.id")
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
