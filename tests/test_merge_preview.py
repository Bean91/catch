"""Session 36: the duplicate-merge preview — both sides, the merged figures and where each comes from, written nowhere."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlmodel import select

from catch.core.models import Activity, CanonicalActivity
from catch.sync.matching import run_matching
from conftest import TEST_PASSWORD


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def test_preview_shows_sides_sources_and_writes_nothing(client, session):
    t0 = datetime(2026, 9, 3, 7, 0, tzinfo=timezone.utc)
    g = Activity(source="garmin", external_id="g1", type="indoor_rowing", start=t0, duration=1800.0, distance=7600.0, avg_hr=148.0)
    c = Activity(source="concept2", external_id="c1", type="rower", start=t0 + timedelta(minutes=2), duration=1100.0, distance=4400.0, avg_power=210.0, workout_type="JustRow")
    session.add_all([g, c])
    session.commit()
    run_matching(session)
    session.refresh(g)
    session.refresh(c)
    before = len(session.exec(select(CanonicalActivity)).all())
    _login(client)
    body = client.post("/api/activities/merge/preview", json={"activity_id_a": g.id, "activity_id_b": c.id}).json()
    assert body["already_merged"] is False, "the fixture must stay a flagged pair, not an automatic merge"
    assert body["a"]["source"] == "garmin" and body["b"]["avg_power"] == 210.0
    assert body["overlap_s"] == 1100.0
    assert body["merged"]["recordings"] == 2 and body["merged"]["values"]["avg_power"] == 210.0
    assert body["merged"]["from"]["avg_power"].startswith("concept2")
    session.expire_all()
    assert len(session.exec(select(CanonicalActivity)).all()) == before  # nothing written
    assert client.post("/api/activities/merge/preview", json={"activity_id_a": 999999, "activity_id_b": c.id}).status_code == 404
