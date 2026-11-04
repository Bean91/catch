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


def test_memory_tools_add_event_and_update_event(session):
    event = tools.call_tool(session, "add_event", {"name": "Head of the Charles", "date": "2027-10-18", "type": "race", "priority": "A"})
    assert event["days_to_go"] > 0

    updated = tools.call_tool(session, "update_event", {"id": int(event["ref"].split(":")[1]), "result": "6:42"})
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
    ]
    for name, args in read_only_calls:
        dumped = json.dumps(tools.call_tool(session, name, args))
        for secret in secrets_:
            assert secret not in dumped, f"{name} leaked a secret"
