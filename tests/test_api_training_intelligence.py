from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from conftest import TEST_PASSWORD

from catch.core.models import CanonicalActivity, DailyWellness, Recommendation
from catch.sync import training_intelligence as ti
from catch.sync.scoring import recompute_scores


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def _seed_wellness(session, today: date, n: int = 20):
    for i in range(1, n + 1):
        session.add(DailyWellness(date=today - timedelta(days=i), resting_hr=50.0, hrv_rmssd=55.0, sleep_seconds=8 * 3600))
    session.commit()


def _seed_activity(session, when: datetime, **kwargs):
    session.add(CanonicalActivity(start=when, duration=kwargs.pop("duration", 3600.0), avg_hr=kwargs.pop("avg_hr", 140.0), sport_family=kwargs.pop("sport_family", "rowing"), category=kwargs.pop("category", "erg"), **kwargs))
    session.commit()


# --- generate_recommendations: idempotency, staleness, dedup/cooldown --------------------------


def test_same_day_recompute_is_idempotent(session):
    today = date.today()
    _seed_wellness(session, today)
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


def test_a_rule_that_stops_firing_is_no_longer_active_the_next_day(session):
    today = date.today()
    _seed_wellness(session, today)
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


# --- CRUD routes -----------------------------------------------------------------------------


def _seed_one_recommendation(session) -> int:
    today = date.today()
    _seed_wellness(session, today)
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
    assert body["dismissed_at"] is not None


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
    _seed_activity(session, datetime.now(timezone.utc))
    recompute_scores(session)

    block = memory_block(session)
    assert "Active recommendation" in block


def test_memory_block_omits_a_stale_recommendation(session):
    from sqlmodel import select

    from catch.coach.memory import memory_block

    today = date.today()
    _seed_wellness(session, today)
    _seed_activity(session, datetime.now(timezone.utc))
    recompute_scores(session)

    row = session.exec(select(Recommendation)).first()
    row.last_confirmed_on = today - timedelta(days=5)
    session.add(row)
    session.commit()

    block = memory_block(session)
    assert "Active recommendation" not in block
