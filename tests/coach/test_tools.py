from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from catch.coach import tools
from catch.core.models import Activity, ApiToken, CoachCredential, DailyWellness, Food, OAuthToken, Stroke
from catch.sync.matching import run_matching


def test_get_today_runs_on_empty_db(session):
    out = tools.call_tool(session, "get_today", {})
    assert out["recovery"] is None
    assert out["next_a_race"] is None


def test_get_zones_includes_zone_mode(session):
    out = tools.call_tool(session, "get_zones", {})
    assert out["zone_mode"] == "hr"
    assert len(out["zones"]) == 5


def test_get_wellness_returns_days_in_range(session):
    for i in range(5):
        session.add(DailyWellness(date=date(2026, 1, 1) + timedelta(days=i), resting_hr=50 + i))
    session.commit()
    out = tools.call_tool(session, "get_wellness", {"from": "2026-01-01", "to": "2026-01-05"})
    assert len(out["days"]) == 5
    assert out["days"][0]["resting_hr"] == 50


def test_get_wellness_caps_and_downsamples_a_wide_range(session):
    start = date(2020, 1, 1)
    for i in range(400):
        session.add(DailyWellness(date=start + timedelta(days=i), resting_hr=50))
    session.commit()
    out = tools.call_tool(session, "get_wellness", {})
    assert len(out["days"]) <= tools._MAX_ROWS


def test_add_note_then_get_load_is_consistent(session):
    session.add(DailyWellness(date=date.today(), resting_hr=50))
    session.commit()
    tools.call_tool(session, "add_note", {"date": date.today().isoformat(), "text": "felt good", "rpe": 4})
    out = tools.call_tool(session, "get_load", {})
    assert out["date"] == date.today().isoformat()
    assert "band" in out["load"]


def test_add_note_rejects_out_of_range_rpe(session):
    try:
        tools.call_tool(session, "add_note", {"date": date.today().isoformat(), "text": "x", "rpe": 99})
        assert False, "should have raised"
    except ValueError:
        pass


def _seed_oats(session) -> Food:
    food = Food(
        source="manual", name="Oats", serving_size=40, serving_unit="g",
        kcal_100g=375, protein_100g=13, carbs_100g=61, fat_100g=7, verified=True,
    )
    session.add(food)
    session.commit()
    session.refresh(food)
    return food


def test_get_nutrition_defaults_to_trailing_week(session):
    out = tools.call_tool(session, "get_nutrition", {})
    assert len(out["days"]) == 7
    assert "under_fuelling" in out


def test_log_food_by_explicit_food_id(session):
    food = _seed_oats(session)
    out = tools.call_tool(session, "log_food", {"food_id": food.id, "quantity": 1, "unit": "serving", "meal": "breakfast"})
    assert out["logged"] is True
    assert out["food"] == "Oats"
    assert out["kcal"] == 150.0  # 40g serving * 375 kcal/100g


def test_log_food_by_description_single_match_logs_directly(session):
    _seed_oats(session)
    out = tools.call_tool(session, "log_food", {"description": "Oats", "quantity": 50, "unit": "g", "meal": "breakfast"})
    assert out["logged"] is True
    assert out["food"] == "Oats"


def test_log_food_by_description_opts_into_off_search(session, monkeypatch):
    """Unlike the search box's debounced as-you-type calls, log_food is one explicit call per
    tool use — exactly what OFF's own "not for search-as-you-type" warning is fine with, so
    this is the one place the coach opts in on the athlete's behalf (task's "text search
    across cache + both APIs")."""
    calls = []

    def _spy(session, query, limit=20, include_off=False):
        calls.append(include_off)
        return []

    monkeypatch.setattr("catch.sync.nutrition.search_foods", _spy)
    tools.call_tool(session, "log_food", {"description": "nonexistent", "quantity": 100, "unit": "g", "meal": "lunch"})
    assert calls == [True]


def test_log_food_by_description_ambiguous_returns_candidates_not_a_guess(session):
    session.add(Food(source="manual", name="Chicken Breast", kcal_100g=165, verified=True))
    session.add(Food(source="manual", name="Chicken Thigh", kcal_100g=209, verified=True))
    session.commit()
    out = tools.call_tool(session, "log_food", {"description": "chicken", "quantity": 100, "unit": "g", "meal": "lunch"})
    assert out["logged"] is False
    assert out["ambiguous"] is True
    assert len(out["candidates"]) == 2


def test_log_food_no_match_reports_clearly(session):
    out = tools.call_tool(session, "log_food", {"description": "nonexistent xyz food", "quantity": 100, "unit": "g", "meal": "lunch"})
    assert out["logged"] is False
    assert "No food found" in out["message"]


def test_log_food_requires_an_identifier(session):
    try:
        tools.call_tool(session, "log_food", {"quantity": 100, "unit": "g", "meal": "lunch"})
        assert False, "should have raised"
    except ValueError:
        pass


def test_get_workout_downsamples_strokes_and_includes_interval_table(session):
    activity = Activity(source="concept2", external_id="r1", type="rower", start=datetime.now(timezone.utc), duration=600, distance=2000)
    session.add(activity)
    session.commit()
    session.refresh(activity)
    for i in range(250):
        session.add(
            Stroke(activity_id=activity.id, seq=i, interval_index=0, t=float(i), distance=float(i) * 8, watts=200, stroke_rate=30, hr=150)
        )
    session.commit()
    run_matching(session)
    session.refresh(activity)

    out = tools.call_tool(session, "get_workout", {"id": activity.canonical_id})
    assert out["activity"]["id"] == activity.canonical_id
    assert len(out["strokes"]) <= tools._MAX_STROKE_POINTS
    assert 0 in out["interval_summary"]


def test_get_workout_has_no_strokes_for_garmin_only_activity(session):
    activity = Activity(source="garmin", external_id="g1", type="indoor_rowing", start=datetime.now(timezone.utc), duration=600)
    session.add(activity)
    session.commit()
    session.refresh(activity)
    run_matching(session)
    session.refresh(activity)

    out = tools.call_tool(session, "get_workout", {"id": activity.canonical_id})
    assert out["strokes"] is None
    assert out["interval_summary"] is None


def test_list_workouts_filters_by_type(session):
    session.add(Activity(source="garmin", external_id="g1", type="indoor_rowing", start=datetime.now(timezone.utc), duration=600))
    session.add(Activity(source="garmin", external_id="g2", type="rowing_v2", start=datetime.now(timezone.utc), duration=600))
    session.commit()
    run_matching(session)

    out = tools.call_tool(session, "list_workouts", {"type": "erg"})
    assert all(item["category"] == "erg" for item in out["items"])
    assert len(out["items"]) == 1


def test_rename_and_tag_activity(session):
    activity = Activity(source="garmin", external_id="r1", type="strength_training", start=datetime.now(timezone.utc), duration=600)
    session.add(activity)
    session.commit()
    run_matching(session)
    session.refresh(activity)

    renamed = tools.call_tool(session, "rename_activity", {"id": activity.canonical_id, "title": "Leg day"})
    assert renamed["title"] == "Leg day"
    tagged = tools.call_tool(session, "tag_activity", {"id": activity.canonical_id, "tags": ["cross-training"]})
    assert tagged["tags"] == ["cross-training"]


def test_merge_activities_previews_then_merges_on_confirm(session):
    a = Activity(source="garmin", external_id="m1", type="indoor_rowing", start=datetime(2026, 4, 1, 7, tzinfo=timezone.utc), duration=1800.0)
    b = Activity(source="concept2", external_id="m2", type="rower", start=datetime(2026, 4, 2, 7, tzinfo=timezone.utc), duration=1800.0)
    session.add(a)
    session.add(b)
    session.commit()
    run_matching(session)
    session.refresh(a)
    session.refresh(b)
    assert a.canonical_id != b.canonical_id  # a day apart — never auto-merges

    preview = tools.call_tool(session, "merge_activities", {"canonical_id_a": a.canonical_id, "canonical_id_b": b.canonical_id})
    assert preview["preview"] is True

    merged = tools.call_tool(
        session, "merge_activities", {"canonical_id_a": a.canonical_id, "canonical_id_b": b.canonical_id, "confirm": True}
    )
    assert {s["source"] for s in merged["sources"]} == {"garmin", "concept2"}


def test_merge_activities_errors_cleanly_on_an_id_with_no_matching_canonical(session):
    """Regression context: merge_activities used to take raw activity ids, like the one a
    model would read from a workout's `sources` list — but every other tool only ever deals
    in canonical ids, so a model handing it one of those by mistake could coincidentally
    match a real-but-wrong canonical and merge the wrong pair. It now resolves strictly via
    `Activity.canonical_id == X` (never `Activity.id == X`), so a value that isn't a real
    canonical id for anything — however plausible-looking — fails loudly instead of
    resolving to some unrelated activity by accident."""
    a = Activity(source="garmin", external_id="d1", type="strength_training", start=datetime(2026, 5, 1, tzinfo=timezone.utc), duration=600.0)
    session.add(a)
    session.commit()
    run_matching(session)
    session.refresh(a)

    try:
        tools.call_tool(session, "merge_activities", {"canonical_id_a": a.canonical_id, "canonical_id_b": 999999})
        assert False, "should have raised"
    except ValueError:
        pass


def test_merge_activities_preview_reports_the_real_canonical_members(session):
    a = Activity(source="garmin", external_id="d1", type="indoor_rowing", start=datetime(2026, 5, 1, 7, tzinfo=timezone.utc), duration=1800.0)
    b = Activity(source="concept2", external_id="d2", type="rower", start=datetime(2026, 5, 2, 7, tzinfo=timezone.utc), duration=1800.0)
    session.add(a)
    session.add(b)
    session.commit()
    run_matching(session)
    session.refresh(a)
    session.refresh(b)

    preview = tools.call_tool(session, "merge_activities", {"canonical_id_a": a.canonical_id, "canonical_id_b": b.canonical_id})
    assert preview["a"]["source"] == "garmin"
    assert preview["b"]["source"] == "concept2"


def test_get_body_comp_with_a_date_range(session):
    from catch.core.models import BodyComp

    session.add(BodyComp(source="withings", external_id="b1", ts=datetime(2026, 1, 1, 12, tzinfo=timezone.utc), weight_kg=80.0))
    session.commit()

    out = tools.call_tool(session, "get_body_comp", {"from": "2026-01-01", "to": "2026-01-31"})
    assert out["readings"][0]["weight"] == 80.0
    assert out["readings"][0]["weight_source"] == "withings"


def test_predict_2k_insufficient_data(session):
    out = tools.call_tool(session, "predict_2k", {})
    assert out["band"] == "insufficient_data"


def test_memory_tools_remember_recall_forget(session):
    fact = tools.call_tool(session, "remember", {"category": "injury", "text": "sore lower back"})
    assert fact["ref"].startswith("fact:")

    results = tools.call_tool(session, "recall", {"query": "back"})["results"]
    assert any(r["text"] == "sore lower back" for r in results)

    out = tools.call_tool(session, "forget", {"ref": fact["ref"]})
    assert out["deleted"] is True
    assert tools.call_tool(session, "recall", {"query": "back"})["results"] == []


def test_event_tools_preview_then_save_on_confirm(session):
    args = {"name": "Head of the Charles", "date": "2027-10-18", "type": "race", "priority": "A"}
    preview = tools.call_tool(session, "create_event", args)
    assert preview["saved"] is False and preview["preview"]["name"] == "Head of the Charles"
    assert tools.call_tool(session, "recall", {"query": "Charles"})["results"] == []
    event = tools.call_tool(session, "create_event", {**args, "confirm": True})["event"]
    assert event["days_to_go"] > 0

    held = tools.call_tool(session, "update_event", {"id": event["id"], "result": "6:42"})
    assert held["saved"] is False and held["preview"]["changes"]["result"] == {"from": None, "to": "6:42"}
    updated = tools.call_tool(session, "update_event", {"id": event["id"], "result": "6:42", "confirm": True})["event"]
    assert updated["result"] == "6:42"


def test_remember_rejects_unknown_category(session):
    try:
        tools.call_tool(session, "remember", {"category": "nonsense", "text": "x"})
        assert False, "should have raised"
    except ValueError:
        pass


def test_tool_outputs_never_leak_secrets(session):
    """No tool ever returns tokens, keys, or raw OAuth data — serialize every read-only tool's
    output and grep for secrets planted in OAuthToken/CoachCredential/ApiToken rows."""
    session.add(OAuthToken(source="garmin", access_token_enc="SUPER-SECRET-GARMIN-TOKEN"))
    session.add(CoachCredential(provider="anthropic", api_key_enc="ENCRYPTED-BLOB", last4="wxyz"))
    session.add(ApiToken(name="laptop", token_hash="deadbeef" * 8))
    activity = Activity(source="concept2", external_id="r1", type="rower", start=datetime.now(timezone.utc), duration=600, distance=2000)
    session.add(activity)
    session.commit()
    run_matching(session)
    session.refresh(activity)

    secrets_ = ["SUPER-SECRET-GARMIN-TOKEN", "ENCRYPTED-BLOB", "deadbeef" * 8]
    read_only_calls = [
        ("get_today", {}),
        ("get_wellness", {}),
        ("list_workouts", {}),
        ("get_workout", {"id": activity.canonical_id}),
        ("get_trends", {"metric": "recovery"}),
        ("get_body_comp", {}),
        ("get_load", {}),
        ("predict_2k", {}),
        ("get_zones", {}),
        ("recall", {}),
        ("get_nutrition", {}),
        ("get_strength", {}),
        ("get_muscle_readiness", {}),
    ]
    for name, args in read_only_calls:
        dumped = json.dumps(tools.call_tool(session, name, args))
        for secret in secrets_:
            assert secret not in dumped, f"{name} leaked a secret"


# -- gym logger tools (session 14 — see PLAN.md Part D) ------------------------------------


def _seed_squat(session):
    from catch.core.models import Exercise

    row = Exercise(
        name="Barbell Squat",
        default_equipment_type="barbell",
        movement_pattern="squat",
        primary_muscles_json='["quadriceps"]',
        secondary_muscles_json='["glutes"]',
        custom=True,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def test_parse_strength_text_basic_example():
    parsed = tools._parse_strength_text("3x8 cable row stack 12 on station 2")
    assert parsed["sets_count"] == 3
    assert parsed["reps"] == 8
    assert parsed["load_kg"] == 12.0
    assert parsed["equipment_type"] == "cable"
    assert parsed["station"] == 2
    assert "row" in parsed["exercise_name"].lower()


def test_parse_strength_text_barbell_with_kg():
    parsed = tools._parse_strength_text("squat 5x5 100kg")
    assert parsed["sets_count"] == 5
    assert parsed["reps"] == 5
    assert parsed["load_kg"] == 100.0
    assert parsed["equipment_type"] == "barbell"


def test_parse_strength_text_pounds_converted_to_kg():
    parsed = tools._parse_strength_text("bench press 3 sets of 8 at 135lbs")
    assert parsed["sets_count"] == 3
    assert parsed["reps"] == 8
    assert abs(parsed["load_kg"] - 135 * 0.453592) < 0.01


def test_parse_strength_text_rir_and_rpe():
    parsed = tools._parse_strength_text("deadlift 1x5 140kg rir 1")
    assert parsed["rir"] == 1.0
    parsed2 = tools._parse_strength_text("deadlift 1x5 140kg rpe 9")
    assert parsed2["rpe"] == 9.0


def test_log_strength_from_text_previews_before_saving(session):
    _seed_squat(session)
    out = tools.call_tool(session, "log_strength", {"text": "squat 3x5 100kg"})
    assert out["saved"] is False
    assert len(out["preview"]) == 3
    assert out["preview"][0]["exercise_name"] == "Barbell Squat"

    from catch.core.models import StrengthSet
    from sqlmodel import select

    assert session.exec(select(StrengthSet)).all() == []  # nothing written yet.


def test_log_strength_confirm_true_saves_sets(session):
    _seed_squat(session)
    preview = tools.call_tool(session, "log_strength", {"text": "squat 3x5 100kg"})
    confirmed = tools.call_tool(session, "log_strength", {"sets": preview["preview"], "confirm": True})
    assert confirmed["saved"] is True
    assert len(confirmed["sets"]) == 3
    assert confirmed["sets"][0]["effective_load_kg"] == 120.0  # 100kg + default 20kg bar.


def test_log_strength_unknown_exercise_asks_rather_than_guesses(session):
    out = tools.call_tool(session, "log_strength", {"text": "some made up exercise 3x5 50kg"})
    assert out["saved"] is False
    assert "no exercise found" in out["message"].lower()


def test_log_strength_second_call_same_day_appends_to_one_session(session):
    _seed_squat(session)
    preview1 = tools.call_tool(session, "log_strength", {"text": "squat 3x5 100kg"})
    tools.call_tool(session, "log_strength", {"sets": preview1["preview"], "confirm": True})
    preview2 = tools.call_tool(session, "log_strength", {"text": "squat 2x3 120kg"})
    tools.call_tool(session, "log_strength", {"sets": preview2["preview"], "confirm": True})

    from catch.core.models import Activity
    from sqlmodel import select

    sessions = session.exec(select(Activity).where(Activity.source == "catch_strength")).all()
    assert len(sessions) == 1  # both calls landed in the same day's session.


def test_get_strength_filters_by_exercise_name(session):
    squat = _seed_squat(session)
    preview = tools.call_tool(session, "log_strength", {"text": "squat 2x5 80kg"})
    tools.call_tool(session, "log_strength", {"sets": preview["preview"], "confirm": True})

    out = tools.call_tool(session, "get_strength", {"exercise_name": "squat"})
    assert len(out["sets"]) == 2
    assert all(s["exercise_id"] == squat.id for s in out["sets"])


def test_get_muscle_readiness_reflects_a_logged_session(session):
    _seed_squat(session)
    preview = tools.call_tool(session, "log_strength", {"text": "squat 3x5 100kg"})
    tools.call_tool(session, "log_strength", {"sets": preview["preview"], "confirm": True})

    out = tools.call_tool(session, "get_muscle_readiness", {})
    assert out["by_muscle"]["quadriceps"] > 0


# --- Session 15 Part C: erg test center tools -------------------------------------------


def _seed_confirmed_2000m_test(session, external_id: str = "c1") -> int:
    activity = Activity(
        source="concept2", external_id=external_id, type="rower",
        start=datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc), duration=400.0, distance=2000.0,
    )
    session.add(activity)
    session.commit()
    run_matching(session)
    session.refresh(activity)
    for i in range(1, 5):
        session.add(Stroke(activity_id=activity.id, seq=i, interval_index=0, t=100.0 * i, distance=500.0 * i))
    session.commit()
    from catch.api import routes_activities

    routes_activities.patch_activity(
        activity.canonical_id, body=routes_activities.ActivityEditRequest(tags=["test"], test_type="2000m"), db=session
    )
    return activity.canonical_id


def test_get_tests_and_get_test_round_trip(session):
    canonical_id = _seed_confirmed_2000m_test(session)
    listed = tools.call_tool(session, "get_tests", {"type": "2000m"})
    assert listed["tests"][0]["canonical_id"] == canonical_id

    detail = tools.call_tool(session, "get_test", {"id": canonical_id})
    assert detail["test_type"] == "2000m"
    assert detail["pacing_analysis"]["even_split_s"] == 100.0


def test_make_pacing_plan_saves_to_next_event_by_default(session):
    from catch.core.models import Event

    event = Event(name="Trial", date=date.today() + timedelta(days=10), type="2k_test")
    session.add(event)
    session.commit()

    out = tools.call_tool(session, "make_pacing_plan", {"test_type": "2000m", "goal_time_s": 400.0, "style": "even"})
    assert out["saved_to_event"]["id"] == event.id
    session.refresh(event)
    assert event.plan_json is not None
