from __future__ import annotations

"""Session 22 (see PLAN.md, docs/library.md): the eight workout-library / technique-note /
coach-feedback tools, merged into catch.coach.tools.TOOLS (the one shared registry — in-app coach,
MCP and REST all dispatch here).

Every handler reads the caller via `principal_from(ctx)`, which is the fail-closed viewer when a
transport forgot to set one. Reads are filtered by the same visibility functions the web routes
use; writes preview first and only save with `confirm is True`."""

from datetime import date
from typing import Any

from sqlmodel import Session

from catch.analytics.workout_library import DIFFICULTIES, WORKOUT_TYPES
from catch.analytics.zones import ZONE_ORDER
from catch.core import principal as pr
from catch.core.principal import OWNER_ID, Principal, principal_from
from catch.sync import coaching_notes as cn
from catch.sync import workout_library as lib


def _gate(args: dict, preview: dict, what: str) -> dict | None:
    from catch.coach.tools import _gate as gate

    return gate(args, preview, what)


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"'{value}' isn't an ISO date (YYYY-MM-DD)") from exc


def _caller(ctx: dict) -> Principal:
    p = principal_from(ctx)
    if p.role not in (pr.ATHLETE_ROLE, pr.COACH_ROLE):
        raise ValueError("This caller isn't identified, so coaching data isn't available.")
    return p


def _athlete(ctx: dict, what: str) -> Principal:
    p = _caller(ctx)
    if not p.is_athlete:
        raise ValueError(f"Only the athlete can {what}.")
    return p


def _wrap(fn):
    def inner(session: Session, args: dict, ctx: dict) -> dict:
        try:
            return fn(session, args, ctx)
        except (lib.LibraryError, cn.CoachingError) as exc:
            raise ValueError(str(exc)) from exc

    return inner


_TEMPLATE_KEYS = ("name", "description", "workout_type", "session_type", "purpose", "difficulty", "target_zone", "tags", "structure")


def _template_fields(args: dict) -> dict:
    return {k: args[k] for k in _TEMPLATE_KEYS if k in args and args[k] is not None}


# --- Workout library -------------------------------------------------------------------------------


def _search_workout_library(session: Session, args: dict, ctx: dict) -> dict:
    p = _caller(ctx)
    athlete = p.is_athlete
    rows = lib.search_templates(
        session, OWNER_ID,
        q=args.get("query"), workout_type=args.get("workout_type"), session_type=args.get("session_type"),
        difficulty=args.get("difficulty"), tags=args.get("tags"),
        include_examples=bool(args.get("include_examples", False)),
        include_archived=bool(args.get("include_archived", False)) and athlete,
        limit=int(args.get("limit") or 20),
    )
    return {
        "templates": [lib.template_dict(r, summary=True) for r in rows],
        "note": "Templates are reusable definitions, not workouts that happened. Examples are only structural illustrations, not prescribed training.",
    }


def _get_workout_template(session: Session, args: dict, ctx: dict) -> dict:
    p = _caller(ctx)
    row = lib.get_template(session, OWNER_ID, int(args["id"]))
    if row.archived_at is not None and not p.is_athlete:
        raise lib.NotFound(f"No workout template with id {args['id']}")
    return lib.template_dict(row)


def _create_workout_template(session: Session, args: dict, ctx: dict) -> dict:
    _athlete(ctx, "create workout templates")
    fields = _template_fields(args)
    held = _gate(args, lib.preview_create_template(session, OWNER_ID, fields), "creating this template")
    if held:
        return held
    row = lib.create_template(session, OWNER_ID, fields)
    return {"saved": True, "template": lib.template_dict(row)}


def _update_workout_template(session: Session, args: dict, ctx: dict) -> dict:
    _athlete(ctx, "change workout templates")
    template_id = int(args["id"])
    fields = _template_fields(args)
    archived = args.get("archived")
    if not fields and archived is None:
        raise ValueError("Give at least one field to change, or archived")
    if archived is not None and not fields:
        row = lib.get_template(session, OWNER_ID, template_id)
        preview = {"id": row.id, "name": row.name, "changes": {"archived": {"from": row.archived_at is not None, "to": bool(archived)}}}
    else:
        preview = lib.preview_update_template(session, OWNER_ID, template_id, fields)
        if archived is not None:
            preview["changes"]["archived"] = {"from": lib.get_template(session, OWNER_ID, template_id).archived_at is not None, "to": bool(archived)}
    held = _gate(args, preview, "this template change")
    if held:
        return held
    if fields:
        lib.update_template(session, OWNER_ID, template_id, fields)
    if archived is not None:
        lib.set_archived(session, OWNER_ID, template_id, bool(archived))
    return {"saved": True, "template": lib.template_dict(lib.get_template(session, OWNER_ID, template_id))}


# --- Technique notes ---------------------------------------------------------------------------------


def _get_technique_notes(session: Session, args: dict, ctx: dict) -> dict:
    p = _caller(ctx)
    rows = cn.list_technique_notes(
        session, OWNER_ID, p,
        canonical_id=args.get("workout_id"), piece_id=args.get("piece_id"), note_date=_parse_date(args.get("date")),
        category=args.get("category"), date_from=_parse_date(args.get("from")), date_to=_parse_date(args.get("to")),
        limit=int(args.get("limit") or 30),
    )
    return {"notes": [cn.note_dict(session, r) for r in rows], "note": cn.CANNOT_RATE}


def _add_technique_note(session: Session, args: dict, ctx: dict) -> dict:
    p = _athlete(ctx, "add technique notes")
    fields = {k: args[k] for k in ("category", "text", "visibility", "media", "piece_id") if k in args and args[k] is not None}
    if args.get("workout_id") is not None:
        fields["canonical_id"] = args["workout_id"]
    if args.get("date"):
        fields["note_date"] = args["date"]
    held = _gate(args, cn.preview_technique_note(session, OWNER_ID, p, fields), "saving this technique note")
    if held:
        return held
    row = cn.create_technique_note(session, OWNER_ID, p, fields)
    return {"saved": True, "note": cn.note_dict(session, row)}


# --- Coach feedback -----------------------------------------------------------------------------------


def _get_coach_feedback(session: Session, args: dict, ctx: dict) -> dict:
    p = _caller(ctx)
    rows = cn.list_feedback(
        session, OWNER_ID, p, coach=args.get("coach"), category=args.get("category"),
        date_from=_parse_date(args.get("from")), date_to=_parse_date(args.get("to")),
        canonical_id=args.get("workout_id"), event_id=args.get("event_id"), limit=int(args.get("limit") or 30),
    )
    return {"feedback": [cn.feedback_dict(session, r, p) for r in rows], "note": cn.CANNOT_RATE}


def _add_coach_feedback(session: Session, args: dict, ctx: dict) -> dict:
    p = _caller(ctx)
    via = ctx.get("via") if ctx.get("via") in cn.CREATED_VIA else "mcp"
    fields = {k: args[k] for k in ("text", "date", "workout_date", "focus_areas", "visibility", "coach_name", "event_id", "planned_id") if k in args and args[k] is not None}
    if args.get("workout_id") is not None:
        fields["canonical_id"] = args["workout_id"]
    held = _gate(args, cn.preview_feedback(session, OWNER_ID, p, fields, via), "saving this feedback")
    if held:
        return held
    row = cn.create_feedback(session, OWNER_ID, p, fields, via)
    return {"saved": True, "feedback": cn.feedback_dict(session, row, p)}


# --- Registry entries -----------------------------------------------------------------------------------

_CONFIRM = {"type": "boolean", "description": "Leave unset on the first call to get a preview. Set true only after the athlete has seen the preview and agreed."}
_BLOCK = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "reps": {"type": "integer", "minimum": 1, "maximum": 100},
        "work_s": {"type": "number", "description": "Work time per rep in seconds (give this OR work_m)."},
        "work_m": {"type": "number", "description": "Work distance per rep in metres (give this OR work_s)."},
        "rest_s": {"type": "number", "description": "Rest after each rep in seconds (none after the final rep)."},
        "zone": {"type": "string", "enum": list(ZONE_ORDER)},
        "rate_min": {"type": "number"}, "rate_max": {"type": "number"},
        "split_s": {"type": "number", "description": "Target split in seconds per 500m."},
        "watts": {"type": "number"},
        "note": {"type": "string"},
    },
}
_SEGMENT = {
    "type": "object", "additionalProperties": False,
    "properties": {"duration_min": {"type": "number"}, "distance_m": {"type": "number"}, "zone": {"type": "string", "enum": list(ZONE_ORDER)}, "note": {"type": "string"}},
}
_STRUCTURE = {
    "type": "object",
    "additionalProperties": False,
    "description": "warmup / blocks / cooldown (timed work) or strength_items (exercise_id + target_sets/target_reps) for a strength template.",
    "properties": {
        "warmup": _SEGMENT, "cooldown": _SEGMENT, "blocks": {"type": "array", "items": _BLOCK},
        "strength_items": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {
            "exercise_id": {"type": "integer"}, "target_sets": {"type": "integer"}, "target_reps": {"type": "integer"}, "note": {"type": "string"}}, "required": ["exercise_id"]}},
    },
}
_TEMPLATE_PROPS = {
    "name": {"type": "string"},
    "description": {"type": "string"},
    "workout_type": {"type": "string", "enum": list(WORKOUT_TYPES)},
    "session_type": {"type": "string", "description": "erg | on_water | run | bike | strength | cross | other; defaults from workout_type."},
    "purpose": {"type": "string", "description": "What the session is for, in the athlete's words."},
    "difficulty": {"type": "string", "enum": list(DIFFICULTIES)},
    "target_zone": {"type": "string", "enum": list(ZONE_ORDER)},
    "tags": {"type": "array", "items": {"type": "string"}},
    "structure": _STRUCTURE,
}
_CATEGORY = {"type": "string", "enum": list(cn.TECHNIQUE_CATEGORIES)}
_FOCUS = {"type": "string", "enum": list(cn.FOCUS_AREAS)}

TOOLS: dict[str, dict] = {
    "search_workout_library": {
        "fn": _wrap(_search_workout_library),
        "write": False,
        "description": "Search the athlete's reusable workout templates (erg intervals, steady state, rate ladders, "
        "distance/time pieces, strength, on-water, custom). Excludes the built-in illustrative examples unless "
        "include_examples=true; never prescribe training from an example.",
        "input_schema": {"type": "object", "additionalProperties": False, "properties": {
            "query": {"type": "string"}, "workout_type": {"type": "string", "enum": list(WORKOUT_TYPES)}, "session_type": {"type": "string"},
            "difficulty": {"type": "string", "enum": list(DIFFICULTIES)}, "tags": {"type": "array", "items": {"type": "string"}},
            "include_examples": {"type": "boolean"}, "include_archived": {"type": "boolean"}, "limit": {"type": "integer"}}},
    },
    "get_workout_template": {
        "fn": _wrap(_get_workout_template),
        "write": False,
        "description": "One workout template with its structure and computed totals (duration is only given when it can be known; "
        "duration_basis says exact, estimated or unknown).",
        "input_schema": {"type": "object", "additionalProperties": False, "properties": {"id": {"type": "integer"}}, "required": ["id"]},
    },
    "create_workout_template": {
        "fn": _wrap(_create_workout_template),
        "write": True,
        "description": "Create a workout template. Previews first and saves only with confirm=true after the athlete agrees. "
        "A template is not a workout and not a prescription.",
        "input_schema": {"type": "object", "additionalProperties": False, "properties": {**_TEMPLATE_PROPS, "confirm": _CONFIRM}, "required": ["name", "workout_type"]},
    },
    "update_workout_template": {
        "fn": _wrap(_update_workout_template),
        "write": True,
        "description": "Change a template's fields, or archive/unarchive it with archived. Built-in examples are read-only. "
        "Previews first (showing each change); saves only with confirm=true. Sessions already scheduled from it are unaffected.",
        "input_schema": {"type": "object", "additionalProperties": False, "properties": {"id": {"type": "integer"}, **_TEMPLATE_PROPS, "archived": {"type": "boolean"}, "confirm": _CONFIRM}, "required": ["id"]},
    },
    "get_technique_notes": {
        "fn": _wrap(_get_technique_notes),
        "write": False,
        "description": "The athlete's technique notes (catch, drive, finish, recovery, sequencing, posture, rate control, blade/boat handling), "
        "optionally for one workout, piece, date or category. Notes marked private are only returned to the athlete's own "
        "assistant; a coach sees only notes shared with them. These are written observations — Catch cannot measure technique quality, "
        "so never score or rate technique from them or from stroke data.",
        "input_schema": {"type": "object", "additionalProperties": False, "properties": {
            "workout_id": {"type": "integer"}, "piece_id": {"type": "integer"}, "date": {"type": "string"}, "category": _CATEGORY,
            "from": {"type": "string"}, "to": {"type": "string"}, "limit": {"type": "integer"}}},
    },
    "add_technique_note": {
        "fn": _wrap(_add_technique_note),
        "write": True,
        "description": "Save a technique note in the athlete's own words, optionally attached to a workout, piece or date. "
        "visibility is 'private' (default, only the athlete) or 'coach' (shared with a linked coach). Previews first; confirm=true to save. "
        "Do not infer or add a quality judgement the athlete didn't state.",
        "input_schema": {"type": "object", "additionalProperties": False, "properties": {
            "category": _CATEGORY, "text": {"type": "string"}, "workout_id": {"type": "integer"}, "piece_id": {"type": "integer"}, "date": {"type": "string"},
            "visibility": {"type": "string", "enum": list(pr.NOTE_VISIBILITIES)},
            "media": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"url": {"type": "string"}, "label": {"type": "string"}}, "required": ["url"]}},
            "confirm": _CONFIRM}, "required": ["category", "text"]},
    },
    "get_coach_feedback": {
        "fn": _wrap(_get_coach_feedback),
        "write": False,
        "description": "Feedback entries from coaches (and feedback the athlete logged), newest first, filterable by coach name, "
        "focus area, date range, workout or event. Entries marked private never appear for a coach; each shows its author, "
        "whether it was edited, and the athlete's response.",
        "input_schema": {"type": "object", "additionalProperties": False, "properties": {
            "coach": {"type": "string"}, "category": _FOCUS, "from": {"type": "string"}, "to": {"type": "string"},
            "workout_id": {"type": "integer"}, "event_id": {"type": "integer"}, "limit": {"type": "integer"}}},
    },
    "add_coach_feedback": {
        "fn": _wrap(_add_coach_feedback),
        "write": True,
        "description": "Record a feedback entry. A coach's token writes shared feedback under that coach's name. For the athlete, use this "
        "to log feedback they received (pass coach_name) — never write feedback as if from a coach. Link it with workout_id, or "
        "workout_date when only the date is known (exactly one workout that day), or event_id. Previews first; confirm=true to save.",
        "input_schema": {"type": "object", "additionalProperties": False, "properties": {
            "text": {"type": "string"}, "date": {"type": "string"}, "workout_id": {"type": "integer"}, "workout_date": {"type": "string"},
            "event_id": {"type": "integer"}, "planned_id": {"type": "integer"},
            "focus_areas": {"type": "array", "items": _FOCUS}, "visibility": {"type": "string", "enum": list(pr.FEEDBACK_VISIBILITIES)},
            "coach_name": {"type": "string"}, "confirm": _CONFIRM}, "required": ["text"]},
    },
}
