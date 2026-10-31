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
