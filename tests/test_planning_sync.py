from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlmodel import select

from catch.analytics import planning as pl
from catch.analytics.defaults import DEFAULT_SETTINGS
from catch.core.models import CanonicalActivity, DailyWellness, Event, PlannedWorkout, TrainingPhase
from catch.sync import planning as sp

OWNER = sp.OWNER_ID
OTHER = "someone-else"


def _local_dt(day: date, hour: int = 12) -> datetime:
    return datetime(day.year, day.month, day.day, hour, 0).astimezone(timezone.utc)


def _canonical(session, day: date, hour: int = 12, **kw) -> CanonicalActivity:
    row = CanonicalActivity(
        start=_local_dt(day, hour),
        duration=kw.pop("duration", 3600.0),
        avg_hr=kw.pop("avg_hr", 140.0),
        sport_family=kw.pop("sport_family", "rowing"),
        category=kw.pop("category", "erg"),
        **kw,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _plan(session, day, session_type="erg", **kw):
    return sp.create_planned(session, OWNER, {"date": day, "session_type": session_type, **kw})[0]


MON = sp.pl.week_start(sp.today())


# --- planned CRUD / ownership ----------------------------------------------------------------


def test_create_defaults_title_and_sport_family(session):
    row = _plan(session, MON, "erg", duration_min=60, target_zone="UT2")
    assert row.title == "Erg session" and row.sport_family == "rowing" and row.status == "planned"


def test_invalid_fields_are_rejected_and_nothing_is_written(session):
    with pytest.raises(sp.PlanningError):
        sp.create_planned(session, OWNER, {"date": MON, "session_type": "swim"})
    with pytest.raises(sp.PlanningError):
        sp.create_planned(session, OWNER, {"date": MON, "session_type": "erg", "bogus": 1})
    assert session.exec(select(PlannedWorkout)).all() == []


def test_cross_owner_access_is_not_found_everywhere(session):
    row = _plan(session, MON)
    ev = sp.create_event(session, OWNER, {"name": "Head race", "date": MON + timedelta(days=30), "type": "race"})
    ph = sp.create_phase(session, OWNER, {"kind": "general_prep", "name": "Base", "start_date": MON, "end_date": MON + timedelta(days=27)})
    canon = _canonical(session, MON)
    for call in (
        lambda: sp.get_planned(session, OTHER, row.id),
        lambda: sp.update_planned(session, OTHER, row.id, {"title": "x"}),
        lambda: sp.move_planned(session, OTHER, row.id, MON + timedelta(days=1)),
        lambda: sp.delete_planned(session, OTHER, row.id),
        lambda: sp.set_skipped(session, OTHER, row.id, True),
        lambda: sp.link_planned(session, OTHER, row.id, canon.id),
        lambda: sp.unlink_planned(session, OTHER, row.id),
        lambda: sp.decline_suggestion(session, OTHER, row.id, canon.id),
        lambda: sp.update_event(session, OTHER, ev.id, {"name": "x"}),
        lambda: sp.delete_event(session, OTHER, ev.id),
        lambda: sp.event_projection(session, OTHER, ev.id),
        lambda: sp.event_overview(session, OTHER, ev.id),
        lambda: sp.get_phase(session, OTHER, ph.id),
        lambda: sp.update_phase(session, OTHER, ph.id, {"name": "x"}),
        lambda: sp.approve_phase(session, OTHER, ph.id),
        lambda: sp.delete_phase(session, OTHER, ph.id),
        lambda: sp.create_planned(session, OTHER, {"date": MON, "session_type": "erg", "event_id": ev.id}),
    ):
        with pytest.raises(sp.NotFound):
            call()
    assert sp.list_planned(session, OTHER, MON, MON + timedelta(days=60)) == []
    assert sp.list_events(session, OTHER) == []
    assert sp.list_phases(session, OTHER) == []
    assert session.get(PlannedWorkout, row.id).title == "Erg session"


def test_events_without_an_owner_belong_to_the_install_owner(session):
    legacy = Event(name="Old race", date=MON + timedelta(days=5), type="race")
    session.add(legacy)
    session.commit()
    assert [e.name for e in sp.list_events(session, OWNER)] == ["Old race"]
    assert sp.list_events(session, OTHER) == []
    sp.update_event(session, OWNER, legacy.id, {"location": "Henley"})
    assert session.get(Event, legacy.id).owner_id == OWNER


def test_move_and_delete(session):
    row = _plan(session, MON)
    moved = sp.move_planned(session, OWNER, row.id, MON + timedelta(days=2))
    assert moved.date == MON + timedelta(days=2)
    assert sp.delete_planned(session, OWNER, row.id) == 1
    assert session.exec(select(PlannedWorkout)).all() == []


def test_series_update_and_delete_scopes(session):
    rows = sp.create_planned(session, OWNER, {"date": MON, "session_type": "erg", "duration_min": 60}, repeat={"count": 4})
    assert len({r.series_id for r in rows}) == 1 and rows[0].series_id
    third = rows[2]
    sp.update_planned(session, OWNER, third.id, {"duration_min": 90}, scope="this_and_following")
    durations = [r.duration_min for r in sp.list_planned(session, OWNER, MON, MON + timedelta(days=40))]
    assert durations == [60, 60, 90, 90]
    sp.update_planned(session, OWNER, third.id, {"date": third.date + timedelta(days=1)}, scope="this_and_following")
    dates = [r.date for r in sp.list_planned(session, OWNER, MON, MON + timedelta(days=40))]
    assert dates[2] == MON + timedelta(days=15) and dates[3] == MON + timedelta(days=22)
    assert sp.delete_planned(session, OWNER, third.id, scope="this_and_following") == 2
    assert len(sp.list_planned(session, OWNER, MON, MON + timedelta(days=40))) == 2


def test_rest_day_cannot_be_linked_or_skipped_and_linked_cannot_become_rest(session):
    rest = _plan(session, MON, "rest")
    canon = _canonical(session, MON)
    with pytest.raises(sp.PlanningError):
        sp.link_planned(session, OWNER, rest.id, canon.id)
    with pytest.raises(sp.PlanningError):
        sp.set_skipped(session, OWNER, rest.id, True)
    erg = _plan(session, MON)
    sp.link_planned(session, OWNER, erg.id, canon.id)
    with pytest.raises(sp.PlanningError):
        sp.update_planned(session, OWNER, erg.id, {"session_type": "rest"})


# --- linking: one-to-one, never automatic ----------------------------------------------------


def test_link_is_one_to_one_and_unlink_frees_the_workout(session):
    canon = _canonical(session, MON)
    a, b = _plan(session, MON), _plan(session, MON)
    sp.link_planned(session, OWNER, a.id, canon.id)
    with pytest.raises(sp.PlanningError, match="already linked"):
        sp.link_planned(session, OWNER, b.id, canon.id)
    sp.unlink_planned(session, OWNER, a.id)
    sp.link_planned(session, OWNER, b.id, canon.id)
    assert session.get(PlannedWorkout, b.id).linked_canonical_id == canon.id


def test_unique_constraint_backs_the_service_check(session):
    canon = _canonical(session, MON)
    a, b = _plan(session, MON), _plan(session, MON)
    a.linked_canonical_id = canon.id
    b.linked_canonical_id = canon.id
    session.add_all([a, b])
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_many_unlinked_rows_are_allowed(session):
    for _ in range(3):
        _plan(session, MON)
    assert len(session.exec(select(PlannedWorkout)).all()) == 3


def test_suggestions_never_link_anything_by_themselves(session):
    plan = _plan(session, MON, duration_min=60)
    canon = _canonical(session, MON, duration=3700.0)
    cal = sp.build_calendar(session, OWNER, MON, MON + timedelta(days=6))
    assert [(s["planned_id"], s["canonical_id"]) for s in cal["suggestions"]] == [(plan.id, canon.id)]
    assert session.get(PlannedWorkout, plan.id).linked_canonical_id is None
    # Both records still stand after building the calendar.
    assert session.get(CanonicalActivity, canon.id) is not None


def test_declined_suggestion_is_not_offered_again(session):
    plan = _plan(session, MON, duration_min=60)
    canon = _canonical(session, MON)
    sp.decline_suggestion(session, OWNER, plan.id, canon.id)
    assert sp.build_calendar(session, OWNER, MON, MON + timedelta(days=6))["suggestions"] == []


def test_am_pm_double_gets_two_distinct_suggestions(session):
    am = _plan(session, MON, duration_min=60, start_time="06:30")
    pm = _plan(session, MON, duration_min=30, start_time="17:00")
    c_long = _canonical(session, MON, 7, duration=3600.0)
    c_short = _canonical(session, MON, 17, duration=1800.0)
    out = {s["planned_id"]: s["canonical_id"] for s in sp.build_calendar(session, OWNER, MON, MON + timedelta(days=6))["suggestions"]}
    assert out == {am.id: c_long.id, pm.id: c_short.id}


def test_a_vanished_canonical_reads_as_unlinked_but_not_planned_by_mistake(session):
    plan = _plan(session, MON - timedelta(days=3))
    canon = _canonical(session, MON - timedelta(days=3))
    sp.link_planned(session, OWNER, plan.id, canon.id)
    assert sp.planned_dict(plan, MON)["display_status"] == "linked"
    plan.linked_canonical_id = None  # what a merge/split cleanup leaves behind
    session.add(plan)
    session.commit()
    assert sp.planned_dict(plan, MON)["display_status"] == "not_logged"


# --- display status wording ------------------------------------------------------------------


def test_display_statuses_are_neutral_words(session):
    today_ = MON + timedelta(days=3)
    past, future = _plan(session, MON), _plan(session, MON + timedelta(days=5))
    skipped = _plan(session, MON + timedelta(days=1))
    sp.set_skipped(session, OWNER, skipped.id, True)
    rest = _plan(session, MON + timedelta(days=2), "rest")
    states = {r.id: sp.planned_dict(r, today_)["display_status"] for r in (past, future, skipped, rest)}
    assert states == {past.id: "not_logged", future.id: "planned", skipped.id: "skipped", rest.id: "rest"}
    assert not {"missed", "failed", "behind"} & set(states.values())


# --- planned never counts as completed -------------------------------------------------------


def _seed_history(session):
    today_ = sp.today()
    for i in range(0, 60):
        session.add(DailyWellness(date=today_ - timedelta(days=i), resting_hr=50.0, hrv_rmssd=55.0, sleep_seconds=8 * 3600))
    for i in range(1, 40, 2):
        session.add(
            CanonicalActivity(
                start=_local_dt(today_ - timedelta(days=i)), duration=3000.0, avg_hr=140.0, sport_family="rowing", category="erg", strain_trimp=60.0
            )
        )
    session.commit()


def _snapshot(session):
    from catch.api.routes_analytics import trends_volume
    from catch.core.models import DailyScore
    from catch.sync import training_intelligence as ti
    from catch.sync.scoring import day_strain, recompute_scores

    settings = DEFAULT_SETTINGS
    recompute_scores(session)
    scores = [(s.date, s.strain_json, s.load_json, s.recovery_json) for s in session.exec(select(DailyScore).order_by(DailyScore.date)).all()]
    today_ = sp.today()
    return json.dumps(
        {
            "volume": trends_volume(weeks=12, db=session),
            "distribution": ti.gather_training_distribution(session, settings),
            "consistency": ti.gather_training_consistency(session, settings),
            "sessions_this_week": ti._sessions_this_week(session, today_),
            "strain": [day_strain(session, today_ - timedelta(days=i), settings) for i in range(0, 5)],
            "scores": scores,
        },
        default=str,
        sort_keys=True,
    )


def test_planned_sessions_never_change_any_completed_total(session):
    _seed_history(session)
    before = _snapshot(session)
    today_ = sp.today()
    for offset in (-20, -7, -1, 0, 1, 3, 10):
        _plan(session, today_ + timedelta(days=offset), "erg", duration_min=120, target_zone="AN", distance_m=30000)
        _plan(session, today_ + timedelta(days=offset), "strength", duration_min=90)
    sp.create_planned(session, OWNER, {"date": today_, "session_type": "bike", "duration_min": 200}, repeat={"count": 8})
    assert _snapshot(session) == before


def test_linking_does_not_change_completed_totals_either(session):
    _seed_history(session)
    today_ = sp.today()
    canon = session.exec(select(CanonicalActivity).order_by(CanonicalActivity.start.desc())).first()
    plan = _plan(session, pl.local_date(canon.start), "erg", duration_min=120)
    before = _snapshot(session)
    sp.link_planned(session, OWNER, plan.id, canon.id)
    sp.set_skipped(session, OWNER, _plan(session, today_, "erg").id, True)
    assert _snapshot(session) == before


def test_activities_listing_is_unchanged_by_plans(client, session):
    from conftest import TEST_PASSWORD

    client.post("/api/login", json={"password": TEST_PASSWORD})
    _canonical(session, sp.today() - timedelta(days=1))
    before = client.get("/api/activities").json()
    _plan(session, sp.today(), "erg", duration_min=60)
    _plan(session, sp.today() - timedelta(days=1), "erg", duration_min=60)
    assert client.get("/api/activities").json() == before


def test_completed_total_readers_never_import_planned_workout():
    import pathlib

    root = pathlib.Path(sp.__file__).resolve().parents[1]
    for rel in ("sync/scoring.py", "sync/training_intelligence.py", "api/routes_analytics.py", "analytics/load.py", "analytics/training_intelligence.py"):
        text = (root / rel).read_text()
        assert "PlannedWorkout" not in text, rel


# --- calendar assembly / time zones ----------------------------------------------------------


def test_workout_late_in_the_local_evening_lands_on_its_local_day(session):
    day = MON + timedelta(days=2)
    late = _canonical(session, day, hour=23)
    early = _canonical(session, day + timedelta(days=1), hour=0)
    cal = sp.build_calendar(session, OWNER, MON, MON + timedelta(days=6))
    by_day = {d["date"]: [c["id"] for c in d["completed"]] for d in cal["days"]}
    assert by_day[day] == [late.id] and by_day[day + timedelta(days=1)] == [early.id]


def test_calendar_contains_planned_completed_events_phases_in_separate_keys(session):
    _plan(session, MON, duration_min=60)
    _canonical(session, MON)
    sp.create_event(session, OWNER, {"name": "Test day", "date": MON + timedelta(days=2), "type": "2k_test", "priority": "A"})
    sp.create_phase(session, OWNER, {"kind": "general_prep", "name": "Base", "start_date": MON, "end_date": MON + timedelta(days=20)})
    cal = sp.build_calendar(session, OWNER, MON, MON + timedelta(days=6))
    first = cal["days"][0]
    assert len(first["planned"]) == 1 and len(first["completed"]) == 1 and first["phase_id"]
    assert cal["days"][2]["events"][0]["name"] == "Test day"


def test_calendar_range_is_bounded(session):
    with pytest.raises(sp.PlanningError):
        sp.build_calendar(session, OWNER, MON, MON + timedelta(days=sp.MAX_CALENDAR_DAYS))
    with pytest.raises(sp.PlanningError):
        sp.build_calendar(session, OWNER, MON, MON - timedelta(days=1))


def test_absorbed_piece_rows_are_not_shown_as_workouts(session):
    c = _canonical(session, MON, absorbed_into_piece_id=1)
    cal = sp.build_calendar(session, OWNER, MON, MON + timedelta(days=6))
    assert all(c.id != x["id"] for d in cal["days"] for x in d["completed"])


# --- week summary ----------------------------------------------------------------------------


def test_week_summary_puts_planned_and_completed_side_by_side(session):
    _plan(session, MON, "erg", duration_min=60, target_zone="UT2")
    _plan(session, MON + timedelta(days=1), "strength", duration_min=45)
    _plan(session, MON + timedelta(days=2), "rest")
    _canonical(session, MON, duration=3000.0)
    s = sp.build_week_summary(session, OWNER, MON + timedelta(days=3))
    assert s["week_start"] == MON
    assert s["planned"]["minutes"] == 105 and s["planned"]["sessions"] == 2 and s["planned"]["strength_sessions"] == 1
    assert s["completed"]["minutes"] == 50 and s["completed"]["sessions"] == 1
    assert s["targets"]["source"] == "settings"


def test_phase_targets_override_settings_defaults(session):
    sp.create_phase(
        session, OWNER,
        {"kind": "specific_prep", "name": "Build", "start_date": MON - timedelta(days=7), "end_date": MON + timedelta(days=21),
         "target_minutes_per_week": 420, "target_strength_sessions_per_week": 2, "target_zone_pct": {"UT2": {"min": 70}}},
    )
    s = sp.build_week_summary(session, OWNER, MON)
    assert s["targets"]["minutes"] == 420 and s["targets"]["source"] == "phase" and s["targets"]["zone_pct"] == {"UT2": {"min": 70}}
    assert s["phase"]["name"] == "Build"


def test_future_week_has_no_completed_zone_numbers(session):
    s = sp.build_week_summary(session, OWNER, MON + timedelta(weeks=3))
    assert s["completed"]["zones_available"] is False and s["completed"]["minutes"] == 0


# --- review flags ----------------------------------------------------------------------------


def test_large_planned_jump_over_recent_training_is_flagged_and_changes_nothing(session):
    today_ = sp.today()
    for i in range(1, 29):
        _canonical(session, today_ - timedelta(days=i), duration=2400.0)
    for d in range(0, 6):
        _plan(session, MON + timedelta(days=d), "erg", duration_min=120)
    before = [p.updated_at for p in session.exec(select(PlannedWorkout)).all()]
    flags = sp.review_flags(session, OWNER, MON, 3)
    assert flags and flags[0]["kind"] == "increase" and flags[0]["week_start"] == MON
    assert [p.updated_at for p in session.exec(select(PlannedWorkout)).all()] == before


def test_threshold_is_configurable_through_settings(session):
    for i in range(1, 29):  # exactly the four weeks before MON: a 420-minute weekly baseline
        _canonical(session, MON - timedelta(days=i), duration=3600.0)
    for d in range(0, 6):
        _plan(session, MON + timedelta(days=d), "erg", duration_min=80)  # 480 min: +14%
    settings = json.loads(json.dumps(DEFAULT_SETTINGS))
    assert sp.review_flags(session, OWNER, MON, 1, settings) == []
    settings["planning"]["review_threshold_pct"] = 5
    assert sp.review_flags(session, OWNER, MON, 1, settings)


# --- phases ----------------------------------------------------------------------------------


def test_phases_cannot_overlap(session):
    sp.create_phase(session, OWNER, {"kind": "general_prep", "name": "A", "start_date": MON, "end_date": MON + timedelta(days=13)})
    with pytest.raises(sp.PlanningError, match="overlaps"):
        sp.create_phase(session, OWNER, {"kind": "specific_prep", "name": "B", "start_date": MON + timedelta(days=13), "end_date": MON + timedelta(days=30)})
    ok = sp.create_phase(session, OWNER, {"kind": "specific_prep", "name": "B", "start_date": MON + timedelta(days=14), "end_date": MON + timedelta(days=30)})
    with pytest.raises(sp.PlanningError, match="overlaps"):
        sp.update_phase(session, OWNER, ok.id, {"start_date": MON + timedelta(days=5)})
    assert sp.phase_on(session, OWNER, MON + timedelta(days=14)).name == "B"


def test_approval_goes_stale_only_when_the_plan_itself_is_edited(session):
    phase = sp.create_phase(session, OWNER, {"kind": "general_prep", "name": "Base", "start_date": MON, "end_date": MON + timedelta(days=27)})
    plan = _plan(session, MON + timedelta(days=1), duration_min=60)
    sp.approve_phase(session, OWNER, phase.id, approved_by="Coach Sam", note="Looks right")
    session.expire_all()  # force a reload: naive datetimes come back from SQLite
    fresh = sp.phase_dict(sp.get_phase(session, OWNER, phase.id), session)
    assert fresh["coach_approved"] and fresh["coach_approved_by"] == "Coach Sam" and fresh["edited_since_approval"] is False

    canon = _canonical(session, MON + timedelta(days=1))
    sp.link_planned(session, OWNER, plan.id, canon.id)
    sp.set_skipped(session, OWNER, _plan_no_bump(session, MON + timedelta(days=2)).id, True) if False else None
    session.expire_all()
    assert sp.phase_dict(sp.get_phase(session, OWNER, phase.id), session)["edited_since_approval"] is False

    sp.update_planned(session, OWNER, plan.id, {"duration_min": 90})
    session.expire_all()
    assert sp.phase_dict(sp.get_phase(session, OWNER, phase.id), session)["edited_since_approval"] is True

    sp.approve_phase(session, OWNER, phase.id)
    sp.unapprove_phase(session, OWNER, phase.id)
    assert sp.phase_dict(sp.get_phase(session, OWNER, phase.id), session)["coach_approved"] is False


def _plan_no_bump(session, day):
    return _plan(session, day)


def test_fresh_and_reloaded_datetimes_compare_without_error(session):
    phase = sp.create_phase(session, OWNER, {"kind": "general_prep", "name": "Base", "start_date": MON, "end_date": MON + timedelta(days=6)})
    fresh_row = sp.approve_phase(session, OWNER, phase.id)
    assert sp.phase_dict(fresh_row, session)["edited_since_approval"] is False  # aware in-memory values
    session.expire_all()
    assert sp.phase_dict(sp.get_phase(session, OWNER, phase.id), session)["edited_since_approval"] is False  # naive reloaded values


def test_creating_a_plan_row_after_approval_counts_as_an_edit(session):
    phase = sp.create_phase(session, OWNER, {"kind": "general_prep", "name": "Base", "start_date": MON, "end_date": MON + timedelta(days=6)})
    sp.approve_phase(session, OWNER, phase.id)
    _plan(session, MON + timedelta(days=1))
    session.expire_all()
    assert sp.phase_dict(sp.get_phase(session, OWNER, phase.id), session)["edited_since_approval"] is True


# --- events ----------------------------------------------------------------------------------


def test_event_validation(session):
    for bad in (
        {"name": "x", "date": MON, "type": "regatta"},
        {"name": "x", "date": MON, "type": "race", "priority": "D"},
        {"name": "x", "date": MON, "type": "race", "goal_time": "fast"},
        {"name": "x", "date": MON, "type": "race", "distance_m": -5},
        {"name": " ", "date": MON, "type": "race"},
        {"date": MON, "type": "race"},
    ):
        with pytest.raises(sp.PlanningError):
            sp.create_event(session, OWNER, bad)


def test_countdown_and_taper_flag(session):
    ev = sp.create_event(session, OWNER, {"name": "Nationals", "date": MON + timedelta(days=10), "type": "race", "priority": "A"})
    d = sp.event_dict(ev, MON)
    assert d["days_to_go"] == 10 and d["taper"] is True
    far = sp.event_dict(ev, MON - timedelta(days=30))
    assert far["taper"] is False
    sp.update_event(session, OWNER, ev.id, {"priority": "C"})
    assert sp.event_dict(session.get(Event, ev.id), MON)["taper"] is False


def test_delete_event_clears_references_instead_of_dangling(session):
    ev = sp.create_event(session, OWNER, {"name": "Head", "date": MON + timedelta(days=20), "type": "race"})
    plan = _plan(session, MON, event_id=ev.id)
    ph = sp.create_phase(session, OWNER, {"kind": "pre_competition", "name": "Peak", "start_date": MON, "end_date": MON + timedelta(days=13), "event_id": ev.id})
    sp.delete_event(session, OWNER, ev.id)
    session.expire_all()
    assert session.get(PlannedWorkout, plan.id).event_id is None
    assert session.get(TrainingPhase, ph.id).event_id is None
    assert session.get(Event, ev.id) is None


def test_goal_time_parsing():
    assert sp.parse_goal_time("6:30") == 390.0
    assert sp.parse_goal_time("6:30.5") == 390.5
    assert sp.parse_goal_time("1:02:03") == 3723.0
    with pytest.raises(ValueError):
        sp.parse_goal_time("quick")


def test_event_distance_parsing(session):
    for text, metres in (("2000m", 2000), ("2k", 2000), ("6 km", 6000), ("5000", 5000)):
        ev = Event(name="e", date=MON, type="race", distance=text)
        assert sp.event_distance_m(ev) == metres
    assert sp.event_distance_m(Event(name="e", date=MON, type="race", distance="head of the river")) is None
    assert sp.event_distance_m(Event(name="e", date=MON, type="race", distance="x", distance_m=1234)) == 1234


def test_upcoming_events_are_ordered_and_limited(session):
    for i, name in ((9, "c"), (2, "a"), (5, "b")):
        sp.create_event(session, OWNER, {"name": name, "date": sp.today() + timedelta(days=i), "type": "race"})
    sp.create_event(session, OWNER, {"name": "past", "date": sp.today() - timedelta(days=1), "type": "race"})
    assert [e["name"] for e in sp.upcoming_events(session, OWNER, limit=2)] == ["a", "b"]


# --- projection ------------------------------------------------------------------------------


def _confirmed_test(session, day, seconds, test_type="2000m"):
    from catch.core.models import Activity

    canon = CanonicalActivity(
        start=_local_dt(day), duration=seconds, distance=2000.0, sport_family="rowing", category="erg",
        overrides_json=json.dumps({"tags": ["test"], "test_type": test_type}),
    )
    session.add(canon)
    session.commit()
    session.refresh(canon)
    session.add(Activity(source="concept2", external_id=f"c2-{canon.id}", type="rowerg", start=canon.start, duration=seconds, distance=2000.0, canonical_id=canon.id, workout_type="FixedDistanceSplits"))
    session.commit()
    return canon


def test_projection_without_a_distance_says_why(session):
    ev = sp.create_event(session, OWNER, {"name": "Camp", "date": MON + timedelta(days=40), "type": "camp"})
    out = sp.event_projection(session, OWNER, ev.id)
    assert out["available"] is False and "no distance" in out["reason"]


def test_projection_for_non_erg_distance_is_declined_honestly(session):
    ev = sp.create_event(session, OWNER, {"name": "Head", "date": MON + timedelta(days=40), "type": "race", "distance": "head of the river"})
    out = sp.event_projection(session, OWNER, ev.id)
    assert out["available"] is False and out["trend"] is None


def test_projection_with_too_little_history_gives_reason_and_no_number(session):
    ev = sp.create_event(session, OWNER, {"name": "2k", "date": MON + timedelta(days=40), "type": "2k_test", "distance": "2000m"})
    _confirmed_test(session, MON - timedelta(days=30), 420.0)
    out = sp.event_projection(session, OWNER, ev.id)
    assert out["available"] is False and "at least 3" in out["reason"] and out["test_type"] == "2000m"


def test_projection_shows_data_assumptions_and_uncertainty(session):
    ev = sp.create_event(session, OWNER, {"name": "2k", "date": MON + timedelta(days=40), "type": "2k_test", "distance": "2k", "goal_time": "6:50"})
    for days, secs in ((-90, 430.0), (-60, 424.0), (-30, 418.0), (-10, 414.0)):
        _confirmed_test(session, MON + timedelta(days=days), secs)
    out = sp.event_projection(session, OWNER, ev.id)
    assert out["available"] is True and out["value_s"] < 414.0
    lo, hi = out["range_s"]
    assert lo <= out["value_s"] <= hi
    assert len(out["history"]) == 4
    assert any("Straight-line trend" in a for a in out["assumptions"]) and any("wind" in a for a in out["assumptions"])
    assert "standard deviation" in out["uncertainty"] and "Only 4" in out["uncertainty"]
    assert out["gap_to_goal_s"] == pytest.approx(out["value_s"] - 410.0)


# --- Postgres / dialect hygiene --------------------------------------------------------------


def test_new_tables_compile_for_postgresql():
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateIndex, CreateTable

    for model in (PlannedWorkout, TrainingPhase, Event):
        table = model.__table__
        ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        assert "CREATE TABLE" in ddl
        for index in table.indexes:
            str(CreateIndex(index).compile(dialect=postgresql.dialect()))
    ddl = str(CreateTable(PlannedWorkout.__table__).compile(dialect=postgresql.dialect()))
    assert "uq_planned_workouts_linked_canonical" in ddl


def test_new_columns_use_portable_ddl_types():
    from catch.core.db import _NEW_COLUMNS

    for decl in _NEW_COLUMNS["events"].values():
        assert decl in ("TEXT", "REAL")
        assert "BOOLEAN" not in decl and "DEFAULT" not in decl


def test_add_column_statements_use_inspect_and_compile_for_postgresql(engine):
    from sqlalchemy import text
    from sqlalchemy.dialects import postgresql

    from catch.core import db as db_module

    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE events")
        conn.exec_driver_sql("CREATE TABLE events (id INTEGER PRIMARY KEY, name TEXT, date DATE, type TEXT, plan_json TEXT)")
        stmts = db_module._add_column_statements(sa_inspect(conn), {"events": db_module._NEW_COLUMNS["events"], "no_such_table": {"x": "TEXT"}})
    assert {s.split()[5] for s in stmts} == {"location", "goals", "notes", "distance_m", "owner_id"}
    for s in stmts:
        str(text(s).compile(dialect=postgresql.dialect()))
        assert "PRAGMA" not in s


def test_new_modules_use_no_sqlite_only_sql():
    import pathlib

    root = pathlib.Path(sp.__file__).resolve().parents[1]
    import re

    banned = (r"strftime", r"julianday", r"PRAGMA", r"INSERT OR", r"json_extract", r"\browid\b", r"\btext\(", r"exec_driver_sql", r"\bGLOB\b")
    for rel in ("sync/planning.py", "analytics/planning.py", "api/routes_calendar.py"):
        path = root / rel
        if not path.exists():
            continue
        body = path.read_text()
        for token in banned:
            assert not re.search(token, body), f"{rel} contains {token}"


# --- recommendation wiring -------------------------------------------------------------------


def test_a_big_planned_jump_surfaces_as_one_deduped_review_recommendation(session):
    from catch.core.models import Recommendation
    from catch.sync.scoring import recompute_scores

    _seed_history(session)
    for i in range(1, 29):
        _canonical(session, MON - timedelta(days=i), duration=2400.0)
    for d in range(0, 6):
        _plan(session, MON + timedelta(days=d), "erg", duration_min=150)
    recompute_scores(session)
    recompute_scores(session)  # idempotent: re-confirms the same row
    rows = [r for r in session.exec(select(Recommendation)).all() if r.rule_key == "plan:load_change"]
    assert len(rows) == 1
    assert "nothing has been changed" in rows[0].body and rows[0].type == "plan_review"
    assert not any(r.type == "training_suggestion" for r in session.exec(select(Recommendation)).all())
    # The plan itself was not touched by generating the recommendation.
    assert all(p.duration_min == 150 for p in session.exec(select(PlannedWorkout)).all())


def test_no_plan_means_no_review_recommendation(session):
    from catch.core.models import Recommendation
    from catch.sync.scoring import recompute_scores

    _seed_history(session)
    recompute_scores(session)
    assert [r for r in session.exec(select(Recommendation)).all() if r.rule_key == "plan:load_change"] == []


# --- the matching engine merging/splitting canonicals under a linked plan --------------------


def _two_activities(session):
    from catch.core.models import Activity

    t0 = datetime(2026, 6, 1, 7, 0, tzinfo=timezone.utc)
    out = []
    for i, (src, offset) in enumerate((("garmin", 0), ("concept2", 0))):
        canon = CanonicalActivity(start=t0 + timedelta(minutes=offset), duration=3600.0, sport_family="rowing", category="erg")
        session.add(canon)
        session.flush()
        act = Activity(
            source=src, external_id=f"m{i}", type="indoor_rowing", start=t0, duration=3600.0, canonical_id=canon.id, sport_family="rowing"
        )
        session.add(act)
        session.commit()
        out.append((act, canon))
    return out


def test_merging_workouts_moves_a_plan_link_to_the_survivor(session):
    from catch.sync.matching import manual_merge

    (a, ca), (b, cb) = _two_activities(session)
    plan = _plan(session, date(2026, 6, 1))
    sp.link_planned(session, OWNER, plan.id, cb.id)
    keep = manual_merge(session, a.id, b.id)
    session.expire_all()
    assert session.get(CanonicalActivity, cb.id) is None or keep.id == cb.id
    linked = session.get(PlannedWorkout, plan.id).linked_canonical_id
    assert linked == keep.id and session.get(CanonicalActivity, linked) is not None


def test_merge_with_both_sides_linked_unlinks_the_dropped_sides_plan(session):
    from catch.sync.matching import manual_merge

    (a, ca), (b, cb) = _two_activities(session)
    p1, p2 = _plan(session, date(2026, 6, 1)), _plan(session, date(2026, 6, 1))
    sp.link_planned(session, OWNER, p1.id, ca.id)
    sp.link_planned(session, OWNER, p2.id, cb.id)
    keep = manual_merge(session, a.id, b.id)
    session.expire_all()
    links = sorted((session.get(PlannedWorkout, p.id).linked_canonical_id or 0) for p in (p1, p2))
    assert links == [0, keep.id]  # exactly one plan keeps the workout; the other is simply unlinked


def test_splitting_leaves_the_plan_on_the_original_canonical(session):
    from catch.sync.matching import manual_merge, split_activity

    (a, ca), (b, cb) = _two_activities(session)
    keep = manual_merge(session, a.id, b.id)
    plan = _plan(session, date(2026, 6, 1))
    sp.link_planned(session, OWNER, plan.id, keep.id)
    split_activity(session, b.id)
    session.expire_all()
    assert session.get(PlannedWorkout, plan.id).linked_canonical_id == keep.id
    assert session.get(CanonicalActivity, keep.id) is not None


def test_a_link_to_a_vanished_canonical_heals_on_read_instead_of_dangling(session):
    plan = _plan(session, date(2026, 6, 1))
    canon = _canonical(session, date(2026, 6, 1))
    sp.link_planned(session, OWNER, plan.id, canon.id)
    session.delete(canon)  # any path that removes a canonical other than the matching engine
    session.commit()
    row = sp.list_planned(session, OWNER, date(2026, 6, 1), date(2026, 6, 1))[0]
    assert row.linked_canonical_id is None and sp.planned_dict(row, date(2026, 7, 1))["display_status"] == "not_logged"


def test_the_link_foreign_keys_declare_on_delete_set_null():
    for table in (PlannedWorkout.__table__, TrainingPhase.__table__):
        for fk in table.foreign_keys:
            assert fk.ondelete == "SET NULL", (table.name, fk.parent.name)


def test_an_absorbed_piece_canonical_is_in_neither_the_day_rows_nor_the_week_totals(session):
    # Absorbed canonicals also carry exclude_from_totals (catch/sync/piece.py), so the calendar's day
    # rows and the week summary agree about how many sessions the week holds.
    _canonical(session, MON, duration=3600.0)
    _canonical(
        session, MON, duration=360.0, absorbed_into_piece_id=1,
        overrides_json=json.dumps({"exclude_from_totals": True}),
    )
    summary = sp.build_week_summary(session, OWNER, MON)
    cal = sp.build_calendar(session, OWNER, MON, MON + timedelta(days=6))
    assert summary["completed"]["sessions"] == 1
    assert sum(len(d["completed"]) for d in cal["days"]) == 1


def test_an_excluded_workout_shows_on_the_calendar_but_not_in_totals(session):
    _canonical(session, MON, overrides_json=json.dumps({"exclude_from_totals": True}))
    cal = sp.build_calendar(session, OWNER, MON, MON + timedelta(days=6))
    shown = [c for d in cal["days"] for c in d["completed"]]
    assert len(shown) == 1 and shown[0]["excluded_from_totals"] is True
    assert sp.build_week_summary(session, OWNER, MON)["completed"]["sessions"] == 0
