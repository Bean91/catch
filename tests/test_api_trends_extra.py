from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from catch.core.models import Activity, BodyComp, DailyScore, OAuthToken, Stroke
from catch.sync.matching import run_matching
from catch.sync.samples import store_samples_from_strokes
from conftest import TEST_PASSWORD


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def test_trends_weight(client, session):
    session.add(BodyComp(source="withings", external_id="b1", ts=datetime(2026, 1, 1, tzinfo=timezone.utc), weight_kg=80.0))
    session.add(BodyComp(source="withings", external_id="b2", ts=datetime(2026, 1, 2, tzinfo=timezone.utc), weight_kg=79.5))
    session.commit()

    _login(client)
    resp = client.get("/api/trends", params={"metric": "weight", "from": "2026-01-01", "to": "2026-01-31"})
    assert resp.status_code == 200
    body = resp.json()
    assert [p["value"] for p in body] == [80.0, 79.5]
    assert body[0]["smoothed"] == 80.0  # day 1's trailing window only has day 1 itself
    assert body[1]["smoothed"] == 79.75  # day 2's window has both readings -> median of 2


def test_trends_w_per_kg(client, session):
    session.add(BodyComp(source="withings", external_id="b1", ts=datetime(2026, 1, 1, tzinfo=timezone.utc), weight_kg=80.0))
    session.add(
        Activity(source="concept2", external_id="c1", type="rower", start=datetime(2026, 1, 1, 12, tzinfo=timezone.utc), avg_power=320.0)
    )
    session.commit()

    _login(client)
    resp = client.get("/api/trends", params={"metric": "w_per_kg"})
    body = resp.json()
    assert body[0]["value"] == 4.0


def test_trends_predicted_2k_per_piece(client, session):
    session.add(
        Activity(
            source="concept2",
            external_id="c1",
            type="rower",
            workout_type="JustRow",
            start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            distance=2000,
            duration=420.0,
        )
    )
    session.commit()

    _login(client)
    resp = client.get("/api/trends", params={"metric": "predicted_2k"})
    body = resp.json()
    assert len(body) == 1
    assert body[0]["value"] == 420.0  # the piece itself is already exactly 2k


def test_trends_load_acr_includes_components(client, session):
    day = date(2026, 1, 1)
    session.add(
        DailyScore(
            date=day,
            load_json=json.dumps(
                {"value": 1.1, "band": "optimal", "components": [{"acute_7d": 60.0, "chronic_42d": 54.5, "form": -5.5}], "explanation": "x"}
            ),
        )
    )
    session.commit()

    _login(client)
    resp = client.get("/api/trends", params={"metric": "load_acr"})
    point = resp.json()[0]
    assert point["value"] == 1.1
    assert point["acute_7d"] == 60.0
    assert point["form"] == -5.5


def test_trends_volume_estimates_from_avg_hr_without_strokes(client, session):
    from catch.core.settings_store import update_settings

    update_settings(session, {"max_hr": 190})
    today = date.today()
    this_monday = today - timedelta(days=today.weekday())
    session.add(
        Activity(
            source="garmin",
            external_id="g1",
            type="strength_training",
            start=datetime.combine(this_monday, datetime.min.time()).astimezone(timezone.utc),
            avg_hr=150,
            duration=3600.0,
        )
    )
    session.commit()
    run_matching(session)

    _login(client)
    resp = client.get("/api/trends/volume", params={"weeks": 2})
    weeks = resp.json()
    this_week = next(w for w in weeks if w["week_start"] == this_monday.isoformat())
    assert this_week["estimated"] is True
    assert this_week["zones"]["UT1"] == 3600.0


def test_trends_volume_uses_real_stroke_zones_when_available(client, session):
    from catch.core.settings_store import update_settings

    update_settings(session, {"max_hr": 190})
    today = date.today()
    this_monday = today - timedelta(days=today.weekday())
    activity = Activity(
        source="concept2",
        external_id="c1",
        type="rower",
        start=datetime.combine(this_monday, datetime.min.time()).astimezone(timezone.utc),
    )
    session.add(activity)
    session.commit()
    session.add(Stroke(activity_id=activity.id, seq=0, interval_index=0, t=0.0, hr=150))
    session.add(Stroke(activity_id=activity.id, seq=1, interval_index=0, t=60.0, hr=150))
    session.commit()
    # Mirrors what catch/sync/concept2_client.py's real sync does with the same stroke data
    # (Part E — per-sample zones cached on the canonical), so this test exercises the same
    # path a real sync would rather than only inserting raw Stroke rows.
    store_samples_from_strokes(
        session,
        activity.id,
        [
            {"seq": 0, "interval_index": 0, "t": 0.0, "hr": 150},
            {"seq": 1, "interval_index": 0, "t": 60.0, "hr": 150},
        ],
    )
    run_matching(session)

    _login(client)
    resp = client.get("/api/trends/volume", params={"weeks": 1})
    week = resp.json()[0]
    assert week["estimated"] is False
    assert week["zones"]["UT1"] == 61.0


def test_pbs_distance_and_time_buckets(client, session):
    session.add(
        Activity(
            source="concept2",
            external_id="c1",
            type="rower",
            workout_type="JustRow",
            start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            distance=2000,
            duration=420.0,
        )
    )
    session.add(
        Activity(
            source="concept2",
            external_id="c2",
            type="rower",
            workout_type="FixedTimeSplits",
            start=datetime(2026, 1, 2, tzinfo=timezone.utc),
            distance=8200,
            duration=1800.0,
        )
    )
    session.commit()

    _login(client)
    resp = client.get("/api/pbs")
    body = resp.json()
    assert body["2000m"]["duration_s"] == 420.0
    assert body["30min"]["distance_m"] == 8200
    assert body["500m"] is None


def test_sync_status_includes_token_expiry(client, session):
    session.add(OAuthToken(source="garmin", access_token_enc="x", expires_at=datetime(2026, 2, 1, tzinfo=timezone.utc)))
    session.commit()

    _login(client)
    resp = client.get("/api/sync/status")
    by_source = {row["source"]: row for row in resp.json()}
    assert by_source["garmin"]["token_expires_at"] is not None
    assert by_source["concept2"]["token_expires_at"] is None
