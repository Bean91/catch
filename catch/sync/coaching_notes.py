from __future__ import annotations

"""Session 22 (see PLAN.md, docs/library.md): technique notes and coach feedback.

Every read takes the caller's `Principal` and filters through catch/core/principal.py — the same
functions the tests table-drive — so "private never reaches a coach" is one rule, not one per
endpoint. A row that belongs to another owner is *not found*; one the caller may not see is
also *not found* (never "forbidden", which would confirm it exists).

Technique notes are the athlete's own words. There is no rating, score or quality field, and
nothing here derives one: Catch's data (strokes, HR, GPS) does not measure technique quality."""

import json
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlmodel import Session, select

from catch.analytics.planning import aware_utc, local_date
from catch.core import principal as pr
from catch.core.models import CanonicalActivity, CoachFeedback, CoachFeedbackRevision, Event, Piece, PlannedWorkout, TechniqueNote
from catch.core.principal import Principal

TECHNIQUE_CATEGORIES = ("catch", "drive", "finish", "recovery", "sequencing", "posture", "rate_control", "blade_boat_handling")
OTHER_FOCUS = ("pacing", "fitness", "strength", "racing", "other")
FOCUS_AREAS = TECHNIQUE_CATEGORIES + OTHER_FOCUS
CREATED_VIA = ("web", "ai_coach", "mcp", "rest")
MAX_TEXT = 4000
MAX_MEDIA = 5
MAX_LIST = 500
CANNOT_RATE = "Catch can't observe technique from this data — these are the athlete's and coach's own words, not a measurement."


class CoachingError(ValueError):
    pass


class NotFound(CoachingError):
    pass


class Forbidden(CoachingError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _text(value: Any, field: str, *, required: bool = True) -> Optional[str]:
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise CoachingError(f"{field} is required")
        return None
    if not isinstance(value, str):
        raise CoachingError(f"{field} must be text")
    value = value.strip()
    if len(value) > MAX_TEXT:
        raise CoachingError(f"{field} can be at most {MAX_TEXT} characters")
    return value


def _date(value: Any, field: str) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise CoachingError(f"{field} must be an ISO date (YYYY-MM-DD)") from exc


# --- References (workout / piece / event / plan) --------------------------------------------------


def _canonical_label(session: Session, canonical_id: Optional[int]) -> Optional[dict]:
    if canonical_id is None:
        return None
    c = session.get(CanonicalActivity, canonical_id)
    if c is None:
        return None
    day = local_date(c.start) if c.start else None
    return {"id": c.id, "title": c.title or c.sport_family or "Workout", "date": day.isoformat() if day else None}


def _require_canonical(session: Session, canonical_id: Any) -> int:
    if isinstance(canonical_id, bool) or not isinstance(canonical_id, int) or session.get(CanonicalActivity, canonical_id) is None:
        raise NotFound(f"No workout with id {canonical_id}")
    return canonical_id


def resolve_workout_on(session: Session, day: date) -> int:
    """For callers (a coach) who know a date but no id. Exactly one workout that local day, or a
    clear error naming how many — never a guess."""
    rows = session.exec(select(CanonicalActivity).where(CanonicalActivity.start.is_not(None))).all()
    matches = [c for c in rows if c.start and local_date(c.start) == day and c.absorbed_into_piece_id is None]
    if not matches:
        raise CoachingError(f"No workout on {day.isoformat()}")
    if len(matches) > 1:
        raise CoachingError(f"{len(matches)} workouts on {day.isoformat()} — say which (e.g. by title) or use a workout id")
    return matches[0].id


# --- Technique notes -------------------------------------------------------------------------------


def _clean_media(value: Any) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_MEDIA:
        raise CoachingError(f"media must be a list of at most {MAX_MEDIA} references")
    out = []
    for m in value:
        if not isinstance(m, dict):
            raise CoachingError("each media reference needs a url")
        url = str(m.get("url") or "").strip()
        if not (url.startswith("https://") or url.startswith("http://") or (url.startswith("/") and not url.startswith("//"))):
            raise CoachingError("media urls must start with http://, https:// or /")
        if len(url) > 500:
            raise CoachingError("media url is too long")
        label = str(m.get("label") or "").strip()[:100]
        out.append({"url": url, "label": label})
    return out


def note_dict(session: Session, row: TechniqueNote) -> dict:
    piece = session.get(Piece, row.piece_id) if row.piece_id else None
    return {
        "id": row.id,
        "category": row.category,
        "text": row.text,
        "visibility": row.visibility,
        "shared_with_coach": row.visibility == "coach",
        "workout": _canonical_label(session, row.canonical_id),
        "piece": {"id": piece.id, "piece_type": piece.piece_type} if piece else None,
        "date": row.note_date,
        "media": json.loads(row.media_json or "[]"),
        "note": CANNOT_RATE,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _note_fields(session: Session, fields: dict, existing: Optional[TechniqueNote] = None) -> dict:
    allowed = {"category", "text", "canonical_id", "piece_id", "note_date", "date", "visibility", "media"}
    unknown = set(fields) - allowed
    if unknown:
        raise CoachingError(f"Unknown technique-note field(s): {sorted(unknown)}")
    out: dict = {}
    if "category" in fields or existing is None:
        if fields.get("category") not in TECHNIQUE_CATEGORIES:
            raise CoachingError(f"category must be one of {list(TECHNIQUE_CATEGORIES)}")
        out["category"] = fields["category"]
    if "text" in fields or existing is None:
        out["text"] = _text(fields.get("text"), "text")
    if "visibility" in fields:
        if fields["visibility"] not in pr.NOTE_VISIBILITIES:
            raise CoachingError(f"visibility must be one of {list(pr.NOTE_VISIBILITIES)}")
        out["visibility"] = fields["visibility"]
    if "media" in fields:
        out["media_json"] = json.dumps(_clean_media(fields["media"]))
    if "note_date" in fields or "date" in fields:
        out["note_date"] = _date(fields.get("note_date", fields.get("date")), "date")
    canonical = existing.canonical_id if existing else None
    piece_id = existing.piece_id if existing else None
    touched = "canonical_id" in fields or "piece_id" in fields
    if "canonical_id" in fields:
        canonical = None if fields["canonical_id"] is None else _require_canonical(session, fields["canonical_id"])
    if "piece_id" in fields:
        piece_id = fields["piece_id"]
    if piece_id is not None:
        piece = session.get(Piece, piece_id) if isinstance(piece_id, int) and not isinstance(piece_id, bool) else None
        if piece is None:
            raise NotFound(f"No piece with id {piece_id}")
        if canonical is not None and canonical != piece.canonical_id:
            raise CoachingError("That piece belongs to a different workout")
        canonical = piece.canonical_id
    if touched:
        out["canonical_id"] = canonical
        out["piece_id"] = piece_id
    return out


def create_technique_note(session: Session, owner_id: str, principal: Principal, fields: dict) -> TechniqueNote:
    if not principal.is_athlete:
        raise Forbidden("Only the athlete writes technique notes")
    clean = _note_fields(session, fields)
    clean.setdefault("visibility", "private")
    row = TechniqueNote(owner_id=owner_id, **clean)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def preview_technique_note(session: Session, owner_id: str, principal: Principal, fields: dict) -> dict:
    if not principal.is_athlete:
        raise Forbidden("Only the athlete writes technique notes")
    clean = _note_fields(session, fields)
    clean.setdefault("visibility", "private")
    clean["media"] = json.loads(clean.pop("media_json", "[]"))
    return {k: (v.isoformat() if isinstance(v, date) else v) for k, v in clean.items()}


def _own_note(session: Session, owner_id: str, principal: Principal, note_id: int) -> TechniqueNote:
    row = session.get(TechniqueNote, note_id)
    if row is None or row.owner_id != owner_id or not pr.note_visible(row.visibility, principal):
        raise NotFound(f"No technique note with id {note_id}")
    return row


def update_technique_note(session: Session, owner_id: str, principal: Principal, note_id: int, fields: dict) -> TechniqueNote:
    row = _own_note(session, owner_id, principal, note_id)
    if not principal.is_athlete:
        raise Forbidden("Only the athlete edits technique notes")
    for k, v in _note_fields(session, fields, existing=row).items():
        setattr(row, k, v)
    row.updated_at = _now()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def delete_technique_note(session: Session, owner_id: str, principal: Principal, note_id: int) -> None:
    row = _own_note(session, owner_id, principal, note_id)
    if not principal.is_athlete:
        raise Forbidden("Only the athlete deletes technique notes")
    session.delete(row)
    session.commit()


def list_technique_notes(
    session: Session,
    owner_id: str,
    principal: Principal,
    *,
    canonical_id: Optional[int] = None,
    piece_id: Optional[int] = None,
    note_date: Optional[date] = None,
    category: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = 50,
) -> list[TechniqueNote]:
    stmt = select(TechniqueNote).where(TechniqueNote.owner_id == owner_id)
    if not principal.is_athlete:
        if principal.role != pr.COACH_ROLE:
            return []
        stmt = stmt.where(TechniqueNote.visibility == "coach")
    if canonical_id is not None:
        stmt = stmt.where(TechniqueNote.canonical_id == canonical_id)
    if piece_id is not None:
        stmt = stmt.where(TechniqueNote.piece_id == piece_id)
    if note_date is not None:
        stmt = stmt.where(TechniqueNote.note_date == note_date)
    if date_from is not None:
        stmt = stmt.where(TechniqueNote.note_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(TechniqueNote.note_date <= date_to)
    if category:
        if category not in TECHNIQUE_CATEGORIES:
            raise CoachingError(f"category must be one of {list(TECHNIQUE_CATEGORIES)}")
        stmt = stmt.where(TechniqueNote.category == category)
    rows = session.exec(stmt.order_by(TechniqueNote.created_at.desc(), TechniqueNote.id.desc())).all()
    rows = [r for r in rows if pr.note_visible(r.visibility, principal)]
    return rows[: max(1, min(int(limit), MAX_LIST))]


# --- Coach feedback ---------------------------------------------------------------------------------


def _focus(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 8 or not all(isinstance(v, str) for v in value):
        raise CoachingError("focus_areas must be a short list of areas")
    bad = [v for v in value if v not in FOCUS_AREAS]
    if bad:
        raise CoachingError(f"focus_areas must come from {list(FOCUS_AREAS)}")
    return list(dict.fromkeys(value))


def _check_links(session: Session, owner_id: str, fields: dict) -> dict:
    out: dict = {}
    if fields.get("canonical_id") is not None:
        out["canonical_id"] = _require_canonical(session, fields["canonical_id"])
    elif "canonical_id" in fields:
        out["canonical_id"] = None
    if fields.get("event_id") is not None:
        ev = session.get(Event, fields["event_id"]) if isinstance(fields["event_id"], int) else None
        if ev is None or ev.owner_id not in (None, owner_id):
            raise NotFound(f"No event with id {fields['event_id']}")
        out["event_id"] = ev.id
    elif "event_id" in fields:
        out["event_id"] = None
    if fields.get("planned_id") is not None:
        pw = session.get(PlannedWorkout, fields["planned_id"]) if isinstance(fields["planned_id"], int) else None
        if pw is None or pw.owner_id != owner_id:
            raise NotFound(f"No planned session with id {fields['planned_id']}")
        out["planned_id"] = pw.id
    elif "planned_id" in fields:
        out["planned_id"] = None
    return out


def feedback_dict(session: Session, row: CoachFeedback, principal: Principal, *, edit_count: Optional[int] = None) -> dict:
    ev = session.get(Event, row.event_id) if row.event_id else None
    pw = session.get(PlannedWorkout, row.planned_id) if row.planned_id else None
    if edit_count is None:
        edit_count = len(_visible_revisions(session, row, principal, kinds=("edit",)))
    return {
        "id": row.id,
        "author": {"role": row.author_role, "id": row.author_id, "name": row.author_name},
        "coach_name": row.coach_name,
        "created_via": row.created_via,
        "date": row.entry_date,
        "text": row.text,
        "focus_areas": json.loads(row.focus_areas_json or "[]"),
        "visibility": row.visibility,
        "shared": row.visibility == "shared",
        "workout": _canonical_label(session, row.canonical_id),
        "event": {"id": ev.id, "name": ev.name, "date": ev.date} if ev else None,
        "planned": {"id": pw.id, "title": pw.title, "date": pw.date} if pw else None,
        "athlete_response": row.athlete_response,
        "athlete_response_at": row.athlete_response_at,
        "edited": edit_count > 0,
        "edit_count": edit_count,
        "can_edit": pr.can_edit_feedback(row.author_id, row.author_role, principal),
        "can_respond": pr.can_respond_to_feedback(row.visibility, row.author_id, principal),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _visible_revisions(session: Session, row: CoachFeedback, principal: Principal, kinds: Optional[tuple[str, ...]] = None) -> list[CoachFeedbackRevision]:
    revs = session.exec(select(CoachFeedbackRevision).where(CoachFeedbackRevision.feedback_id == row.id).order_by(CoachFeedbackRevision.revision_no)).all()
    return [r for r in revs if pr.feedback_visible(r.visibility, row.author_id, principal) and (kinds is None or r.kind in kinds)]


def _record_revision(session: Session, row: CoachFeedback, kind: str, by: Principal) -> None:
    last = session.exec(select(CoachFeedbackRevision.revision_no).where(CoachFeedbackRevision.feedback_id == row.id).order_by(CoachFeedbackRevision.revision_no.desc())).first()
    session.add(
        CoachFeedbackRevision(
            feedback_id=row.id, revision_no=(last or 0) + 1, kind=kind, text=row.text, focus_areas_json=row.focus_areas_json,
            visibility=row.visibility, athlete_response=row.athlete_response, edited_by_id=by.id, edited_by_name=by.name or by.role,
        )
    )


def _authoring(principal: Principal, fields: dict, via: str) -> dict:
    if via not in CREATED_VIA:
        raise CoachingError(f"created_via must be one of {list(CREATED_VIA)}")
    if principal.role == pr.COACH_ROLE:
        if fields.get("visibility") not in (None, "shared"):
            raise CoachingError("A coach's feedback is always shared with the athlete")
        if fields.get("coach_name"):
            raise CoachingError("coach_name is only for feedback the athlete logs")
        return {"author_role": "coach", "author_id": principal.id, "author_name": principal.name, "visibility": "shared", "coach_name": None, "created_via": via}
    if principal.is_athlete:
        vis = fields.get("visibility", "shared")
        if vis not in pr.FEEDBACK_VISIBILITIES:
            raise CoachingError(f"visibility must be one of {list(pr.FEEDBACK_VISIBILITIES)}")
        name = (fields.get("coach_name") or "").strip()[:80] or None
        return {"author_role": "athlete", "author_id": principal.id, "author_name": principal.name or "You", "visibility": vis, "coach_name": name, "created_via": via}
    raise Forbidden("This caller can't write feedback")


_FEEDBACK_CREATE = {"text", "date", "entry_date", "canonical_id", "event_id", "planned_id", "workout_date", "focus_areas", "visibility", "coach_name"}


def _feedback_create_fields(session: Session, owner_id: str, principal: Principal, fields: dict, via: str) -> dict:
    unknown = set(fields) - _FEEDBACK_CREATE
    if unknown:
        raise CoachingError(f"Unknown feedback field(s): {sorted(unknown)}")
    out = _authoring(principal, fields, via)
    out["text"] = _text(fields.get("text"), "text")
    out["focus_areas_json"] = json.dumps(_focus(fields.get("focus_areas")))
    links = {k: fields[k] for k in ("canonical_id", "event_id", "planned_id") if fields.get(k) is not None}
    if fields.get("workout_date") and "canonical_id" not in links:
        links["canonical_id"] = resolve_workout_on(session, _date(fields["workout_date"], "workout_date"))
    out.update(_check_links(session, owner_id, links))
    out["entry_date"] = _date(fields.get("entry_date", fields.get("date")), "date") or planning_today()
    return out


def planning_today() -> date:
    from catch.sync import planning

    return planning.today()


def create_feedback(session: Session, owner_id: str, principal: Principal, fields: dict, via: str = "web") -> CoachFeedback:
    row = CoachFeedback(owner_id=owner_id, **_feedback_create_fields(session, owner_id, principal, fields, via))
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def preview_feedback(session: Session, owner_id: str, principal: Principal, fields: dict, via: str = "mcp") -> dict:
    clean = _feedback_create_fields(session, owner_id, principal, fields, via)
    return {
        "author": clean["author_name"], "author_role": clean["author_role"], "date": clean["entry_date"].isoformat(),
        "text": clean["text"], "focus_areas": json.loads(clean["focus_areas_json"]), "visibility": clean["visibility"],
        "coach_name": clean["coach_name"], "workout": _canonical_label(session, clean.get("canonical_id")),
        "event_id": clean.get("event_id"), "planned_id": clean.get("planned_id"),
    }


def _visible_feedback(session: Session, owner_id: str, principal: Principal, feedback_id: int) -> CoachFeedback:
    row = session.get(CoachFeedback, feedback_id)
    if row is None or row.owner_id != owner_id or row.deleted_at is not None or not pr.feedback_visible(row.visibility, row.author_id, principal):
        raise NotFound(f"No feedback entry with id {feedback_id}")
    return row


def get_feedback(session: Session, owner_id: str, principal: Principal, feedback_id: int) -> CoachFeedback:
    return _visible_feedback(session, owner_id, principal, feedback_id)


def update_feedback(session: Session, owner_id: str, principal: Principal, feedback_id: int, fields: dict) -> CoachFeedback:
    row = _visible_feedback(session, owner_id, principal, feedback_id)
    if not pr.can_edit_feedback(row.author_id, row.author_role, principal):
        raise Forbidden("Only the author can edit this feedback")
    allowed = {"text", "focus_areas", "visibility", "date", "entry_date", "canonical_id", "event_id", "planned_id"}
    unknown = set(fields) - allowed
    if unknown:
        raise CoachingError(f"Unknown feedback field(s): {sorted(unknown)}")
    updates: dict = {}
    if "text" in fields:
        updates["text"] = _text(fields["text"], "text")
    if "focus_areas" in fields:
        updates["focus_areas_json"] = json.dumps(_focus(fields["focus_areas"]))
    if "visibility" in fields:
        if fields["visibility"] not in pr.FEEDBACK_VISIBILITIES:
            raise CoachingError(f"visibility must be one of {list(pr.FEEDBACK_VISIBILITIES)}")
        if principal.role == pr.COACH_ROLE and fields["visibility"] != "shared":
            raise CoachingError("A coach's feedback is always shared with the athlete")
        updates["visibility"] = fields["visibility"]
    if "date" in fields or "entry_date" in fields:
        d = _date(fields.get("entry_date", fields.get("date")), "date")
        if d is None:
            raise CoachingError("date can't be empty")
        updates["entry_date"] = d
    updates.update(_check_links(session, owner_id, {k: fields[k] for k in ("canonical_id", "event_id", "planned_id") if k in fields}))
    changed = {k: v for k, v in updates.items() if getattr(row, k) != v}
    if not changed:
        return row
    _record_revision(session, row, "edit", principal)
    for k, v in changed.items():
        setattr(row, k, v)
    row.updated_at = _now()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def respond_to_feedback(session: Session, owner_id: str, principal: Principal, feedback_id: int, response: Optional[str]) -> CoachFeedback:
    row = _visible_feedback(session, owner_id, principal, feedback_id)
    if not pr.can_respond_to_feedback(row.visibility, row.author_id, principal):
        raise Forbidden("Only the athlete can respond to feedback")
    text = _text(response, "response", required=False)
    if text == row.athlete_response:
        return row
    _record_revision(session, row, "response", principal)
    row.athlete_response = text
    row.athlete_response_at = _now() if text else None
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def delete_feedback(session: Session, owner_id: str, principal: Principal, feedback_id: int) -> None:
    row = _visible_feedback(session, owner_id, principal, feedback_id)
    if not pr.can_edit_feedback(row.author_id, row.author_role, principal):
        raise Forbidden("Only the author can delete this feedback")
    _record_revision(session, row, "delete", principal)
    row.deleted_at = _now()
    session.add(row)
    session.commit()


def feedback_history(session: Session, owner_id: str, principal: Principal, feedback_id: int) -> list[dict]:
    row = _visible_feedback(session, owner_id, principal, feedback_id)
    return [
        {
            "revision_no": r.revision_no, "kind": r.kind, "text": r.text, "focus_areas": json.loads(r.focus_areas_json or "[]"),
            "visibility": r.visibility, "athlete_response": r.athlete_response,
            "edited_by": r.edited_by_name, "edited_at": aware_utc(r.edited_at),
        }
        for r in _visible_revisions(session, row, principal)
    ]


def list_feedback(
    session: Session,
    owner_id: str,
    principal: Principal,
    *,
    coach: Optional[str] = None,
    category: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    canonical_id: Optional[int] = None,
    event_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[CoachFeedback]:
    if principal.role not in (pr.ATHLETE_ROLE, pr.COACH_ROLE):
        return []
    stmt = select(CoachFeedback).where(CoachFeedback.owner_id == owner_id, CoachFeedback.deleted_at.is_(None))
    if date_from is not None:
        stmt = stmt.where(CoachFeedback.entry_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(CoachFeedback.entry_date <= date_to)
    if canonical_id is not None:
        stmt = stmt.where(CoachFeedback.canonical_id == canonical_id)
    if event_id is not None:
        stmt = stmt.where(CoachFeedback.event_id == event_id)
    if category and category not in FOCUS_AREAS:
        raise CoachingError(f"category must be one of {list(FOCUS_AREAS)}")
    rows = session.exec(stmt.order_by(CoachFeedback.entry_date.desc(), CoachFeedback.id.desc())).all()
    rows = [r for r in rows if pr.feedback_visible(r.visibility, r.author_id, principal)]
    if category:
        rows = [r for r in rows if category in json.loads(r.focus_areas_json or "[]")]
    if coach and coach.strip():
        needle = coach.strip().lower()
        rows = [r for r in rows if needle in (r.coach_name or r.author_name or "").lower() or needle in (r.author_name or "").lower()]
    offset = max(0, int(offset))
    return rows[offset : offset + max(1, min(int(limit), MAX_LIST))]


def list_coach_names(session: Session, owner_id: str, principal: Principal) -> list[str]:
    names = {(r.coach_name or r.author_name) for r in list_feedback(session, owner_id, principal, limit=MAX_LIST) if r.author_role == "coach" or r.coach_name}
    return sorted(n for n in names if n)


# --- References that go stale ------------------------------------------------------------------------


def repoint_canonical(session: Session, keep_id: int, drop_id: int) -> None:
    """The matching engine merged two canonicals and will delete `drop`: notes and feedback follow
    the survivor (SQLite doesn't enforce foreign keys here — session 21's lesson)."""
    for model in (TechniqueNote, CoachFeedback):
        for row in session.exec(select(model).where(model.canonical_id == drop_id)).all():
            row.canonical_id = keep_id
            session.add(row)


def detach_event(session: Session, event_id: int) -> None:
    for row in session.exec(select(CoachFeedback).where(CoachFeedback.event_id == event_id)).all():
        row.event_id = None
        session.add(row)


def detach_planned(session: Session, planned_ids: list[int]) -> None:
    if not planned_ids:
        return
    for row in session.exec(select(CoachFeedback).where(CoachFeedback.planned_id.in_(planned_ids))).all():
        row.planned_id = None
        session.add(row)


def detach_piece(session: Session, piece_id: int) -> None:
    for row in session.exec(select(TechniqueNote).where(TechniqueNote.piece_id == piece_id)).all():
        row.piece_id = None
        session.add(row)
