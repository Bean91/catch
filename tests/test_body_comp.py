from __future__ import annotations

from datetime import date, datetime, timezone

from catch.core.models import BodyComp
from catch.core.settings_store import update_settings
from catch.sync.body_comp import nearest_resolved_weight_kg, resolve_daily
from conftest import TEST_PASSWORD

DAY = date(2026, 3, 1)
NOON = datetime(2026, 3, 1, 12, tzinfo=timezone.utc)


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def test_withings_wins_by_default_when_both_scales_report_the_same_day(session):
    session.add(BodyComp(source="withings", external_id="w1", ts=NOON, weight_kg=80.0, fat_pct=15.0))
    session.add(BodyComp(source="garmin", external_id="g1", ts=NOON, weight_kg=79.0, fat_pct=16.0))
    session.commit()

    daily = resolve_daily(session)
    assert len(daily) == 1
    assert daily[0]["weight"] == 80.0
    assert daily[0]["weight_source"] == "withings"
    assert daily[0]["fat_pct"] == 15.0
    assert daily[0]["fat_pct_source"] == "withings"


def test_never_averages_two_scales(session):
    session.add(BodyComp(source="withings", external_id="w1", ts=NOON, weight_kg=80.0))
    session.add(BodyComp(source="garmin", external_id="g1", ts=NOON, weight_kg=70.0))
    session.commit()

    daily = resolve_daily(session)
    # 75.0 (the average) must never appear — one source wins outright.
    assert daily[0]["weight"] in (80.0, 70.0)
    assert daily[0]["weight"] == 80.0  # withings, the default-priority winner


def test_garmin_only_falls_back_when_withings_has_no_reading_that_day(session):
    session.add(BodyComp(source="garmin", external_id="g1", ts=NOON, weight_kg=79.0))
    session.commit()

    daily = resolve_daily(session)
    assert daily[0]["weight"] == 79.0
    assert daily[0]["weight_source"] == "garmin"


def test_manual_entry_is_always_the_last_resort(session):
    """Part D.3 — manual stays last even if a user reordered body_comp_priority to put it
    first; it's appended unconditionally in catch/sync/body_comp.py."""
    update_settings(session, {"body_comp_priority": {"weight": ["manual", "withings"]}})
    session.add(BodyComp(source="withings", external_id="w1", ts=NOON, weight_kg=80.0))
    session.add(BodyComp(source="manual", external_id=DAY.isoformat(), ts=NOON, weight_kg=81.0))
    session.commit()

    daily = resolve_daily(session)
    assert daily[0]["weight"] == 80.0
    assert daily[0]["weight_source"] == "withings"


def test_manual_entry_used_when_no_scale_exists_at_all(session):
    session.add(BodyComp(source="manual", external_id=DAY.isoformat(), ts=NOON, weight_kg=81.0))
    session.commit()

    daily = resolve_daily(session)
    assert daily[0]["weight"] == 81.0
    assert daily[0]["weight_source"] == "manual"


def test_nearest_resolved_weight_prefers_closest_day_not_closest_source(session):
    session.add(BodyComp(source="withings", external_id="w1", ts=datetime(2026, 3, 1, 8, tzinfo=timezone.utc), weight_kg=80.0))
    session.add(BodyComp(source="garmin", external_id="g1", ts=datetime(2026, 3, 3, 8, tzinfo=timezone.utc), weight_kg=79.0))
    session.commit()

    # An activity on March 2nd is equally close to both days (1 day each) — `min` with a tie
    # takes the first in `resolve_daily`'s sorted-by-date order, i.e. the earlier (March 1st).
    value = nearest_resolved_weight_kg(session, datetime(2026, 3, 2, 8, tzinfo=timezone.utc))
    assert value == 80.0


def test_post_manual_weight_then_shows_up_in_get_body(client, session):
    _login(client)
    resp = client.post("/api/body/manual", json={"date": "2026-03-05", "weight_kg": 82.5})
    assert resp.status_code == 200

    body = client.get("/api/body").json()
    assert body[0]["weight"] == 82.5
    assert body[0]["weight_source"] == "manual"


def test_post_manual_weight_overwrites_same_day(client, session):
    _login(client)
    client.post("/api/body/manual", json={"date": "2026-03-05", "weight_kg": 82.5})
    client.post("/api/body/manual", json={"date": "2026-03-05", "weight_kg": 83.0})

    body = client.get("/api/body").json()
    assert len(body) == 1
    assert body[0]["weight"] == 83.0
