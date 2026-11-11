from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlmodel import Session, select

from catch.analytics.zones import training_zones
from catch.api import (
    routes_activities,
    routes_analytics,
    routes_body,
    routes_gps,
    routes_tests,
    routes_training_intelligence,
    routes_wellness,
)
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


# --- Gym logger tools (session 14 — see PLAN.md Part D) -------------------------------------

_SETSXREPS_RE = re.compile(r"(\d+)\s*x\s*(\d+)", re.I)
_SETS_OF_RE = re.compile(r"(\d+)\s*sets?\s*(?:of)?\s*(\d+)", re.I)
_WEIGHT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|lbs?)\b", re.I)
_STACK_RE = re.compile(r"stack\s*(\d+(?:\.\d+)?)", re.I)
_STATION_RE = re.compile(r"station\s*(\d+)", re.I)
_RIR_RE = re.compile(r"\brir\s*(\d+(?:\.\d+)?)", re.I)
_RPE_RE = re.compile(r"\brpe\s*(\d+(?:\.\d+)?)", re.I)
_LB_TO_KG = 0.453592


def _parse_strength_text(text: str) -> dict:
    """A deliberately simple regex parser, not full NLP — exactly why log_strength always
    returns a preview before saving (task Part D's "confirms parsed sets before saving"), so a
    misparse gets caught by the athlete rather than silently logged. Handles one exercise per
    call (e.g. "3x8 cable row stack 12 on station 2"), matching the task's own example."""
    remaining = text
    sets_count, reps = 1, 0
    m = _SETSXREPS_RE.search(remaining)
    if not m:
        m = _SETS_OF_RE.search(remaining)
    if m:
        sets_count, reps = int(m.group(1)), int(m.group(2))
        remaining = remaining[: m.start()] + remaining[m.end() :]

    load_kg: float | None = None
    equipment_hint: str | None = None
    m = _STACK_RE.search(remaining)
    if m:
        load_kg = float(m.group(1))
        equipment_hint = "cable"
        remaining = remaining[: m.start()] + remaining[m.end() :]
    else:
        m = _WEIGHT_RE.search(remaining)
        if m:
            value = float(m.group(1))
            load_kg = value * _LB_TO_KG if m.group(2).lower().startswith("lb") else value
            remaining = remaining[: m.start()] + remaining[m.end() :]

    station: int | None = None
    m = _STATION_RE.search(remaining)
    if m:
        station = int(m.group(1))
        remaining = remaining[: m.start()] + remaining[m.end() :]

    rir: float | None = None
    m = _RIR_RE.search(remaining)
    if m:
        rir = float(m.group(1))
        remaining = remaining[: m.start()] + remaining[m.end() :]
    rpe: float | None = None
    m = _RPE_RE.search(remaining)
    if m:
        rpe = float(m.group(1))
        remaining = remaining[: m.start()] + remaining[m.end() :]

    if equipment_hint is None:
        lowered = remaining.lower()
        if "cable" in lowered:
            equipment_hint = "cable"
        elif "dumbbell" in lowered or re.search(r"\bdb\b", lowered):
            equipment_hint = "dumbbell"
        elif "kettlebell" in lowered or re.search(r"\bkb\b", lowered):
            equipment_hint = "kettlebell"
        elif "smith" in lowered:
            equipment_hint = "smith"
        elif "machine" in lowered:
            equipment_hint = "machine_plate"
        elif "bodyweight" in lowered or "body weight" in lowered:
            equipment_hint = "bodyweight"
        else:
            equipment_hint = "barbell"

    exercise_name = re.sub(r"\s+", " ", remaining).strip()
    return {
        "exercise_name": exercise_name,
        "sets_count": sets_count,
        "reps": reps,
        "load_kg": load_kg,
        "equipment_type": equipment_hint,
        "station": station,
        "rir": rir,
        "rpe": rpe,
    }


def _resolve_exercise(session: Session, name: str) -> dict | None:
    from catch.sync import gym

    matches = gym.list_exercises(session, query=name)
    return matches[0] if matches else None


def _log_strength(session: Session, args: dict, ctx: dict) -> dict:
    """Task Part D: free text (one exercise per call, e.g. "3x8 cable row stack 12 on station
    2") or a structured `sets` list. Always previews first — `confirm=true` is required to
    actually save, same two-step pattern as merge_activities, so a misparsed exercise/load
    never gets written without the athlete seeing it first. Effective load is always computed
    server-side from the real equipment math (catch/analytics/equipment.py), never trusted
    from whatever number the model/athlete typed."""
    from catch.sync import gym

    parsed_sets = args.get("sets")
    if not parsed_sets:
        text = args.get("text")
        if not text:
            raise ValueError("Provide either `text` or a structured `sets` list.")
        parsed = _parse_strength_text(text)
        exercise = _resolve_exercise(session, parsed["exercise_name"])
        if exercise is None:
            return {
                "saved": False,
                "message": f"No exercise found matching '{parsed['exercise_name']}'. Ask the athlete for the exact exercise name, or add it as a custom exercise first.",
            }
        parsed_sets = [
            {
                "exercise_id": exercise["id"],
                "exercise_name": exercise["name"],
                "equipment_type": parsed["equipment_type"],
                "reps": parsed["reps"],
                "load_kg": parsed["load_kg"],
                "rir": parsed["rir"],
                "rpe": parsed["rpe"],
            }
            for _ in range(parsed["sets_count"])
        ]
    else:
        resolved = []
        for s in parsed_sets:
            s = dict(s)
            if not s.get("exercise_id") and s.get("exercise_name"):
                exercise = _resolve_exercise(session, s["exercise_name"])
                if exercise is None:
                    return {"saved": False, "message": f"No exercise found matching '{s['exercise_name']}'."}
                s["exercise_id"] = exercise["id"]
                s["exercise_name"] = exercise["name"]
            resolved.append(s)
        parsed_sets = resolved

    if not args.get("confirm"):
        return {
            "saved": False,
            "preview": parsed_sets,
            "message": "Preview only — confirm these sets with the athlete, then call log_strength again with the same sets and confirm=true.",
        }

    client_session_id = gym.get_or_create_todays_session_id(session)
    seq_start = len(gym.list_session_sets(session, client_session_id))
    saved = []
    for i, s in enumerate(parsed_sets):
        saved.append(
            gym.upsert_set(
                session,
                client_session_id,
                {
                    "client_id": str(uuid.uuid4()),
                    "exercise_id": s["exercise_id"],
                    "equipment_type": s.get("equipment_type") or "other",
                    "load_kg": s.get("load_kg"),
                    "bar_weight_kg": s.get("bar_weight_kg"),
                    "pulley_multiplier": s.get("pulley_multiplier"),
                    "reps": int(s.get("reps") or 0),
                    "rir": s.get("rir"),
                    "rpe": s.get("rpe"),
                    "set_type": s.get("set_type", "working"),
                    "seq": seq_start + i,
                },
            )
        )
    from catch.sync.scoring import recompute_scores

    recompute_scores(session)
    return {"saved": True, "sets": saved}


def _get_strength(session: Session, args: dict, ctx: dict) -> dict:
    from catch.sync import gym

    to = _parse_date(args.get("to")) or date.today()
    from_ = _parse_date(args.get("from")) or (to - timedelta(days=28))
    exercise_id = args.get("exercise_id")
    if exercise_id is None and args.get("exercise_name"):
        exercise = _resolve_exercise(session, args["exercise_name"])
        exercise_id = exercise["id"] if exercise else None
    rows = gym.list_sets_in_range(session, from_, to, exercise_id)
    return {"from": from_, "to": to, "sets": _downsample(rows, _MAX_ROWS)}


def _get_muscle_readiness(session: Session, args: dict, ctx: dict) -> dict:
    from catch.sync import gym

    return gym.muscle_readiness(session)


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
            # One call per tool use, never as-you-type — unlike the search box's debounced
            # calls, this is exactly the explicit, deliberate action OFF's own "not for
            # search-as-you-type" warning is fine with, so this is the one place the coach
            # tool opts in on the athlete's behalf.
            matches = nutrition_module.search_foods(session, description, limit=5, include_off=True)
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


# --- Erg test center tools (session 15 — see PLAN.md Part C) --------------------------------


def _get_tests(session: Session, args: dict, ctx: dict) -> dict:
    return routes_tests.get_tests(test_type=args.get("type"), db=session)


def _get_test(session: Session, args: dict, ctx: dict) -> dict:
    """Session 17: get_tests' rows now include pieces (`"kind": "piece"`, with their own
    `piece_id`, since a piece's `canonical_id` is the *containing* activity, not unique to it)
    — pass `piece_id` for one of those rows instead of `id`."""
    if args.get("piece_id") is not None:
        return routes_tests.get_piece_test_detail(int(args["piece_id"]), db=session)
    if args.get("id") is not None:
        return routes_tests.get_test_detail(int(args["id"]), db=session)
    raise ValueError("Provide either `id` (a confirmed test) or `piece_id` (a piece row from get_tests).")


# --- Session 20 (see PLAN.md): GPS, on-water metrics, routes and weather ---------------------
# Read-only, delegating to routes_gps's build_* functions (same precedent as _get_tests). The
# coach is deliberately never handed a coordinate track: get_route returns an area and summary
# figures, and the weather payload carries only the 0.1-degree cell the provider was asked about.


def _get_route(session: Session, args: dict, ctx: dict) -> dict:
    return routes_gps.build_route_summary(session, int(args["activity_id"]))


def _get_route_history(session: Session, args: dict, ctx: dict) -> dict:
    return routes_gps.build_route_history(session, int(args["route_id"]))


def _get_on_water_metrics(session: Session, args: dict, ctx: dict) -> dict:
    return routes_gps.build_on_water(session, int(args["activity_id"]), args.get("split_m"))


def _get_workout_weather(session: Session, args: dict, ctx: dict) -> dict:
    return routes_gps.build_weather(session, int(args["activity_id"]))


# --- Session 18 (see PLAN.md): training intelligence & recommendations ---------------------
# The 6 read tools delegate straight to routes_training_intelligence's handler functions,
# same precedent as _get_tests -> routes_tests.get_tests above; rate_recommendation is the
# only write tool here (a direct mutation on an existing row, no preview step — same
# precedent as routes_illness.py's mark_backtest, which this in effect generalizes).


def _get_training_profile(session: Session, args: dict, ctx: dict) -> dict:
    return routes_training_intelligence.get_training_profile(db=session)


def _get_interval_comparisons(session: Session, args: dict, ctx: dict) -> dict:
    return routes_training_intelligence.get_interval_comparisons(db=session)


def _get_performance_trends(session: Session, args: dict, ctx: dict) -> dict:
    return routes_training_intelligence.get_performance_trends(piece_type=args.get("piece_type"), db=session)


def _get_training_distribution(session: Session, args: dict, ctx: dict) -> dict:
    weeks = int(args["weeks"]) if args.get("weeks") is not None else 12
    return routes_training_intelligence.get_training_distribution(weeks=weeks, db=session)


def _get_training_consistency(session: Session, args: dict, ctx: dict) -> dict:
    weeks = int(args["weeks"]) if args.get("weeks") is not None else None
    return routes_training_intelligence.get_training_consistency(weeks=weeks, db=session)


def _get_training_insights(session: Session, args: dict, ctx: dict) -> dict:
    return routes_training_intelligence.get_training_insights(db=session)


def _get_recommendations(session: Session, args: dict, ctx: dict) -> dict:
    return routes_training_intelligence.get_recommendations(
        status=args.get("status", "active"), rec_type=args.get("type"), db=session
    )


def _rate_recommendation(session: Session, args: dict, ctx: dict) -> dict:
    body = routes_training_intelligence.RateRequest(rating=args["rating"])
    return routes_training_intelligence.rate_recommendation(int(args["id"]), body=body, db=session)


_PIECE_TIME_RE = re.compile(r"\d+:\d+(?:\.\d+)?")


def _parse_piece_free_text(piece_type: str, text: str) -> tuple[list[dict], float | None]:
    """Session 17 Part E: "my 2k was 6:32.4, splits 1:36.8, 1:38.9, 1:39.0, 1:37.7" -> split
    rows + the total time. The first m:ss token is always the total; every token after it is
    one split, in order — matching the task's own example exactly. When the split count
    matches this piece_type's standard row count, each split's distance comes from
    catch/analytics/piece.py's own template (so 500/1000/1500/2000m line up); otherwise the
    rows are left distance-less rather than guessed."""
    from catch.analytics.piece import default_splits, parse_time_token

    times = _PIECE_TIME_RE.findall(text)
    if not times:
        raise ValueError("Couldn't find any m:ss split times in that text.")
    total_s = parse_time_token(times[0], "total time")
    split_tokens = times[1:]
    if not split_tokens:
        return [], total_s

    template = default_splits(piece_type, duration_s=total_s)
    if len(template) == len(split_tokens):
        rows = []
        for row, tok in zip(template, split_tokens):
            r = dict(row)
            r["split_s"] = parse_time_token(tok, "split")
            rows.append(r)
        return rows, total_s
    return (
        [{"split_index": i + 1, "distance_m": None, "split_s": parse_time_token(t, f"split {i + 1}"), "rate": None, "watts": None, "hr": None} for i, t in enumerate(split_tokens)],
        total_s,
    )


def _add_piece(session: Session, args: dict, ctx: dict) -> dict:
    """Task Part E: free text or a structured splits list, always previewed first — same
    two-step pattern as merge_activities/log_strength, so a misheard "my 2k was ..." never
    saves without the athlete seeing the parsed table. canonical_id defaults to the most
    recent activity with a start time (the session the athlete is presumably still talking
    about) when omitted."""
    from catch.analytics.piece import PIECE_TYPES, aggregate_from_splits, validate_splits
    from catch.core.models import CanonicalActivity
    from catch.sync import piece as piece_sync

    piece_type = args["piece_type"]
    if piece_type not in PIECE_TYPES:
        raise ValueError(f"piece_type must be one of {PIECE_TYPES}")

    canonical_id = args.get("canonical_id")
    if canonical_id is None:
        latest = session.exec(select(CanonicalActivity).where(CanonicalActivity.start.is_not(None)).order_by(CanonicalActivity.start.desc())).first()
        canonical_id = latest.id if latest else None
    if canonical_id is None or session.get(CanonicalActivity, canonical_id) is None:
        return {"saved": False, "message": "No activity found to attach this piece to — ask which workout it belongs to."}

    if args.get("intervals") or args.get("repeat"):
        return _add_interval_piece(session, args, piece_type, canonical_id)

    splits = args.get("splits")
    total_duration_s = args.get("duration_s")
    if not splits:
        text = args.get("text")
        if not text:
            raise ValueError("Provide either `text` or a structured `splits` list.")
        splits, parsed_total = _parse_piece_free_text(piece_type, text)
        total_duration_s = total_duration_s or parsed_total

    agg = aggregate_from_splits(splits)
    distance_m = args.get("distance_m") or agg["distance_m"]
    duration_s = total_duration_s or agg["duration_s"]
    validation = validate_splits(splits, distance_m, duration_s)

    if not args.get("confirm"):
        return {
            "saved": False,
            "preview": splits,
            "validation": validation,
            "piece_type": piece_type,
            "canonical_id": canonical_id,
            "message": "Preview only — confirm this table with the athlete, then call add_piece again with confirm=true.",
        }

    # force=True: the preview above already surfaced any validation issues to the athlete —
    # confirm=true means they've seen them and still want it saved as typed (task's "manual
    # entry always works" — the same athlete-facing issues list is still on the response).
    piece, validation = piece_sync.create_piece(
        session, canonical_id, piece_type, splits, distance_m=distance_m, duration_s=duration_s, source="manual", force=True
    )
    return {"saved": True, "piece": piece_sync.piece_dict(piece), "validation": validation}


def _add_interval_piece(session: Session, args: dict, piece_type: str, canonical_id: int) -> dict:
    """Session 19: a piece made of intervals — either `repeat` ({count, distance_m|duration_s,
    rest_s}, expanded by the same expand_repeat the API/UI use) or an explicit `intervals`
    list. Same preview-then-confirm contract as the splits path."""
    from catch.analytics.piece_intervals import expand_repeat, summarize_intervals, validate_intervals
    from catch.sync import piece as piece_sync
    from catch.sync import piece_intervals as intervals_sync

    if args.get("repeat"):
        r = args["repeat"]
        rows = expand_repeat(int(r["count"]), work_distance_m=r.get("distance_m"), work_duration_s=r.get("duration_s"), rest_duration_s=r.get("rest_s"))
    else:
        rows = [{**row, "position": i} for i, row in enumerate(args["intervals"])]
    validation = validate_intervals(rows)
    if not args.get("confirm"):
        return {
            "saved": False,
            "preview": rows,
            "summary": summarize_intervals(rows),
            "validation": validation,
            "piece_type": piece_type,
            "canonical_id": canonical_id,
            "message": "Preview only — confirm these intervals with the athlete, then call add_piece again with confirm=true.",
        }
    piece, validation = intervals_sync.create_interval_piece(session, canonical_id, rows, piece_type=piece_type, force=True)
    return {"saved": True, "piece": piece_sync.piece_payload(session, piece), "validation": validation}


def _make_pacing_plan(session: Session, args: dict, ctx: dict) -> dict:
    body = routes_tests.PacingPlanRequest(
        test_type=args["test_type"],
        goal_time_s=float(args["goal_time_s"]),
        style=args["style"],
        distance_m=args.get("distance_m"),
        # The task's own framing ("save it to the next event in coach memory") makes saving
        # the default for this tool specifically — unlike the equivalent API call
        # (POST /api/tests/pacing-plan), which defaults to off for an explicit opt-in Save
        # button in the UI.
        save_to_next_event=bool(args.get("save_to_next_event", True)),
    )
    return routes_tests.make_pacing_plan(body=body, db=session)


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
                "type": {"type": "string", "enum": ["erg", "on_water", "strength", "other"], "description": "Workout category filter."},
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
                        "checkin_soreness", "checkin_stress", "checkin_mood", "checkin_sleep_quality",
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
    "log_strength": {
        "fn": _log_strength,
        "write": True,
        "description": (
            "Log a lifting set, from free text (one exercise per call, e.g. '3x8 cable row stack 12 on "
            "station 2') or a structured sets list. Always call once without confirm=true first — this "
            "returns a preview of the parsed exercise/reps/load for the athlete to check (parsing free text "
            "is best-effort and can get the exercise or load wrong). Only call again with the same sets and "
            "confirm=true once the athlete has confirmed it's right. Appends to today's session if one "
            "already exists."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Free-text description of one exercise's sets."},
                "sets": {
                    "type": "array",
                    "description": "Alternative to text — one entry per set.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "exercise_id": {"type": "integer"},
                            "exercise_name": {"type": "string", "description": "Used to look up exercise_id if exercise_id isn't given."},
                            "equipment_type": {
                                "type": "string",
                                "enum": ["barbell", "dumbbell", "kettlebell", "machine_plate", "machine_selectorized", "smith", "cable", "bodyweight", "weighted", "assisted", "band", "other"],
                            },
                            "reps": {"type": "integer"},
                            "load_kg": {"type": "number", "description": "The raw number read off the equipment — plates added for barbell/smith, per-hand for dumbbell/kettlebell, stack number for cable/selectorized."},
                            "bar_weight_kg": {"type": "number"},
                            "pulley_multiplier": {"type": "number"},
                            "rir": {"type": "number"},
                            "rpe": {"type": "number"},
                            "set_type": {"type": "string", "enum": ["warmup", "working", "drop", "failure", "amrap"]},
                        },
                        "required": ["reps"],
                    },
                },
                "confirm": {"type": "boolean", "description": "Only set true after the athlete has confirmed the preview."},
            },
            "additionalProperties": False,
        },
    },
    "get_strength": {
        "fn": _get_strength,
        "write": False,
        "description": "Logged strength sets over a date range (defaults to the last 28 days), optionally filtered to one exercise by exercise_id or exercise_name. Capped to 180 rows.",
        "input_schema": {
            "type": "object",
            "properties": {
                **_DATE_RANGE_PROPS,
                "exercise_id": {"type": "integer"},
                "exercise_name": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    "get_muscle_readiness": {
        "fn": _get_muscle_readiness,
        "write": False,
        "description": "Raw muscular load (AU) per muscle group over the trailing 72 hours — which muscle groups are still loaded from recent lifting, for planning what to train next or whether to go heavy again.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "get_tests": {
        "fn": _get_tests,
        "write": False,
        "description": "List confirmed erg tests (500m/1000m/2000m/5000m/6000m/30min_r20/60min/custom), newest first, optionally filtered to one type.",
        "input_schema": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["500m", "1000m", "2000m", "5000m", "6000m", "30min_r20", "60min", "custom"],
                },
            },
            "additionalProperties": False,
        },
    },
    "get_test": {
        "fn": _get_test,
        "write": False,
        "description": "One erg test's full detail: pacing analysis (start/middle-1000/sprint, deviation from even split, where time was lost) vs. any saved plan, comparison to the athlete's earlier test of the same type, and W/kg. get_tests' rows carry a \"kind\" of \"test\" or \"piece\" — pass that row's id for a test, or piece_id for a piece.",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "Canonical workout id, for a get_tests row with kind=='test'."},
                "piece_id": {"type": "integer", "description": "For a get_tests row with kind=='piece'."},
            },
            "additionalProperties": False,
        },
    },
    "get_training_profile": {
        "fn": _get_training_profile,
        "write": False,
        "description": "The athlete's current training profile: inferred phase, recent performance trajectory, a consistency summary, data-supported strengths and areas to investigate, today's recovery/load/illness context, and a confidence level based on how much data backs it.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "get_performance_trends": {
        "fn": _get_performance_trends,
        "write": False,
        "description": "Equivalent-piece performance trends per standard test/piece type: best, typical, and recent results, a trend projection, and a note on whether an apparent improvement might just be a pacing/rate change rather than real improvement.",
        "input_schema": {
            "type": "object",
            "properties": {
                "piece_type": {
                    "type": "string",
                    "enum": ["500m", "1000m", "2000m", "5000m", "6000m", "30min_r20", "60min", "custom"],
                },
            },
            "additionalProperties": False,
        },
    },
    "get_route": {
        "fn": _get_route,
        "write": False,
        "description": "GPS summary of one workout (by the same id get_workout uses): the general area, GPS-derived distance/moving time/average speed next to the distance Garmin itself reported, the filtering report, and which repeated route (if any) it belongs to. Returns no coordinates. Every figure is labelled gps_derived or provider. If the activity has no GPS track it says why — report that rather than guessing.",
        "input_schema": {
            "type": "object",
            "properties": {"activity_id": {"type": "integer", "description": "The workout id (as in list_workouts)."}},
            "required": ["activity_id"],
            "additionalProperties": False,
        },
    },
    "get_route_history": {
        "fn": _get_route_history,
        "write": False,
        "description": "Every session on one repeated route (route id from get_route): best, typical (median) and recent moving average speed, speed distribution, heart-rate context and the weather beside each session. Times are NOT wind-, current- or water-corrected and include workout structure; weather differences are observations, not adjustments. Comparisons only exist because the tracks aligned.",
        "input_schema": {
            "type": "object",
            "properties": {"route_id": {"type": "integer"}},
            "required": ["route_id"],
            "additionalProperties": False,
        },
    },
    "get_on_water_metrics": {
        "fn": _get_on_water_metrics,
        "write": False,
        "description": "GPS-derived on-water (or any outdoor) metrics for one workout: distance, elapsed vs moving time, average and peak speed, pace (s/500m for rowing), split table over a chosen distance, pace consistency, and lap breakdown when more than one lap was recorded. Each figure has a source (gps_derived, provider or manual); provider figures are shown alongside, never blended. These are raw GPS figures and are not corrected for conditions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "activity_id": {"type": "integer"},
                "split_m": {"type": "number", "minimum": 50, "maximum": 10000, "description": "Split distance in metres (50-10000). Default 500 for rowing, 1000 for running."},
            },
            "required": ["activity_id"],
            "additionalProperties": False,
        },
    },
    "get_workout_weather": {
        "fn": _get_workout_weather,
        "write": False,
        "description": "Observed weather for a workout's time window and area: temperature, wind speed/gusts and the direction it blows FROM, precipitation, humidity, pressure and conditions, with a status (ok/partial/unavailable/not_fetched/no_gps) and coverage. It is gridded reanalysis data for the area, not a measurement at the water, and context only: it may help explain a session but is never a performance correction. Anything you say about how conditions affected the session is your inference, not data — say so.",
        "input_schema": {
            "type": "object",
            "properties": {"activity_id": {"type": "integer"}},
            "required": ["activity_id"],
            "additionalProperties": False,
        },
    },
    "get_interval_comparisons": {
        "fn": _get_interval_comparisons,
        "write": False,
        "description": "Interval-session progress, grouped by identical structure (e.g. '4x500m/r60'): best/typical/recent weighted-average split across sessions, with watts/rate/HR for each. Interval pieces are kept out of single-effort PBs, 2k prediction and test trends, so this is where interval progress lives.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "get_training_distribution": {
        "fn": _get_training_distribution,
        "write": False,
        "description": "Weekly training volume by HR zone (UT2/UT1/AT/TR/AN) plus strength-session minutes, over a trailing window.",
        "input_schema": {
            "type": "object",
            "properties": {"weeks": {"type": "integer", "description": "1-52, default 12."}},
            "additionalProperties": False,
        },
    },
    "get_training_consistency": {
        "fn": _get_training_consistency,
        "write": False,
        "description": "Sessions completed vs. the athlete's own configured weekly target, rest days, whether training has been unusually concentrated on a couple of days, and the zone-distribution split, over a trailing window.",
        "input_schema": {
            "type": "object",
            "properties": {"weeks": {"type": "integer", "description": "1-52, default settings.training_intelligence.consistency_lookback_weeks."}},
            "additionalProperties": False,
        },
    },
    "get_training_insights": {
        "fn": _get_training_insights,
        "write": False,
        "description": "A short list of recurring patterns the data supports (weekday concentration, recovery after high-strain days, a recurring fast-start pacing pattern, zone polarization, consistency gaps), each with its own confidence and supporting evidence. Worded correlationally, never as proof of cause.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "get_recommendations": {
        "fn": _get_recommendations,
        "write": False,
        "description": "Training/recovery/data-quality/overload recommendations the app has generated, with the reasoning and evidence behind each. Never prescribes aggressive training or tells the athlete to ignore symptoms.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["active", "dismissed", "all"], "description": "Default 'active'."},
                "type": {"type": "string", "enum": ["training_suggestion", "recovery_suggestion", "data_quality_warning", "overload_warning"]},
            },
            "additionalProperties": False,
        },
    },
    "rate_recommendation": {
        "fn": _rate_recommendation,
        "write": True,
        "description": "Mark a recommendation (by its id from get_recommendations) useful or not useful, for the athlete's own record. Call this only when the athlete explicitly says whether a specific recommendation helped — it doesn't change which recommendations get generated.",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "rating": {"type": "string", "enum": ["useful", "not_useful"]},
            },
            "required": ["id", "rating"],
            "additionalProperties": False,
        },
    },
    "add_piece": {
        "fn": _add_piece,
        "write": True,
        "description": (
            "Add a piece (a segment of a workout, e.g. a 2k inside a longer row) from free text like 'my 2k was "
            "6:32.4, splits 1:36.8, 1:38.9, 1:39.0, 1:37.7' or a structured splits list. Always call once without "
            "confirm=true first to preview the parsed table for the athlete to check, then call again with the "
            "same data and confirm=true once they've confirmed it's right."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "piece_type": {
                    "type": "string",
                    "enum": ["500m", "1000m", "2000m", "5000m", "6000m", "30min_r20", "60min", "custom"],
                },
                "canonical_id": {"type": "integer", "description": "Which workout this piece belongs to. Defaults to the most recent workout."},
                "text": {"type": "string", "description": "Free text containing the total time followed by each split, e.g. '6:32.4, splits 1:36.8, 1:38.9, 1:39.0, 1:37.7'."},
                "splits": {
                    "type": "array",
                    "description": "Structured splits, alternative to text.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "split_index": {"type": "integer"},
                            "distance_m": {"type": "number"},
                            "split_s": {"type": "number"},
                            "rate": {"type": "number"},
                            "watts": {"type": "number"},
                            "hr": {"type": "number"},
                        },
                    },
                },
                "repeat": {
                    "type": "object",
                    "description": "An interval piece such as 4 x 500m with 1:00 rest: {count, distance_m OR duration_s, rest_s}. Use piece_type 'custom'. Alternative to text/splits.",
                    "properties": {"count": {"type": "integer"}, "distance_m": {"type": "number"}, "duration_s": {"type": "number"}, "rest_s": {"type": "number"}},
                    "required": ["count"],
                },
                "intervals": {
                    "type": "array",
                    "description": "Explicit interval list for variable structures; each has target_type ('distance'|'time'), work_distance_m and/or work_duration_s, and optional rest_duration_s, avg_split_s, avg_watts, avg_rate, avg_hr, max_hr, calories.",
                    "items": {"type": "object"},
                },
                "distance_m": {"type": "number", "description": "Total distance, if not implied by piece_type."},
                "duration_s": {"type": "number", "description": "Total time in seconds, if not already parsed from text."},
                "confirm": {"type": "boolean", "description": "Defaults to false (preview only)."},
            },
            "required": ["piece_type"],
            "additionalProperties": False,
        },
    },
    "make_pacing_plan": {
        "fn": _make_pacing_plan,
        "write": True,
        "description": "Generate a pacing plan (per-500m targets, scaled to the goal time) for a given test type and style. Saves it to the athlete's next upcoming event by default, so it shows on that test's detail page afterward.",
        "input_schema": {
            "type": "object",
            "properties": {
                "test_type": {
                    "type": "string",
                    "enum": ["500m", "1000m", "2000m", "5000m", "6000m", "30min_r20", "60min", "custom"],
                },
                "goal_time_s": {"type": "number", "description": "Goal time in seconds."},
                "style": {"type": "string", "enum": ["even", "fast_start_settle", "negative_split"]},
                "distance_m": {
                    "type": "number",
                    "description": "Required for 'custom'. For 30min_r20/60min, the target distance to cover in that fixed duration.",
                },
                "save_to_next_event": {"type": "boolean", "description": "Defaults to true."},
            },
            "required": ["test_type", "goal_time_s", "style"],
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
