from __future__ import annotations

from datetime import date, timedelta

from sqlmodel import select

from conftest import TEST_PASSWORD


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def test_checkins_require_auth(client):
    resp = client.get("/api/checkins/today")
    assert resp.status_code == 401


def test_today_checkin_not_completed_before_any_post(client):
    _login(client)
    resp = client.get("/api/checkins/today")
    assert resp.status_code == 200
    assert resp.json()["completed"] is False
    assert resp.json()["checkin"] is None


def test_post_checkin_creates_and_is_readable_as_today(client):
    _login(client)
    resp = client.post(
        "/api/checkins",
        json={"soreness": 3, "stress": 2, "mood": 4, "sleep_quality": 4},
    )
    assert resp.status_code == 200
    assert resp.json()["soreness"] == 3

    today_resp = client.get("/api/checkins/today")
    assert today_resp.json()["completed"] is True
    assert today_resp.json()["checkin"]["mood"] == 4


def test_post_checkin_same_day_upserts_editable_later_that_day(client, session):
    from catch.core.models import CheckIn

    _login(client)
    client.post("/api/checkins", json={"soreness": 2, "mood": 3})
    client.post("/api/checkins", json={"soreness": 4, "mood": 5})

    assert len(session.exec(select(CheckIn)).all()) == 1
    resp = client.get("/api/checkins/today")
    assert resp.json()["checkin"]["soreness"] == 4
    assert resp.json()["checkin"]["mood"] == 5


def test_post_checkin_rejects_out_of_range_slider(client):
    _login(client)
    resp = client.post("/api/checkins", json={"soreness": 6})
    assert resp.status_code == 422


def test_niggle_severity_requires_niggle_area(client):
    _login(client)
    resp = client.post("/api/checkins", json={"niggle_severity": 2})
    assert resp.status_code == 422


def test_niggle_never_changes_recovery_but_shows_as_a_flag(client, session):
    from catch.core.models import DailyWellness
    from catch.sync.scoring import recompute_scores

    today = date.today()
    for i in range(10):
        session.add(DailyWellness(date=today - timedelta(days=i + 1), resting_hr=50, hrv_rmssd=55.0, sleep_seconds=8 * 3600))
    session.add(DailyWellness(date=today, resting_hr=50, hrv_rmssd=55.0, sleep_seconds=8 * 3600))
    session.commit()
    recompute_scores(session)

    _login(client)
    before = client.get("/api/today").json()["recovery"]["value"]

    client.post("/api/checkins", json={"niggle_area": "left knee", "niggle_severity": 2})
    after_resp = client.get("/api/today")
    after = after_resp.json()
    assert after["recovery"]["value"] == before
    assert after["checkin"]["niggle_area"] == "left knee"
    assert after["checkin"]["niggle_flag"] is False  # only 1 day so far


def test_niggle_flag_set_after_min_days(client, session):
    from catch.core.models import CheckIn

    today = date.today()
    for i in range(3):
        session.add(CheckIn(date=today - timedelta(days=i), niggle_area="left knee", niggle_severity=1))
    session.commit()

    _login(client)
    resp = client.get("/api/today")
    checkin = resp.json()["checkin"]
    assert checkin["niggle_streak_days"] == 3
    assert checkin["niggle_flag"] is True


def test_checkin_sliders_appear_in_trends(client):
    _login(client)
    client.post("/api/checkins", json={"soreness": 3})
    resp = client.get("/api/trends", params={"metric": "checkin_soreness"})
    assert resp.status_code == 200
    points = resp.json()
    assert points[-1]["value"] == 3
