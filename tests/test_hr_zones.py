"""Session 33, Part B: heart-rate-reserve zones through the real pipeline — the basis each workout's zones use, what triggers a
recalculation, what stays untouched (raw samples, strain), and how the values reach the screens and the coach."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlmodel import select

from catch.coach import tools
from catch.core.models import Activity, ActivitySamples, CanonicalActivity, DailyWellness
from catch.core.settings_store import get_settings, update_settings
from catch.sync import wellness_readings
from catch.sync.canonical import resolve_all_canonicals, resolve_canonical
from catch.sync.matching import run_matching
from catch.sync.samples import store_samples
from conftest import TEST_PASSWORD

T0 = datetime(2026, 7, 15, 7, tzinfo=timezone.utc)
DAY = T0.date()


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def _rhr_history(session, value: float, days: int = 14, end: date = DAY) -> None:
    for i in range(1, days + 1):
        d = end - timedelta(days=i)
        row = session.get(DailyWellness, ("owner", d)) or session.exec(select(DailyWellness).where(DailyWellness.date == d)).first()
        if row is None:
            row = DailyWellness(date=d)
        row.resting_hr = value
        session.add(row)
    session.commit()


def _workout(session, ext: str, start: datetime = T0, hr: float = 140.0, n: int = 1200) -> CanonicalActivity:
    a = Activity(source="garmin", external_id=ext, type="indoor_rowing", start=start, duration=float(n), sport_family="rowing")
    session.add(a)
    session.commit()
    # ±1 bpm jitter (samples are stored as whole bpm): a perfectly flat line is (rightly) treated as a stuck sensor and dropped.
    store_samples(session, a.id, start=start, hr=[hr + (i % 3 - 1) for i in range(n)], power=[None] * n, cadence=[20.0] * n)
    run_matching(session)
    session.refresh(a)
    return session.get(CanonicalActivity, a.canonical_id)


def _zones(c: CanonicalActivity) -> dict:
    return json.loads(c.zones_json)


def test_a_workout_uses_the_median_resting_hr_of_the_14_days_before_it(session):
    update_settings(session, {"max_hr": 190})
    _rhr_history(session, 50)
    c = _workout(session, "w1", hr=140.0)
    z = _zones(c)
    assert z["basis"]["method"] == "hrr" and z["basis"]["resting_hr"] == 50 and z["basis"]["rhr_source"] == "measured"
    # 140 bpm: UT1 starts at 50 + 140 * .67 = 143.8, so this is UT2 under HRR — it was UT1 (73.7 % of max) under % of max.
    assert z["hr"]["UT2"] == pytest.approx(1200) and z["hr"]["UT1"] == 0


def test_without_resting_hr_the_zones_use_percent_of_max_and_say_why(session):
    update_settings(session, {"max_hr": 190})
    c = _workout(session, "w1", hr=140.0)
    z = _zones(c)
    assert z["basis"]["method"] == "max_pct" and "No resting heart rate" in z["basis"]["reason"]
    assert z["hr"]["UT1"] == pytest.approx(1200)


def test_without_max_hr_there_are_no_hr_zones(session):
    _rhr_history(session, 50)
    c = _workout(session, "w1")
    z = _zones(c)
    assert z["basis"]["method"] == "none" and not any((z["hr"] or {}).values())


def test_changing_the_resting_hr_setting_recalculates_history_and_keeps_raw_samples(client, session):
    update_settings(session, {"max_hr": 190})
    _rhr_history(session, 50)
    c = _workout(session, "w1", hr=148.0)
    assert _zones(c)["hr"]["UT1"] == pytest.approx(1200)  # UT1 is 143.8–155 at resting 50
    raw_before = session.get(ActivitySamples, session.exec(select(Activity.id)).first()).hr_blob
    strain_before = c.strain_trimp

    _login(client)
    assert client.put("/api/settings", json={"resting_hr": 70}).status_code == 200  # the re-resolve runs as a background task
    session.expire_all()
    after = session.get(CanonicalActivity, c.id)
    z = _zones(after)
    assert z["basis"]["rhr_source"] == "setting" and z["basis"]["resting_hr"] == 70
    assert z["hr"]["UT2"] == pytest.approx(1200)  # UT1 now starts at 70 + 120 * .67 = 150.4
    assert session.get(ActivitySamples, session.exec(select(Activity.id)).first()).hr_blob == raw_before
    assert after.strain_trimp == pytest.approx(strain_before)  # strain keeps the day's own resting HR (unchanged model)


def test_changing_max_hr_or_method_recalculates(client, session):
    update_settings(session, {"max_hr": 190})
    _rhr_history(session, 50)
    c = _workout(session, "w1", hr=160.0)
    _login(client)
    client.put("/api/settings", json={"max_hr": 175})
    session.expire_all()
    assert _zones(session.get(CanonicalActivity, c.id))["basis"]["max_hr"] == 175
    client.put("/api/settings", json={"hr_zone_method": "max_pct"})
    session.expire_all()
    assert _zones(session.get(CanonicalActivity, c.id))["basis"]["method"] == "max_pct"


@pytest.mark.parametrize(
    "patch",
    [{"max_hr": 90}, {"max_hr": 260}, {"resting_hr": 10}, {"resting_hr": "fast"}, {"hr_zone_method": "lthr"},
     {"zones": {"hrr_pct": {"UT2": 70, "UT1": 60, "AT": 75, "TR": 85, "AN": 95}}}, {"zones": {"hrr_pct": {"UT2": 59, "UT1": 67, "AT": 75, "TR": 85, "AN": 120}}}],
)
def test_invalid_heart_rate_settings_are_refused(client, session, patch):
    _login(client)
    assert client.put("/api/settings", json=patch).status_code == 422


def test_resting_must_sit_well_below_max(client, session):
    _login(client)
    assert client.put("/api/settings", json={"max_hr": 150}).status_code == 200
    resp = client.put("/api/settings", json={"resting_hr": 120})
    assert resp.status_code == 422


def test_a_new_resting_hr_reading_rezones_only_the_next_two_weeks(session):
    update_settings(session, {"max_hr": 190})
    _rhr_history(session, 50, days=60, end=DAY + timedelta(days=30))
    near = _workout(session, "near", start=T0 + timedelta(days=3))
    far = _workout(session, "far", start=T0 + timedelta(days=25))
    stamp_near, stamp_far = near.updated_at, far.updated_at

    wellness_readings.record_reading(session, DAY, "garmin", "resting_hr", 70)
    wellness_readings.resolve_days(session, [DAY])
    session.expire_all()
    assert session.get(CanonicalActivity, near.id).updated_at != stamp_near
    assert session.get(CanonicalActivity, far.id).updated_at == stamp_far


def test_maintenance_re_resolves_zones_cached_before_hrr(session, monkeypatch):
    from catch.sync import scoring

    update_settings(session, {"max_hr": 190})
    _rhr_history(session, 50)
    c = _workout(session, "w1")
    old = _zones(c)
    old.pop("basis")
    c.zones_json = json.dumps(old)
    session.add(c)
    session.commit()
    assert scoring.zones_model_is_current(session) is False
    resolve_all_canonicals(session)
    assert scoring.zones_model_is_current(session) is True


def test_workout_detail_shows_the_basis_its_zones_used_not_todays_settings(client, session):
    update_settings(session, {"max_hr": 190})
    _rhr_history(session, 50)
    c = _workout(session, "w1")
    # Change the setting without re-resolving: the detail must still describe the cached zones it shows.
    update_settings(session, {"max_hr": 170})
    _login(client)
    detail = client.get(f"/api/activities/{c.id}").json()
    assert detail["zones_config"]["hr_basis"]["max_hr"] == 190 and detail["zones_config"]["hr_basis"]["resting_hr"] == 50
    zones = {z["zone"]: z for z in detail["zones_config"]["zones"]}
    assert zones["UT2"]["hr_lo"] == pytest.approx(132.6)
    samples = client.get(f"/api/activities/{c.id}/samples").json()
    assert samples["zones_config"]["hr_basis"] == detail["zones_config"]["hr_basis"]


def test_zones_endpoint_and_the_observed_max_suggestion(client, session):
    update_settings(session, {"max_hr": 190})
    _rhr_history(session, 52, end=date.today())
    a = Activity(source="garmin", external_id="peak", type="indoor_rowing", start=datetime.now(timezone.utc) - timedelta(days=3), duration=600.0, avg_hr=150, max_hr=187)
    session.add(a)
    session.commit()
    run_matching(session)
    _login(client)
    body = client.get("/api/zones").json()
    assert body["basis"]["method"] == "hrr" and body["basis"]["resting_hr"] == 52
    assert body["observed_max_hr"]["value"] == 187
    assert get_settings(session)["max_hr"] == 190  # the suggestion is never applied on its own
    assert [z["zone"] for z in body["zones"]] == ["UT2", "UT1", "AT", "TR", "AN"]


def test_coach_get_zones_reports_the_basis(session):
    update_settings(session, {"max_hr": 190})
    _rhr_history(session, 50, end=date.today())
    out = tools.call_tool(session, "get_zones", {})
    assert out["hr_basis"]["method"] == "hrr" and out["hr_basis"]["resting_hr"] == 50


@pytest.mark.real_ai_sharing
def test_resting_hr_is_not_shared_with_the_ai_when_wellness_is_off(session):
    from catch.coach import ai_sharing

    update_settings(session, {"max_hr": 190})
    _rhr_history(session, 50, end=date.today())
    ai_sharing.update(session, acknowledge=True, categories={"workouts": True, "wellness": False})
    raw = tools._get_zones(session, {}, {})
    trimmed = ai_sharing.limit_result(session, "get_zones", raw)
    assert "resting_hr" not in json.dumps(trimmed) and "rhr_source" not in json.dumps(trimmed)
    assert trimmed["zones"][0]["hr_lo"] is not None  # the training targets themselves still go
    ai_sharing.update(session, acknowledge=True, categories={"workouts": True, "wellness": True})
    assert "resting_hr" in json.dumps(ai_sharing.limit_result(session, "get_zones", raw))


def test_resolve_is_idempotent(session):
    update_settings(session, {"max_hr": 190})
    _rhr_history(session, 50)
    c = _workout(session, "w1")
    first = c.zones_json
    resolve_canonical(session, c.id)
    assert session.get(CanonicalActivity, c.id).zones_json == first
