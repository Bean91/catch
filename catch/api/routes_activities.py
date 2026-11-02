from __future__ import annotations

import json
from datetime import date, datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_
from sqlmodel import Session, select

from catch.analytics.matching import category_for_canonical, is_indoor
from catch.analytics.zones import training_zones, zone_for_hr
from catch.api.deps import as_utc, get_db, require_auth
from catch.core.models import Activity, ActivitySamples, CanonicalActivity, DailyScore, Note
from catch.core.settings_store import get_settings
from catch.sync.canonical import provenance, resolve_canonical

router = APIRouter(dependencies=[Depends(require_auth)])

_PAGE_SIZE_DEFAULT = 30
_PAGE_SIZE_MAX = 100
_OVERRIDE_FIELDS = {"title", "sport_family", "notes", "rpe", "exclude_from_totals", "tags"}


def _overrides(canonical: CanonicalActivity) -> dict:
    return json.loads(canonical.overrides_json) if canonical.overrides_json else {}


def _members(db: Session, canonical_id: int) -> list[Activity]:
    return db.exec(select(Activity).where(Activity.canonical_id == canonical_id).order_by(Activity.id)).all()


def _category_filter(category: str):
    if category not in ("erg", "on_water", "other"):
        raise HTTPException(status_code=400, detail=f"Unknown category '{category}'. Allowed: erg, on_water, other")
    if category == "other":
        return CanonicalActivity.sport_family != "rowing"
    return CanonicalActivity.sport_family == "rowing"  # narrowed to erg/on_water below in Python


def _parse_cursor(cursor: str | None) -> tuple[datetime, int] | None:
    if not cursor:
        return None
    try:
        start_iso, id_str = cursor.rsplit("_", 1)
        return as_utc(datetime.fromisoformat(start_iso)), int(id_str)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid cursor") from exc


def _activity_strain(db: Session, canonical: CanonicalActivity, strain_by_date: dict[date, dict] | None = None) -> dict | None:
    if canonical.start is None:
        return None
    local_date = canonical.start.astimezone().date()
    if strain_by_date is not None:
        day_strain = strain_by_date.get(local_date)
    else:
        row = db.get(DailyScore, local_date)
        day_strain = json.loads(row.strain_json) if (row and row.strain_json) else None
    if not day_strain:
        return None
    for component in day_strain.get("components", []):
        if component.get("canonical_id") == canonical.id:
            return component
    return None


def _source_summary(member: Activity) -> dict:
    return {
        "activity_id": member.id,
        "source": member.source,
        "external_id": member.external_id,
        "provenance": provenance(member),
        "type": member.type,
        "origin": member.origin,
        "hr_source_type": member.hr_source_type,
        "has_fit": bool(member.fit_path),
        "has_strokes": member.source == "concept2",
    }


def _canonical_payload(db: Session, canonical: CanonicalActivity, members: list[Activity] | None = None) -> dict:
    members = members if members is not None else _members(db, canonical.id)
    overrides = _overrides(canonical)
    indoor = is_indoor(members[0].source, members[0].type) if members else None
    data = canonical.model_dump(exclude={"overrides_json", "field_sources_json", "zones_json"})
    data["category"] = category_for_canonical(canonical.sport_family or "other", indoor)
    data["field_sources"] = json.loads(canonical.field_sources_json) if canonical.field_sources_json else {}
    data["zones"] = json.loads(canonical.zones_json) if canonical.zones_json else None
    data["notes"] = overrides.get("notes")
    data["rpe"] = overrides.get("rpe")
    data["exclude_from_totals"] = bool(overrides.get("exclude_from_totals"))
    data["tags"] = overrides.get("tags") or []
    data["overrides"] = overrides
    data["sources"] = [_source_summary(m) for m in members]
    data["editable_fields"] = sorted(_OVERRIDE_FIELDS)
    # Garmin's Personal API is read-only (task Part C.5) — edits here never push back.
    data["edits_push_back_to_source"] = False
    return data


@router.get("/api/activities")
def list_activities(
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    category: str | None = Query(None, description="erg | on_water | other"),
    limit: int = Query(_PAGE_SIZE_DEFAULT, ge=1, le=_PAGE_SIZE_MAX),
    cursor: str | None = Query(None, description="opaque, from the previous page's next_cursor"),
    db: Session = Depends(get_db),
):
    from_, to = as_utc(from_), as_utc(to)
    stmt = select(CanonicalActivity).where(CanonicalActivity.start.is_not(None))
    if from_:
        stmt = stmt.where(CanonicalActivity.start >= from_)
    if to:
        stmt = stmt.where(CanonicalActivity.start <= to)
    if category:
        stmt = stmt.where(_category_filter(category))

    cursor_parsed = _parse_cursor(cursor)
    if cursor_parsed:
        cursor_start, cursor_id = cursor_parsed
        stmt = stmt.where(
            or_(CanonicalActivity.start < cursor_start, (CanonicalActivity.start == cursor_start) & (CanonicalActivity.id < cursor_id))
        )
    stmt = stmt.order_by(CanonicalActivity.start.desc(), CanonicalActivity.id.desc()).limit(limit)
    rows = db.exec(stmt).all()

    all_members = db.exec(select(Activity).where(Activity.canonical_id.in_([r.id for r in rows]))).all() if rows else []
    members_by_canonical: dict[int, list[Activity]] = {}
    for m in all_members:
        members_by_canonical.setdefault(m.canonical_id, []).append(m)

    dates = {r.start.astimezone().date() for r in rows if r.start is not None}
    score_rows = db.exec(select(DailyScore).where(DailyScore.date.in_(dates))).all() if dates else []
    strain_by_date = {s.date: json.loads(s.strain_json) for s in score_rows if s.strain_json}

    # category narrows further than the SQL filter (erg vs on_water both share sport_family
    # == "rowing"; the indoor/outdoor split needs each row's member type).
    items = []
    for r in rows:
        payload = _canonical_payload(db, r, members_by_canonical.get(r.id, []))
        if category and payload["category"] != category:
            continue
        payload["strain"] = _activity_strain(db, r, strain_by_date)
        items.append(payload)

    next_cursor = None
    if len(rows) == limit and rows[-1].start is not None:
        next_cursor = f"{rows[-1].start.isoformat()}_{rows[-1].id}"
    return {"items": items, "next_cursor": next_cursor}


@router.get("/api/activities/{canonical_id}")
def get_activity(canonical_id: int, db: Session = Depends(get_db)):
    canonical = db.get(CanonicalActivity, canonical_id)
    if canonical is None:
        raise HTTPException(status_code=404, detail="Activity not found")

    settings = get_settings(db)
    members = _members(db, canonical_id)
    local_date = canonical.start.astimezone().date() if canonical.start else None
    note = db.exec(select(Note).where(Note.date == local_date)).first() if local_date else None

    data = _canonical_payload(db, canonical, members)
    data["local_date"] = local_date
    data["strain"] = _activity_strain(db, canonical)
    data["zones_config"] = training_zones(max_hr=settings.get("max_hr"), settings=settings)
    data["hr_zone"] = zone_for_hr(canonical.avg_hr, settings.get("max_hr"), settings)
    data["day_note"] = note
    data["has_samples"] = any(db.get(ActivitySamples, m.id) is not None for m in members)
    return data


class ActivityEditRequest(BaseModel):
    title: str | None = None
    sport_family: str | None = None
    notes: str | None = None
    rpe: int | None = None
    exclude_from_totals: bool | None = None
    tags: list[str] | None = None


@router.patch("/api/activities/{canonical_id}")
def patch_activity(canonical_id: int, body: ActivityEditRequest = Body(...), db: Session = Depends(get_db)):
    canonical = db.get(CanonicalActivity, canonical_id)
    if canonical is None:
        raise HTTPException(status_code=404, detail="Activity not found")
    if body.rpe is not None and not (0 <= body.rpe <= 10):
        raise HTTPException(status_code=422, detail="rpe must be between 0 and 10")

    overrides = _overrides(canonical)
    patch = body.model_dump(exclude_unset=True)
    overrides.update(patch)
    canonical.overrides_json = json.dumps(overrides)
    db.add(canonical)
    db.commit()
    resolve_canonical(db, canonical_id)

    from catch.sync.scoring import recompute_scores

    recompute_scores(db)
    return get_activity(canonical_id, db=db)


class RevertFieldRequest(BaseModel):
    field: str


@router.post("/api/activities/{canonical_id}/revert")
def revert_activity_field(canonical_id: int, body: RevertFieldRequest = Body(...), db: Session = Depends(get_db)):
    if body.field not in _OVERRIDE_FIELDS:
        raise HTTPException(status_code=422, detail=f"field must be one of {sorted(_OVERRIDE_FIELDS)}")
    canonical = db.get(CanonicalActivity, canonical_id)
    if canonical is None:
        raise HTTPException(status_code=404, detail="Activity not found")

    overrides = _overrides(canonical)
    overrides.pop(body.field, None)
    canonical.overrides_json = json.dumps(overrides)
    db.add(canonical)
    db.commit()
    resolve_canonical(db, canonical_id)

    from catch.sync.scoring import recompute_scores

    recompute_scores(db)
    return get_activity(canonical_id, db=db)


class BulkEditRequest(BaseModel):
    canonical_ids: list[int]
    patch: ActivityEditRequest


@router.post("/api/activities/bulk")
def bulk_edit_activities(body: BulkEditRequest = Body(...), db: Session = Depends(get_db)):
    updated = []
    for canonical_id in body.canonical_ids:
        canonical = db.get(CanonicalActivity, canonical_id)
        if canonical is None:
            continue
        overrides = _overrides(canonical)
        overrides.update(body.patch.model_dump(exclude_unset=True))
        canonical.overrides_json = json.dumps(overrides)
        db.add(canonical)
        db.commit()
        resolve_canonical(db, canonical_id)
        updated.append(canonical_id)

    from catch.sync.scoring import recompute_scores

    recompute_scores(db)
    return {"updated": updated}


# -- Duplicates review (task Part A.5) ---------------------------------------------------


@router.get("/api/activities/duplicates")
def list_duplicates(db: Session = Depends(get_db)):
    from catch.sync.matching import list_flagged_duplicates

    return {"pairs": list_flagged_duplicates(db)}


class ActivityPairRequest(BaseModel):
    activity_id_a: int
    activity_id_b: int


@router.post("/api/activities/merge")
def merge_activities(body: ActivityPairRequest = Body(...), db: Session = Depends(get_db)):
    from catch.sync.matching import manual_merge

    try:
        canonical = manual_merge(db, body.activity_id_a, body.activity_id_b)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    from catch.sync.scoring import recompute_scores

    recompute_scores(db)
    return get_activity(canonical.id, db=db)


class SplitActivityRequest(BaseModel):
    activity_id: int


@router.post("/api/activities/split")
def split_activity_route(body: SplitActivityRequest = Body(...), db: Session = Depends(get_db)):
    from catch.sync.matching import split_activity

    try:
        canonical = split_activity(db, body.activity_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    from catch.sync.scoring import recompute_scores

    recompute_scores(db)
    return get_activity(canonical.id, db=db)


@router.post("/api/activities/not-duplicate")
def mark_not_duplicate_route(body: ActivityPairRequest = Body(...), db: Session = Depends(get_db)):
    from catch.sync.matching import mark_not_duplicate

    try:
        mark_not_duplicate(db, body.activity_id_a, body.activity_id_b)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}
