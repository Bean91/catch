"""The DB half of provider-independent recovery inputs (the pure rules are in
catch/analytics/wellness_inputs.py, docs/analytics.md §30).

Every provider records what it measured as `wellness_readings` rows keyed (date, source, signal).
`resolve_days` is then the ONLY writer of the signal columns of `daily_wellness` — a later sync
from one provider can never overwrite another provider's winning value, because a sync records a
reading and the resolver re-decides. Columns that aren't signals (steps, kcal, stress, body
battery, intensity minutes, floors, Garmin's sleep_score, whole-day respiration) are untouched here.
"""

from __future__ import annotations

from catch.core import tenant
import json
from datetime import date, datetime, timezone
from typing import Iterable

from sqlmodel import Session, select

from catch.analytics.wellness_inputs import SIGNALS, SLEEP_META_COLUMNS, Reading, resolve_signal
from catch.core.models import DailyWellness, WellnessReading
from catch.core.settings_store import get_settings


def record_reading(
    session: Session,
    day: date,
    source: str,
    signal: str,
    value: float | None,
    *,
    recorded_at: datetime | None = None,
    external_id: str | None = None,
    meta: dict | None = None,
    commit: bool = True,
) -> None:
    if value is None or signal not in SIGNALS:
        return
    row = session.get(WellnessReading, tenant.pk(day, source, signal))
    if row is None:
        row = WellnessReading(date=day, source=source, signal=signal, value=float(value))
        session.add(row)
    row.value = float(value)
    row.fetched_at = datetime.now(timezone.utc)
    row.recorded_at = recorded_at or row.recorded_at
    row.external_id = external_id or row.external_id
    row.meta_json = json.dumps(meta) if meta else row.meta_json
    if commit:
        session.commit()


def record_garmin(
    session: Session,
    day: date,
    *,
    hrv_rmssd=None,
    resting_hr=None,
    sleep_seconds=None,
    sleep_meta: dict | None = None,
    sleep_respiration=None,
    spo2=None,
) -> None:
    record_reading(session, day, "garmin", "hrv_rmssd", hrv_rmssd, commit=False)
    record_reading(session, day, "garmin", "resting_hr", resting_hr, commit=False)
    record_reading(session, day, "garmin", "sleep_seconds", sleep_seconds, meta=sleep_meta, commit=False)
    record_reading(session, day, "garmin", "sleep_respiration", sleep_respiration, commit=False)
    record_reading(session, day, "garmin", "spo2", spo2, commit=False)
    session.commit()


def _readings_by_day(session: Session, days: list[date]) -> dict[date, dict[str, list[Reading]]]:
    out: dict[date, dict[str, list[Reading]]] = {d: {} for d in days}
    if not days:
        return out
    rows = session.exec(select(WellnessReading).where(WellnessReading.date.in_(days))).all()
    for r in rows:
        out[r.date].setdefault(r.signal, []).append(
            Reading(r.source, r.signal, r.value, r.fetched_at, r.recorded_at, json.loads(r.meta_json) if r.meta_json else {})
        )
    return out


def resolve_days(session: Session, days: Iterable[date]) -> int:
    """Re-decide every signal for these days and write the winners. Returns the number of days
    whose row changed."""
    day_list = sorted(set(days))
    if not day_list:
        return 0
    priority = get_settings(session)["wellness_priority"]
    by_day = _readings_by_day(session, day_list)
    changed = 0
    for day in day_list:
        resolved = {}
        for signal in SIGNALS:
            winner = resolve_signal(by_day[day].get(signal, []), priority.get(signal, []))
            if winner is not None:
                resolved[signal] = winner
        if not resolved:
            continue
        row = session.get(DailyWellness, tenant.pk(day))
        if row is None:
            row = DailyWellness(date=day, source=next(iter(resolved.values())).source)
            session.add(row)
        before = (json.dumps({c: getattr(row, c) for c in _written_columns()}, default=str), row.field_sources_json)
        sources = json.loads(row.field_sources_json) if row.field_sources_json else {}
        for signal, winner in resolved.items():
            integer = signal in ("resting_hr", "sleep_seconds")
            setattr(row, SIGNALS[signal][0], int(round(winner.value)) if integer else winner.value)
            sources[signal] = winner.source
            if signal == "sleep_seconds":
                for meta_key, column in SLEEP_META_COLUMNS.items():
                    value = winner.meta.get(meta_key)
                    setattr(row, column, int(value) if value is not None else None)
        row.field_sources_json = json.dumps(sources, sort_keys=True)
        after = (json.dumps({c: getattr(row, c) for c in _written_columns()}, default=str), row.field_sources_json)
        if before != after:
            row.updated_at = datetime.now(timezone.utc)
            changed += 1
    session.commit()
    return changed


def _written_columns() -> list[str]:
    return sorted({col for col, _ in SIGNALS.values()} | set(SLEEP_META_COLUMNS.values()))


def resolve_all(session: Session) -> int:
    days = session.exec(select(WellnessReading.date).distinct()).all()
    return resolve_days(session, days)


def seed_from_daily_wellness(session: Session) -> int:
    """One-time, idempotent: a Garmin-era row that predates `wellness_readings` gets the readings
    it implies, so resolving it later reproduces the same numbers. Only rows whose `source` is
    Garmin, that have no Garmin readings yet, and that the resolver has *never touched*
    (`field_sources_json IS NULL`) are seeded — a row the resolver has written may hold another
    provider's winning values, which must not be re-labelled as Garmin's."""
    seeded_days = set(session.exec(select(WellnessReading.date).where(WellnessReading.source == "garmin")).all())
    rows = session.exec(
        select(DailyWellness).where(DailyWellness.source == "garmin", DailyWellness.field_sources_json.is_(None))
    ).all()
    n = 0
    for row in rows:
        if row.date in seeded_days:
            continue
        meta = {k: getattr(row, c) for k, c in SLEEP_META_COLUMNS.items() if getattr(row, c) is not None}
        record_garmin(
            session,
            row.date,
            hrv_rmssd=row.hrv_rmssd,
            resting_hr=row.resting_hr,
            sleep_seconds=row.sleep_seconds,
            sleep_meta=meta or None,
            sleep_respiration=row.sleep_respiration_avg,
            spo2=row.spo2,
        )
        n += 1
    return n
