from __future__ import annotations

from datetime import datetime, timezone

from catch.core.models import Activity, Stroke
from catch.sync.matching import run_matching
from catch.sync.samples import store_samples, store_samples_from_strokes
from conftest import TEST_PASSWORD


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def test_no_heart_rate_data_state(client, session):
    activity = Activity(source="garmin", external_id="g1", type="strength_training", start=datetime.now(timezone.utc), duration=600.0)
    session.add(activity)
    session.commit()
    run_matching(session)
    session.refresh(activity)

    _login(client)
    resp = client.get(f"/api/activities/{activity.canonical_id}/samples")
    assert resp.status_code == 200
    assert resp.json()["has_data"] is False


def test_no_samples_row_at_all(client, session):
    activity = Activity(source="garmin", external_id="g2", type="strength_training", start=datetime.now(timezone.utc), duration=600.0)
    session.add(activity)
    session.commit()
    run_matching(session)
    session.refresh(activity)

    _login(client)
    resp = client.get(f"/api/activities/{activity.canonical_id}/samples")
    assert resp.json() == {"has_data": False, "reason": "no per-sample data for this activity"}


def test_real_hr_samples_downsample_and_report_summary_chips(client, session):
    from catch.core.settings_store import update_settings

    update_settings(session, {"max_hr": 190})
    activity = Activity(source="garmin", external_id="g3", type="indoor_rowing", start=datetime.now(timezone.utc), duration=1800.0)
    session.add(activity)
    session.commit()

    hr = [120.0 + (i % 40) for i in range(1800)]  # a wandering HR, never None
    store_samples(session, activity.id, start=activity.start, hr=hr, power=[None] * 1800, cadence=[20.0] * 1800)
    run_matching(session)
    session.refresh(activity)

    _login(client)
    resp = client.get(f"/api/activities/{activity.canonical_id}/samples", params={"points": 100})
    body = resp.json()
    assert body["has_data"] is True
    assert body["returned_count"] <= 100
    assert body["max_hr_observed"] == 159.0
    assert body["min_hr_observed"] == 120.0
    assert body["points"][0]["elapsed_s"] == 0
    assert body["points"][-1]["elapsed_s"] == 1799


def test_auto_trimmed_tail_excluded_from_summary_chips(client, session):
    from catch.core.settings_store import update_settings

    update_settings(session, {"max_hr": 190})
    activity = Activity(source="garmin", external_id="g4", type="indoor_rowing", start=datetime.now(timezone.utc), duration=1200.0)
    session.add(activity)
    session.commit()

    # 600s of real rowing (hr=150, cadence=24), then a 300s idle tail someone forgot to stop
    # the watch during (hr settles near resting, cadence=0).
    hr = [150.0] * 600 + [70.0] * 300
    cadence = [24.0] * 600 + [0.0] * 300
    store_samples(session, activity.id, start=activity.start, hr=hr, power=[None] * 900, cadence=cadence)
    run_matching(session)
    session.refresh(activity)

    _login(client)
    resp = client.get(f"/api/activities/{activity.canonical_id}/samples")
    body = resp.json()
    assert body["trimmed_tail_s"] == 300.0
    assert body["usable_n_samples"] == 600
    assert body["max_hr_observed"] == 150.0  # the idle-tail's lower HR never pulls this down
    assert body["min_hr_observed"] == 150.0


def test_start_end_window_gives_full_resolution_within_a_zoomed_range(client, session):
    from catch.core.settings_store import update_settings

    update_settings(session, {"max_hr": 190})
    activity = Activity(source="garmin", external_id="g5", type="indoor_rowing", start=datetime.now(timezone.utc), duration=1800.0)
    session.add(activity)
    session.commit()

    hr = [120.0 + (i % 40) for i in range(1800)]
    store_samples(session, activity.id, start=activity.start, hr=hr, power=[None] * 1800, cadence=[20.0] * 1800)
    run_matching(session)
    session.refresh(activity)

    _login(client)
    resp = client.get(
        f"/api/activities/{activity.canonical_id}/samples", params={"points": 5000, "start_s": 100, "end_s": 200}
    )
    body = resp.json()
    assert body["raw_count"] == 100
    assert body["points"][0]["elapsed_s"] == 100
    assert body["points"][-1]["elapsed_s"] == 199
    # Summary chips still reflect the whole session, not just the zoomed window.
    assert body["max_hr_observed"] == 159.0


def test_concept2_laps_derived_from_stroke_intervals(client, session):
    activity = Activity(source="concept2", external_id="c1", type="rower", start=datetime.now(timezone.utc), duration=120.0)
    session.add(activity)
    session.commit()
    strokes = [
        {"seq": 0, "interval_index": 0, "t": 0.0, "hr": 140},
        {"seq": 1, "interval_index": 0, "t": 60.0, "hr": 150},
        {"seq": 2, "interval_index": 1, "t": 0.0, "hr": 100},
        {"seq": 3, "interval_index": 1, "t": 60.0, "hr": 110},
    ]
    for s in strokes:
        session.add(Stroke(activity_id=activity.id, **s))
    session.commit()
    store_samples_from_strokes(session, activity.id, strokes)
    run_matching(session)
    session.refresh(activity)

    _login(client)
    resp = client.get(f"/api/activities/{activity.canonical_id}/samples")
    body = resp.json()
    assert body["has_data"] is True
    assert len(body["laps"]) == 2
    assert body["laps"][0]["offset_s"] == 0.0
    assert body["laps"][1]["offset_s"] == 60.0
