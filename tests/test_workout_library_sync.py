from __future__ import annotations

import json
from datetime import timedelta

import pytest
from sqlmodel import select

from catch.analytics import workout_library as wl
from catch.core.models import Activity, CanonicalActivity, Exercise, PlannedWorkout, WorkoutTemplate
from catch.sync import planning as sp
from catch.sync import workout_library as lib
from test_planning_sync import MON, _canonical, _seed_history, _snapshot

OWNER = lib.OWNER_ID
OTHER = "someone-else"

INTERVALS = {
    "name": "4x500",
    "workout_type": "erg_intervals",
    "description": "Short intervals",
    "difficulty": "hard",
    "tags": ["Speed", "speed", " Erg "],
    "target_zone": "AN",
    "structure": {"warmup": {"duration_min": 10}, "blocks": [{"reps": 4, "work_m": 500, "rest_s": 60, "split_s": 105}], "cooldown": {"duration_min": 5}},
}
STEADY = {"name": "Steady 60", "workout_type": "steady_state", "target_zone": "UT2", "structure": {"blocks": [{"reps": 1, "work_s": 3600, "zone": "UT2"}]}}
DISTANCE_ONLY = {"name": "5k", "workout_type": "distance_piece", "structure": {"blocks": [{"reps": 1, "work_m": 5000}]}}


def _make(session, fields=None):
    return lib.create_template(session, OWNER, fields or INTERVALS)


# --- CRUD / validation -----------------------------------------------------------------------------------


def test_create_normalises_tags_derives_session_type_and_computes_summary(session):
    row = _make(session)
    d = lib.template_dict(row)
    assert d["tags"] == ["speed", "erg"] and d["session_type"] == "erg" and d["sport_family"] == "rowing"
    assert d["summary"]["duration_basis"] == "estimated" and d["signature"] == "4x500m/r60"
    assert d["is_example"] is False and d["archived"] is False


def test_invalid_template_is_rejected_with_the_first_issue_and_nothing_is_written(session):
    with pytest.raises(lib.LibraryError, match=r"structure\.blocks"):
        lib.create_template(session, OWNER, {"name": "x", "workout_type": "rate_ladder", "structure": {"blocks": [{"reps": 1, "work_s": 60}]}})
    with pytest.raises(lib.LibraryError, match="Unknown template field"):
        lib.create_template(session, OWNER, {**STEADY, "owner_id": "x"})
    assert session.exec(select(WorkoutTemplate).where(WorkoutTemplate.is_example.is_(False))).all() == []


def test_strength_templates_check_exercise_ids_against_the_library(session):
    ex = Exercise(name="Back squat", default_equipment_type="barbell", movement_pattern="squat", unilateral=False, primary_muscles_json="[]", secondary_muscles_json="[]")
    session.add(ex)
    session.commit()
    ok = lib.create_template(session, OWNER, {"name": "Legs", "workout_type": "strength", "structure": {"strength_items": [{"exercise_id": ex.id, "target_sets": 3, "target_reps": 5}]}})
    assert ok.session_type == "strength"
    with pytest.raises(lib.LibraryError, match="No exercise"):
        lib.create_template(session, OWNER, {"name": "Bad", "workout_type": "strength", "structure": {"strength_items": [{"exercise_id": 99999}]}})


def test_update_revalidates_the_merged_result_and_bumps_updated_at(session):
    row = _make(session)
    before = row.updated_at
    lib.update_template(session, OWNER, row.id, {"description": "New", "difficulty": "moderate"})
    assert row.description == "New" and row.updated_at >= before
    with pytest.raises(lib.LibraryError):
        lib.update_template(session, OWNER, row.id, {"workout_type": "steady_state"})  # 4x500 isn't one continuous block
    assert row.workout_type == "erg_intervals"


def test_changing_workout_type_resets_the_default_session_type(session):
    row = lib.create_template(session, OWNER, {"name": "w", "workout_type": "time_piece", "structure": {"blocks": [{"reps": 1, "work_s": 600}]}})
    lib.update_template(session, OWNER, row.id, {"workout_type": "on_water"})
    assert row.session_type == "on_water" and row.sport_family == "rowing"


def test_duplicate_is_an_independent_editable_copy(session):
    src = _make(session)
    copy = lib.duplicate_template(session, OWNER, src.id)
    assert copy.id != src.id and copy.name == "4x500 (copy)" and copy.duplicated_from_id == src.id and not copy.is_example
    lib.update_template(session, OWNER, copy.id, {"name": "Mine"})
    assert src.name == "4x500"


def test_archive_hides_from_default_search_but_keeps_the_row(session):
    row = _make(session)
    lib.set_archived(session, OWNER, row.id, True)
    assert lib.search_templates(session, OWNER, include_examples=False) == []
    assert [r.id for r in lib.search_templates(session, OWNER, include_examples=False, include_archived=True)] == [row.id]
    lib.set_archived(session, OWNER, row.id, False)
    assert [r.id for r in lib.search_templates(session, OWNER, include_examples=False)] == [row.id]


def test_search_filters(session):
    a, b = _make(session), _make(session, STEADY)
    names = lambda **kw: sorted(r.name for r in lib.search_templates(session, OWNER, include_examples=False, **kw))  # noqa: E731
    assert names(q="steady") == ["Steady 60"]
    assert names(workout_type="erg_intervals") == ["4x500"]
    assert names(difficulty="hard") == ["4x500"]
    assert names(tags=["speed"]) == ["4x500"] and names(tags=["speed", "nope"]) == []
    assert names(session_type="erg") == ["4x500", "Steady 60"]
    assert len(lib.search_templates(session, OWNER, include_examples=False, limit=1)) == 1
    assert a.id and b.id


def test_everything_is_owner_scoped(session):
    row = _make(session)
    for call in (
        lambda: lib.get_template(session, OTHER, row.id),
        lambda: lib.update_template(session, OTHER, row.id, {"name": "x"}),
        lambda: lib.duplicate_template(session, OTHER, row.id),
        lambda: lib.set_archived(session, OTHER, row.id, True),
        lambda: lib.schedule_template(session, OTHER, row.id, MON),
        lambda: lib.preview_schedule(session, OTHER, row.id, MON),
    ):
        with pytest.raises(lib.NotFound):
            call()
    assert lib.search_templates(session, OTHER, include_examples=True) == []


# --- examples ---------------------------------------------------------------------------------------------------


def test_seed_is_idempotent_labelled_and_read_only(session):
    n = lib.seed_examples(session)
    assert n >= 6 and lib.seed_examples(session) == 0
    ex = lib.search_templates(session, OWNER, only_examples=True)
    assert len(ex) == n and all(r.is_example and r.external_id for r in ex)
    d = lib.template_dict(ex[0])
    assert d["example_label"] == "Example — not prescribed training"
    with pytest.raises(lib.LibraryError, match="read-only"):
        lib.update_template(session, OWNER, ex[0].id, {"name": "x"})
    copy = lib.duplicate_template(session, OWNER, ex[0].id)
    assert not copy.is_example and copy.external_id is None
    lib.update_template(session, OWNER, copy.id, {"description": "mine"})


def test_an_archived_example_stays_archived_after_reseeding(session):
    lib.seed_examples(session)
    ex = lib.search_templates(session, OWNER, only_examples=True)[0]
    lib.set_archived(session, OWNER, ex.id, True)
    lib.seed_examples(session)
    assert session.get(WorkoutTemplate, ex.id).archived_at is not None


def test_default_search_can_exclude_examples(session):
    lib.seed_examples(session)
    mine = _make(session)
    assert [r.id for r in lib.search_templates(session, OWNER, include_examples=False)] == [mine.id]
    assert len(lib.search_templates(session, OWNER, include_examples=True)) > 1


# --- scheduling ---------------------------------------------------------------------------------------------------


def test_schedule_creates_a_snapshot_plan_with_provenance(session):
    row = _make(session)
    plans = lib.schedule_template(session, OWNER, row.id, MON, start_time="07:30")
    p = plans[0]
    assert p.template_id == row.id and p.title == "4x500" and p.session_type == "erg" and p.start_time == "07:30"
    summary = wl.summarize_template(json.loads(row.structure_json), row.target_zone)
    assert p.duration_min == pytest.approx(summary["total_duration_s"] / 60.0)
    assert p.distance_m is None  # the timed warm-up/cool-down have no honest distance
    assert summary["work_distance_m"] == 2000.0
    assert sp.planned_dict(p)["template_id"] == row.id
    lib.update_template(session, OWNER, row.id, {"name": "Renamed", "structure": STEADY["structure"], "workout_type": "steady_state"})
    session.refresh(p)
    assert p.title == "4x500" and p.duration_min == pytest.approx(summary["total_duration_s"] / 60.0)


def test_schedule_repeat_makes_a_series_all_pointing_at_the_template(session):
    row = _make(session)
    plans = lib.schedule_template(session, OWNER, row.id, MON, repeat={"weekdays": [0, 2], "count": 4})
    assert len(plans) == 4 and len({p.series_id for p in plans}) == 1 and {p.template_id for p in plans} == {row.id}


def test_preview_matches_what_schedule_then_writes_and_writes_nothing(session):
    row = _make(session)
    before = len(session.exec(select(PlannedWorkout)).all())
    preview = lib.preview_schedule(session, OWNER, row.id, MON, repeat={"count": 2, "weekdays": [0]})
    assert len(session.exec(select(PlannedWorkout)).all()) == before and preview["count"] == 2
    assert len(lib.schedule_template(session, OWNER, row.id, MON, repeat={"count": 2, "weekdays": [0]})) == preview["count"]


def test_archived_template_cannot_be_scheduled_and_bad_event_is_rejected(session):
    row = _make(session)
    with pytest.raises(lib.LibraryError, match="archived"):
        lib.set_archived(session, OWNER, row.id, True)
        lib.schedule_template(session, OWNER, row.id, MON)
    lib.set_archived(session, OWNER, row.id, False)
    with pytest.raises(lib.LibraryError):
        lib.schedule_template(session, OWNER, row.id, MON, event_id=424242)


def test_scheduling_a_template_with_unknown_duration_sets_no_duration(session):
    row = _make(session, DISTANCE_ONLY)
    p = lib.schedule_template(session, OWNER, row.id, MON)[0]
    assert p.duration_min is None and p.distance_m == 5000.0


def test_scheduled_numbers_match_the_week_summary(session):
    steady = _make(session, {**STEADY, "structure": {"blocks": [{"reps": 1, "work_s": 3600, "zone": "UT2"}]}})
    intervals = _make(session, {**INTERVALS, "target_zone": None, "structure": {"blocks": [{"reps": 6, "work_s": 180, "rest_s": 120, "zone": "AT"}]}})
    lib.schedule_template(session, OWNER, steady.id, MON)
    lib.schedule_template(session, OWNER, intervals.id, MON + timedelta(days=2))
    week = sp.build_week_summary(session, OWNER, MON)["planned"]
    s1 = wl.summarize_template(json.loads(steady.structure_json), steady.target_zone)
    s2 = wl.summarize_template(json.loads(intervals.structure_json), intervals.target_zone)
    assert week["minutes"] == pytest.approx((s1["total_duration_s"] + s2["total_duration_s"]) / 60.0)
    assert week["zone_minutes"]["UT2"] == pytest.approx(s1["zone_minutes"]["UT2"])
    assert week["zone_minutes"]["AT"] == pytest.approx(s2["zone_minutes"]["AT"])
    assert week["sessions"] == 2


# --- scheduled -> matched to a completed workout --------------------------------------------------------------------


def _suggested(session, day):
    cal = sp.build_calendar(session, OWNER, day, day)
    return cal["suggestions"]


def test_scheduled_template_is_suggested_then_linked_to_the_completed_workout(session):
    row = _make(session, STEADY)
    plan = lib.schedule_template(session, OWNER, row.id, MON)[0]
    done = _canonical(session, MON, duration=3500.0, sport_family="rowing", category="erg")
    sugg = _suggested(session, MON)
    assert [(s["planned_id"], s["canonical_id"]) for s in sugg] == [(plan.id, done.id)]
    linked = sp.link_planned(session, OWNER, plan.id, done.id)
    assert linked.linked_canonical_id == done.id and linked.template_id == row.id
    assert _suggested(session, MON) == []
    assert sp.planned_dict(linked)["display_status"] == "linked"


def test_a_template_with_no_derivable_duration_still_matches_on_day_and_sport(session):
    row = _make(session, DISTANCE_ONLY)
    plan = lib.schedule_template(session, OWNER, row.id, MON)[0]
    done = _canonical(session, MON, duration=1500.0, sport_family="rowing", category="erg")
    assert [(s["planned_id"], s["canonical_id"]) for s in _suggested(session, MON)] == [(plan.id, done.id)]


def test_a_different_sport_is_not_suggested(session):
    row = _make(session, STEADY)
    lib.schedule_template(session, OWNER, row.id, MON)
    _canonical(session, MON, duration=3500.0, sport_family="running", category="other")
    assert _suggested(session, MON) == []


def test_templates_and_scheduled_sessions_never_change_completed_totals(session):
    _seed_history(session)
    before = _snapshot(session)
    activities, canonicals = len(session.exec(select(Activity)).all()), len(session.exec(select(CanonicalActivity)).all())
    t = sp.today()
    row = _make(session)
    lib.seed_examples(session)
    for offset in (-10, -1, 0, 2, 9):
        lib.schedule_template(session, OWNER, row.id, t + timedelta(days=offset))
    lib.schedule_template(session, OWNER, row.id, t, repeat={"count": 6, "weekdays": [0, 3]})
    assert _snapshot(session) == before
    assert (len(session.exec(select(Activity)).all()), len(session.exec(select(CanonicalActivity)).all())) == (activities, canonicals)
