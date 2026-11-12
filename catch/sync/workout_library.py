from __future__ import annotations

"""Session 22 (see PLAN.md, docs/library.md): the DB-facing half of the workout library.

Same ownership contract as catch/sync/planning.py: every function takes `owner_id`, and a row
that belongs to someone else is *not found*. A template is never a workout — scheduling one
copies it into a `PlannedWorkout` snapshot through planning.create_planned, so the calendar,
the plan-to-workout matcher and every "planned never counts" guarantee apply unchanged."""

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlmodel import Session, select

from catch.analytics import workout_library as wl
from catch.core.models import Exercise, PlannedWorkout, WorkoutTemplate
from catch.core.principal import OWNER_ID
from catch.sync import planning

SEED_PATH = Path(__file__).resolve().parent.parent / "seed" / "workout_templates.json"
EXAMPLE_LABEL = "Example — not prescribed training"
MAX_LIST = 200

_WRITABLE = ("name", "description", "workout_type", "session_type", "purpose", "difficulty", "target_zone", "tags", "structure")


class LibraryError(ValueError):
    pass


class NotFound(LibraryError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _own(session: Session, owner_id: str, template_id: int) -> WorkoutTemplate:
    row = session.get(WorkoutTemplate, template_id)
    if row is None or row.owner_id != owner_id:
        raise NotFound(f"No workout template with id {template_id}")
    return row


def template_dict(row: WorkoutTemplate, *, summary: bool = True) -> dict:
    structure = json.loads(row.structure_json or "{}")
    out = {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "workout_type": row.workout_type,
        "session_type": row.session_type,
        "sport_family": row.sport_family,
        "purpose": row.purpose,
        "difficulty": row.difficulty,
        "target_zone": row.target_zone,
        "tags": json.loads(row.tags_json or "[]"),
        "structure": structure,
        "is_example": row.is_example,
        "example_label": EXAMPLE_LABEL if row.is_example else None,
        "duplicated_from_id": row.duplicated_from_id,
        "archived": row.archived_at is not None,
        "signature": wl.template_signature(structure),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
    if summary:
        out["summary"] = wl.summarize_template(structure, row.target_zone)
    return out


def _check_exercises(session: Session, structure: dict) -> list[dict]:
    issues = []
    for i, item in enumerate(structure.get("strength_items") or []):
        eid = item.get("exercise_id") if isinstance(item, dict) else None
        if isinstance(eid, int) and session.get(Exercise, eid) is None:
            issues.append({"path": f"structure.strength_items[{i}].exercise_id", "message": "No exercise with that id in the library."})
    return issues


def validate(session: Session, fields: dict) -> dict:
    """The one validation path: pure rules, then the checks that need the database."""
    candidate = dict(fields)
    result = wl.validate_template(candidate)
    issues = list(result["issues"])
    if isinstance(candidate.get("structure"), dict):
        issues += _check_exercises(session, candidate["structure"])
    return {"ok": not issues, "issues": issues}


def preview_template(session: Session, fields: dict) -> dict:
    """Validation plus the server-computed totals, for the editor's live summary. The browser
    holds no interval math."""
    merged = {**fields}
    merged.setdefault("session_type", wl.default_session_type(merged.get("workout_type", "")))
    result = validate(session, merged)
    out: dict[str, Any] = {**result, "summary": None, "planned": None}
    if result["ok"]:
        structure = merged.get("structure") or {}
        out["summary"] = wl.summarize_template(structure, merged.get("target_zone"))
        out["signature"] = wl.template_signature(structure)
        out["planned"] = wl.to_planned_fields({**merged, "name": merged.get("name", ""), "structure": structure})
    return out


def _raise_issues(result: dict) -> None:
    if not result["ok"]:
        first = result["issues"][0]
        extra = f" (+{len(result['issues']) - 1} more)" if len(result["issues"]) > 1 else ""
        raise LibraryError(f"{first['path']}: {first['message']}{extra}")


def _clean(fields: dict) -> dict:
    unknown = set(fields) - set(_WRITABLE)
    if unknown:
        raise LibraryError(f"Unknown template field(s): {sorted(unknown)}")
    out = {k: v for k, v in fields.items() if k in _WRITABLE}
    for key in ("name", "description", "purpose"):
        if isinstance(out.get(key), str):
            out[key] = out[key].strip() or None
    if isinstance(out.get("tags"), list):
        out["tags"] = list(dict.fromkeys(t.strip().lower() for t in out["tags"] if isinstance(t, str) and t.strip()))
    return out


def _row_fields(clean: dict) -> dict:
    wt = clean["workout_type"]
    st = clean.get("session_type") or wl.default_session_type(wt)
    row = {k: clean.get(k) for k in ("name", "description", "workout_type", "purpose", "difficulty", "target_zone")}
    row["session_type"] = st
    row["sport_family"] = planning.pl.family_for_session_type(st)
    row["tags_json"] = json.dumps(clean.get("tags") or [])
    row["structure_json"] = json.dumps(clean.get("structure") or {})
    return row


def create_template(session: Session, owner_id: str, fields: dict) -> WorkoutTemplate:
    clean = _clean(fields)
    _raise_issues(validate(session, {**clean, "session_type": clean.get("session_type") or wl.default_session_type(clean.get("workout_type", ""))}))
    row = WorkoutTemplate(owner_id=owner_id, **_row_fields(clean))
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _merged(row: WorkoutTemplate, clean: dict) -> dict:
    current = template_dict(row, summary=False)
    base = {k: current[k] for k in _WRITABLE}
    base.update(clean)
    if "workout_type" in clean and "session_type" not in clean:
        base["session_type"] = wl.default_session_type(base["workout_type"])
    return base


def update_template(session: Session, owner_id: str, template_id: int, fields: dict) -> WorkoutTemplate:
    row = _own(session, owner_id, template_id)
    if row.is_example:
        raise LibraryError("Examples are read-only — duplicate it to make your own copy.")
    clean = _clean(fields)
    if not clean:
        return row
    merged = _merged(row, clean)
    _raise_issues(validate(session, merged))
    for key, value in _row_fields(merged).items():
        setattr(row, key, value)
    row.updated_at = _now()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def preview_update_template(session: Session, owner_id: str, template_id: int, fields: dict) -> dict:
    row = _own(session, owner_id, template_id)
    if row.is_example:
        raise LibraryError("Examples are read-only — duplicate it to make your own copy.")
    clean = _clean(fields)
    merged = _merged(row, clean)
    _raise_issues(validate(session, merged))
    current = template_dict(row, summary=False)
    changes = {k: {"from": current[k], "to": merged[k]} for k in clean if current.get(k) != merged.get(k)}
    return {"id": row.id, "name": row.name, "changes": changes, "summary": wl.summarize_template(merged.get("structure") or {}, merged.get("target_zone"))}


def preview_create_template(session: Session, owner_id: str, fields: dict) -> dict:
    clean = _clean(fields)
    st = clean.get("session_type") or wl.default_session_type(clean.get("workout_type", ""))
    _raise_issues(validate(session, {**clean, "session_type": st}))
    structure = clean.get("structure") or {}
    return {"template": {**clean, "session_type": st}, "summary": wl.summarize_template(structure, clean.get("target_zone")), "signature": wl.template_signature(structure)}


def duplicate_template(session: Session, owner_id: str, template_id: int, name: Optional[str] = None) -> WorkoutTemplate:
    src = _own(session, owner_id, template_id)
    copy = WorkoutTemplate(
        owner_id=owner_id,
        name=(name or f"{src.name} (copy)")[:120],
        description=src.description, workout_type=src.workout_type, session_type=src.session_type,
        sport_family=src.sport_family, purpose=src.purpose, difficulty=src.difficulty,
        target_zone=src.target_zone, tags_json=src.tags_json, structure_json=src.structure_json,
        is_example=False, duplicated_from_id=src.id,
    )
    session.add(copy)
    session.commit()
    session.refresh(copy)
    return copy


def set_archived(session: Session, owner_id: str, template_id: int, archived: bool) -> WorkoutTemplate:
    row = _own(session, owner_id, template_id)
    row.archived_at = _now() if archived else None
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def get_template(session: Session, owner_id: str, template_id: int) -> WorkoutTemplate:
    return _own(session, owner_id, template_id)


def search_templates(
    session: Session,
    owner_id: str,
    *,
    q: Optional[str] = None,
    workout_type: Optional[str] = None,
    session_type: Optional[str] = None,
    difficulty: Optional[str] = None,
    tags: Optional[list[str]] = None,
    include_examples: bool = True,
    only_examples: bool = False,
    include_archived: bool = False,
    limit: int = 50,
) -> list[WorkoutTemplate]:
    stmt = select(WorkoutTemplate).where(WorkoutTemplate.owner_id == owner_id)
    if not include_archived:
        stmt = stmt.where(WorkoutTemplate.archived_at.is_(None))
    if only_examples:
        stmt = stmt.where(WorkoutTemplate.is_example.is_(True))
    elif not include_examples:
        stmt = stmt.where(WorkoutTemplate.is_example.is_(False))
    if workout_type:
        stmt = stmt.where(WorkoutTemplate.workout_type == workout_type)
    if session_type:
        stmt = stmt.where(WorkoutTemplate.session_type == session_type)
    if difficulty:
        stmt = stmt.where(WorkoutTemplate.difficulty == difficulty)
    rows = list(session.exec(stmt.order_by(WorkoutTemplate.name)).all())
    wanted = [t.strip().lower() for t in (tags or []) if t and t.strip()]
    if wanted:
        rows = [r for r in rows if set(wanted) <= set(json.loads(r.tags_json or "[]"))]
    if q and q.strip():
        needle = q.strip().lower()
        rows = [r for r in rows if needle in " ".join(filter(None, [r.name, r.description, r.purpose, r.tags_json])).lower()]
    return rows[: max(1, min(int(limit), MAX_LIST))]


# --- Scheduling -----------------------------------------------------------------------------------


def planned_fields_for(row: WorkoutTemplate) -> dict:
    return wl.to_planned_fields({**template_dict(row, summary=False)})


def _schedule_fields(row: WorkoutTemplate, day: date, start_time: Optional[str], event_id: Optional[int]) -> dict:
    if row.archived_at is not None:
        raise LibraryError("This template is archived — unarchive it before scheduling.")
    fields = {**planned_fields_for(row), "date": day}
    if start_time:
        fields["start_time"] = start_time
    if event_id is not None:
        fields["event_id"] = event_id
    return fields


def preview_schedule(session: Session, owner_id: str, template_id: int, day: date, *, start_time: Optional[str] = None, repeat: Optional[dict] = None, event_id: Optional[int] = None) -> dict:
    row = _own(session, owner_id, template_id)
    try:
        return planning.preview_create_planned(session, owner_id, _schedule_fields(row, day, start_time, event_id), repeat)
    except planning.PlanningError as exc:
        raise LibraryError(str(exc)) from exc


def schedule_template(session: Session, owner_id: str, template_id: int, day: date, *, start_time: Optional[str] = None, repeat: Optional[dict] = None, event_id: Optional[int] = None) -> list[PlannedWorkout]:
    row = _own(session, owner_id, template_id)
    try:
        planned = planning.create_planned(session, owner_id, _schedule_fields(row, day, start_time, event_id), repeat)
    except planning.PlanningError as exc:
        raise LibraryError(str(exc)) from exc
    for p in planned:
        p.template_id = row.id
        session.add(p)
    session.commit()
    for p in planned:
        session.refresh(p)
    return planned


# --- Seed ------------------------------------------------------------------------------------------


def seed_examples(session: Session) -> int:
    """Idempotent: inserts any example whose `external_id` isn't present, never rewrites one that
    is (an archived example stays archived across restarts)."""
    if not SEED_PATH.exists():
        return 0
    existing = set(session.exec(select(WorkoutTemplate.external_id).where(WorkoutTemplate.external_id.is_not(None))).all())
    added = 0
    for e in json.loads(SEED_PATH.read_text()):
        if e["external_id"] in existing:
            continue
        clean = _clean({k: e[k] for k in _WRITABLE if k in e})
        row = WorkoutTemplate(owner_id=OWNER_ID, external_id=e["external_id"], is_example=True, **_row_fields(clean))
        session.add(row)
        added += 1
    if added:
        session.commit()
    return added
