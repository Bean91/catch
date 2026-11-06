from __future__ import annotations

from datetime import date, timedelta

import pytest

from conftest import TEST_PASSWORD

from catch.core.models import DailyWellness
from catch.sync.scoring import recompute_scores

NORMAL_RHR, NORMAL_HRV, NORMAL_RESP = 50.0, 55.0, 14.0


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def _seed_baseline(session, through: date, n: int = 20):
    for i in range(1, n + 1):
        session.add(
            DailyWellness(
                date=through - timedelta(days=i),
                resting_hr=NORMAL_RHR,
                hrv_rmssd=NORMAL_HRV,
                sleep_seconds=8 * 3600,
                sleep_respiration_avg=NORMAL_RESP,
            )
        )
    session.commit()


def _seed_sick_day(session, day: date):
    session.add(
        DailyWellness(date=day, resting_hr=NORMAL_RHR + 8, hrv_rmssd=NORMAL_HRV * 0.85, sleep_seconds=7 * 3600, sleep_respiration_avg=NORMAL_RESP + 3)
    )
    session.commit()


def test_two_consecutive_illness_nights_reach_likely_and_show_on_today(client, session):
    today = date.today()
    _seed_baseline(session, today - timedelta(days=1))
    _seed_sick_day(session, today - timedelta(days=1))
    _seed_sick_day(session, today)
    recompute_scores(session)

    _login(client)
    resp = client.get("/api/today")
    illness = resp.json()["illness"]
    assert illness["level"] == "likely"
    assert "sick" not in illness["explanation"].lower()


def test_recommendation_caps_intensity_when_likely(client, session):
    today = date.today()
    _seed_baseline(session, today - timedelta(days=1))
    _seed_sick_day(session, today - timedelta(days=1))
    _seed_sick_day(session, today)
    recompute_scores(session)

    _login(client)
    resp = client.get("/api/today")
    recommendation = resp.json()["recommendation"]
    assert "no tr" in recommendation.lower() or "no tests" in recommendation.lower()


def test_dismiss_requires_a_known_reason(client, session):
    today = date.today()
    _seed_baseline(session, today - timedelta(days=1))
    _seed_sick_day(session, today - timedelta(days=1))
    _seed_sick_day(session, today)
    recompute_scores(session)

    _login(client)
    bad = client.post(f"/api/illness/{today.isoformat()}/dismiss", json={"reason": "homework"})
    assert bad.status_code == 422

    good = client.post(f"/api/illness/{today.isoformat()}/dismiss", json={"reason": "alcohol"})
    assert good.status_code == 200
    assert good.json()["dismissed"] is True
    assert good.json()["dismiss_reason"] == "alcohol"


def test_dismissal_excludes_that_day_from_future_baselines(client, session):
    import json as json_module

    from catch.core.models import DailyScore

    today = date.today()
    spike_day = today - timedelta(days=10)
    for i in range(25):
        day = today - timedelta(days=i)
        rhr = 90.0 if day == spike_day else NORMAL_RHR
        session.add(DailyWellness(date=day, resting_hr=rhr, hrv_rmssd=NORMAL_HRV, sleep_seconds=8 * 3600, sleep_respiration_avg=NORMAL_RESP))
    session.commit()
    recompute_scores(session)

    _login(client)
    client.post(f"/api/illness/{spike_day.isoformat()}/dismiss", json={"reason": "alcohol"})
    recompute_scores(session)

    row = session.get(DailyScore, today)
    illness = json_module.loads(row.illness_json)
    # Without the exclusion, the spike would pull today's resting-HR baseline above 50.0.
    assert illness["signals"]["resting_hr"]["baseline"] == pytest.approx(NORMAL_RHR)


def test_recompute_never_overwrites_an_existing_ack(client, session):
    from catch.core.models import IllnessAck

    today = date.today()
    _seed_baseline(session, today - timedelta(days=1))
    _seed_sick_day(session, today - timedelta(days=1))
    _seed_sick_day(session, today)
    recompute_scores(session)

    _login(client)
    client.post(f"/api/illness/{today.isoformat()}/mark", json={"correct": True})
    recompute_scores(session)  # a later sync must not clobber the backtest mark

    ack = session.get(IllnessAck, today)
    assert ack.backtest_mark == "correct"


def test_backtest_lists_flagged_nights_and_computes_precision(client, session):
    today = date.today()
    _seed_baseline(session, today - timedelta(days=1))
    _seed_sick_day(session, today - timedelta(days=1))
    _seed_sick_day(session, today)
    recompute_scores(session)

    _login(client)
    client.post(f"/api/illness/{today.isoformat()}/mark", json={"correct": True})
    resp = client.get("/api/illness/backtest")
    body = resp.json()
    assert body["marked_count"] == 1
    assert body["precision"] == 1.0
    assert any(f["date"] == today.isoformat() for f in body["flagged"])
