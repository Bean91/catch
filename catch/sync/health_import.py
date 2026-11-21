"""Session 30 (docs/mobile/health-data.md): the DB-facing half of the Apple Health / Health Connect import.

The phone reads its own health store (after the person consented in the app, and then at the OS permission sheet) and posts
what the person agreed to share; nothing here ever reaches back to the device. Everything is owner-scoped through the ordinary
tenant machinery — these are owned tables — and imported rows join the existing pipeline (canonical activities, wellness
readings, the matching engine), so they appear beside Garmin/Whoop data with their provenance, never in place of it."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlmodel import Session, select

from catch.analytics import health_import as h
from catch.core import localtime
from catch.core.models import Activity, CanonicalActivity, HealthConsent, Piece, WellnessReading
from catch.sync import connections, wellness_readings
from catch.sync.upsert import upsert_activity

NOTICE_VERSION = "1"


class HealthError(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _consent(db: Session, platform: str) -> Optional[HealthConsent]:
    return db.exec(select(HealthConsent).where(HealthConsent.platform == platform)).first()


def _view(c: HealthConsent) -> dict:
    return {"platform": c.platform, "categories": json.loads(c.categories_json or "[]"), "granted_at": c.granted_at, "revoked_at": c.revoked_at,
            "last_import_at": c.last_import_at, "active": c.revoked_at is None, "notice_version": c.notice_version}


def _check_platform(platform: str) -> None:
    if platform not in h.SOURCES:
        raise HealthError("Unknown health platform")


def grant_consent(db: Session, platform: str, categories: list[str]) -> dict:
    """Records exactly which categories the person ticked. Re-granting replaces the list (so unticking a box narrows it)."""
    _check_platform(platform)
    allowed = set(h.CATEGORIES_BY_SOURCE[platform])
    chosen = sorted({c for c in categories if isinstance(c, str)})
    if not chosen or any(c not in allowed for c in chosen):
        raise HealthError("Choose at least one of the data types this phone can share")
    row = _consent(db, platform)
    if row is None:
        row = HealthConsent(platform=platform)
        db.add(row)
    row.categories_json = json.dumps(chosen)
    row.granted_at = _now()
    row.revoked_at = None
    row.notice_version = NOTICE_VERSION
    db.commit()
    db.refresh(row)
    return _view(row)


def revoke_consent(db: Session, platform: str, *, delete_data: bool) -> dict:
    _check_platform(platform)
    row = _consent(db, platform)
    if row is not None and row.revoked_at is None:
        row.revoked_at = _now()
        db.commit()
    deleted = delete_imported(db, platform) if delete_data else {"workouts": 0, "readings": 0}
    return {"revoked": True, **deleted}


def status(db: Session) -> dict:
    consents = [_view(c) for c in db.exec(select(HealthConsent).order_by(HealthConsent.platform)).all()]
    counts = {}
    for source in h.SOURCES:
        counts[source] = {
            "workouts": len(db.exec(select(Activity.id).where(Activity.source == source)).all()),
            "readings": len(db.exec(select(WellnessReading.signal).where(WellnessReading.source == source)).all()),
        }
    # The marker table travels to the app so its "don't send what Catch already gets from the source" filter and the server's are the same list.
    return {"consents": consents, "counts": counts, "connected_providers": sorted(_connected(db)), "provider_app_markers": {k: list(v) for k, v in h.PROVIDER_APP_MARKERS.items()}}


def _connected(db: Session) -> set[str]:
    return {p for p in h.PROVIDER_APP_MARKERS if connections.is_connected(db, p)}


def import_batch(db: Session, platform: str, workouts: list[dict], readings: list[dict]) -> dict:
    _check_platform(platform)
    consent = _consent(db, platform)
    if consent is None or consent.revoked_at is not None:
        raise HealthError("Health import isn't switched on for this phone. Turn it on in Settings → Health data first.", 403)
    if len(workouts) > h.MAX_WORKOUTS_PER_REQUEST or len(readings) > h.MAX_READINGS_PER_REQUEST:
        raise HealthError("That's too much to send at once. The app sends smaller batches.", 413)
    granted = set(json.loads(consent.categories_json or "[]"))
    connected = _connected(db)
    out = {"workouts": 0, "readings": 0, "skipped_duplicate": 0, "skipped_not_consented": 0, "skipped_invalid": 0}
    days: set[date] = set()

    for raw in workouts:
        if "workouts" not in granted:
            out["skipped_not_consented"] += 1
            continue
        try:
            w = h.validate_workout(raw if isinstance(raw, dict) else {})
        except h.Invalid:
            out["skipped_invalid"] += 1
            continue
        if h.duplicate_of(w["origin_app"], w["origin_id"], connected):
            out["skipped_duplicate"] += 1
            continue
        upsert_activity(
            db, platform, w["external_id"], type=w["type"], start=w["start"], duration=w["duration"], distance=w["distance"], calories=w["calories"],
            avg_hr=w["avg_hr"], max_hr=w["max_hr"], workout_type=None,
            raw_json=json.dumps({"origin_app": w["origin_app"], "origin_id": w["origin_id"], "utc_offset_minutes": w["utc_offset_minutes"]}),  # provenance: which app actually recorded it
            title_hint=None,
        )
        out["workouts"] += 1

    for raw in readings:
        try:
            r = h.validate_reading(raw if isinstance(raw, dict) else {}, today=localtime.today(db))
        except h.Invalid:
            out["skipped_invalid"] += 1
            continue
        if r["category"] not in granted:
            out["skipped_not_consented"] += 1
            continue
        if r["category"] not in h.CATEGORIES_BY_SOURCE[platform]:
            out["skipped_invalid"] += 1
            continue
        if h.duplicate_of(r["origin_app"], r["origin_id"], connected):
            out["skipped_duplicate"] += 1
            continue
        meta: dict[str, Any] = {**r["meta"], "origin_app": r["origin_app"]}
        wellness_readings.record_reading(db, r["date"], platform, r["signal"], r["value"], meta=meta, commit=False)
        days.add(r["date"])
        out["readings"] += 1

    consent.last_import_at = _now()
    db.commit()
    if out["workouts"] or out["readings"]:
        _refresh(db, days)
    return out


def _refresh(db: Session, days: set[date]) -> None:
    from catch.sync import matching
    from catch.sync.scoring import recompute_scores

    if days:
        wellness_readings.resolve_days(db, days)
    matching.run_matching(db)
    recompute_scores(db)


def delete_imported(db: Session, platform: Optional[str] = None) -> dict:
    """Everything this feature imported (one platform, or both): activities and wellness readings. Other sources' rows are never touched;
    a day's wellness values are re-decided without the deleted source, and a canonical activity left with no source record is removed
    unless the person attached a piece to it."""
    from catch.sync.canonical import resolve_canonical

    sources = [platform] if platform else list(h.SOURCES)
    acts = db.exec(select(Activity).where(Activity.source.in_(sources))).all()  # type: ignore[attr-defined]
    canonical_ids = {a.canonical_id for a in acts if a.canonical_id is not None}
    for a in acts:
        db.delete(a)
    db.flush()
    readings = db.exec(select(WellnessReading).where(WellnessReading.source.in_(sources))).all()  # type: ignore[attr-defined]
    days = {r.date for r in readings}
    for r in readings:
        db.delete(r)
    db.flush()
    for cid in canonical_ids:
        left = db.exec(select(Activity.id).where(Activity.canonical_id == cid)).first()
        if left is not None:
            resolve_canonical(db, cid)
        elif db.exec(select(Piece.id).where(Piece.canonical_id == cid)).first() is None:
            c = db.get(CanonicalActivity, cid)
            if c is not None:
                db.delete(c)
    db.commit()
    if days:
        wellness_readings.resolve_days(db, days)
    from catch.sync.scoring import recompute_scores

    recompute_scores(db)
    return {"workouts": len(acts), "readings": len(readings)}
