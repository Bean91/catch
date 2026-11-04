from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlmodel import Session, select

from catch.analytics.predict import predict_2k as predict_2k_fn
from catch.analytics.zones import training_zones
from catch.api import routes_activities, routes_analytics, routes_body, routes_wellness
from catch.core.models import Activity, DailyScore, Food
from catch.core.settings_store import get_settings
from catch.coach import memory
from catch.sync.upsert import upsert_note

# Every range tool is capped — an uncapped "all history" query would blow both the model's
# context window and the Pi's 1GB RAM budget (CLAUDE.md). Downsampled evenly rather than
# tail-cut, so a capped series still shows the whole requested range, just coarser.
_MAX_ROWS = 180
_MAX_STROKE_POINTS = 100


def _downsample(items: list, cap: int) -> list:
    if len(items) <= cap:
        return items
    step = len(items) / cap
    return [items[int(i * step)] for i in range(cap)]


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    return date.fromisoformat(value) if isinstance(value, str) else value


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    return datetime.fromisoformat(value) if isinstance(value, str) else value


# --- Read-only tools ---------------------------------------------------------


def _get_today(session: Session, args: dict, ctx: dict) -> dict:
    return routes_analytics.today(db=session)


def _get_wellness(session: Session, args: dict, ctx: dict) -> dict:
    rows = routes_wellness.list_wellness(from_=_parse_date(args.get("from")), to=_parse_date(args.get("to")), db=session)
    return {"days": _downsample(rows, _MAX_ROWS)}


def _list_workouts(session: Session, args: dict, ctx: dict) -> dict:
    page = routes_activities.list_activities(
        from_=_parse_datetime(args.get("from")),
        to=_parse_datetime(args.get("to")),
        category=args.get("type"),
        limit=50,
        cursor=None,
        db=session,
    )
    return page


def _get_workout(session: Session, args: dict, ctx: dict) -> dict:
    canonical_id = int(args["id"])
    detail = routes_activities.get_activity(canonical_id, db=session)
    strokes_payload = None
    concept2_source = next((s for s in detail["sources"] if s["source"] == "concept2"), None)
    if concept2_source is not None:
        strokes_payload = routes_analytics.erg_strokes(concept2_source["activity_id"], db=session)
    return {
        "activity": detail,
        "strokes": _downsample(strokes_payload["strokes"], _MAX_STROKE_POINTS) if strokes_payload else None,
        "interval_summary": strokes_payload["interval_summary"] if strokes_payload else None,
        "technique_by_interval": strokes_payload["technique_by_interval"] if strokes_payload else None,
    }


def _get_trends(session: Session, args: dict, ctx: dict) -> dict:
    points = routes_analytics.trends(
        metric=args["metric"], from_=_parse_date(args.get("from")), to=_parse_date(args.get("to")), db=session
    )
    return {"metric": args["metric"], "points": _downsample(points, _MAX_ROWS)}


def _get_body_comp(session: Session, args: dict, ctx: dict) -> dict:
    # GET /api/body (session 8/12 — see PLAN.md) takes dates, not datetimes, and now returns
    # one resolved row per day (weight/fat_pct/muscle_kg + which source each came from) —
    # `_parse_datetime` here used to work only because the date-vs-datetime mismatch never
    # got compared against anything; routes_body.resolve_daily compares them directly.
    rows = routes_body.list_body_comp(from_=_parse_date(args.get("from")), to=_parse_date(args.get("to")), db=session)
    return {"readings": _downsample(rows, _MAX_ROWS)}


def _get_load(session: Session, args: dict, ctx: dict) -> dict:
    # Most recent scored day with a load figure — usually today once a sync has run, but
    # recompute_scores only ever runs from a sync/note/settings change, so fall back a little.
    row = session.exec(select(DailyScore).where(DailyScore.load_json.is_not(None)).order_by(DailyScore.date.desc())).first()
    if row is None:
        return {"date": None, "load": None}
    return {"date": row.date, "load": json.loads(row.load_json)}


def _predict_2k_tool(session: Session, args: dict, ctx: dict) -> dict:
    settings = get_settings(session)
    return routes_analytics._predict_2k(session, settings)


def _get_zones(session: Session, args: dict, ctx: dict) -> dict:
    settings = get_settings(session)
    zones = training_zones(max_hr=settings.get("max_hr"), settings=settings)
    return {**zones, "zone_mode": settings.get("zone_mode")}


def _get_nutrition(session: Session, args: dict, ctx: dict) -> dict:
    """Task Part B.8. Defaults to the trailing week so "how's my fuelling been" needs no
    arguments — the same week_summary the Nutrition page's week view reads, including the
    under-fuelling flag (relatable to recovery/strain without medical claims, per the system
    prompt)."""
    from catch.sync import nutrition as nutrition_module

    to = _parse_date(args.get("to")) or date.today()
    from_ = _parse_date(args.get("from")) or (to - timedelta(days=6))
    return nutrition_module.week_summary(session, from_, to)


# --- Write tools --------------------------------------------------------------


def _rename_activity(session: Session, args: dict, ctx: dict) -> dict:
    result = routes_activities.patch_activity(int(args["id"]), body=routes_activities.ActivityEditRequest(title=args["title"]), db=session)
    return {"id": result["id"], "title": result["title"]}


def _tag_activity(session: Session, args: dict, ctx: dict) -> dict:
    result = routes_activities.patch_activity(int(args["id"]), body=routes_activities.ActivityEditRequest(tags=args["tags"]), db=session)
    return {"id": result["id"], "tags": result["tags"]}


def _merge_activities(session: Session, args: dict, ctx: dict) -> dict:
    """Two-step: without confirm=true, returns a preview so the model asks the athlete
    before merging (task Part C.4's explicit "asks me to confirm in chat before merging").

    Takes *canonical* ids, like every other workout tool (list_workouts/get_workout) — never
    a raw per-source activity id. Picking a representative member of each canonical here,
    rather than asking the model for raw ids, avoids a small model confusing a canonical id
    with a same-numbered raw activity id and silently merging the wrong pair."""
    from catch.sync.matching import manual_merge

    canonical_id_a, canonical_id_b = int(args["canonical_id_a"]), int(args["canonical_id_b"])
    member_a = session.exec(select(Activity).where(Activity.canonical_id == canonical_id_a)).first()
    member_b = session.exec(select(Activity).where(Activity.canonical_id == canonical_id_b)).first()
    if member_a is None or member_b is None:
        raise ValueError("canonical workout not found")

    if not args.get("confirm"):
        return {
            "preview": True,
            "message": "Merging will combine these into one canonical activity. Call again with confirm=true to proceed.",
            "a": {"canonical_id": canonical_id_a, "source": member_a.source, "start": member_a.start.isoformat() if member_a.start else None, "duration": member_a.duration},
            "b": {"canonical_id": canonical_id_b, "source": member_b.source, "start": member_b.start.isoformat() if member_b.start else None, "duration": member_b.duration},
        }
    canonical = manual_merge(session, member_a.id, member_b.id)
    from catch.sync.scoring import recompute_scores

    recompute_scores(session)
    return routes_activities.get_activity(canonical.id, db=session)


def _log_food(session: Session, args: dict, ctx: dict) -> dict:
    """Task Part B.8. Resolves a food three ways, in order: an explicit `food_id` (the
    athlete/model picked one from a previous ambiguous response, or already knows it);
    `barcode` (same lookup_or_fetch_barcode the scanner uses); `description` (a free-text
    search). A description match that isn't a single confident hit returns `candidates`
    instead of guessing which one the athlete meant — call again with the right `food_id`."""
    from catch.sync import nutrition as nutrition_module

    food_id = args.get("food_id")
    if food_id is None:
        barcode = args.get("barcode")
        description = args.get("description")
        if barcode:
            food = nutrition_module.lookup_or_fetch_barcode(session, barcode)
            if food is None:
                return {"logged": False, "message": f"No food found for barcode {barcode}. It can be added manually in the app."}
            food_id = food.id
        elif description:
            matches = nutrition_module.search_foods(session, description, limit=5)
            if not matches:
                return {"logged": False, "message": f"No food found matching '{description}'. Try a more specific description."}
            if len(matches) > 1:
                return {
                    "logged": False,
                    "ambiguous": True,
                    "candidates": [{"food_id": m["id"], "name": m["name"], "brand": m["brand"]} for m in matches],
                    "message": "More than one match — call log_food again with the right food_id from candidates.",
                }
            food_id = matches[0]["id"]
        else:
            raise ValueError("Provide a description, a barcode, or a food_id.")

    row = nutrition_module.create_food_log(
        session,
        ts=datetime.now(timezone.utc),
        meal=args["meal"],
        food_id=food_id,
        quantity=float(args["quantity"]),
        unit=args.get("unit", "g"),
        estimated=True,
    )
    food = session.get(Food, food_id)
    return {
        "logged": True,
        "food": food.name,
        "quantity": row.quantity,
        "unit": row.unit,
        "kcal": row.kcal,
        "protein": row.protein,
        "carbs": row.carbs,
        "fat": row.fat,
    }


def _add_note(session: Session, args: dict, ctx: dict) -> dict:
    rpe = args.get("rpe")
    if rpe is not None and not (0 <= int(rpe) <= 10):
        raise ValueError("rpe must be between 0 and 10")
    note = upsert_note(session, _parse_date(args["date"]), args["text"], rpe)
    from catch.sync.scoring import recompute_scores

    recompute_scores(session)
    return note.model_dump()


# --- Memory tools ---------------------------------------------------------------


def _remember(session: Session, args: dict, ctx: dict) -> dict:
    fact = memory.remember(
        session,
        category=args["category"],
        text=args["text"],
        valid_until=_parse_date(args.get("valid_until")),
        source_conversation=ctx.get("conversation_id"),
    )
    return memory._fact_dict(fact)


def _add_event(session: Session, args: dict, ctx: dict) -> dict:
    event = memory.add_event(
        session,
        name=args["name"],
        date_=_parse_date(args["date"]),
        type=args["type"],
        distance=args.get("distance"),
        boat_class=args.get("boat_class"),
        priority=args.get("priority"),
        goal_time=args.get("goal_time"),
        result=args.get("result"),
    )
    return memory._event_dict(event, date.today())


def _update_event(session: Session, args: dict, ctx: dict) -> dict:
    fields = {k: v for k, v in args.items() if k != "id"}
    if "date" in fields:
        fields["date"] = _parse_date(fields["date"])
    event = memory.update_event(session, int(args["id"]), **fields)
    return memory._event_dict(event, date.today())


def _set_goal(session: Session, args: dict, ctx: dict) -> dict:
    goal = memory.set_goal(
        session,
        text=args["text"],
        target_date=_parse_date(args.get("target_date")),
        status=args.get("status", "active"),
        goal_id=int(args["id"]) if args.get("id") is not None else None,
    )
    return memory._goal_dict(goal)


def _forget(session: Session, args: dict, ctx: dict) -> dict:
    return {"deleted": memory.forget(session, args["ref"])}


def _recall(session: Session, args: dict, ctx: dict) -> dict:
    return {"results": memory.recall(session, args.get("query"))}


# --- Registry -------------------------------------------------------------------

_DATE_RANGE_PROPS = {
    "from": {"type": "string", "format": "date", "description": "ISO date, inclusive lower bound. Omit for no lower bound."},
    "to": {"type": "string", "format": "date", "description": "ISO date, inclusive upper bound. Omit for no upper bound."},
}

TOOLS: dict[str, dict[str, Any]] = {
    "get_today": {
        "fn": _get_today,
        "write": False,
        "description": (
            "Today's recovery, strain, sleep, HRV/resting-HR trend, latest erg piece, predicted 2k, and the "
            "next A-priority race with days-to-go and a taper flag (<=14 days out). Call this first for "
            "'how should I train today'-type questions."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "get_wellness": {
        "fn": _get_wellness,
        "write": False,
        "description": "Daily wellness history (resting HR, HRV rMSSD, sleep, stress, body battery, SpO2, respiration). Capped to 180 days, evenly downsampled if the range is wider.",
        "input_schema": {"type": "object", "properties": dict(_DATE_RANGE_PROPS), "additionalProperties": False},
    },
    "list_workouts": {
        "fn": _list_workouts,
        "write": False,
        "description": "Recent canonical workouts (Garmin/Concept2/Peloton sources matched and merged), newest first, up to 50. Optionally filter by date range and category.",
        "input_schema": {
            "type": "object",
            "properties": {
                **_DATE_RANGE_PROPS,
                "type": {"type": "string", "enum": ["erg", "on_water", "other"], "description": "Workout category filter."},
            },
            "additionalProperties": False,
        },
    },
    "get_workout": {
        "fn": _get_workout,
        "write": False,
        "description": "One canonical workout's full detail: zones, strain, note, which source each metric came from. For a Concept2 erg piece, also stroke data (downsampled to at most 100 points) plus the per-interval table (split/rate/watts/HR/drift, technique metrics).",
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "integer", "description": "Canonical workout id, from list_workouts or get_today's latest_erg.canonical_id."}},
            "required": ["id"],
            "additionalProperties": False,
        },
    },
    "get_trends": {
        "fn": _get_trends,
        "write": False,
        "description": "A daily time series for one metric. Capped to 180 points, evenly downsampled if the range is wider.",
        "input_schema": {
            "type": "object",
            "properties": {
                "metric": {
                    "type": "string",
                    "enum": [
                        "recovery", "hrv_rmssd", "resting_hr", "sleep_score", "stress", "body_battery",
                        "spo2", "respiration", "strain", "load_acr", "weight", "w_per_kg", "predicted_2k",
                    ],
                },
                **_DATE_RANGE_PROPS,
            },
            "required": ["metric"],
            "additionalProperties": False,
        },
    },
    "get_body_comp": {
        "fn": _get_body_comp,
        "write": False,
        "description": "Resolved daily body-composition readings (weight, fat_pct, muscle_kg — Withings and/or Garmin scale, or a manual entry; never averaged, each tagged with which source it came from) over a date range. Capped to 180 days.",
        "input_schema": {"type": "object", "properties": dict(_DATE_RANGE_PROPS), "additionalProperties": False},
    },
    "get_load": {
        "fn": _get_load,
        "write": False,
        "description": "Most recent acute:chronic training-load figure (7d/42d EWMA, form, band).",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "predict_2k": {
        "fn": _predict_2k_tool,
        "write": False,
        "description": "Predicted 2k time, extrapolated via Paul's law from recent qualifying erg pieces.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "get_zones": {
        "fn": _get_zones,
        "write": False,
        "description": "Current HR and power training-zone boundaries (UT2/UT1/AT/TR/AN), plus which mode (hr/power) is the default view.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "get_nutrition": {
        "fn": _get_nutrition,
        "write": False,
        "description": (
            "Daily intake (kcal/protein) vs. Garmin expenditure over a date range (default: trailing 7 days), plus a "
            "calm under-fuelling flag when several recent logged days ran well below expenditure. Unlogged days are "
            "never treated as zero intake."
        ),
        "input_schema": {"type": "object", "properties": dict(_DATE_RANGE_PROPS), "additionalProperties": False},
    },
    "add_note": {
        "fn": _add_note,
        "write": True,
        "description": "Save a training note and/or RPE (0-10) for a date. Overwrites any existing note for that date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "format": "date"},
                "text": {"type": "string"},
                "rpe": {"type": "integer", "minimum": 0, "maximum": 10},
            },
            "required": ["date", "text"],
            "additionalProperties": False,
        },
    },
    "log_food": {
        "fn": _log_food,
        "write": True,
        "description": (
            "Log a food to the nutrition diary. Identify the food by exactly one of description (free text, searched "
            "against the local cache + USDA), barcode, or food_id (from a prior ambiguous response's candidates). A "
            "description match that isn't a single confident hit returns candidates instead of guessing — call again "
            "with the right food_id. Always confirm in chat what was logged (food, quantity, kcal/protein/carbs/fat)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "Free-text food description, e.g. 'grilled chicken breast'."},
                "barcode": {"type": "string"},
                "food_id": {"type": "integer", "description": "A specific food id, e.g. from a previous ambiguous candidates list."},
                "quantity": {"type": "number"},
                "unit": {"type": "string", "enum": ["g", "serving"], "description": "Defaults to g."},
                "meal": {"type": "string", "enum": ["breakfast", "lunch", "dinner", "snack", "pre_workout", "post_workout"]},
            },
            "required": ["quantity", "meal"],
            "additionalProperties": False,
        },
    },
    "rename_activity": {
        "fn": _rename_activity,
        "write": True,
        "description": "Rename a canonical workout (overrides any source/auto title, survives re-sync).",
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "integer", "description": "Canonical workout id."}, "title": {"type": "string"}},
            "required": ["id", "title"],
            "additionalProperties": False,
        },
    },
    "tag_activity": {
        "fn": _tag_activity,
        "write": True,
        "description": "Set a canonical workout's tags (e.g. race, test, technique, cross-training) — replaces any existing tags.",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "Canonical workout id."},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["id", "tags"],
            "additionalProperties": False,
        },
    },
    "merge_activities": {
        "fn": _merge_activities,
        "write": True,
        "description": "Merge two canonical workouts (e.g. a watch recording and a Peloton-pushed duplicate of the same ride) into one. Call once without confirm to preview, tell the athlete what will merge, and only call again with confirm=true once they agree.",
        "input_schema": {
            "type": "object",
            "properties": {
                "canonical_id_a": {"type": "integer", "description": "Canonical workout id, e.g. from list_workouts."},
                "canonical_id_b": {"type": "integer"},
                "confirm": {"type": "boolean", "description": "Only set true after the athlete has confirmed in chat."},
            },
            "required": ["canonical_id_a", "canonical_id_b"],
            "additionalProperties": False,
        },
    },
    "remember": {
        "fn": _remember,
        "write": True,
        "description": "Save a durable fact about the athlete (injury, schedule constraint, equipment, preference). Only call this for something the athlete actually said — never infer or guess a fact.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": ["injury", "schedule", "equipment", "preference", "other"]},
                "text": {"type": "string"},
                "valid_until": {"type": "string", "format": "date", "description": "Omit for facts with no expiry."},
            },
            "required": ["category", "text"],
            "additionalProperties": False,
        },
    },
    "add_event": {
        "fn": _add_event,
        "write": True,
        "description": "Record a race, test, camp, or selection event the athlete mentioned. Ask for a concrete date first if the athlete was vague about timing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "date": {"type": "string", "format": "date"},
                "type": {"type": "string", "enum": ["race", "2k_test", "camp", "selection"]},
                "distance": {"type": "string"},
                "boat_class": {"type": "string"},
                "priority": {"type": "string", "enum": ["A", "B", "C"]},
                "goal_time": {"type": "string"},
                "result": {"type": "string"},
            },
            "required": ["name", "date", "type"],
            "additionalProperties": False,
        },
    },
    "update_event": {
        "fn": _update_event,
        "write": True,
        "description": "Update fields on an existing event (e.g. record a result after it happened). Only pass the fields that changed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "string"},
                "date": {"type": "string", "format": "date"},
                "type": {"type": "string", "enum": ["race", "2k_test", "camp", "selection"]},
                "distance": {"type": "string"},
                "boat_class": {"type": "string"},
                "priority": {"type": "string", "enum": ["A", "B", "C"]},
                "goal_time": {"type": "string"},
                "result": {"type": "string"},
            },
            "required": ["id"],
            "additionalProperties": False,
        },
    },
    "set_goal": {
        "fn": _set_goal,
        "write": True,
        "description": "Create a new goal, or pass id to update an existing one's text/target_date/status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "Omit to create a new goal."},
                "text": {"type": "string"},
                "target_date": {"type": "string", "format": "date"},
                "status": {"type": "string", "enum": ["active", "done", "abandoned"]},
            },
            "required": ["text"],
            "additionalProperties": False,
        },
    },
    "forget": {
        "fn": _forget,
        "write": True,
        "description": "Delete a memory item by its prefixed ref (e.g. 'fact:12', 'event:3', 'goal:5'), as returned by recall.",
        "input_schema": {
            "type": "object",
            "properties": {"ref": {"type": "string", "description": "e.g. 'fact:12'"}},
            "required": ["ref"],
            "additionalProperties": False,
        },
    },
    "recall": {
        "fn": _recall,
        "write": False,
        "description": "Search stored events, goals, and facts. Omit query to list everything current (expired facts are already excluded).",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "additionalProperties": False,
        },
    },
}


def anthropic_tool_schemas() -> list[dict]:
    return [{"name": name, "description": spec["description"], "input_schema": spec["input_schema"]} for name, spec in TOOLS.items()]


def ollama_tool_schemas() -> list[dict]:
    return [
        {"type": "function", "function": {"name": name, "description": spec["description"], "parameters": spec["input_schema"]}}
        for name, spec in TOOLS.items()
    ]


def call_tool(session: Session, name: str, args: dict, ctx: dict | None = None) -> dict:
    spec = TOOLS.get(name)
    if spec is None:
        raise ValueError(f"Unknown tool '{name}'")
    result = spec["fn"](session, args, ctx or {})
    return jsonable_encoder(result)
