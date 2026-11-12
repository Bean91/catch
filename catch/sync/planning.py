from __future__ import annotations

"""Session 21 (see PLAN.md, docs/calendar.md): the DB-facing half of calendar planning.

Ownership: this app is single-user, but every function here takes `owner_id` and filters or
asserts on it, so the multi-user build can't forget a check. A row that belongs to someone
else is reported as *not found* — never as "forbidden", which would confirm it exists.

Planned ≠ completed: nothing in this module creates or edits an Activity/CanonicalActivity.
A link is `planned_workouts.linked_canonical_id`, nothing more. The only place plans and
completed workouts meet is the read-only assemblers below, which keep the two in separate
keys of every payload."""

import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from catch.analytics import planning as pl
from catch.analytics.erg_test import TEST_SPECS, detect_test_type, project_time
from catch.analytics.piece import parse_time_token
from catch.analytics.predict import predict_2k
from catch.analytics.training_intelligence import _history_confidence
from catch.analytics.zones import ZONE_ORDER
from catch.core.models import CanonicalActivity, Event, PlannedWorkout, TrainingPhase
from catch.core.tenant import PERSONAL_OWNER as OWNER_ID  # the personal install's owner; the public build passes the request's
from catch.core.settings_store import get_settings
from catch.sync import erg_test, rowing_predict
from catch.sync.training_intelligence import _history_days, _overrides, _qualifying_activities


MAX_CALENDAR_DAYS = 100


class PlanningError(ValueError):
    pass


class NotFound(PlanningError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _tz():
    """The zone completed workouts are bucketed in everywhere else in the app: the host's
    local zone (None). See docs/calendar.md for why this isn't a setting."""
    return None


def today() -> date:
    return pl.today_in(_tz())


# --- Planned workouts -----------------------------------------------------------------------

# Editing one of these changes *what the plan says*; linking, skipping and feedback don't, so
# they never make an approved phase read "edited since approval".
_PLAN_FIELDS = (
    "date", "start_time", "session_type", "sport_family", "title", "duration_min", "distance_m",
    "target_zone", "intensity_note", "description", "structure", "event_id",
)
_EDITABLE = _PLAN_FIELDS + ("notes", "coach_feedback", "status")

_DEFAULT_TITLES = {
    "erg": "Erg session", "on_water": "On-water session", "run": "Run", "bike": "Ride",
    "strength": "Strength", "cross": "Cross-training", "test": "Test", "rest": "Rest day", "other": "Session",
}


def _own(session: Session, model: type, owner_id: str, row_id: int):
    row = session.get(model, row_id)
    if row is None or getattr(row, "owner_id", None) != owner_id:
        raise NotFound(f"No {model.__name__} with id {row_id}")
    return row


def _check_event(session: Session, owner_id: str, event_id: int | None) -> None:
    if event_id is not None:
        _own_event(session, owner_id, event_id)


def planned_dict(row: PlannedWorkout, today_: date | None = None) -> dict:
    today_ = today_ or today()
    if row.session_type == "rest":
        display = "rest"
    elif row.linked_canonical_id is not None:
        display = "linked"
    elif row.status == "skipped":
        display = "skipped"
    elif row.date < today_:
        # Deliberately neutral: not "missed". The UI shows this as "Not logged".
        display = "not_logged"
    else:
        display = "planned"
    return {
        "id": row.id,
        "date": row.date,
        "start_time": row.start_time,
        "session_type": row.session_type,
        "sport_family": row.sport_family,
        "title": row.title,
        "duration_min": row.duration_min,
        "distance_m": row.distance_m,
        "target_zone": row.target_zone,
        "intensity_note": row.intensity_note,
        "description": row.description,
        "structure": json.loads(row.structure_json) if row.structure_json else [],
        "status": row.status,
        "display_status": display,
        "linked_canonical_id": row.linked_canonical_id,
        "series_id": row.series_id,
        "template_id": row.template_id,
        "event_id": row.event_id,
        "notes": row.notes,
        "coach_feedback": row.coach_feedback,
        "planned_minutes": pl.planned_minutes({**_planned_input(row)}),
    }


def _planned_input(row: PlannedWorkout) -> dict:
    return {
        "id": row.id,
        "date": row.date,
        "session_type": row.session_type,
        "duration_min": row.duration_min,
        "distance_m": row.distance_m,
        "target_zone": row.target_zone,
        "status": row.status,
        "structure": json.loads(row.structure_json) if row.structure_json else [],
    }


def _prepare_fields(fields: dict) -> dict:
    out = {k: v for k, v in _coerce_dates(fields, "date").items() if k in _EDITABLE}
    unknown = set(fields) - set(_EDITABLE) - {"repeat", "scope"}
    if unknown:
        raise PlanningError(f"Unknown planned-workout field(s): {sorted(unknown)}")
    try:
        pl.validate_planned_fields(out)
        if "structure" in out:
            out["structure"] = pl.validate_structure(out["structure"])
    except ValueError as exc:
        raise PlanningError(str(exc)) from exc
    return out


def create_planned(session: Session, owner_id: str, fields: dict, repeat: dict | None = None) -> list[PlannedWorkout]:
    if "date" not in fields or "session_type" not in fields:
        raise PlanningError("date and session_type are required")
    clean = _prepare_fields(fields)
    _check_event(session, owner_id, clean.get("event_id"))
    try:
        dates = pl.expand_repeat(clean["date"], repeat)
    except ValueError as exc:
        raise PlanningError(str(exc)) from exc
    series_id = uuid.uuid4().hex if len(dates) > 1 else None
    structure = clean.pop("structure", None)
    clean.setdefault("sport_family", pl.family_for_session_type(clean["session_type"]))
    clean.setdefault("title", _DEFAULT_TITLES[clean["session_type"]])
    rows = []
    for d in dates:
        row = PlannedWorkout(owner_id=owner_id, series_id=series_id, structure_json=json.dumps(structure) if structure else None, **{**clean, "date": d})
        session.add(row)
        rows.append(row)
    session.commit()
    for r in rows:
        session.refresh(r)
    return rows


def get_planned(session: Session, owner_id: str, planned_id: int) -> PlannedWorkout:
    row = _own(session, PlannedWorkout, owner_id, planned_id)
    _heal_links(session, [row])
    return row


def relink_after_merge(session: Session, keep_id: int, drop_id: int) -> None:
    """The matching engine merged two canonicals and is about to delete `drop`: a plan linked to
    it follows the survivor. If the survivor is already linked to another plan, the dropped
    side's plan becomes unlinked (one workout, one plan). Splits need nothing: the original
    canonical still exists and keeps the link."""
    rows = session.exec(select(PlannedWorkout).where(PlannedWorkout.linked_canonical_id == drop_id)).all()
    if not rows:
        return
    taken = session.exec(select(PlannedWorkout).where(PlannedWorkout.linked_canonical_id == keep_id)).first() is not None
    for row in rows:
        if taken:
            row.linked_canonical_id = None
            row.linked_at = None
        else:
            row.linked_canonical_id = keep_id
            taken = True
        session.add(row)


def _heal_links(session: Session, rows: list[PlannedWorkout]) -> None:
    """Belt and braces for any other way a canonical could vanish (a hand edit, a restore): a
    link to a missing canonical reads as unlinked rather than as "Done" pointing at a 404."""
    ids = {r.linked_canonical_id for r in rows if r.linked_canonical_id is not None}
    if not ids:
        return
    present = set(session.exec(select(CanonicalActivity.id).where(CanonicalActivity.id.in_(ids))).all())
    dirty = False
    for r in rows:
        if r.linked_canonical_id is not None and r.linked_canonical_id not in present:
            r.linked_canonical_id = None
            r.linked_at = None
            session.add(r)
            dirty = True
    if dirty:
        session.commit()


def _series_following(session: Session, owner_id: str, row: PlannedWorkout) -> list[PlannedWorkout]:
    if not row.series_id:
        return [row]
    rows = session.exec(
        select(PlannedWorkout).where(
            PlannedWorkout.owner_id == owner_id, PlannedWorkout.series_id == row.series_id, PlannedWorkout.date >= row.date
        ).order_by(PlannedWorkout.date)
    ).all()
    return list(rows)


def update_planned(session: Session, owner_id: str, planned_id: int, fields: dict, scope: str = "this") -> list[PlannedWorkout]:
    if scope not in ("this", "this_and_following"):
        raise PlanningError("scope must be 'this' or 'this_and_following'")
    row = get_planned(session, owner_id, planned_id)
    clean = _prepare_fields(fields)
    if not clean:
        return [row]
    _check_event(session, owner_id, clean.get("event_id"))
    targets = _series_following(session, owner_id, row) if scope == "this_and_following" else [row]
    shift = (clean["date"] - row.date) if "date" in clean else None
    for t in targets:
        new_type = clean.get("session_type", t.session_type)
        if new_type == "rest" and t.linked_canonical_id is not None:
            raise PlanningError("Unlink the workout before turning this into a rest day")
        plan_changed = False
        for key, value in clean.items():
            if key == "date":
                value = t.date + shift if scope == "this_and_following" else value
                attr = "date"
            elif key == "structure":
                value = json.dumps(value) if value else None
                attr = "structure_json"
            else:
                if scope == "this_and_following" and key in ("notes", "coach_feedback", "status"):
                    continue
                attr = key
            if getattr(t, attr) != value:
                setattr(t, attr, value)
                if key in _PLAN_FIELDS:
                    plan_changed = True
        if "session_type" in clean and "sport_family" not in clean:
            t.sport_family = pl.family_for_session_type(t.session_type)
        if plan_changed:
            t.updated_at = _now()
        session.add(t)
    session.commit()
    for t in targets:
        session.refresh(t)
    return targets


def move_planned(session: Session, owner_id: str, planned_id: int, new_date: date) -> PlannedWorkout:
    return update_planned(session, owner_id, planned_id, {"date": new_date})[0]


def delete_planned(session: Session, owner_id: str, planned_id: int, scope: str = "this") -> int:
    if scope not in ("this", "this_and_following"):
        raise PlanningError("scope must be 'this' or 'this_and_following'")
    row = get_planned(session, owner_id, planned_id)
    targets = _series_following(session, owner_id, row) if scope == "this_and_following" else [row]
    from catch.sync import coaching_notes

    coaching_notes.detach_planned(session, [t.id for t in targets])
    for t in targets:
        session.delete(t)
    session.commit()
    return len(targets)


def set_skipped(session: Session, owner_id: str, planned_id: int, skipped: bool) -> PlannedWorkout:
    row = get_planned(session, owner_id, planned_id)
    if skipped and row.linked_canonical_id is not None:
        raise PlanningError("Unlink the workout before marking this session skipped")
    if row.session_type == "rest":
        raise PlanningError("A rest day can't be skipped")
    row.status = "skipped" if skipped else "planned"
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def link_planned(session: Session, owner_id: str, planned_id: int, canonical_id: int) -> PlannedWorkout:
    row = get_planned(session, owner_id, planned_id)
    if row.session_type == "rest":
        raise PlanningError("A rest day can't be linked to a workout")
    if session.get(CanonicalActivity, canonical_id) is None:
        raise NotFound(f"No workout with id {canonical_id}")
    taken = session.exec(select(PlannedWorkout).where(PlannedWorkout.linked_canonical_id == canonical_id)).first()
    if taken is not None and taken.id != row.id:
        raise PlanningError("That workout is already linked to another planned session")
    row.linked_canonical_id = canonical_id
    row.linked_at = _now()
    row.status = "planned"
    session.add(row)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise PlanningError("That workout is already linked to another planned session") from exc
    session.refresh(row)
    return row


def unlink_planned(session: Session, owner_id: str, planned_id: int) -> PlannedWorkout:
    row = get_planned(session, owner_id, planned_id)
    row.linked_canonical_id = None
    row.linked_at = None
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def decline_suggestion(session: Session, owner_id: str, planned_id: int, canonical_id: int) -> None:
    row = get_planned(session, owner_id, planned_id)
    declined = set(json.loads(row.declined_json) if row.declined_json else [])
    declined.add(canonical_id)
    row.declined_json = json.dumps(sorted(declined))
    session.add(row)
    session.commit()


def list_planned(session: Session, owner_id: str, start: date, end: date) -> list[PlannedWorkout]:
    rows = list(
        session.exec(
            select(PlannedWorkout)
            .where(PlannedWorkout.owner_id == owner_id, PlannedWorkout.date >= start, PlannedWorkout.date <= end)
            .order_by(PlannedWorkout.date, PlannedWorkout.start_time, PlannedWorkout.id)
        ).all()
    )
    _heal_links(session, rows)
    return rows


# --- Events ---------------------------------------------------------------------------------

_EVENT_FIELDS = ("name", "date", "type", "distance", "distance_m", "boat_class", "priority", "goal_time", "result", "location", "goals", "notes")


def _event_visible(event: Event, owner_id: str) -> bool:
    # Rows that predate the owner column are NULL: they belong to the install's one owner.
    return event.owner_id == owner_id


def _own_event(session: Session, owner_id: str, event_id: int) -> Event:
    event = session.get(Event, event_id)
    if event is None or not _event_visible(event, owner_id):
        raise NotFound(f"No event with id {event_id}")
    return event


def _coerce_dates(fields: dict, *keys: str) -> dict:
    """Tool and REST callers hand dates over as ISO strings; the ORM needs real dates."""
    out = dict(fields)
    for key in keys:
        value = out.get(key)
        if isinstance(value, str):
            try:
                out[key] = date.fromisoformat(value)
            except ValueError as exc:
                raise PlanningError(f"{key} must be an ISO date (YYYY-MM-DD)") from exc
    return out


def _validate_event(fields: dict) -> None:
    if "type" in fields and fields["type"] not in pl.EVENT_TYPES:
        raise PlanningError(f"type must be one of {list(pl.EVENT_TYPES)}")
    if fields.get("priority") is not None and fields["priority"] not in pl.PRIORITIES:
        raise PlanningError("priority must be one of A, B, C")
    if fields.get("name") is not None and not str(fields["name"]).strip():
        raise PlanningError("name can't be empty")
    dm = fields.get("distance_m")
    if dm is not None and (isinstance(dm, bool) or not isinstance(dm, (int, float)) or dm <= 0):
        raise PlanningError("distance_m must be a positive number")
    gt = fields.get("goal_time")
    if gt:
        try:
            parse_goal_time(gt)
        except ValueError as exc:
            raise PlanningError(str(exc)) from exc


def create_event(session: Session, owner_id: str, fields: dict) -> Event:
    unknown = set(fields) - set(_EVENT_FIELDS)
    if unknown:
        raise PlanningError(f"Unknown event field(s): {sorted(unknown)}")
    fields = _coerce_dates(fields, "date")
    if not fields.get("name") or fields.get("date") is None or not fields.get("type"):
        raise PlanningError("name, date and type are required")
    _validate_event(fields)
    event = Event(owner_id=owner_id, **{k: v for k, v in fields.items() if v is not None})
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def update_event(session: Session, owner_id: str, event_id: int, fields: dict) -> Event:
    event = _own_event(session, owner_id, event_id)
    unknown = set(fields) - set(_EVENT_FIELDS)
    if unknown:
        raise PlanningError(f"Unknown event field(s): {sorted(unknown)}")
    fields = _coerce_dates(fields, "date")
    _validate_event(fields)
    for key, value in fields.items():
        # name/date/type are required columns; every other field may be cleared with None.
        if value is None and key in ("name", "date", "type"):
            continue
        setattr(event, key, value)
    if event.owner_id is None:
        event.owner_id = owner_id
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def delete_event(session: Session, owner_id: str, event_id: int) -> None:
    from catch.sync import coaching_notes

    event = _own_event(session, owner_id, event_id)
    coaching_notes.detach_event(session, event_id)
    for model in (PlannedWorkout, TrainingPhase):
        for row in session.exec(select(model).where(model.event_id == event_id)).all():
            row.event_id = None
            session.add(row)
    session.delete(event)
    session.commit()


def parse_goal_time(text: str) -> float:
    """"6:30", "6:30.5" or "1:02:03" -> seconds. Events keep goal_time as free text (the Memory
    page predates this), so anything unparseable is rejected on write rather than guessed at."""
    text = text.strip()
    parts = text.split(":")
    if len(parts) == 3:
        try:
            return int(parts[0]) * 3600 + parse_time_token(f"{parts[1]}:{parts[2]}")
        except ValueError as exc:
            raise ValueError(f"Can't read goal time '{text}' — use m:ss or m:ss.t") from exc
    try:
        return parse_time_token(text, "goal time")
    except ValueError as exc:
        raise ValueError(f"Can't read goal time '{text}' — use m:ss or m:ss.t") from exc


def event_dict(event: Event, today_: date | None = None) -> dict:
    today_ = today_ or today()
    return {
        "id": event.id,
        "ref": f"event:{event.id}",
        "name": event.name,
        "date": event.date,
        "type": event.type,
        "distance": event.distance,
        "distance_m": event.distance_m,
        "boat_class": event.boat_class,
        "priority": event.priority,
        "goal_time": event.goal_time,
        "result": event.result,
        "location": event.location,
        "goals": event.goals,
        "notes": event.notes,
        "has_pacing_plan": event.plan_json is not None,
        "days_to_go": pl.days_to_go(event.date, today_),
        "taper": event.priority in ("A", "B") and 0 <= pl.days_to_go(event.date, today_) <= 14,
    }


def list_events(session: Session, owner_id: str, start: date | None = None, end: date | None = None) -> list[Event]:
    stmt = select(Event)
    if start is not None:
        stmt = stmt.where(Event.date >= start)
    if end is not None:
        stmt = stmt.where(Event.date <= end)
    rows = session.exec(stmt.order_by(Event.date, Event.id)).all()
    return [e for e in rows if _event_visible(e, owner_id)]


def upcoming_events(session: Session, owner_id: str, limit: int = 5, today_: date | None = None) -> list[dict]:
    today_ = today_ or today()
    return [event_dict(e, today_) for e in list_events(session, owner_id, start=today_)[:limit]]


# --- Phases ---------------------------------------------------------------------------------


def phase_dict(row: TrainingPhase, session: Session | None = None) -> dict:
    approved_at = pl.aware_utc(row.coach_approved_at)
    out = {
        "id": row.id,
        "kind": row.kind,
        "name": row.name,
        "start_date": row.start_date,
        "end_date": row.end_date,
        "goals": row.goals,
        "target_minutes_per_week": row.target_minutes_per_week,
        "target_sessions_per_week": row.target_sessions_per_week,
        "target_strength_sessions_per_week": row.target_strength_sessions_per_week,
        "target_zone_pct": json.loads(row.target_zone_pct_json) if row.target_zone_pct_json else None,
        "event_id": row.event_id,
        "coach_approved": approved_at is not None,
        "coach_approved_at": approved_at,
        "coach_approved_by": row.coach_approved_by,
        "coach_approved_note": row.coach_approved_note,
        "edited_since_approval": False,
    }
    if approved_at is not None and session is not None:
        out["edited_since_approval"] = _edited_since(session, row, approved_at)
    return out


def _edited_since(session: Session, phase: TrainingPhase, approved_at: datetime) -> bool:
    if (pl.aware_utc(phase.updated_at) or approved_at) > approved_at:
        return True
    rows = session.exec(
        select(PlannedWorkout).where(
            PlannedWorkout.owner_id == phase.owner_id, PlannedWorkout.date >= phase.start_date, PlannedWorkout.date <= phase.end_date
        )
    ).all()
    return any((pl.aware_utc(r.updated_at) or approved_at) > approved_at for r in rows)


def _phase_inputs(session: Session, owner_id: str) -> list[dict]:
    rows = session.exec(select(TrainingPhase).where(TrainingPhase.owner_id == owner_id).order_by(TrainingPhase.start_date)).all()
    return [{"id": r.id, "start_date": r.start_date, "end_date": r.end_date} for r in rows]


_PHASE_FIELDS = (
    "kind", "name", "start_date", "end_date", "goals", "target_minutes_per_week", "target_sessions_per_week",
    "target_strength_sessions_per_week", "target_zone_pct", "event_id",
)


def list_phases(session: Session, owner_id: str) -> list[TrainingPhase]:
    return list(session.exec(select(TrainingPhase).where(TrainingPhase.owner_id == owner_id).order_by(TrainingPhase.start_date)).all())


def get_phase(session: Session, owner_id: str, phase_id: int) -> TrainingPhase:
    return _own(session, TrainingPhase, owner_id, phase_id)


def create_phase(session: Session, owner_id: str, fields: dict) -> TrainingPhase:
    fields = _coerce_dates(fields, "start_date", "end_date")
    unknown = set(fields) - set(_PHASE_FIELDS)
    if unknown:
        raise PlanningError(f"Unknown phase field(s): {sorted(unknown)}")
    for req in ("kind", "name", "start_date", "end_date"):
        if not fields.get(req):
            raise PlanningError(f"{req} is required")
    try:
        pl.validate_phase_fields(fields)
    except ValueError as exc:
        raise PlanningError(str(exc)) from exc
    _check_event(session, owner_id, fields.get("event_id"))
    clash = pl.overlapping_phase(_phase_inputs(session, owner_id), fields["start_date"], fields["end_date"])
    if clash is not None:
        raise PlanningError("That date range overlaps another training phase")
    data = {k: v for k, v in fields.items() if k != "target_zone_pct"}
    zp = fields.get("target_zone_pct")
    row = TrainingPhase(owner_id=owner_id, target_zone_pct_json=json.dumps(zp) if zp else None, **data)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update_phase(session: Session, owner_id: str, phase_id: int, fields: dict) -> TrainingPhase:
    row = get_phase(session, owner_id, phase_id)
    fields = _coerce_dates(fields, "start_date", "end_date")
    unknown = set(fields) - set(_PHASE_FIELDS)
    if unknown:
        raise PlanningError(f"Unknown phase field(s): {sorted(unknown)}")
    try:
        pl.validate_phase_fields(fields)
    except ValueError as exc:
        raise PlanningError(str(exc)) from exc
    start = fields.get("start_date", row.start_date)
    end = fields.get("end_date", row.end_date)
    if end < start:
        raise PlanningError("end_date can't be before start_date")
    _check_event(session, owner_id, fields.get("event_id"))
    if pl.overlapping_phase(_phase_inputs(session, owner_id), start, end, ignore_id=row.id) is not None:
        raise PlanningError("That date range overlaps another training phase")
    changed = False
    for key, value in fields.items():
        if key == "target_zone_pct":
            value = json.dumps(value) if value else None
            attr = "target_zone_pct_json"
        else:
            attr = key
        if getattr(row, attr) != value:
            setattr(row, attr, value)
            changed = True
    if changed:
        row.updated_at = _now()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def delete_phase(session: Session, owner_id: str, phase_id: int) -> None:
    row = get_phase(session, owner_id, phase_id)
    session.delete(row)
    session.commit()


def approve_phase(session: Session, owner_id: str, phase_id: int, approved_by: str | None = None, note: str | None = None) -> TrainingPhase:
    row = get_phase(session, owner_id, phase_id)
    now = _now()
    row.coach_approved_at = now
    row.coach_approved_by = (approved_by or "").strip() or None
    row.coach_approved_note = (note or "").strip() or None
    row.updated_at = now
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def unapprove_phase(session: Session, owner_id: str, phase_id: int) -> TrainingPhase:
    row = get_phase(session, owner_id, phase_id)
    row.coach_approved_at = None
    row.coach_approved_by = None
    row.coach_approved_note = None
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def phase_on(session: Session, owner_id: str, day: date) -> TrainingPhase | None:
    return session.exec(
        select(TrainingPhase).where(TrainingPhase.owner_id == owner_id, TrainingPhase.start_date <= day, TrainingPhase.end_date >= day)
    ).first()


def weekly_targets(session: Session, phase: TrainingPhase | None, settings: dict) -> dict:
    ti = settings["training_intelligence"]
    out = {
        "minutes": ti["target_minutes_per_week"],
        "sessions": ti["target_sessions_per_week"],
        "strength_sessions": None,
        "zone_pct": None,
        "source": "settings",
    }
    if phase is not None:
        any_phase_target = False
        for key, attr in (
            ("minutes", "target_minutes_per_week"), ("sessions", "target_sessions_per_week"), ("strength_sessions", "target_strength_sessions_per_week"),
        ):
            value = getattr(phase, attr)
            if value is not None:
                out[key] = value
                any_phase_target = True
        if phase.target_zone_pct_json:
            out["zone_pct"] = json.loads(phase.target_zone_pct_json)
            any_phase_target = True
        if any_phase_target:
            out["source"] = "phase"
    return out


# --- Calendar / week summary ----------------------------------------------------------------


def _completed_dict(c: CanonicalActivity, linked_to: int | None) -> dict:
    ov = _overrides(c)
    return {
        "id": c.id,
        "title": ov.get("title") or c.title,
        "sport_family": c.sport_family,
        "category": c.category,
        "start": c.start,
        "duration_min": (c.duration / 60.0) if c.duration else None,
        "distance_m": c.distance,
        "avg_hr": c.avg_hr,
        "is_test": "test" in (ov.get("tags") or []),
        "test_type": ov.get("test_type"),
        "notes": ov.get("notes"),
        "rpe": ov.get("rpe"),
        "excluded_from_totals": bool(ov.get("exclude_from_totals")),
        "linked_planned_id": linked_to,
    }


def _completed_in_range(session: Session, start: date, end: date) -> list[CanonicalActivity]:
    lo, _ = pl.local_day_utc_range(start, _tz())
    _, hi = pl.local_day_utc_range(end, _tz())
    return list(
        session.exec(
            select(CanonicalActivity).where(
                CanonicalActivity.start >= lo, CanonicalActivity.start < hi, CanonicalActivity.absorbed_into_piece_id.is_(None)
            )
        ).all()
    )


def _match_inputs(planned: list[PlannedWorkout], completed: list[CanonicalActivity]) -> tuple[list[dict], list[dict], set[tuple[int, int]]]:
    p_in = [_planned_input(p) for p in planned if p.linked_canonical_id is None and p.session_type != "rest" and p.status != "skipped"]
    a_in = [
        {
            "id": c.id,
            "local_date": pl.local_date(c.start, _tz()),
            "sport_family": c.sport_family,
            "category": c.category,
            "duration_min": (c.duration / 60.0) if c.duration else None,
            "distance_m": c.distance,
        }
        for c in completed
        if c.start is not None and not _overrides(c).get("exclude_from_totals")
    ]
    declined = {(p.id, cid) for p in planned if p.declined_json for cid in json.loads(p.declined_json)}
    return p_in, a_in, declined


def build_calendar(session: Session, owner_id: str, start: date, end: date) -> dict:
    if end < start:
        raise PlanningError("'to' can't be before 'from'")
    if (end - start).days + 1 > MAX_CALENDAR_DAYS:
        raise PlanningError(f"Ask for at most {MAX_CALENDAR_DAYS} days at a time")
    today_ = today()
    planned = list_planned(session, owner_id, start, end)
    # Matching looks one day either side, so fetch that wider window of workouts and plans.
    wide_planned = list_planned(session, owner_id, start - timedelta(days=1), end + timedelta(days=1))
    completed_wide = _completed_in_range(session, start - timedelta(days=1), end + timedelta(days=1))
    completed = [c for c in completed_wide if c.start is not None and start <= pl.local_date(c.start, _tz()) <= end]
    link_by_canonical = {p.linked_canonical_id: p.id for p in wide_planned if p.linked_canonical_id is not None}
    events = list_events(session, owner_id, start, end)
    phases = [phase_dict(p, session) for p in list_phases(session, owner_id) if p.start_date <= end and p.end_date >= start]

    p_in, a_in, declined = _match_inputs(wide_planned, [c for c in completed_wide if c.id not in link_by_canonical])
    suggestions = [s for s in pl.suggest_matches(p_in, a_in, declined) if any(p.id == s["planned_id"] and start <= p.date <= end for p in planned)]

    days: dict[str, dict] = {}
    for i in range((end - start).days + 1):
        d = start + timedelta(days=i)
        days[d.isoformat()] = {"date": d, "planned": [], "completed": [], "events": [], "phase_id": None}
    for p in planned:
        days[p.date.isoformat()]["planned"].append(planned_dict(p, today_))
    for c in sorted(completed, key=lambda c: c.start):
        days[pl.local_date(c.start, _tz()).isoformat()]["completed"].append(_completed_dict(c, link_by_canonical.get(c.id)))
    for e in events:
        days[e.date.isoformat()]["events"].append(event_dict(e, today_))
    for ph in phases:
        for key, day in days.items():
            if ph["start_date"] <= day["date"] <= ph["end_date"]:
                day["phase_id"] = ph["id"]
    return {
        "from": start,
        "to": end,
        "today": today_,
        "days": list(days.values()),
        "phases": phases,
        "suggestions": suggestions,
    }


def _completed_minutes_by_week(session: Session, first_week: date, last_week: date) -> dict[date, dict]:
    out: dict[date, dict] = {}
    for a in _qualifying_activities(session, first_week, last_week + timedelta(days=7)):
        if a.start is None:
            continue
        wk = pl.week_start(pl.local_date(a.start, _tz()))
        bucket = out.setdefault(wk, {"minutes": 0.0, "sessions": 0, "strength_sessions": 0})
        bucket["minutes"] += (a.duration or 0.0) / 60.0
        bucket["sessions"] += 1
        if a.sport_family == "strength":
            bucket["strength_sessions"] += 1
    return out


def _completed_zone_seconds(session: Session, week: date) -> dict[str, float] | None:
    """Zone seconds for one past/current week from the same function the Trends page uses
    (so the two can't disagree). Only the last 52 weeks exist there; older or future weeks
    return None rather than a made-up number."""
    from catch.api.routes_analytics import trends_volume

    this_week = pl.week_start(today())
    if week > this_week:
        return None
    back = (this_week - week).days // 7 + 1
    if back > 52:
        return None
    rows = trends_volume(weeks=back, db=session)
    row = next((r for r in rows if r["week_start"] == week), None)
    return dict(row["zones"]) if row else None


def review_flags(session: Session, owner_id: str, first_week: date, n_weeks: int, settings: dict | None = None) -> list[dict]:
    settings = settings or get_settings(session)
    threshold = settings["planning"]["review_threshold_pct"]
    today_ = today()
    this_week = pl.week_start(today_)
    weeks = [first_week + timedelta(weeks=i) for i in range(n_weeks)]
    # Baseline = the 4 weeks of *completed* training before the earlier of "that week" and
    # "this week": a future plan is judged against what was actually trained recently.
    done = _completed_minutes_by_week(session, min(weeks[0], this_week) - timedelta(weeks=4), max(weeks[-1], this_week))
    planned_rows = list_planned(session, owner_id, weeks[0], weeks[-1] + timedelta(days=6))
    by_week: dict[date, list[dict]] = {w: [] for w in weeks}
    for p in planned_rows:
        by_week[pl.week_start(p.date)].append(_planned_input(p))
    phases = list_phases(session, owner_id)
    entries = []
    for w in weeks:
        ref_week = min(w, this_week)
        prior = [done.get(ref_week - timedelta(weeks=i), {}).get("minutes", 0.0) for i in range(1, 5)]
        baseline = sum(prior) / 4.0 if any(prior) else None
        ph = next((p for p in phases if p.start_date <= w + timedelta(days=3) <= p.end_date), None)
        approved = ph is not None and ph.coach_approved_at is not None
        entries.append(
            {
                "week_start": w,
                "planned_minutes": pl.planned_totals(by_week[w])["minutes"],
                "completed_baseline_minutes": baseline,
                "phase_kind": ph.kind if ph else None,
                "phase_approved": approved,
            }
        )
    confidence = _history_confidence(_history_days(session, today_), settings)
    return pl.workload_change_flags(entries, threshold, confidence)


def build_week_summary(session: Session, owner_id: str, week: date) -> dict:
    week = pl.week_start(week)
    settings = get_settings(session)
    end = week + timedelta(days=6)
    planned_rows = list_planned(session, owner_id, week, end)
    planned_in = [_planned_input(p) for p in planned_rows]
    planned = pl.planned_totals(planned_in)
    done = _completed_minutes_by_week(session, week, week).get(week, {"minutes": 0.0, "sessions": 0, "strength_sessions": 0})
    zone_seconds = _completed_zone_seconds(session, week)
    zone_minutes = {z: (zone_seconds or {}).get(z, 0.0) / 60.0 for z in ZONE_ORDER}
    completed_pct = pl.zone_pct(zone_minutes)
    phase = phase_on(session, owner_id, week + timedelta(days=3)) or phase_on(session, owner_id, week)
    targets = weekly_targets(session, phase, settings)
    flags = review_flags(session, owner_id, week, 3, settings)
    return {
        "week_start": week,
        "week_end": end,
        "planned": {**planned, "zone_pct": pl.zone_pct(planned["zone_minutes"])},
        "completed": {**done, "zone_minutes": zone_minutes, "zone_pct": completed_pct, "zones_available": zone_seconds is not None},
        "targets": targets,
        "comparison": pl.compare_week_to_targets(planned, done, targets, completed_pct),
        "phase": phase_dict(phase, session) if phase else None,
        "review_flags": flags,
    }


def planned_load_context(session: Session, owner_id: str, settings: dict) -> dict:
    """The one thing the recommendation engine gets from the plan: pre-computed review flags
    for this week and the next two. Passed in through the evaluator `context` so that
    training_intelligence.py itself never reads a planned row."""
    this_week = pl.week_start(today())
    return {"flags": review_flags(session, owner_id, this_week, 3, settings)}


# --- Race planning --------------------------------------------------------------------------

_DIST_RE = re.compile(r"^\s*([\d.,]+)\s*(k|km|m|meters?|metres?)?\s*$", re.IGNORECASE)


def event_distance_m(event: Event) -> float | None:
    if event.distance_m:
        return float(event.distance_m)
    if not event.distance:
        return None
    match = _DIST_RE.match(event.distance.replace(" ", ""))
    if not match:
        return None
    value = float(match.group(1).replace(",", ""))
    unit = (match.group(2) or "m").lower()
    return value * 1000.0 if unit in ("k", "km") else value


def event_test_type(event: Event) -> str | None:
    dist = event_distance_m(event)
    return detect_test_type(dist, None, None) if dist else None


def event_projection(session: Session, owner_id: str, event_id: int) -> dict:
    """Composes the projections that already exist (linear trend over confirmed tests +
    the Paul's-law 2k estimate) and says what each rests on. No new model: if there isn't
    enough data the answer is `available: False` with the reason, not a guess."""
    event = _own_event(session, owner_id, event_id)
    today_ = today()
    settings = get_settings(session)
    test_type = event_test_type(event)
    goal_s = None
    if event.goal_time:
        try:
            goal_s = parse_goal_time(event.goal_time)
        except ValueError:
            goal_s = None
    base = {
        "event_id": event.id,
        "event_date": event.date,
        "days_to_go": pl.days_to_go(event.date, today_),
        "test_type": test_type,
        "goal_time_s": goal_s,
        "available": False,
        "reason": None,
        "trend": None,
        "predict_2k": None,
        "history": [],
        "assumptions": [],
        "uncertainty": None,
        "gap_to_goal_s": None,
    }
    if test_type is None or "distance_m" not in TEST_SPECS[test_type]:
        base["reason"] = (
            "Projections exist for standard erg test distances (500 m to 6 km). Set this event's distance "
            "to one of those to see one."
            if event.distance or event.distance_m
            else "This event has no distance set, so there's nothing to project."
        )
        return base

    history = sorted(
        ((date.fromisoformat(t["date"]), t["duration_s"]) for t in erg_test.list_tests(session, test_type) if t["date"] and t["duration_s"]),
        key=lambda h: h[0],
    )
    base["history"] = [{"date": d, "duration_s": v} for d, v in history]
    trend = project_time(history, event.date)
    base["trend"] = trend
    assumptions = [
        f"Straight-line trend through {len(history)} confirmed {test_type} result(s), extended to the event date.",
        "Assumes training and conditions between now and then resemble the period the results came from.",
        "Erg results only: wind, current, water and race-day conditions are not modelled.",
    ]
    if test_type == "2000m":
        p = predict_2k(rowing_predict.recent_rower_pieces(session, settings))
        base["predict_2k"] = p
        assumptions.append("The 2k estimate scales recent efforts at other distances with Paul's law (about +5 s per 500 m for each doubling of distance).")
    base["assumptions"] = assumptions

    value = trend.get("value")
    if value is None and base["predict_2k"] and base["predict_2k"].get("predicted_time_s") is not None:
        value = base["predict_2k"]["predicted_time_s"]
    if value is None:
        base["reason"] = trend.get("explanation") or "Not enough data to project."
        base["uncertainty"] = "No projection: too little data to say anything honest."
        return base
    base["available"] = True
    base["value_s"] = value
    rng = trend.get("range") or (base["predict_2k"] or {}).get("range")
    base["uncertainty"] = (
        "The band is ±1 standard deviation of how far past results sit from the trend line — a rough guide to spread, not a guarantee."
        if trend.get("value") is not None
        else "The band comes from the spread between the efforts used for the 2k estimate."
    )
    if len(history) < 5:
        base["uncertainty"] += f" Only {len(history)} result(s) back it, so treat it loosely."
    base["range_s"] = rng
    if goal_s is not None:
        base["gap_to_goal_s"] = value - goal_s
    return base


def event_overview(session: Session, owner_id: str, event_id: int) -> dict:
    event = _own_event(session, owner_id, event_id)
    today_ = today()
    phase = phase_on(session, owner_id, today_) if event.date >= today_ else None
    upcoming = list_planned(session, owner_id, today_, max(event.date, today_))
    test_type = event_test_type(event)
    tests = erg_test.list_tests(session, test_type) if test_type else []
    weeks_left = max(0, pl.days_to_go(event.date, today_)) / 7.0
    return {
        "event": event_dict(event, today_),
        "weeks_to_go": round(weeks_left, 1),
        "phase": phase_dict(phase, session) if phase else None,
        "planned_sessions_before_event": len([p for p in upcoming if p.session_type != "rest"]),
        "test_type": test_type,
        "tests": [
            {k: t[k] for k in ("kind", "canonical_id", "piece_id", "test_type", "title", "date", "distance_m", "duration_s")}
            for t in tests[:10]
        ],
        "pacing_plan": json.loads(event.plan_json) if event.plan_json else None,
        "linked_phases": [phase_dict(p, session) for p in session.exec(select(TrainingPhase).where(TrainingPhase.event_id == event.id)).all()],
    }


# --- Previews (coach/MCP write tools show these before anything is saved) -------------------


def _ser(value: Any) -> Any:
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def preview_create_planned(session: Session, owner_id: str, fields: dict, repeat: dict | None) -> dict:
    """Runs exactly the validation `create_planned` runs, without writing — so a preview that
    comes back clean can't fail on the confirming call for a reason the athlete never saw."""
    if "date" not in fields or "session_type" not in fields:
        raise PlanningError("date and session_type are required")
    clean = _prepare_fields(fields)
    _check_event(session, owner_id, clean.get("event_id"))
    try:
        dates = pl.expand_repeat(clean["date"], repeat)
    except ValueError as exc:
        raise PlanningError(str(exc)) from exc
    clean.setdefault("title", _DEFAULT_TITLES[clean["session_type"]])
    return {"count": len(dates), "dates": [d.isoformat() for d in dates], "session": {k: _ser(v) for k, v in clean.items() if k != "date"}}


def preview_update_planned(session: Session, owner_id: str, planned_id: int, fields: dict, scope: str) -> dict:
    if scope not in ("this", "this_and_following"):
        raise PlanningError("scope must be 'this' or 'this_and_following'")
    row = get_planned(session, owner_id, planned_id)
    clean = _prepare_fields(fields)
    _check_event(session, owner_id, clean.get("event_id"))
    current = planned_dict(row)
    changes = {}
    for key, value in clean.items():
        if key in ("notes", "coach_feedback", "status") and scope == "this_and_following":
            continue
        if current.get(key) != value:
            changes[key] = {"from": _ser(current.get(key)), "to": _ser(value)}
    targets = _series_following(session, owner_id, row) if scope == "this_and_following" else [row]
    if clean.get("session_type") == "rest" and any(t.linked_canonical_id is not None for t in targets):
        raise PlanningError("Unlink the workout before turning this into a rest day")
    return {"planned_id": planned_id, "sessions_affected": len(targets), "changes": changes}


def preview_delete_planned(session: Session, owner_id: str, planned_id: int, scope: str) -> dict:
    if scope not in ("this", "this_and_following"):
        raise PlanningError("scope must be 'this' or 'this_and_following'")
    row = get_planned(session, owner_id, planned_id)
    targets = _series_following(session, owner_id, row) if scope == "this_and_following" else [row]
    return {
        "sessions_to_delete": [
            {"id": t.id, "date": t.date.isoformat(), "title": t.title, "linked_to_a_workout": t.linked_canonical_id is not None} for t in targets
        ],
        "note": "A linked workout itself is never deleted — only the plan entry.",
    }


def preview_create_event(fields: dict) -> dict:
    unknown = set(fields) - set(_EVENT_FIELDS)
    if unknown:
        raise PlanningError(f"Unknown event field(s): {sorted(unknown)}")
    fields = _coerce_dates(fields, "date")
    if not fields.get("name") or fields.get("date") is None or not fields.get("type"):
        raise PlanningError("name, date and type are required")
    _validate_event(fields)
    return {k: _ser(v) for k, v in fields.items() if v is not None}


def preview_update_event(session: Session, owner_id: str, event_id: int, fields: dict) -> dict:
    event = _own_event(session, owner_id, event_id)
    unknown = set(fields) - set(_EVENT_FIELDS)
    if unknown:
        raise PlanningError(f"Unknown event field(s): {sorted(unknown)}")
    fields = _coerce_dates(fields, "date")
    _validate_event(fields)
    current = event_dict(event)
    return {
        "event_id": event_id,
        "name": event.name,
        "changes": {k: {"from": _ser(current.get(k)), "to": _ser(v)} for k, v in fields.items() if current.get(k) != v},
    }


def preview_delete_event(session: Session, owner_id: str, event_id: int) -> dict:
    event = _own_event(session, owner_id, event_id)
    refs = [p.id for p in session.exec(select(PlannedWorkout).where(PlannedWorkout.event_id == event_id)).all()]
    return {"event_id": event_id, "name": event.name, "date": event.date.isoformat(), "planned_sessions_unlinked_from_event": len(refs)}


def compact_calendar(cal: dict) -> dict:
    """The calendar payload trimmed for an LLM context window: empty days dropped, only the
    fields a coach reasons from. Planned and completed stay in separate keys."""
    days = []
    for d in cal["days"]:
        if not (d["planned"] or d["completed"] or d["events"]):
            continue
        days.append(
            {
                "date": d["date"].isoformat(),
                "planned": [
                    {k: p[k] for k in ("id", "title", "session_type", "duration_min", "distance_m", "target_zone", "display_status", "linked_canonical_id")}
                    for p in d["planned"]
                ],
                "completed": [
                    {k: c[k] for k in ("id", "title", "sport_family", "duration_min", "distance_m", "is_test", "linked_planned_id")} for c in d["completed"]
                ],
                "events": [{k: e[k] for k in ("id", "name", "type", "priority", "days_to_go")} for e in d["events"]],
            }
        )
    return {
        "from": cal["from"].isoformat(),
        "to": cal["to"].isoformat(),
        "days": days,
        "phases": [{k: p[k] for k in ("id", "kind", "name", "start_date", "end_date", "coach_approved")} for p in cal["phases"]],
        "possible_matches": cal["suggestions"],
        "note": "'planned' entries are intentions, not training done; only 'completed' entries count as training.",
    }
