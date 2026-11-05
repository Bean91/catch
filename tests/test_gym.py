from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlmodel import select

from catch.core.models import Activity, BodyComp, CanonicalActivity, Exercise, StrengthSet
from catch.sync import gym
from catch.sync.matching import run_matching

T0 = datetime(2026, 11, 1, 18, 0, 0, tzinfo=timezone.utc)


def _exercise(session, name="Barbell Squat", equipment="barbell", primary=None, secondary=None, unilateral=False) -> Exercise:
    row = Exercise(
        name=name,
        default_equipment_type=equipment,
        movement_pattern="squat",
        unilateral=unilateral,
        primary_muscles_json=json.dumps(primary or ["quadriceps"]),
        secondary_muscles_json=json.dumps(secondary or ["glutes"]),
        custom=True,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _uuid() -> str:
    return str(uuid.uuid4())


# -- exercise library -------------------------------------------------------------------------


def test_create_and_update_custom_exercise(session):
    created = gym.create_custom_exercise(
        session,
        name="Reverse Nordic",
        default_equipment_type="bodyweight",
        movement_pattern="other",
        primary_muscles=["quadriceps"],
    )
    assert created["custom"] is True
    assert created["primary_muscles"] == ["quadriceps"]

    updated = gym.update_exercise(session, created["id"], {"name": "Reverse Nordic Curl", "unilateral": True})
    assert updated["name"] == "Reverse Nordic Curl"
    assert updated["unilateral"] is True


def test_list_exercises_filters_by_query(session):
    _exercise(session, name="Barbell Bench Press")
    _exercise(session, name="Dumbbell Row")
    results = gym.list_exercises(session, query="bench")
    assert len(results) == 1
    assert results[0]["name"] == "Barbell Bench Press"


# -- gyms / stations ----------------------------------------------------------------------


def test_gym_and_station_round_trip(session):
    g = gym.create_gym(session, "Uni Gym")
    station = gym.upsert_station(
        session, gym_id=g.id, name="Cable 2", equipment_type="cable", config={"dual_stack": True, "pulley_multiplier": 0.5}
    )
    assert station["equipment_type"] == "cable"
    assert station["config"]["pulley_multiplier"] == 0.5

    listed = gym.list_stations(session, g.id)
    assert len(listed) == 1
    assert listed[0]["name"] == "Cable 2"


# -- effective load dispatch (through compute_effective_load, not equipment.py directly) ----


def test_effective_load_barbell(session):
    effective, estimated, note, bw = gym.compute_effective_load(
        session,
        equipment_type="barbell",
        load_kg=60.0,
        bar_weight_kg=20.0,
        pulley_multiplier=None,
        added_weight_kg=None,
        assistance_kg=None,
        bilateral=True,
        band_tag=None,
        station_config=None,
        at=T0,
    )
    assert effective == 80.0
    assert not estimated


def test_effective_load_smith_uses_station_bar_weight(session):
    effective, estimated, note, bw = gym.compute_effective_load(
        session,
        equipment_type="smith",
        load_kg=40.0,
        bar_weight_kg=10.0,
        pulley_multiplier=None,
        added_weight_kg=None,
        assistance_kg=None,
        bilateral=True,
        band_tag=None,
        station_config=None,
        at=T0,
    )
    assert effective == 50.0
    assert not estimated


def test_effective_load_bodyweight_uses_nearest_withings_weight(session):
    session.add(BodyComp(source="withings", external_id="w1", ts=T0 - timedelta(hours=1), weight_kg=82.0))
    session.commit()
    effective, estimated, note, bw = gym.compute_effective_load(
        session,
        equipment_type="bodyweight",
        load_kg=None,
        bar_weight_kg=None,
        pulley_multiplier=None,
        added_weight_kg=None,
        assistance_kg=None,
        bilateral=True,
        band_tag=None,
        station_config=None,
        at=T0,
    )
    assert effective == 82.0
    assert bw == 82.0
    assert not estimated


def test_effective_load_bodyweight_with_no_weight_on_file_is_estimated(session):
    effective, estimated, note, bw = gym.compute_effective_load(
        session,
        equipment_type="bodyweight",
        load_kg=None,
        bar_weight_kg=None,
        pulley_multiplier=None,
        added_weight_kg=None,
        assistance_kg=None,
        bilateral=True,
        band_tag=None,
        station_config=None,
        at=T0,
    )
    assert effective is None
    assert estimated


# -- logging sets, idempotency, PRs, session window ---------------------------------------


def test_upsert_set_is_idempotent_on_client_id(session):
    exercise = _exercise(session)
    session_id = _uuid()
    set_id = _uuid()

    first = gym.upsert_set(
        session,
        session_id,
        {
            "client_id": set_id,
            "exercise_id": exercise.id,
            "equipment_type": "barbell",
            "load_kg": 60.0,
            "bar_weight_kg": 20.0,
            "reps": 5,
            "rir": 2,
            "created_at": T0.isoformat(),
        },
    )
    assert first["effective_load_kg"] == 80.0

    # Retried after a dropped response, same client_id, slightly different payload — must
    # update in place, never create a second row.
    second = gym.upsert_set(
        session,
        session_id,
        {
            "client_id": set_id,
            "exercise_id": exercise.id,
            "equipment_type": "barbell",
            "load_kg": 65.0,
            "bar_weight_kg": 20.0,
            "reps": 5,
            "rir": 1,
            "created_at": T0.isoformat(),
        },
    )
    assert second["effective_load_kg"] == 85.0

    activity = session.exec(
        select(Activity).where(Activity.source == "catch_strength", Activity.external_id == session_id)
    ).first()
    all_sets = session.exec(
        select(StrengthSet).where(StrengthSet.activity_id == activity.id)
    ).all()
    assert len(all_sets) == 1


def test_session_window_recomputed_from_first_minus_10_last_plus_5(session):
    exercise = _exercise(session)
    session_id = _uuid()

    gym.upsert_set(
        session,
        session_id,
        {
            "client_id": _uuid(),
            "exercise_id": exercise.id,
            "equipment_type": "barbell",
            "load_kg": 60.0,
            "bar_weight_kg": 20.0,
            "reps": 5,
            "created_at": T0.isoformat(),
        },
    )
    last_set_time = T0 + timedelta(minutes=35)
    gym.upsert_set(
        session,
        session_id,
        {
            "client_id": _uuid(),
            "exercise_id": exercise.id,
            "equipment_type": "barbell",
            "load_kg": 100.0,
            "bar_weight_kg": 20.0,
            "reps": 3,
            "created_at": last_set_time.isoformat(),
        },
    )
    activity = session.exec(
        select(Activity).where(Activity.source == "catch_strength", Activity.external_id == session_id)
    ).first()
    session.refresh(activity)
    assert activity.start == T0 - timedelta(minutes=10)
    assert activity.duration == (last_set_time - (T0 - timedelta(minutes=10))).total_seconds() + 300


def test_rep_pr_and_e1rm_pr_detection_across_sets(session):
    exercise = _exercise(session)
    session_id = _uuid()

    s1 = gym.upsert_set(
        session,
        session_id,
        {"client_id": _uuid(), "exercise_id": exercise.id, "equipment_type": "barbell", "load_kg": 60.0, "bar_weight_kg": 20.0, "reps": 5, "created_at": T0.isoformat()},
    )
    assert s1["is_rep_pr"] and s1["is_e1rm_pr"]  # first ever set at this exercise.

    s2 = gym.upsert_set(
        session,
        session_id,
        {"client_id": _uuid(), "exercise_id": exercise.id, "equipment_type": "barbell", "load_kg": 40.0, "bar_weight_kg": 20.0, "reps": 5, "created_at": (T0 + timedelta(minutes=5)).isoformat()},
    )
    assert not s2["is_rep_pr"]  # lighter than the prior 5-rep set.

    s3 = gym.upsert_set(
        session,
        session_id,
        {"client_id": _uuid(), "exercise_id": exercise.id, "equipment_type": "barbell", "load_kg": 80.0, "bar_weight_kg": 20.0, "reps": 5, "created_at": (T0 + timedelta(minutes=10)).isoformat()},
    )
    assert s3["is_rep_pr"] and s3["is_e1rm_pr"]


def test_warmup_set_never_a_pr_and_contributes_no_muscular_au(session):
    exercise = _exercise(session)
    session_id = _uuid()
    s = gym.upsert_set(
        session,
        session_id,
        {"client_id": _uuid(), "exercise_id": exercise.id, "equipment_type": "barbell", "load_kg": 100.0, "bar_weight_kg": 20.0, "reps": 5, "set_type": "warmup", "created_at": T0.isoformat()},
    )
    assert not s["is_rep_pr"]
    assert s["muscular_au"] == 0.0


def test_delete_set_is_a_tombstone_excluded_from_session_sets(session):
    exercise = _exercise(session)
    session_id = _uuid()
    set_id = _uuid()
    gym.upsert_set(
        session,
        session_id,
        {"client_id": set_id, "exercise_id": exercise.id, "equipment_type": "barbell", "load_kg": 60.0, "bar_weight_kg": 20.0, "reps": 5, "created_at": T0.isoformat()},
    )
    assert len(gym.list_session_sets(session, session_id)) == 1
    gym.delete_set(session, set_id)
    assert gym.list_session_sets(session, session_id) == []


# -- last session / repeat workout / templates --------------------------------------------


def test_last_session_sets_for_exercise(session):
    exercise = _exercise(session)
    old_session, new_session = _uuid(), _uuid()
    gym.upsert_set(session, old_session, {"client_id": _uuid(), "exercise_id": exercise.id, "equipment_type": "barbell", "load_kg": 40.0, "bar_weight_kg": 20.0, "reps": 8, "created_at": (T0 - timedelta(days=3)).isoformat()})
    gym.upsert_set(session, new_session, {"client_id": _uuid(), "exercise_id": exercise.id, "equipment_type": "barbell", "load_kg": 60.0, "bar_weight_kg": 20.0, "reps": 5, "created_at": T0.isoformat()})

    last = gym.last_session_sets_for_exercise(session, exercise.id)
    assert len(last) == 1
    assert last[0]["load_kg"] == 60.0


def test_repeat_last_workout_returns_planned_sets_without_reps_or_load(session):
    squat = _exercise(session, name="Squat")
    bench = _exercise(session, name="Bench", equipment="barbell")
    session_id = _uuid()
    gym.upsert_set(session, session_id, {"client_id": _uuid(), "exercise_id": squat.id, "equipment_type": "barbell", "load_kg": 60.0, "bar_weight_kg": 20.0, "reps": 5, "seq": 0, "created_at": T0.isoformat()})
    gym.upsert_set(session, session_id, {"client_id": _uuid(), "exercise_id": bench.id, "equipment_type": "barbell", "load_kg": 40.0, "bar_weight_kg": 20.0, "reps": 8, "seq": 1, "created_at": (T0 + timedelta(minutes=10)).isoformat()})

    plan = gym.repeat_last_workout(session)
    assert [p["exercise_id"] for p in plan] == [squat.id, bench.id]
    assert all("load_kg" not in p for p in plan)


def test_template_save_list_delete(session):
    saved = gym.save_template(session, name="Push Day", items=[{"exercise_id": 1, "target_sets": 3, "target_reps": 8}])
    assert saved["name"] == "Push Day"
    assert len(gym.list_templates(session)) == 1
    gym.delete_template(session, saved["id"])
    assert gym.list_templates(session) == []


# -- muscular load caching + readiness -----------------------------------------------------


def test_muscular_load_cached_onto_canonical_by_muscle(session):
    squat = _exercise(session, name="Squat", primary=["quadriceps", "glutes"], secondary=["hamstrings"])
    session_id = _uuid()
    gym.upsert_set(
        session,
        session_id,
        {"client_id": _uuid(), "exercise_id": squat.id, "equipment_type": "barbell", "load_kg": 100.0, "bar_weight_kg": 20.0, "reps": 5, "rir": 1, "created_at": T0.isoformat()},
    )
    run_matching(session)
    activity = session.exec(
        select(Activity).where(Activity.source == "catch_strength", Activity.external_id == session_id)
    ).first()
    canonical = session.get(CanonicalActivity, activity.canonical_id)
    assert canonical.muscular_load_au and canonical.muscular_load_au > 0
    by_muscle = json.loads(canonical.muscular_by_muscle_json)
    assert by_muscle["quadriceps"] == by_muscle["glutes"]  # both primary, full credit each.
    assert by_muscle["hamstrings"] == by_muscle["quadriceps"] * 0.5  # secondary, half credit.


def test_muscle_readiness_window_excludes_old_sessions(session):
    squat = _exercise(session, name="Squat")
    old_session, recent_session = _uuid(), _uuid()
    gym.upsert_set(session, old_session, {"client_id": _uuid(), "exercise_id": squat.id, "equipment_type": "barbell", "load_kg": 100.0, "bar_weight_kg": 20.0, "reps": 5, "created_at": (T0 - timedelta(days=10)).isoformat()})
    gym.upsert_set(session, recent_session, {"client_id": _uuid(), "exercise_id": squat.id, "equipment_type": "barbell", "load_kg": 100.0, "bar_weight_kg": 20.0, "reps": 5, "created_at": T0.isoformat()})
    run_matching(session)

    readiness = gym.muscle_readiness(session, now=T0 + timedelta(hours=1))
    # Only the recent session's AU should count — the 10-day-old one is outside 72h.
    assert readiness["by_muscle"]["quadriceps"] > 0

    # A single session's own raw AU, fetched directly, is the upper bound a correct 72h
    # window must not exceed (it would if the old session leaked in too).
    recent_activity = session.exec(
        select(Activity).where(Activity.source == "catch_strength", Activity.external_id == recent_session)
    ).first()
    recent_canonical = session.get(CanonicalActivity, recent_activity.canonical_id)
    assert readiness["by_muscle"]["quadriceps"] == recent_canonical.muscular_load_au


# -- merging with a Garmin strength_training activity (task Part B.2) ----------------------


def test_catch_strength_merges_with_garmin_and_garmin_wins_duration_hr(session):
    squat = _exercise(session, name="Squat")
    session_id = _uuid()
    gym.upsert_set(session, session_id, {"client_id": _uuid(), "exercise_id": squat.id, "equipment_type": "barbell", "load_kg": 100.0, "bar_weight_kg": 20.0, "reps": 5, "created_at": T0.isoformat()})

    activity = session.exec(
        select(Activity).where(Activity.source == "catch_strength", Activity.external_id == session_id)
    ).first()
    session.refresh(activity)
    garmin_start = activity.start + timedelta(minutes=2)
    garmin = Activity(
        source="garmin",
        external_id="watch-strength-1",
        type="strength_training",
        start=garmin_start,
        duration=2000.0,
        avg_hr=120,
        calories=250,
    )
    session.add(garmin)
    session.commit()

    run_matching(session)
    session.refresh(activity)
    canonical = session.get(CanonicalActivity, activity.canonical_id)
    assert canonical.id == session.get(Activity, garmin.id).canonical_id  # merged into one canonical.
    assert canonical.avg_hr == 120  # Garmin wins HR.
    assert canonical.duration == 2000.0  # Garmin wins duration.
    assert canonical.calories == 250  # Garmin wins calories.

    # Sets stay Catch's, untouched by the merge.
    sets = gym.list_session_sets(session, session_id)
    assert len(sets) == 1
    assert sets[0]["effective_load_kg"] == 120.0


def test_catch_strength_alone_keeps_its_own_computed_window(session):
    """No Garmin counterpart — the canonical's start/duration must fall back to Catch's own
    padded window, not go missing (task Part B.3's "sessions logged with no watch still
    count")."""
    squat = _exercise(session, name="Squat")
    session_id = _uuid()
    gym.upsert_set(session, session_id, {"client_id": _uuid(), "exercise_id": squat.id, "equipment_type": "barbell", "load_kg": 100.0, "bar_weight_kg": 20.0, "reps": 5, "created_at": T0.isoformat()})
    run_matching(session)
    activity = session.exec(
        select(Activity).where(Activity.source == "catch_strength", Activity.external_id == session_id)
    ).first()
    canonical = session.get(CanonicalActivity, activity.canonical_id)
    assert canonical.start == T0 - timedelta(minutes=10)
    assert canonical.category == "strength"


# -- Garmin draft import (task Part B.2) ---------------------------------------------------


def _garmin_strength_activity(session, fit_path="data/fit/fake.fit") -> Activity:
    from catch.sync.matching import ensure_canonicals

    row = Activity(source="garmin", external_id="watch-strength-draft", type="strength_training", start=T0, duration=1800.0, fit_path=fit_path)
    session.add(row)
    session.commit()
    session.refresh(row)
    ensure_canonicals(session)  # real sync always gives a new Activity a canonical immediately.
    session.refresh(row)
    return row


def test_import_garmin_drafts_requires_a_fit_path(session):
    row = Activity(source="garmin", external_id="no-fit", type="strength_training", start=T0, duration=1800.0)
    session.add(row)
    session.commit()
    session.refresh(row)
    result = gym.import_garmin_draft_sets(session, row.id)
    assert result["imported"] == 0
    assert result["skipped_reason"]


def test_import_garmin_drafts_creates_unconfirmed_sets(session, monkeypatch):
    from catch.sync.fit_parse import FitDraftSet

    _exercise(session, name="Squat")
    activity = _garmin_strength_activity(session)
    monkeypatch.setattr(
        "catch.sync.gym.parse_fit_sets",
        lambda path: [
            FitDraftSet(offset_s=0.0, duration_s=30.0, reps=5, weight_kg=100.0, category="squat", set_type="active"),
            FitDraftSet(offset_s=120.0, duration_s=25.0, reps=8, weight_kg=None, category=None, set_type="active"),
        ],
    )
    result = gym.import_garmin_draft_sets(session, activity.id)
    assert result["imported"] == 2
    assert result["unmatched"] == 1  # the second draft had no category to match against.

    sets = session.exec(select(StrengthSet).where(StrengthSet.activity_id == activity.id)).all()
    assert len(sets) == 2
    assert all(s.source == "garmin_draft" and not s.is_confirmed for s in sets)


def test_import_garmin_drafts_is_a_noop_when_already_imported(session, monkeypatch):
    from catch.sync.fit_parse import FitDraftSet

    activity = _garmin_strength_activity(session)
    monkeypatch.setattr(
        "catch.sync.gym.parse_fit_sets",
        lambda path: [FitDraftSet(offset_s=0.0, duration_s=30.0, reps=5, weight_kg=100.0, category=None, set_type="active")],
    )
    gym.import_garmin_draft_sets(session, activity.id)
    second = gym.import_garmin_draft_sets(session, activity.id)
    assert second["imported"] == 0
    assert second["skipped_reason"] == "already imported"


def test_import_garmin_drafts_skipped_when_catch_already_logged_the_merged_session(session, monkeypatch):
    from catch.sync.fit_parse import FitDraftSet

    squat = _exercise(session)
    catch_session_id = _uuid()
    gym.upsert_set(session, catch_session_id, {"client_id": _uuid(), "exercise_id": squat.id, "equipment_type": "barbell", "load_kg": 100.0, "bar_weight_kg": 20.0, "reps": 5, "created_at": T0.isoformat()})
    run_matching(session)

    catch_activity = session.exec(select(Activity).where(Activity.source == "catch_strength", Activity.external_id == catch_session_id)).first()
    garmin = Activity(source="garmin", external_id="merged-watch", type="strength_training", start=T0, duration=1800.0, fit_path="x.fit", canonical_id=catch_activity.canonical_id)
    session.add(garmin)
    session.commit()

    monkeypatch.setattr(
        "catch.sync.gym.parse_fit_sets",
        lambda path: [FitDraftSet(offset_s=0.0, duration_s=30.0, reps=5, weight_kg=100.0, category=None, set_type="active")],
    )
    result = gym.import_garmin_draft_sets(session, garmin.id)
    assert result["imported"] == 0
    assert "already exists" in result["skipped_reason"]


def test_confirm_draft_set_assigns_exercise_and_recomputes_muscular_load(session, monkeypatch):
    from catch.sync.fit_parse import FitDraftSet

    squat = _exercise(session, primary=["quadriceps"], secondary=[])
    activity = _garmin_strength_activity(session)
    monkeypatch.setattr(
        "catch.sync.gym.parse_fit_sets",
        lambda path: [FitDraftSet(offset_s=0.0, duration_s=30.0, reps=5, weight_kg=100.0, category=None, set_type="active")],
    )
    gym.import_garmin_draft_sets(session, activity.id)
    draft = session.exec(select(StrengthSet).where(StrengthSet.activity_id == activity.id)).first()
    assert draft.exercise_id is None

    confirmed = gym.confirm_draft_set(session, draft.client_id, exercise_id=squat.id, equipment_type="barbell", bar_weight_kg=20.0)
    assert confirmed["source"] == "catch"
    assert confirmed["is_confirmed"] is True
    assert confirmed["effective_load_kg"] == 120.0  # 100kg entered + 20kg bar.

    run_matching(session)
    canonical = session.get(CanonicalActivity, session.get(Activity, activity.id).canonical_id)
    assert canonical.muscular_load_au and canonical.muscular_load_au > 0
