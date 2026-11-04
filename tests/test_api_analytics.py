from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

import pytest

from catch.core.models import Activity, BodyComp, DailyScore, DailyWellness, Stroke
from conftest import TEST_PASSWORD


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def test_today_with_no_data_yet(client):
    _login(client)
    resp = client.get("/api/today")
    assert resp.status_code == 200
    body = resp.json()
    assert body["recovery"] is None
    assert "recommendation" in body


def test_today_generated_at_is_a_real_utc_timestamp(client):
    # Session 10: the client used to infer "offline/stale" by comparing this endpoint's `date`
    # against its own local date string, which disagrees for hours whenever the browser and the
    # Pi aren't in the same timezone, regardless of connectivity. `generated_at` is a real
    # timestamp the client can use to show actual data age instead.
    _login(client)
    body = client.get("/api/today").json()
    generated_at = datetime.fromisoformat(body["generated_at"])
    assert generated_at.tzinfo is not None
    assert abs((datetime.now(timezone.utc) - generated_at).total_seconds()) < 5


def test_today_reflects_cached_daily_score(client, session):
    today = date.today()
    session.add(DailyWellness(date=today, sleep_seconds=25000, sleep_score=85))
    session.add(
        DailyScore(
            date=today,
            recovery_json='{"value": 80.0, "band": "green", "components": [], "explanation": "x"}',
            strain_json='{"value": 5.0, "band": "light", "components": [], "explanation": "x"}',
            load_json='{"value": 1.0, "band": "optimal", "components": [], "explanation": "x"}',
        )
    )
    session.commit()

    _login(client)
    resp = client.get("/api/today")
    body = resp.json()
    assert body["recovery"]["band"] == "green"
    assert body["sleep_last_night"]["seconds"] == 25000
    assert "clear for a harder session" in body["recommendation"]


def test_today_includes_sleep_strain_target_hrv_and_erg(client, session):
    today = date.today()
    session.add(
        DailyWellness(
            date=today,
            hrv_rmssd=55.0,
            resting_hr=50,
            sleep_seconds=25000,
            sleep_score=85,
            deep_sleep_seconds=4000,
            rem_sleep_seconds=5000,
            steps=9000,
            active_kcal=400,
        )
    )
    session.add(
        DailyScore(
            date=today,
            recovery_json=(
                '{"value": 80.0, "band": "green", "components": '
                '[{"metric": "hrv", "baseline_7d_ln": 4.0, "spread_60d": 0.1, "value": 90}], '
                '"explanation": "x"}'
            ),
            strain_json='{"value": 5.0, "band": "light", "components": [], "explanation": "x"}',
            load_json='{"value": 1.0, "band": "optimal", "components": [], "explanation": "x"}',
        )
    )
    session.add(
        Activity(source="concept2", external_id="c1", type="rower", start=datetime.now(timezone.utc), distance=2000, duration=420.0)
    )
    session.commit()

    _login(client)
    resp = client.get("/api/today")
    body = resp.json()
    assert body["sleep_last_night"]["need_seconds"] == 8 * 3600
    assert body["sleep_last_night"]["deep_seconds"] == 4000
    assert body["strain_target_range"] == [10, 16]  # green band default
    assert body["hrv"]["today"] == 55.0
    assert len(body["hrv"]["sparkline_14d"]) == 1
    assert body["hrv"]["baseline_band"]["baseline"] == pytest.approx(math.exp(4.0))
    assert body["latest_erg"]["external_id"] == "c1"
    assert body["daily_activity"] == {"steps": 9000, "active_kcal": 400}
    assert "raw_json" not in body["latest_erg"]
    assert body["predicted_2k"]["value"] is not None


def test_today_daily_activity_is_none_without_wellness_steps(client, session):
    _login(client)
    resp = client.get("/api/today")
    assert resp.json()["daily_activity"] is None


def test_trends_rejects_unknown_metric(client):
    _login(client)
    resp = client.get("/api/trends", params={"metric": "not_a_real_metric"})
    assert resp.status_code == 400


def test_trends_wellness_metric(client, session):
    day = date(2026, 1, 1)
    session.add(DailyWellness(date=day, resting_hr=48))
    session.commit()

    _login(client)
    resp = client.get("/api/trends", params={"metric": "resting_hr", "from": "2026-01-01", "to": "2026-01-02"})
    assert resp.status_code == 200
    assert resp.json() == [{"date": "2026-01-01", "value": 48}]


def test_erg_results_filters_to_concept2(client, session):
    session.add(Activity(source="garmin", external_id="g1", type="rowing_v2", start=datetime(2026, 1, 1, tzinfo=timezone.utc)))
    session.add(Activity(source="concept2", external_id="c1", type="rower", start=datetime(2026, 1, 1, tzinfo=timezone.utc)))
    session.commit()

    _login(client)
    resp = client.get("/api/erg/results")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["source"] == "concept2"


def test_erg_strokes_returns_404_for_non_concept2_activity(client, session):
    session.add(Activity(source="garmin", external_id="g1", type="rowing_v2"))
    session.commit()

    _login(client)
    resp = client.get("/api/erg/1/strokes")
    assert resp.status_code == 404


def test_erg_strokes_groups_by_interval(client, session):
    activity = Activity(source="concept2", external_id="c1", type="rower")
    session.add(activity)
    session.commit()
    session.add(Stroke(activity_id=activity.id, seq=0, interval_index=0, t=10.0, distance=50.0, watts=300, stroke_rate=30, pace_500m=105.0))
    session.add(Stroke(activity_id=activity.id, seq=1, interval_index=1, t=5.0, distance=20.0, watts=280, stroke_rate=28, pace_500m=110.0))
    session.commit()

    _login(client)
    resp = client.get(f"/api/erg/{activity.id}/strokes")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["strokes"]) == 2
    assert set(body["technique_by_interval"].keys()) == {"0", "1"}
    # Neither stroke has an hr reading -> no per-sample HR to bucket into zones.
    assert body["time_in_zone_by_interval"]["0"] is None
    assert body["time_in_zone_by_interval"]["1"] is None


def test_erg_strokes_time_in_zone_with_hr(client, session):
    from catch.core.settings_store import update_settings

    update_settings(session, {"max_hr": 190})
    activity = Activity(source="concept2", external_id="c2", type="rower")
    session.add(activity)
    session.commit()
    session.add(Stroke(activity_id=activity.id, seq=0, interval_index=0, t=0.0, hr=150))
    session.add(Stroke(activity_id=activity.id, seq=1, interval_index=0, t=60.0, hr=150))
    session.commit()

    _login(client)
    resp = client.get(f"/api/erg/{activity.id}/strokes")
    totals = resp.json()["time_in_zone_by_interval"]["0"]
    # 150/190 = 78.9% -> UT1; first sample duration=t itself (0), second=60-0=60.
    assert totals["UT1"] == 60.0


def test_erg_results_includes_nearest_weight(client, session):
    when = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)
    session.add(BodyComp(source="withings", external_id="b1", ts=when - timedelta(days=1), weight_kg=80.0))
    session.add(
        Activity(source="concept2", external_id="c1", type="rower", start=when, avg_power=320.0, duration=1200.0)
    )
    session.commit()

    _login(client)
    resp = client.get("/api/erg/results")
    row = resp.json()[0]
    assert row["weight_kg"] == 80.0
    assert row["w_per_kg"] == 4.0


def test_predict_2k_excludes_interval_workouts_and_old_pieces(client, session):
    session.add(
        Activity(
            source="concept2",
            external_id="interval1",
            type="rower",
            workout_type="FixedDistanceInterval",
            start=datetime.now(timezone.utc) - timedelta(days=5),
            distance=2000,
            duration=600.0,
        )
    )
    session.add(
        Activity(
            source="concept2",
            external_id="old1",
            type="rower",
            workout_type="JustRow",
            start=datetime.now(timezone.utc) - timedelta(days=400),
            distance=5000,
            duration=1100.0,
        )
    )
    session.commit()

    _login(client)
    resp = client.get("/api/predict/2k")
    assert resp.json()["band"] == "insufficient_data"


def test_predict_2k_with_no_history(client):
    _login(client)
    resp = client.get("/api/predict/2k")
    assert resp.status_code == 200
    assert resp.json()["band"] == "insufficient_data"


def test_predict_2k_uses_best_piece_per_bucket(client, session):
    session.add(
        Activity(
            source="concept2",
            external_id="c1",
            type="rower",
            start=datetime.now(timezone.utc) - timedelta(days=10),
            distance=6000,
            duration=660.0,  # 110.0 s/500m
        )
    )
    session.commit()

    _login(client)
    resp = client.get("/api/predict/2k")
    body = resp.json()
    assert body["value"] is not None
    assert body["components"][0]["distance_m"] == 6000


def test_get_settings_returns_defaults(client):
    _login(client)
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    assert resp.json()["recovery_green"] == 67


def test_put_settings_updates_and_rejects_unknown_keys(client):
    _login(client)
    resp = client.put("/api/settings", json={"max_hr": 188})
    assert resp.status_code == 200
    assert resp.json()["max_hr"] == 188

    resp2 = client.get("/api/settings")
    assert resp2.json()["max_hr"] == 188

    bad = client.put("/api/settings", json={"not_a_real_setting": 1})
    assert bad.status_code == 422


def test_settings_require_auth(client):
    resp = client.get("/api/settings")
    assert resp.status_code == 401


def test_put_settings_max_hr_change_updates_an_existing_activitys_cached_zones(client, session):
    """Regression: PUT /api/settings used to leave every already-resolved canonical's cached
    zones/strain untouched — only orphaned/blank/newly-merged canonicals got re-resolved."""
    from catch.core.models import CanonicalActivity
    from catch.sync.matching import run_matching
    from catch.sync.samples import store_samples

    _login(client)
    client.put("/api/settings", json={"max_hr": 190})
    session.add(DailyWellness(date=date(2026, 6, 1), resting_hr=50))
    activity = Activity(
        source="garmin", external_id="put1", type="indoor_rowing",
        start=datetime(2026, 6, 1, 7, tzinfo=timezone.utc), duration=1800.0,
    )
    session.add(activity)
    session.commit()
    # ±1 bpm oscillation, not a flat 150.0 for 1800s straight — drop_dropouts (Part E.2)
    # treats a 30s+ run of one exact value as a stuck sensor, which a real HR trace never
    # does but a naive constant-value test fixture would, wiping the samples this test needs.
    hr = [150.0 + (i % 3 - 1) for i in range(1800)]
    store_samples(session, activity.id, start=activity.start, hr=hr, power=[None] * 1800, cadence=[20.0] * 1800)
    run_matching(session)
    session.refresh(activity)
    zones_before = session.get(CanonicalActivity, activity.canonical_id).zones_json

    resp = client.put("/api/settings", json={"max_hr": 160})
    assert resp.status_code == 200

    zones_after = session.get(CanonicalActivity, activity.canonical_id).zones_json
    assert zones_after != zones_before


def test_put_settings_skips_the_full_resolve_when_nothing_zone_or_strain_affecting_changed(client, monkeypatch):
    """A Pi-3 cost check (advisor review): resolve_all_canonicals walks every canonical
    (~6.5ms each with real FIT samples, ~3s over this account's real 451-activity history on
    this laptop — assuming the Pi 3's single ARM core is 10-20x slower single-threaded, not
    measured directly, call it ~30-60s there) and must not run for a settings save that can't
    possibly change any canonical's cached fields.

    The check compares before/after *values*, not which keys are present in the incoming
    patch — web/src/pages/Settings.tsx's one Save button always PUTs the entire form (every
    field, every time), so this test sends a full-form-shaped payload too, matching what the
    real UI actually does. A key-presence check would have looked correct against a
    hand-crafted partial patch (the first version of this test) while doing nothing for any
    real save."""
    called = {"n": 0}
    monkeypatch.setattr(
        "catch.api.routes_analytics._resolve_all_and_recompute_in_background",
        lambda engine: called.__setitem__("n", called["n"] + 1),
    )
    _login(client)
    current = client.get("/api/settings").json()

    # A full-form resend where only an unrelated field changes — the real shape of every
    # Settings-page save.
    full_form_unrelated_change = {**current, "body_comp_priority": {**current["body_comp_priority"], "weight": ["garmin", "withings"]}}
    resp = client.put("/api/settings", json=full_form_unrelated_change)
    assert resp.status_code == 200
    assert called["n"] == 0

    full_form_with_max_hr_change = {**current, "max_hr": (current.get("max_hr") or 180) + 5}
    resp = client.put("/api/settings", json=full_form_with_max_hr_change)
    assert resp.status_code == 200
    assert called["n"] == 1
