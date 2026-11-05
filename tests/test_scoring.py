from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlmodel import select

from catch.core.models import Activity, CanonicalActivity, DailyScore, DailyWellness, Note
from catch.core.settings_store import get_settings, update_settings
from catch.sync import scoring
from catch.sync.matching import ensure_canonicals, run_matching

START = date(2026, 10, 1)
HRV_VALUES = [50.0, 55.0, 52.0, 58.0, 54.0, 60.0, 53.0, 57.0, 56.0, 59.0]  # 10 days, varied


def _seed_wellness(session):
    for i, hrv in enumerate(HRV_VALUES):
        day = START + timedelta(days=i)
        session.add(DailyWellness(date=day, resting_hr=50, hrv_rmssd=hrv, sleep_seconds=8 * 3600))
    session.commit()


def _seed_linked_rowing_pair(session):
    """A Garmin watch + Concept2 PM5 recording of the same row — the matching engine
    (catch/sync/matching.py) should auto-merge them into one canonical on the next
    recompute, same as the old session-2 `linked_activity_id` mechanism this replaced."""
    day10 = START + timedelta(days=9)
    garmin = Activity(
        source="garmin",
        external_id="g1",
        type="indoor_rowing",
        start=datetime(day10.year, day10.month, day10.day, 7, 0, 0, tzinfo=timezone.utc),
        duration=1800.0,
        avg_hr=155,
    )
    session.add(garmin)
    session.commit()
    concept2 = Activity(
        source="concept2",
        external_id="c1",
        type="rower",
        start=datetime(day10.year, day10.month, day10.day, 7, 0, 30, tzinfo=timezone.utc),
        duration=1800.0,
        avg_hr=150,
    )
    session.add(concept2)
    session.commit()
    return garmin, concept2


def test_day_activities_counts_a_linked_pair_once(session):
    _seed_wellness(session)
    garmin, concept2 = _seed_linked_rowing_pair(session)
    run_matching(session)
    session.refresh(garmin)
    session.refresh(concept2)
    assert garmin.canonical_id == concept2.canonical_id

    rows = scoring._day_activities(session, START + timedelta(days=9))
    assert [r.id for r in rows] == [garmin.canonical_id]


def test_recompute_scores_writes_a_row_per_day_and_calibrates_early(session):
    _seed_wellness(session)
    update_settings(session, {"max_hr": 190})
    _seed_linked_rowing_pair(session)

    count = scoring.recompute_scores(session)
    expected_days = (date.today() - START).days + 1
    assert count == expected_days

    day1_score = session.get(DailyScore, START)
    recovery_day1 = json.loads(day1_score.recovery_json)
    assert recovery_day1["band"] == "calibrating"

    day10 = START + timedelta(days=9)
    day10_score = session.get(DailyScore, day10)
    strain_day10 = json.loads(day10_score.strain_json)
    # Only the concept2 side of the linked pair should have been scored.
    assert len(strain_day10["components"]) == 1
    assert strain_day10["value"] is not None

    load_day10 = json.loads(day10_score.load_json)
    assert load_day10["components"][0]["acute_7d"] >= 0


def test_recompute_scores_is_idempotent(session):
    _seed_wellness(session)
    update_settings(session, {"max_hr": 190})
    _seed_linked_rowing_pair(session)

    scoring.recompute_scores(session)
    first_count = len(session.exec(select(DailyScore)).all())
    scoring.recompute_scores(session)
    second_count = len(session.exec(select(DailyScore)).all())
    assert first_count == second_count


def test_recompute_relinks_when_concept2_synced_before_garmin(session):
    _seed_wellness(session)
    update_settings(session, {"max_hr": 190})
    day10 = START + timedelta(days=9)

    # Concept2 arrives first (e.g. scheduler ran it before Garmin that cycle) and has no HR
    # of its own — linking must still succeed on a *later* recompute, once Garmin shows up.
    concept2 = Activity(
        source="concept2",
        external_id="c1",
        type="rower",
        start=datetime(day10.year, day10.month, day10.day, 7, 0, 30, tzinfo=timezone.utc),
        duration=1800.0,
    )
    session.add(concept2)
    session.commit()

    garmin = Activity(
        source="garmin",
        external_id="g1",
        type="indoor_rowing",
        start=datetime(day10.year, day10.month, day10.day, 7, 0, 0, tzinfo=timezone.utc),
        duration=1800.0,
        avg_hr=158,
        max_hr=172,
    )
    session.add(garmin)
    session.commit()

    scoring.recompute_scores(session)

    session.refresh(concept2)
    session.refresh(garmin)
    assert concept2.canonical_id == garmin.canonical_id
    canonical = session.get(CanonicalActivity, garmin.canonical_id)
    # Concept2 has no HR of its own here; the canonical's resolved avg_hr falls back to the
    # Garmin watch (task Part A.3's HR priority), without mutating either source row.
    assert canonical.avg_hr == 158

    day10_score = session.get(DailyScore, day10)
    strain_day10 = json.loads(day10_score.strain_json)
    assert len(strain_day10["components"]) == 1  # not double-counted


def test_session_rpe_fallback_is_attached_by_calendar_date(session):
    _seed_wellness(session)
    update_settings(session, {"max_hr": None})  # force the HR path to fail -> RPE fallback
    day10 = START + timedelta(days=9)
    session.add(
        Activity(
            source="garmin",
            external_id="strength1",
            type="strength_training",
            start=datetime(day10.year, day10.month, day10.day, 18, 0, 0, tzinfo=timezone.utc),
            duration=3600.0,
        )
    )
    session.add(Note(date=day10, text="heavy session", rpe=7))
    session.commit()
    ensure_canonicals(session)

    settings = get_settings(session)
    strain = scoring.day_strain(session, day10, settings)
    assert strain["components"][0]["components"][0]["method"] == "srpe"
    assert strain["value"] is not None


def test_rest_day_with_15k_steps_stays_low(session):
    """Task Part A.3's explicit example: a rest day (no activities logged) with 15k steps
    must not look like a training session — the daily-activity component alone is capped at
    `daily_activity_strain_cap` (default 1.5 of the 0-21 scale)."""
    day = START
    session.add(DailyWellness(date=day, resting_hr=50, steps=15000, active_kcal=550))
    session.commit()

    settings = get_settings(session)
    strain = scoring.day_strain(session, day, settings)
    assert strain["value"] is not None
    assert strain["value"] <= settings["daily_activity_strain_cap"]
    assert strain["value"] < 10  # well within the "light" band
    assert strain["band"] == "light"
    assert strain["trimp_like"] == 0.0  # never leaks into load/acute:chronic
    assert strain["daily_activity"]["steps"] == 15000


def test_daily_activity_excludes_a_logged_garmin_workouts_own_steps(session):
    """A Garmin activity's own steps/calories are already inside the day's wellness totals —
    subtracting them out is what keeps a workout from being counted twice (task Part A.2)."""
    day = START
    session.add(DailyWellness(date=day, resting_hr=50, steps=12000, active_kcal=500))
    session.add(
        Activity(
            source="garmin",
            external_id="run1",
            type="running",
            start=datetime(day.year, day.month, day.day, 7, 0, 0, tzinfo=timezone.utc),
            duration=1800.0,
            avg_hr=150,
            max_hr=180,
            calories=300.0,
            bmr_kcal=50.0,
            steps=5000,
        )
    )
    session.commit()
    ensure_canonicals(session)

    settings = get_settings(session)
    settings = {**settings, "max_hr": 180}
    strain = scoring.day_strain(session, day, settings)
    daily_activity = strain["daily_activity"]
    # non-exercise steps = 12000 - 5000 = 7000; non-exercise active kcal = 500 - (300-50) = 250.
    assert daily_activity["steps"] == 7000
    assert daily_activity["active_kcal"] == pytest.approx(250.0)


# -- session 14 (see PLAN.md Part C): cardio/muscular strain split -------------------------


def _squat_exercise(session):
    from catch.core.models import Exercise

    row = Exercise(
        name="Barbell Squat",
        default_equipment_type="barbell",
        movement_pattern="squat",
        primary_muscles_json=json.dumps(["quadriceps", "glutes"]),
        secondary_muscles_json=json.dumps(["hamstrings"]),
        custom=True,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _log_working_sets(session, day, exercise_id, *, n_sets, reps, load_kg, rir):
    from catch.sync import gym

    import uuid as _uuid

    day_dt = datetime(day.year, day.month, day.day, 17, 0, 0, tzinfo=timezone.utc)
    session_id = str(_uuid.uuid4())
    for i in range(n_sets):
        gym.upsert_set(
            session,
            session_id,
            {
                "client_id": str(_uuid.uuid4()),
                "exercise_id": exercise_id,
                "equipment_type": "barbell",
                "load_kg": load_kg,
                "bar_weight_kg": 20.0,
                "reps": reps,
                "rir": rir,
                "created_at": (day_dt + timedelta(minutes=5 * i)).isoformat(),
            },
        )
    return session_id


def test_heavy_squat_day_registers_meaningful_strain_at_zero_hr(session):
    """Task Part C.2's explicit example: a heavy lifting day with no HR data must still show
    real strain, not fall into "insufficient data" just because trimp_like is 0."""
    squat = _squat_exercise(session)
    day = START
    _log_working_sets(session, day, squat.id, n_sets=5, reps=5, load_kg=130.0, rir=1)
    run_matching(session)

    settings = get_settings(session)
    strain = scoring.day_strain(session, day, settings)
    assert strain["trimp_like"] == 0.0  # no HR at all.
    assert strain["value"] is not None
    assert strain["value"] >= 6.0  # a real, meaningful number — not "insufficient data".
    assert strain["muscular"]["value"] > 0


def test_heavy_squat_day_beats_a_light_pump_day_beats_a_long_easy_erg(session):
    from catch.sync import gym

    heavy_day = START
    light_day = START + timedelta(days=1)
    erg_day = START + timedelta(days=2)

    # Persisted (not just passed locally to day_strain below) since resolve_canonical — run as
    # part of run_matching, below — reads max_hr itself via get_settings for the erg piece's
    # own HR-trimp-based muscular share (session 15).
    update_settings(session, {"max_hr": 180})

    squat = _squat_exercise(session)
    _log_working_sets(session, heavy_day, squat.id, n_sets=5, reps=5, load_kg=130.0, rir=1)
    _log_working_sets(session, light_day, squat.id, n_sets=3, reps=12, load_kg=40.0, rir=6)

    # A long UT2 erg piece — all HR, no power above threshold, no lifting at all that day.
    session.add(DailyWellness(date=erg_day, resting_hr=50))
    erg_start = datetime(erg_day.year, erg_day.month, erg_day.day, 7, 0, 0, tzinfo=timezone.utc)
    session.add(
        Activity(source="garmin", external_id="erg-ut2", type="indoor_rowing", start=erg_start, duration=3600.0, avg_hr=130)
    )
    session.commit()
    run_matching(session)

    settings = get_settings(session)
    settings = {**settings, "max_hr": 180}
    heavy = scoring.day_strain(session, heavy_day, settings)
    light = scoring.day_strain(session, light_day, settings)
    erg = scoring.day_strain(session, erg_day, settings)

    assert heavy["muscular"]["value"] > light["muscular"]["value"]
    assert light["muscular"]["value"] > erg["muscular"]["value"]
    # Session 15: an HR-only erg (no power at all) now gets a small HR-trimp-derived muscular
    # share instead of a hard 0 — see cardio_muscular_au_from_hr_trimp's docstring for why a
    # power-only share left most real rowing/cycling sessions undersold.
    assert erg["muscular"]["value"] > 0.0
    assert erg["cardio"]["value"] > 0  # the erg piece still registers plenty of cardio strain.


def test_muscular_strain_normalizes_against_28_day_baseline(session):
    """A lifter who trains the same muscle heavy every week shouldn't see every single
    session read as a baseline-busting spike — catch/analytics/strength.py's
    normalize_muscle_au clamps a day at/near its own established baseline."""
    squat = _squat_exercise(session)
    base_day = START
    for i in range(4):  # 4 weekly heavy squat days establish a real baseline.
        _log_working_sets(session, base_day + timedelta(days=7 * i), squat.id, n_sets=5, reps=5, load_kg=130.0, rir=1)
    run_matching(session)
    settings = get_settings(session)

    today = base_day + timedelta(days=28)
    strain_at_baseline = scoring.day_strain(session, base_day + timedelta(days=21), settings)
    # One more identical session, same load/volume as every prior week.
    _log_working_sets(session, today, squat.id, n_sets=5, reps=5, load_kg=130.0, rir=1)
    run_matching(session)
    strain_today = scoring.day_strain(session, today, settings)

    # A repeat of the lifter's own normal week should land close to prior weeks, not spike.
    assert strain_today["muscular"]["value"] == pytest.approx(strain_at_baseline["muscular"]["value"], rel=0.15)
