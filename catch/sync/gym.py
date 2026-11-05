from __future__ import annotations

"""The DB-facing gym-logger layer (session 14 — see PLAN.md Part A/B/C): exercise library,
gyms/stations, logging a session's sets, e1RM/PR detection, and muscular-load caching onto
CanonicalActivity. catch/analytics/equipment.py and catch/analytics/strength.py hold the pure
math; this module is only I/O, mirroring catch/sync/nutrition.py's split from
catch/analytics/nutrition.py.

A Catch lifting session *is* an `Activity` row (`source="catch_strength"`, `external_id=`
the client-generated session UUID — task Part B.1), reusing `catch.sync.upsert.upsert_activity`
so the matching engine, canonical resolution, and every existing "an activity" reader work on
it unchanged. Sets are upserted idempotently keyed on each set's own client-generated UUID
(`StrengthSet.client_id`) — the offline-sync counterpart to CLAUDE.md's "(source,
external_id)" upsert rule, needed because a dropped response on bad gym wifi must retry
without ever duplicating a set."""

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlmodel import Session, select

from catch.analytics import equipment as eq
from catch.analytics.strength import (
    WorkingSet,
    detect_pr,
    distribute_to_muscles,
    set_muscular_au,
)
from catch.core.models import (
    Activity,
    CanonicalActivity,
    Exercise,
    Gym,
    GymStation,
    StrengthSet,
    StrengthTemplate,
)
from catch.sync.body_comp import nearest_resolved_weight_kg
from catch.sync.fit_parse import parse_fit_sets
from catch.sync.upsert import upsert_activity

SESSION_SOURCE = "catch_strength"
SESSION_START_PAD_S = 600  # 10 minutes before the first set (task Part B.1).
SESSION_END_PAD_S = 300  # 5 minutes after the last set.
BASELINE_WINDOW_DAYS = 28
READINESS_WINDOW_HOURS = 72


def _exercise_out(e: Exercise) -> dict:
    return {
        "id": e.id,
        "external_id": e.external_id,
        "name": e.name,
        "default_equipment_type": e.default_equipment_type,
        "movement_pattern": e.movement_pattern,
        "unilateral": e.unilateral,
        "primary_muscles": json.loads(e.primary_muscles_json or "[]"),
        "secondary_muscles": json.loads(e.secondary_muscles_json or "[]"),
        "custom": e.custom,
    }


# -- exercise library -------------------------------------------------------------------------


def list_exercises(session: Session, query: Optional[str] = None) -> list[dict]:
    rows = session.exec(select(Exercise).order_by(Exercise.name)).all()
    if query:
        q = query.strip().lower()
        rows = [r for r in rows if q in r.name.lower()]
    return [_exercise_out(r) for r in rows]


def get_exercise(session: Session, exercise_id: int) -> Optional[Exercise]:
    return session.get(Exercise, exercise_id)


def create_custom_exercise(
    session: Session,
    *,
    name: str,
    default_equipment_type: str,
    movement_pattern: str,
    unilateral: bool = False,
    primary_muscles: Optional[list[str]] = None,
    secondary_muscles: Optional[list[str]] = None,
) -> dict:
    row = Exercise(
        external_id=None,
        name=name,
        default_equipment_type=default_equipment_type,
        movement_pattern=movement_pattern,
        unilateral=unilateral,
        primary_muscles_json=json.dumps(primary_muscles or []),
        secondary_muscles_json=json.dumps(secondary_muscles or []),
        custom=True,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _exercise_out(row)


def update_exercise(session: Session, exercise_id: int, patch: dict) -> dict:
    row = session.get(Exercise, exercise_id)
    if row is None:
        raise ValueError("exercise not found")
    for key in ("name", "default_equipment_type", "movement_pattern", "unilateral"):
        if key in patch:
            setattr(row, key, patch[key])
    if "primary_muscles" in patch:
        row.primary_muscles_json = json.dumps(patch["primary_muscles"])
    if "secondary_muscles" in patch:
        row.secondary_muscles_json = json.dumps(patch["secondary_muscles"])
    session.add(row)
    session.commit()
    session.refresh(row)
    return _exercise_out(row)


# -- gyms / stations (task Part A.3's "save stations per gym") ------------------------------


def list_gyms(session: Session) -> list[Gym]:
    return session.exec(select(Gym).order_by(Gym.name)).all()


def create_gym(session: Session, name: str) -> Gym:
    row = Gym(name=name)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def list_stations(session: Session, gym_id: int) -> list[dict]:
    rows = session.exec(select(GymStation).where(GymStation.gym_id == gym_id).order_by(GymStation.name)).all()
    return [_station_out(r) for r in rows]


def _station_out(s: GymStation) -> dict:
    return {
        "id": s.id,
        "gym_id": s.gym_id,
        "name": s.name,
        "equipment_type": s.equipment_type,
        "config": json.loads(s.config_json or "{}"),
    }


def upsert_station(session: Session, *, gym_id: int, name: str, equipment_type: str, config: dict, station_id: Optional[int] = None) -> dict:
    if station_id:
        row = session.get(GymStation, station_id)
        if row is None:
            raise ValueError("station not found")
    else:
        row = GymStation(gym_id=gym_id, name=name, equipment_type=equipment_type)
        session.add(row)
    row.gym_id = gym_id
    row.name = name
    row.equipment_type = equipment_type
    row.config_json = json.dumps(config)
    session.add(row)
    session.commit()
    session.refresh(row)
    return _station_out(row)


# -- effective load dispatch -----------------------------------------------------------------


def compute_effective_load(
    session: Session,
    *,
    equipment_type: str,
    load_kg: Optional[float],
    bar_weight_kg: Optional[float],
    pulley_multiplier: Optional[float],
    added_weight_kg: Optional[float],
    assistance_kg: Optional[float],
    bilateral: bool,
    band_tag: Optional[str],
    station_config: Optional[dict],
    at: Optional[datetime],
) -> tuple[Optional[float], bool, Optional[str], Optional[float]]:
    """Routes to catch/analytics/equipment.py's pure functions; returns
    (effective_load_kg, is_estimated, note, bodyweight_kg_used). `bodyweight_kg_used` is
    whatever this call actually resolved (Withings via nearest_resolved_weight_kg), snapshotted
    by the caller onto the StrengthSet row — a later Withings sync must never silently rewrite
    a past session's effective load."""
    station_config = station_config or {}
    bw: Optional[float] = None

    if equipment_type == "barbell":
        r = eq.barbell_load(load_kg or 0.0, bar_weight_kg if bar_weight_kg is not None else eq.DEFAULT_BARBELL_KG)
    elif equipment_type == "smith":
        r = eq.smith_load(load_kg or 0.0, bar_weight_kg)
    elif equipment_type in ("dumbbell", "kettlebell"):
        r = eq.dumbbell_or_kettlebell_load(load_kg or 0.0, bilateral)
    elif equipment_type == "machine_plate":
        r = eq.machine_plate_load(load_kg or 0.0, station_config.get("base_weight_kg", 0.0))
    elif equipment_type == "machine_selectorized":
        r = eq.selectorized_load(
            load_kg or 0.0, station_config.get("stack_kg_per_increment", 1.0), station_config.get("base_weight_kg", 0.0)
        )
    elif equipment_type == "cable":
        r = eq.cable_load(load_kg or 0.0, pulley_multiplier if pulley_multiplier is not None else station_config.get("pulley_multiplier", 1.0))
    elif equipment_type == "bodyweight":
        bw = nearest_resolved_weight_kg(session, at or datetime.now(timezone.utc))
        r = eq.bodyweight_load(bw)
    elif equipment_type == "weighted":
        bw = nearest_resolved_weight_kg(session, at or datetime.now(timezone.utc))
        r = eq.weighted_bodyweight_load(bw, added_weight_kg or 0.0)
    elif equipment_type == "assisted":
        bw = nearest_resolved_weight_kg(session, at or datetime.now(timezone.utc))
        r = eq.assisted_bodyweight_load(bw, assistance_kg or 0.0)
    elif equipment_type == "band":
        r = eq.band_load(band_tag or "medium")
    else:
        r = eq.LoadResult(load_kg, False, None)

    return r.effective_load_kg, r.is_estimated, r.note, bw


# -- logging a session -----------------------------------------------------------------------


def get_or_create_session(session: Session, client_session_id: str) -> Activity:
    return upsert_activity(session, SESSION_SOURCE, client_session_id, type="catch_strength", sport_family="strength")


def _recompute_session_window(session: Session, activity: Activity) -> None:
    sets = session.exec(
        select(StrengthSet).where(StrengthSet.activity_id == activity.id, StrengthSet.deleted.is_(False))
    ).all()
    if not sets:
        return
    first = min(s.created_at for s in sets)
    last = max(s.created_at for s in sets)
    activity.start = first - timedelta(seconds=SESSION_START_PAD_S)
    activity.duration = (last - activity.start).total_seconds() + SESSION_END_PAD_S
    activity.updated_at = datetime.now(timezone.utc)
    session.add(activity)
    session.commit()


def _history_for_pr(session: Session, exercise_id: int, exclude_client_id: str) -> list[WorkingSet]:
    rows = session.exec(
        select(StrengthSet).where(
            StrengthSet.exercise_id == exercise_id,
            StrengthSet.deleted.is_(False),
            StrengthSet.client_id != exclude_client_id,
        )
    ).all()
    out = []
    for r in rows:
        if r.effective_load_kg is None:
            continue
        out.append(
            WorkingSet(
                exercise_id=r.exercise_id,
                date=r.created_at.date().isoformat(),
                reps=r.reps,
                effective_load_kg=r.effective_load_kg,
                set_type=r.set_type,
                rir=r.rir,
                rpe=r.rpe,
                side=r.side,
            )
        )
    return out


def upsert_set(session: Session, client_session_id: str, set_data: dict) -> dict:
    """Idempotent on `set_data["client_id"]`. `set_data` also carries the session's own
    `client_session_id` fields implicitly via the caller's session row. Recomputes the
    session Activity's start/duration and this set's PR flags/muscular AU every time — cheap
    at this app's per-session set count, and avoids a second "what changed" code path."""
    activity = get_or_create_session(session, client_session_id)

    client_id = set_data["client_id"]
    row = session.exec(select(StrengthSet).where(StrengthSet.client_id == client_id)).first()
    is_new = row is None
    if row is None:
        row = StrengthSet(client_id=client_id, activity_id=activity.id, exercise_id=set_data["exercise_id"])
    row.activity_id = activity.id
    row.exercise_id = set_data["exercise_id"]
    row.gym_station_id = set_data.get("gym_station_id")
    row.seq = set_data.get("seq", row.seq)
    row.superset_group = set_data.get("superset_group")
    row.set_type = set_data.get("set_type", "working")
    row.reps = set_data["reps"]
    row.side = set_data.get("side")
    row.tempo = set_data.get("tempo")
    row.rir = set_data.get("rir")
    row.rpe = set_data.get("rpe")
    row.equipment_type = set_data["equipment_type"]
    row.load_kg = set_data.get("load_kg")
    row.notes = set_data.get("notes")
    if set_data.get("created_at"):
        row.created_at = datetime.fromisoformat(set_data["created_at"])
    elif is_new:
        row.created_at = datetime.now(timezone.utc)

    exercise = session.get(Exercise, row.exercise_id)
    bilateral = not (exercise and exercise.unilateral and row.side)
    station = session.get(GymStation, row.gym_station_id) if row.gym_station_id else None
    effective, is_estimated, note, bw = compute_effective_load(
        session,
        equipment_type=row.equipment_type,
        load_kg=row.load_kg,
        bar_weight_kg=set_data.get("bar_weight_kg"),
        pulley_multiplier=set_data.get("pulley_multiplier"),
        added_weight_kg=set_data.get("added_weight_kg"),
        assistance_kg=set_data.get("assistance_kg"),
        bilateral=bilateral,
        band_tag=set_data.get("band_tag"),
        station_config=json.loads(station.config_json) if station else None,
        at=row.created_at,
    )
    row.bar_weight_kg = set_data.get("bar_weight_kg")
    row.pulley_multiplier = set_data.get("pulley_multiplier")
    row.added_weight_kg = set_data.get("added_weight_kg")
    row.assistance_kg = set_data.get("assistance_kg")
    row.bodyweight_kg_used = bw
    row.effective_load_kg = effective
    row.load_is_estimated = is_estimated

    history = _history_for_pr(session, row.exercise_id, client_id)
    working_set = WorkingSet(
        exercise_id=row.exercise_id,
        date=row.created_at.date().isoformat(),
        reps=row.reps,
        effective_load_kg=row.effective_load_kg,
        set_type=row.set_type,
        rir=row.rir,
        rpe=row.rpe,
        side=row.side,
    )
    pr = detect_pr(working_set, history)
    row.is_rep_pr = pr.is_rep_pr
    row.is_e1rm_pr = pr.is_e1rm_pr
    row.muscular_au = set_muscular_au(working_set)
    row.updated_at = datetime.now(timezone.utc)
    session.add(row)
    session.commit()
    session.refresh(row)

    _recompute_session_window(session, activity)
    _recompute_canonical_muscular_load(session, activity.id)
    return _set_out(row, note)


def delete_set(session: Session, client_id: str) -> None:
    row = session.exec(select(StrengthSet).where(StrengthSet.client_id == client_id)).first()
    if row is None:
        return
    row.deleted = True
    row.updated_at = datetime.now(timezone.utc)
    session.add(row)
    session.commit()
    activity = session.get(Activity, row.activity_id)
    if activity:
        _recompute_session_window(session, activity)
        _recompute_canonical_muscular_load(session, activity.id)


def _set_out(row: StrengthSet, load_note: Optional[str] = None) -> dict:
    return {
        "client_id": row.client_id,
        "exercise_id": row.exercise_id,
        "gym_station_id": row.gym_station_id,
        "seq": row.seq,
        "superset_group": row.superset_group,
        "set_type": row.set_type,
        "reps": row.reps,
        "side": row.side,
        "tempo": row.tempo,
        "rir": row.rir,
        "rpe": row.rpe,
        "equipment_type": row.equipment_type,
        "load_kg": row.load_kg,
        "effective_load_kg": row.effective_load_kg,
        "load_is_estimated": row.load_is_estimated,
        "load_note": load_note,
        "bodyweight_kg_used": row.bodyweight_kg_used,
        "is_rep_pr": row.is_rep_pr,
        "is_e1rm_pr": row.is_e1rm_pr,
        "muscular_au": row.muscular_au,
        "source": row.source,
        "is_confirmed": row.is_confirmed,
        "notes": row.notes,
        "created_at": row.created_at.isoformat(),
    }


def list_session_sets(session: Session, client_session_id: str) -> list[dict]:
    activity = session.exec(
        select(Activity).where(Activity.source == SESSION_SOURCE, Activity.external_id == client_session_id)
    ).first()
    if activity is None:
        return []
    rows = session.exec(
        select(StrengthSet)
        .where(StrengthSet.activity_id == activity.id, StrengthSet.deleted.is_(False))
        .order_by(StrengthSet.seq)
    ).all()
    return [_set_out(r) for r in rows]


def last_session_sets_for_exercise(session: Session, exercise_id: int, before: Optional[datetime] = None) -> list[dict]:
    """Task Part A.4's "last session's numbers shown inline for each exercise" — the most
    recent calendar day this exercise was logged on, every set from that day."""
    rows = session.exec(
        select(StrengthSet)
        .where(StrengthSet.exercise_id == exercise_id, StrengthSet.deleted.is_(False))
        .order_by(StrengthSet.created_at.desc())
    ).all()
    rows = [r for r in rows if before is None or r.created_at < before]
    if not rows:
        return []
    last_day = rows[0].created_at.date()
    same_day = [r for r in rows if r.created_at.date() == last_day]
    same_day.sort(key=lambda r: r.seq)
    return [_set_out(r) for r in same_day]


def repeat_last_workout(session: Session, before: Optional[datetime] = None) -> list[dict]:
    """Every exercise/equipment config from the most recent strength session, as a template
    of planned sets (no reps/load pre-filled — task Part A.5's "repeat last workout")."""
    rows = session.exec(
        select(StrengthSet).where(StrengthSet.deleted.is_(False)).order_by(StrengthSet.created_at.desc())
    ).all()
    rows = [r for r in rows if before is None or r.created_at < before]
    if not rows:
        return []
    last_activity_id = rows[0].activity_id
    same_session = [r for r in rows if r.activity_id == last_activity_id]
    same_session.sort(key=lambda r: r.seq)
    return [
        {
            "exercise_id": r.exercise_id,
            "gym_station_id": r.gym_station_id,
            "equipment_type": r.equipment_type,
            "set_type": r.set_type,
            "target_reps": r.reps,
        }
        for r in same_session
    ]


# -- templates (task Part A.5) ----------------------------------------------------------------


def list_templates(session: Session) -> list[dict]:
    rows = session.exec(select(StrengthTemplate).order_by(StrengthTemplate.name)).all()
    return [{"id": r.id, "name": r.name, "items": json.loads(r.items_json)} for r in rows]


def save_template(session: Session, *, name: str, items: list[dict], template_id: Optional[int] = None) -> dict:
    if template_id:
        row = session.get(StrengthTemplate, template_id)
        if row is None:
            raise ValueError("template not found")
    else:
        row = StrengthTemplate(name=name, items_json="[]")
        session.add(row)
    row.name = name
    row.items_json = json.dumps(items)
    row.updated_at = datetime.now(timezone.utc)
    session.add(row)
    session.commit()
    session.refresh(row)
    return {"id": row.id, "name": row.name, "items": items}


def delete_template(session: Session, template_id: int) -> None:
    row = session.get(StrengthTemplate, template_id)
    if row:
        session.delete(row)
        session.commit()


# -- muscular load caching (task Part C) ------------------------------------------------------


def _recompute_canonical_muscular_load(session: Session, activity_id: int) -> None:
    """Sums this strength session's own working-set AU per muscle and caches it on the
    activity's CanonicalActivity — catch/sync/scoring.py reads the cache, never recomputes
    across history itself (same pattern as strain_trimp)."""
    activity = session.get(Activity, activity_id)
    if activity is None or activity.canonical_id is None:
        return
    rows = session.exec(
        select(StrengthSet).where(StrengthSet.activity_id == activity_id, StrengthSet.deleted.is_(False))
    ).all()
    by_muscle: dict[str, float] = {}
    total = 0.0
    for r in rows:
        if not r.muscular_au:
            continue
        exercise = session.get(Exercise, r.exercise_id)
        if exercise is None:
            continue
        primary = json.loads(exercise.primary_muscles_json or "[]")
        secondary = json.loads(exercise.secondary_muscles_json or "[]")
        contrib = distribute_to_muscles(r.muscular_au, primary, secondary)
        for muscle, au in contrib.items():
            by_muscle[muscle] = by_muscle.get(muscle, 0.0) + au
        total += r.muscular_au

    canonical = session.get(CanonicalActivity, activity.canonical_id)
    if canonical is None:
        return
    canonical.muscular_load_au = total or None
    canonical.muscular_by_muscle_json = json.dumps(by_muscle) if by_muscle else None
    canonical.updated_at = datetime.now(timezone.utc)
    session.add(canonical)
    session.commit()


def muscle_readiness(session: Session, now: Optional[datetime] = None) -> dict:
    """Task Part C.3: raw (non-normalized — this is a display of real recent load, not a
    strain-curve input) muscular AU per muscle group over the trailing 72h, for the front/
    back body-map view."""
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(hours=READINESS_WINDOW_HOURS)
    rows = session.exec(
        select(CanonicalActivity).where(
            CanonicalActivity.start >= start, CanonicalActivity.start <= now, CanonicalActivity.muscular_by_muscle_json.is_not(None)
        )
    ).all()
    totals: dict[str, float] = {}
    for r in rows:
        for muscle, au in json.loads(r.muscular_by_muscle_json).items():
            totals[muscle] = totals.get(muscle, 0.0) + au
    return {"window_hours": READINESS_WINDOW_HOURS, "by_muscle": totals}


def _local_day_utc_range(day) -> tuple[datetime, datetime]:
    # Same local-day -> UTC-range computation as catch/sync/scoring.py's own helper
    # (duplicated, not imported, to avoid a gym.py<->scoring.py import cycle — both files call
    # into each other's module at different points in the sync pipeline).
    local_midnight = datetime(day.year, day.month, day.day)
    start_utc = local_midnight.astimezone(timezone.utc)
    end_utc = (local_midnight + timedelta(days=1)).astimezone(timezone.utc)
    return start_utc, end_utc


def muscle_baseline_and_today(session: Session, day) -> tuple[dict[str, float], dict[str, list[float]]]:
    """For catch/sync/scoring.py's day-level strain combine: `day`'s own per-muscle AU totals,
    and each muscle's trailing-28-day *daily* totals (one number per day it appears, missing
    days simply absent — catch/analytics/strength.py's normalize_muscle_au only needs an
    average) for catch/analytics/strength.py's normalize_muscle_au baseline."""
    start, end = _local_day_utc_range(day)
    today_rows = session.exec(
        select(CanonicalActivity).where(
            CanonicalActivity.start >= start, CanonicalActivity.start < end, CanonicalActivity.muscular_by_muscle_json.is_not(None)
        )
    ).all()
    today: dict[str, float] = {}
    for r in today_rows:
        for muscle, au in json.loads(r.muscular_by_muscle_json).items():
            today[muscle] = today.get(muscle, 0.0) + au

    baseline_start, _ = _local_day_utc_range(day - timedelta(days=BASELINE_WINDOW_DAYS))
    history_rows = session.exec(
        select(CanonicalActivity).where(
            CanonicalActivity.start >= baseline_start, CanonicalActivity.start < start, CanonicalActivity.muscular_by_muscle_json.is_not(None)
        )
    ).all()
    by_day_muscle: dict[tuple, float] = {}
    for r in history_rows:
        local_day = r.start.astimezone().date()
        for muscle, au in json.loads(r.muscular_by_muscle_json).items():
            key = (local_day, muscle)
            by_day_muscle[key] = by_day_muscle.get(key, 0.0) + au
    baseline: dict[str, list[float]] = {}
    for (_, muscle), au in by_day_muscle.items():
        baseline.setdefault(muscle, []).append(au)

    return today, baseline


# -- importing Garmin watch-counted sets as a draft (task Part B.2) -------------------------


def _best_exercise_match(session: Session, category: Optional[str]) -> Optional[int]:
    """Best-effort only — Garmin's own exercise-category enum (hundreds of values) has no
    reliable mapping onto this app's exercise library, so this is a plain substring match on
    the category's own word against exercise names, not a curated table. None (no match) is
    the common, expected result; the athlete picks the real exercise when confirming the
    draft (task Part B.2's "import ... as a draft I can fix")."""
    if not category:
        return None
    word = category.replace("_", " ").strip().lower()
    row = session.exec(select(Exercise).where(Exercise.name.ilike(f"%{word}%"))).first()
    return row.id if row else None


def import_garmin_draft_sets(session: Session, garmin_activity_id: int) -> dict:
    """Parses `garmin_activity_id`'s FIT file for watch-counted sets and imports them as
    unconfirmed drafts — but only if nothing real is already logged for that physical session
    (task Part B.2: "if both exist, Catch wins and Garmin's sets are ignored"). Checks every
    Activity sharing the same canonical, not just `garmin_activity_id` itself, since a
    Catch-logged session merges onto its own `catch_strength` Activity row, a different id."""
    garmin_activity = session.get(Activity, garmin_activity_id)
    if garmin_activity is None or garmin_activity.source != "garmin" or not garmin_activity.fit_path:
        return {"imported": 0, "unmatched": 0, "skipped_reason": "no Garmin FIT file"}

    if garmin_activity.canonical_id is not None:
        sibling_ids = session.exec(
            select(Activity.id).where(Activity.canonical_id == garmin_activity.canonical_id)
        ).all()
        existing_real = session.exec(
            select(StrengthSet).where(StrengthSet.activity_id.in_(sibling_ids), StrengthSet.source == "catch", StrengthSet.deleted.is_(False))
        ).first()
        if existing_real is not None:
            return {"imported": 0, "unmatched": 0, "skipped_reason": "a real Catch-logged session already exists"}

    already_imported = session.exec(
        select(StrengthSet).where(StrengthSet.activity_id == garmin_activity_id, StrengthSet.source == "garmin_draft")
    ).first()
    if already_imported is not None:
        return {"imported": 0, "unmatched": 0, "skipped_reason": "already imported"}

    drafts = parse_fit_sets(garmin_activity.fit_path)
    imported, unmatched = 0, 0
    base_time = garmin_activity.start or datetime.now(timezone.utc)
    for i, d in enumerate(drafts):
        exercise_id = _best_exercise_match(session, d.category)
        if exercise_id is None:
            unmatched += 1
        row = StrengthSet(
            client_id=f"garmin-draft-{garmin_activity_id}-{i}",
            activity_id=garmin_activity_id,
            exercise_id=exercise_id,
            seq=i,
            set_type="working",
            reps=d.reps or 0,
            equipment_type="other",
            load_kg=d.weight_kg,
            effective_load_kg=d.weight_kg,
            load_is_estimated=True,
            source="garmin_draft",
            is_confirmed=False,
            notes=f"Imported from Garmin (raw category: {d.category})" if d.category else "Imported from Garmin",
            created_at=base_time + timedelta(seconds=d.offset_s),
        )
        session.add(row)
        imported += 1
    if imported:
        session.commit()
    return {"imported": imported, "unmatched": unmatched, "skipped_reason": None}


def confirm_draft_set(
    session: Session,
    client_id: str,
    *,
    exercise_id: int,
    equipment_type: str,
    load_kg: Optional[float] = None,
    bar_weight_kg: Optional[float] = None,
    pulley_multiplier: Optional[float] = None,
) -> dict:
    """The athlete fixing a draft import (task Part B.2): assigns the real exercise/equipment,
    runs it through the same effective-load/PR/muscular-AU math `upsert_set` uses (but without
    creating a new session Activity — a draft already lives on the Garmin activity it was
    imported onto), and flips it to a confirmed "catch" set that counts toward PRs/muscular
    load from here on."""
    row = session.exec(select(StrengthSet).where(StrengthSet.client_id == client_id)).first()
    if row is None or row.source != "garmin_draft":
        raise ValueError("draft set not found")

    row.exercise_id = exercise_id
    row.equipment_type = equipment_type
    row.load_kg = load_kg if load_kg is not None else row.load_kg

    exercise = session.get(Exercise, exercise_id)
    bilateral = not (exercise and exercise.unilateral and row.side)
    station = session.get(GymStation, row.gym_station_id) if row.gym_station_id else None
    effective, is_estimated, note, bw = compute_effective_load(
        session,
        equipment_type=equipment_type,
        load_kg=row.load_kg,
        bar_weight_kg=bar_weight_kg,
        pulley_multiplier=pulley_multiplier,
        added_weight_kg=None,
        assistance_kg=None,
        bilateral=bilateral,
        band_tag=None,
        station_config=json.loads(station.config_json) if station else None,
        at=row.created_at,
    )
    row.bar_weight_kg = bar_weight_kg
    row.pulley_multiplier = pulley_multiplier
    row.bodyweight_kg_used = bw
    row.effective_load_kg = effective
    row.load_is_estimated = is_estimated

    history = _history_for_pr(session, exercise_id, client_id)
    working_set = WorkingSet(
        exercise_id=exercise_id,
        date=row.created_at.date().isoformat(),
        reps=row.reps,
        effective_load_kg=effective,
        set_type=row.set_type,
        rir=row.rir,
        rpe=row.rpe,
        side=row.side,
    )
    pr = detect_pr(working_set, history)
    row.is_rep_pr = pr.is_rep_pr
    row.is_e1rm_pr = pr.is_e1rm_pr
    row.muscular_au = set_muscular_au(working_set)
    row.source = "catch"
    row.is_confirmed = True
    row.updated_at = datetime.now(timezone.utc)
    session.add(row)
    session.commit()
    session.refresh(row)

    _recompute_canonical_muscular_load(session, row.activity_id)
    return _set_out(row, note)
