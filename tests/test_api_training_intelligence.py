from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from conftest import TEST_PASSWORD

from catch.analytics.defaults import DEFAULT_SETTINGS
from catch.core.models import CanonicalActivity, DailyWellness, Recommendation
from catch.sync import training_intelligence as ti
from catch.sync.scoring import recompute_scores

TI = DEFAULT_SETTINGS["training_intelligence"]


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def _seed_wellness(session, today: date, n: int = 95):
    # Includes `today` itself with the same baseline values — evaluate_training_suggestion
    # now requires a real physiologically-backed "green" recovery reading (not just "not
    # red"), which needs today's own HRV/resting-HR, not only a trailing baseline. n=95
    # defaults wide enough to cover _seed_steady_background_training's own 90-day window.
    for i in range(0, n + 1):
        session.add(DailyWellness(date=today - timedelta(days=i), resting_hr=50.0, hrv_rmssd=55.0, sleep_seconds=8 * 3600))
    session.commit()


def _local_dt(day: date, hour: int = 12) -> datetime:
    """A UTC-aware datetime that round-trips back to exactly `day` via the production code's
    own `a.start.astimezone().date()` convention (catch/sync/scoring.py's
    _local_day_utc_range), regardless of this machine's system timezone — unlike
    `datetime.combine(day, ..., tzinfo=timezone.utc)`, which stores `day` as a literal UTC
    date and can round-trip to the *previous* local day in a negative-UTC-offset timezone (the
    exact bug an advisor review caught in an earlier version of this fixture)."""
    return datetime(day.year, day.month, day.day, hour, 0).astimezone(timezone.utc)


def _seed_activity(session, when: datetime, **kwargs):
    session.add(CanonicalActivity(start=when, duration=kwargs.pop("duration", 3600.0), avg_hr=kwargs.pop("avg_hr", 140.0), sport_family=kwargs.pop("sport_family", "rowing"), category=kwargs.pop("category", "erg"), **kwargs))
    session.commit()


def _seed_steady_background_training(session, today: date):
    """~80 days of steady light training ending 8 days ago — `strain_trimp` is set directly
    (bypassing the max_hr/RPE chain `session_strain` would otherwise need, neither of which
    this test DB configures) so `training_load`'s acute/chronic EWMAs actually converge to a
    real, non-"insufficient_data" band. Deliberately stops 8 days before today so the most
    recent week is light — load reads "undertraining" (an allowed band) and this week's own
    session count stays under the default weekly target, the realistic "should fire"
    fixture for evaluate_training_suggestion's `training:add_session`."""
    for i in range(8, 90):
        when = datetime.now(timezone.utc) - timedelta(days=i)
        session.add(CanonicalActivity(start=when, duration=1800.0, avg_hr=120.0, sport_family="rowing", category="erg", strain_trimp=40.0))
    session.commit()


# --- generate_recommendations: idempotency, staleness, dedup/cooldown --------------------------


def test_same_day_recompute_is_idempotent(session):
    today = date.today()
    _seed_wellness(session, today)
    _seed_steady_background_training(session, today)
    _seed_activity(session, datetime.now(timezone.utc))
    recompute_scores(session)
    recompute_scores(session)
    recompute_scores(session)

    from sqlmodel import select

    rows = session.exec(select(Recommendation)).all()
    by_rule = {}
    for r in rows:
        by_rule.setdefault(r.rule_key, []).append(r)
    assert all(len(v) == 1 for v in by_rule.values())


def test_dismissal_does_not_reopen_the_cooldown(session):
    today = date.today()
    _seed_wellness(session, today)
    _seed_steady_background_training(session, today)
    _seed_activity(session, datetime.now(timezone.utc))
    recompute_scores(session)

    from sqlmodel import select

    row = session.exec(select(Recommendation).where(Recommendation.rule_key == "training:add_session")).first()
    assert row is not None
    row.dismissed = True
    session.add(row)
    session.commit()

    recompute_scores(session)
    rows = session.exec(select(Recommendation).where(Recommendation.rule_key == "training:add_session")).all()
    assert len(rows) == 1
    assert rows[0].dismissed is True


def test_reconfirming_within_cooldown_refreshes_the_body_not_just_the_date(session):
    """Every body quotes the day's own numbers ("You're at N of your 5-session weekly
    target"). Bumping only last_confirmed_on on a re-fire would leave the coach asserting an
    earlier day's numbers as "today's" for the rest of the cooldown window — a real bug an
    advisor review caught."""
    today = date.today()
    _seed_wellness(session, today)
    _seed_steady_background_training(session, today)
    _seed_activity(session, datetime.now(timezone.utc))
    recompute_scores(session)

    from sqlmodel import select

    first = session.exec(select(Recommendation).where(Recommendation.rule_key == "training:add_session")).first()
    assert first is not None
    assert "at 1 of your" in first.body
    first_id = first.id

    # A second session logged today changes sessions_this_week from 1 to 2 — still within
    # cooldown, so this must update the existing row's body in place, not insert a new one.
    _seed_activity(session, datetime.now(timezone.utc) + timedelta(hours=1))
    recompute_scores(session)

    rows = session.exec(select(Recommendation).where(Recommendation.rule_key == "training:add_session")).all()
    assert len(rows) == 1
    assert rows[0].id == first_id
    assert "at 2 of your" in rows[0].body


def test_a_rule_that_stops_firing_is_no_longer_active_the_next_day(session):
    today = date.today()
    _seed_wellness(session, today)
    _seed_steady_background_training(session, today)
    _seed_activity(session, datetime.now(timezone.utc))
    recompute_scores(session)

    from sqlmodel import select

    row = session.exec(select(Recommendation).where(Recommendation.rule_key == "training:add_session")).first()
    assert ti.is_active(row, today) is True

    # Simulate a day passing with the rule no longer confirmed (last_confirmed_on untouched).
    tomorrow = today + timedelta(days=1)
    assert ti.is_active(row, tomorrow) is True  # still within the 1-day grace window
    day_after = today + timedelta(days=2)
    assert ti.is_active(row, day_after) is False


def test_failure_in_one_evaluator_does_not_break_recompute_scores(session, monkeypatch):
    today = date.today()
    _seed_wellness(session, today)
    _seed_activity(session, datetime.now(timezone.utc))

    def _boom(context, settings):
        raise RuntimeError("boom")

    monkeypatch.setattr("catch.sync.training_intelligence.evaluate_overload_warning", _boom)
    count = recompute_scores(session)
    assert count > 0  # DailyScore rows still got written despite the evaluator raising

    from catch.core.models import DailyScore

    assert session.get(DailyScore, today) is not None


def test_recompute_scores_runs_exactly_once(session, monkeypatch):
    today = date.today()
    _seed_wellness(session, today)
    _seed_activity(session, datetime.now(timezone.utc))

    calls = []
    import catch.sync.scoring as scoring_module

    real_recompute = scoring_module.recompute_scores

    def _counting(s):
        calls.append(1)
        return real_recompute(s)

    monkeypatch.setattr(scoring_module, "recompute_scores", _counting)
    scoring_module.recompute_scores(session)
    assert len(calls) == 1


def test_fresh_install_produces_only_data_quality_rows(session):
    """A completely empty DB: recompute_scores returns early (no earliest date to anchor the
    day-loop on), so the recommendation hook never runs at all — no rows of any kind. This is
    the vacuous case; the real regression test is the one below."""
    count = recompute_scores(session)
    assert count == 0

    from sqlmodel import select

    assert session.exec(select(Recommendation)).all() == []


def test_training_suggestion_never_fires_on_the_exact_live_bug_scenario(session):
    """The exact shape of the real bug: 24 days of wellness history (clears
    data_quality_min_history_days) but *no row for today itself*, plus one activity logged
    today with no cached strain_trimp and no max_hr configured (so day_strain's HR-based
    TRIMP chain has nothing to compute from). Recovery ends up "green" from prior_strain
    alone — no physiological component for today — and load stays insufficient_data. Before
    the advisor-review fix, this produced a false "nothing to hold you back" claim."""
    today = date.today()
    for i in range(1, 25):
        session.add(DailyWellness(date=today - timedelta(days=i), resting_hr=50.0, hrv_rmssd=55.0, sleep_seconds=8 * 3600))
    session.commit()
    _seed_activity(session, datetime.now(timezone.utc))  # no strain_trimp, settings.max_hr unset
    recompute_scores(session)

    from sqlmodel import select

    rows = session.exec(select(Recommendation)).all()
    assert not any(r.rule_key == "training:add_session" for r in rows)


# --- CRUD routes -----------------------------------------------------------------------------


def _seed_one_recommendation(session) -> int:
    today = date.today()
    _seed_wellness(session, today)
    _seed_steady_background_training(session, today)
    _seed_activity(session, datetime.now(timezone.utc))
    recompute_scores(session)
    from sqlmodel import select

    row = session.exec(select(Recommendation)).first()
    assert row is not None
    return row.id


def test_dismiss_mutates_and_refetches(client, session):
    _login(client)
    rec_id = _seed_one_recommendation(session)
    resp = client.post(f"/api/training-intelligence/recommendations/{rec_id}/dismiss")
    assert resp.status_code == 200
    body = resp.json()
    assert body["dismissed"] is True
    # The response shape matches get_recommendations' own row shape (recommendation_dict),
    # not the bare ORM row — same shape, every mutation route.
    assert body["active"] is False
    assert "evidence" in body and isinstance(body["evidence"], list)


def test_save_toggle(client, session):
    _login(client)
    rec_id = _seed_one_recommendation(session)
    resp = client.post(f"/api/training-intelligence/recommendations/{rec_id}/save", json={"saved": True})
    assert resp.status_code == 200
    assert resp.json()["saved"] is True


def test_rate_accepts_known_values_and_rejects_others(client, session):
    _login(client)
    rec_id = _seed_one_recommendation(session)
    bad = client.post(f"/api/training-intelligence/recommendations/{rec_id}/rate", json={"rating": "meh"})
    assert bad.status_code == 422

    good = client.post(f"/api/training-intelligence/recommendations/{rec_id}/rate", json={"rating": "useful"})
    assert good.status_code == 200
    assert good.json()["rating"] == "useful"


def test_404_on_unknown_recommendation_id(client, session):
    _login(client)
    resp = client.post("/api/training-intelligence/recommendations/999999/dismiss")
    assert resp.status_code == 404


def test_get_recommendations_defaults_to_active_only(client, session):
    _login(client)
    rec_id = _seed_one_recommendation(session)
    client.post(f"/api/training-intelligence/recommendations/{rec_id}/dismiss")

    active = client.get("/api/training-intelligence/recommendations").json()["recommendations"]
    assert all(r["id"] != rec_id for r in active)

    all_rows = client.get("/api/training-intelligence/recommendations?status=all").json()["recommendations"]
    assert any(r["id"] == rec_id for r in all_rows)


# --- consistency/insights date-clamping (never count the future, never count pre-history) -------


def test_consistency_never_counts_future_days_of_the_current_week(session):
    """Before clamping range_end to today+1, the not-yet-elapsed remainder of the current
    week was counted as rest days and the full week's session target was charged on a
    Monday — a live smoke test caught both."""
    from catch.sync.training_intelligence import gather_training_consistency
    from catch.core.settings_store import get_settings

    today = date.today()
    _seed_wellness(session, today, n=10)
    _seed_activity(session, _local_dt(today))
    recompute_scores(session)

    result = gather_training_consistency(session, get_settings(session), weeks=1)
    # Exact values, not a loose bound — the old (buggy) code also happened to satisfy a bare
    # "<=" check on some weekdays (e.g. a Saturday/Sunday run), which is exactly why this was
    # rewritten to assert the precise number rather than an inequality that could pass either
    # way. elapsed_days = today.weekday() + 1 (Monday..today, inclusive) once range_end is
    # correctly clamped to today + 1 and range_start to this week's Monday.
    elapsed_days = today.weekday() + 1
    assert result["rest_days"] == elapsed_days - 1  # one active day (today) in the window
    assert result["sessions_target"] == round(TI["target_sessions_per_week"] * elapsed_days / 7.0)


def test_consistency_never_counts_a_gap_before_the_accounts_own_history(session):
    """A fresh account's pre-history isn't a training gap — it's the absence of the app
    itself. Before clamping range_start to the earliest real data date, a 24-day-old account
    with 8 weeks of configured lookback reported a ~54-day gap, most of it before any data
    existed at all."""
    from catch.sync.training_intelligence import gather_training_insights
    from catch.core.settings_store import get_settings

    today = date.today()
    _seed_wellness(session, today, n=24)
    _seed_activity(session, datetime.now(timezone.utc))
    recompute_scores(session)

    insights = gather_training_insights(session, get_settings(session))
    gap_insight = next((i for i in insights if i["id"] == "consistency_gap"), None)
    if gap_insight is not None:
        assert gap_insight["evidence"][0]["value"] <= 24


def test_concentrated_block_requires_at_least_three_sessions_in_the_week(session):
    """A week with one or two sessions trivially passes a "top-2-days share" check (the top 2
    days ARE the whole week) — flagging it as "unusually concentrated" would be a false
    pattern on an ordinary light week, not a real one."""
    from catch.sync.training_intelligence import gather_training_consistency
    from catch.core.settings_store import get_settings

    today = date.today()
    this_week_start = today - timedelta(days=today.weekday())
    _seed_wellness(session, today, n=10)
    # Exactly 2 sessions this week, both on the same day — would trivially read as 100%
    # concentrated on the old unguarded check.
    _seed_activity(session, _local_dt(this_week_start), duration=1800.0)
    _seed_activity(session, _local_dt(this_week_start, hour=15), duration=1800.0)
    recompute_scores(session)

    result = gather_training_consistency(session, get_settings(session), weeks=1)
    assert result["concentrated_block"] is False


def test_concentrated_block_fires_on_a_genuine_pattern(session):
    """The positive case: 3+ sessions this week, all on the same 2 days — this should fire."""
    from catch.sync.training_intelligence import gather_training_consistency
    from catch.core.settings_store import get_settings

    today = date.today()
    this_week_start = today - timedelta(days=today.weekday())
    _seed_wellness(session, today, n=10)
    _seed_activity(session, _local_dt(this_week_start), duration=1800.0)
    _seed_activity(session, _local_dt(this_week_start, hour=15), duration=1800.0)
    _seed_activity(session, _local_dt(this_week_start, hour=18), duration=1800.0)
    recompute_scores(session)

    result = gather_training_consistency(session, get_settings(session), weeks=1)
    assert result["concentrated_block"] is True


# --- read endpoints smoke-test (full gather pipeline through the real routes) -------------------


def test_read_endpoints_return_grounded_shapes(client, session):
    _login(client)
    today = date.today()
    _seed_wellness(session, today)
    _seed_activity(session, datetime.now(timezone.utc))
    recompute_scores(session)

    profile = client.get("/api/training-intelligence/profile").json()
    assert "confidence" in profile and "phase" in profile

    trends = client.get("/api/training-intelligence/trends").json()
    assert "buckets" in trends

    distribution = client.get("/api/training-intelligence/distribution").json()
    assert "weeks" in distribution

    consistency = client.get("/api/training-intelligence/consistency").json()
    assert "sessions_completed" in consistency

    insights = client.get("/api/training-intelligence/insights").json()
    assert "insights" in insights

    # Context fields present-but-honest, never silently treated as zero when nothing's logged.
    assert profile["nutrition"] == {"logged": False}
    assert profile["daily_activity"] == {"logged": False}
    assert profile["recent_note"] is None


def test_training_profile_surfaces_logged_nutrition_and_activity_context(client, session):
    from catch.core.models import DailyWellness as _DailyWellness
    from catch.core.models import Note

    _login(client)
    today = date.today()
    _seed_wellness(session, today)
    _seed_activity(session, datetime.now(timezone.utc))
    wellness_today = session.get(_DailyWellness, today)
    wellness_today.steps = 8000
    wellness_today.active_kcal = 450
    session.add(wellness_today)
    session.add(Note(date=today, text="Legs felt heavy on the warmup."))
    session.commit()
    recompute_scores(session)

    profile = client.get("/api/training-intelligence/profile").json()
    assert profile["daily_activity"] == {"logged": True, "steps": 8000, "active_kcal": 450}
    assert profile["recent_note"] == "Legs felt heavy on the warmup."


# --- coach tool layer + MCP parity --------------------------------------------------------------


def test_coach_tools_expose_all_seven_and_delegate_correctly(session):
    from catch.coach.tools import TOOLS, call_tool

    for name in (
        "get_training_profile",
        "get_performance_trends",
        "get_training_distribution",
        "get_training_consistency",
        "get_training_insights",
        "get_recommendations",
        "rate_recommendation",
    ):
        assert name in TOOLS

    today = date.today()
    _seed_wellness(session, today)
    _seed_activity(session, datetime.now(timezone.utc))
    recompute_scores(session)

    result = call_tool(session, "get_training_profile", {})
    assert "confidence" in result

    recs = call_tool(session, "get_recommendations", {})
    assert "recommendations" in recs
    if recs["recommendations"]:
        rec_id = recs["recommendations"][0]["id"]
        rated = call_tool(session, "rate_recommendation", {"id": rec_id, "rating": "useful"})
        assert rated["rating"] == "useful"


def test_mcp_server_registers_exactly_the_same_tool_names_as_the_coach_registry():
    import asyncio

    from catch.coach.tools import TOOLS
    from catch.mcp_server.backend import ToolBackend
    from catch.mcp_server.server import build_server

    class _FakeBackend(ToolBackend):
        async def call_tool(self, name, args):
            return {}

    mcp = build_server(_FakeBackend())
    registered = {t.name for t in asyncio.run(mcp.list_tools())}
    assert registered == set(TOOLS)


# --- memory_block surfaces at most the single most severe active recommendation ------------------


def test_memory_block_surfaces_an_active_recommendation(session):
    from catch.coach.memory import memory_block

    today = date.today()
    _seed_wellness(session, today)
    _seed_steady_background_training(session, today)
    _seed_activity(session, datetime.now(timezone.utc))
    recompute_scores(session)

    block = memory_block(session)
    assert "Active recommendation" in block


def test_memory_block_omits_a_stale_recommendation(session):
    from sqlmodel import select

    from catch.coach.memory import memory_block

    today = date.today()
    _seed_wellness(session, today)
    _seed_steady_background_training(session, today)
    _seed_activity(session, datetime.now(timezone.utc))
    recompute_scores(session)

    row = session.exec(select(Recommendation)).first()
    row.last_confirmed_on = today - timedelta(days=5)
    session.add(row)
    session.commit()

    block = memory_block(session)
    assert "Active recommendation" not in block
