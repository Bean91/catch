"""Session 32: per-record time zones end to end (catch/core/localtime.py and its callers). Known zones: New York, Paris, Tokyo."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlmodel import Session, select

from catch.analytics import localtime as lt
from catch.core import localtime, tenant
from catch.core.models import Activity, BodyComp, CanonicalActivity, DailyScore, DailyWellness, FoodLog, Food, UserZonePeriod
from catch.core.settings_store import update_settings
from catch.sync import scoring
from catch.sync.matching import run_matching

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]


def garmin(session, ext, start_utc, local_offset_h, **kw):
    local = start_utc + timedelta(hours=local_offset_h)
    raw = {"startTimeGMT": start_utc.strftime("%Y-%m-%d %H:%M:%S"), "startTimeLocal": local.strftime("%Y-%m-%d %H:%M:%S")}
    a = Activity(source="garmin", external_id=ext, type="indoor_rowing", start=start_utc, duration=kw.pop("duration", 3600.0),
                 avg_hr=kw.pop("avg_hr", 140), raw_json=json.dumps(raw), sport_family="rowing", **kw)
    session.add(a)
    session.commit()
    return a


# -- Fallbacks -----------------------------------------------------------------------------------------------------------------


def test_an_account_with_no_zone_uses_the_pi_host_zone_on_personal_and_utc_on_public(session, monkeypatch):
    assert lt.is_valid_iana(localtime.host_zone_name()) or localtime.host_zone_name() == "UTC"
    assert localtime.current_zone_name(session) == localtime.host_zone_name()
    monkeypatch.setattr(tenant, "is_public", lambda: True)
    localtime.invalidate(session)
    assert localtime.current_zone_name(session) == "UTC"


def test_home_zone_is_validated_and_never_an_offset(session):
    with pytest.raises(ValueError):
        localtime.set_preferences(session, home="+05:00")
    with pytest.raises(ValueError):
        localtime.set_preferences(session, home="Mars/Olympus")
    assert localtime.set_preferences(session, home="Asia/Tokyo")["timezone"] == "Asia/Tokyo"


# -- Stamping ------------------------------------------------------------------------------------------------------------------


def test_records_are_stamped_with_the_day_and_zone_they_happened_in(session):
    localtime.set_preferences(session, home="America/New_York")
    # 23:30 in New York on 3 March = 04:30 UTC on 4 March.
    a = Activity(source="concept2", external_id="c1", type="rower", start=datetime(2026, 3, 4, 4, 30, tzinfo=UTC), duration=1800.0)
    session.add(a)
    food = Food(source="manual", name="Oats")
    session.add(food)
    session.commit()
    log = FoodLog(ts=datetime(2026, 3, 4, 3, 0, tzinfo=UTC), meal="dinner", food_id=food.id, quantity=100, unit="g")
    weigh = BodyComp(source="withings", external_id="w1", ts=datetime(2026, 3, 4, 2, 0, tzinfo=UTC), weight_kg=80.0)
    session.add_all([log, weigh])
    session.commit()
    assert (a.local_date, a.local_tz) == (date(2026, 3, 3), "America/New_York")
    assert log.local_date == date(2026, 3, 3) and weigh.local_date == date(2026, 3, 3)
    assert a.start == datetime(2026, 3, 4, 4, 30, tzinfo=UTC)  # the instant itself is never touched


def test_a_garmin_workout_carries_its_own_offset_and_teaches_the_timeline(session):
    localtime.set_preferences(session, home="America/New_York")
    # 19:00 in Tokyo on 12 May (UTC+9) = 10:00 UTC; New York would call it 06:00 the same day — and 23:30 JST would be New York's
    # previous evening.
    a = garmin(session, "g1", datetime(2026, 5, 12, 14, 30, tzinfo=UTC), 9)
    assert a.local_date == date(2026, 5, 12) and a.local_tz == "+09:00"
    assert localtime.learn_from_records(session) == 1
    session.commit()
    periods = session.exec(select(UserZonePeriod)).all()
    assert [(p.tz, p.source) for p in periods] == [("+09:00", "garmin")]
    # A phone report of Asia/Tokyo with the same offset upgrades the offset-only period to the named zone (DST rules from then on).
    localtime.report_device_zone(session, "Asia/Tokyo", now=datetime(2026, 5, 13, 0, 0, tzinfo=UTC))
    assert session.exec(select(UserZonePeriod.tz)).all() == ["Asia/Tokyo"]


def test_a_late_withings_weigh_in_after_travel_uses_where_the_athlete_was_not_where_they_are_at_sync(session):
    localtime.set_preferences(session, home="America/New_York")
    session.add(UserZonePeriod(start_utc=datetime(2026, 5, 10, tzinfo=UTC), tz="Asia/Tokyo", source="device"))
    session.add(UserZonePeriod(start_utc=datetime(2026, 5, 20, tzinfo=UTC), tz="America/New_York", source="device"))
    session.commit()
    localtime.invalidate(session)
    # Weighed at 07:00 Tokyo on 15 May (22:00 UTC on 14 May), synced weeks later at home.
    w = BodyComp(source="withings", external_id="late", ts=datetime(2026, 5, 14, 22, 0, tzinfo=UTC), weight_kg=79.5)
    session.add(w)
    session.commit()
    assert (w.local_date, w.local_tz) == (date(2026, 5, 15), "Asia/Tokyo")


def test_concept2_account_zone_loses_to_the_timeline_but_a_watch_offset_wins(session):
    localtime.set_preferences(session, home="Europe/Paris")
    session.add(UserZonePeriod(start_utc=datetime(2026, 5, 10, tzinfo=UTC), tz="Asia/Tokyo", source="device"))
    session.commit()
    localtime.invalidate(session)
    at = datetime(2026, 5, 12, 16, 0, tzinfo=UTC)  # 01:00 JST 13 May, 18:00 CEST 12 May
    c2 = Activity(source="concept2", external_id="hotel", type="rower", start=at, duration=1200.0, raw_json=json.dumps({"timezone": "Europe/Paris"}))
    session.add(c2)
    session.commit()
    assert (c2.local_date, c2.local_tz) == (date(2026, 5, 13), "Asia/Tokyo")
    g = garmin(session, "g2", at, 2)  # the watch was still on +02:00 — which is the home zone's offset, so it reads as Paris
    assert (g.local_date, g.local_tz) == (date(2026, 5, 12), "Europe/Paris")


def test_a_change_day_override_moves_one_workout_and_nothing_else(session):
    localtime.set_preferences(session, home="Europe/Paris")
    c = CanonicalActivity(sport_family="rowing", start=datetime(2026, 9, 1, 21, 40, tzinfo=UTC), duration=3000.0,
                          overrides_json=json.dumps({"local_date": "2026-09-02"}))
    session.add(c)
    session.commit()
    localtime.stamp_canonical(session, c, [])
    assert c.local_date == date(2026, 9, 2)


# -- Device reports --------------------------------------------------------------------------------------------------------------


def test_opening_the_app_abroad_moves_today_without_the_athlete_doing_anything(session):
    localtime.set_preferences(session, home="America/New_York")
    now = datetime(2026, 5, 12, 2, 0, tzinfo=UTC)  # 22:00 on 11 May in New York, 11:00 on 12 May in Tokyo
    assert localtime.today(session, now) == date(2026, 5, 11)
    out = localtime.report_device_zone(session, "Asia/Tokyo", now=now)
    assert out["changed"] and out["current_zone"] == "Asia/Tokyo" and out["today"] == "2026-05-12"
    assert localtime.today(session, now) == date(2026, 5, 12)


def test_a_laptop_left_on_home_time_cannot_drag_today_back_while_the_watch_is_abroad(session):
    localtime.set_preferences(session, home="America/New_York")
    garmin(session, "g3", datetime(2026, 5, 12, 10, 0, tzinfo=UTC), 9)
    localtime.learn_from_records(session)
    session.commit()
    out = localtime.report_device_zone(session, "America/New_York", now=datetime(2026, 5, 12, 14, 0, tzinfo=UTC))
    assert not out["changed"] and out["current_zone"] in ("+09:00", "Asia/Tokyo")


def test_unknown_device_zones_are_refused(client):
    assert client.post("/api/login", json={"password": "correct-horse-battery-staple"}).status_code == 200
    assert client.put("/api/time-zone/device", json={"timezone": "Atlantis/Lost"}).status_code == 422
    assert client.put("/api/time-zone", json={"timezone": "+09:00"}).status_code == 422


def test_time_zone_api_round_trip_and_me(client):
    assert client.post("/api/login", json={"password": "correct-horse-battery-staple"}).status_code == 200
    out = client.put("/api/time-zone", json={"timezone": "Europe/Paris", "follow_device_zone": False}).json()
    assert out["timezone"] == "Europe/Paris" and out["follow_device_zone"] is False and out["current_zone"] == "Europe/Paris"
    me = client.get("/api/me").json()
    assert me["timezone"] == "Europe/Paris" and me["current_zone"] == "Europe/Paris" and re.fullmatch(r"\d{4}-\d\d-\d\d", me["today"])
    # Follow is off: a phone report changes nothing.
    assert client.put("/api/time-zone/device", json={"timezone": "Asia/Tokyo"}).json()["current_zone"] == "Europe/Paris"


# -- Changing zones never moves instants; derived days follow ---------------------------------------------------------------------


def test_changing_the_home_zone_restamps_days_keeps_instants_and_asks_for_a_recompute(session):
    localtime.set_preferences(session, home="Asia/Tokyo", follow=False)
    start = datetime(2026, 3, 4, 4, 30, tzinfo=UTC)  # 13:30 JST on 4 March; 23:30 EST on 3 March
    a = Activity(source="concept2", external_id="x", type="rower", start=start, duration=1800.0)
    session.add(a)
    session.commit()
    assert a.local_date == date(2026, 3, 4)
    localtime.pending_recompute_from(session)
    localtime.set_preferences(session, home="America/New_York")
    session.refresh(a)
    assert a.start == start and a.local_date == date(2026, 3, 3)
    assert localtime.pending_recompute_from(session) == date(2026, 3, 3)


def test_daily_strain_uses_local_days_across_the_utc_boundary(session):
    localtime.set_preferences(session, home="America/New_York")
    update_settings(session, {"max_hr": 190})
    day = date(2026, 3, 3)
    session.add(DailyWellness(date=day, resting_hr=50))
    session.add(DailyWellness(date=day + timedelta(days=1), resting_hr=50))
    # 23:30 New York time (04:30 UTC next day): the athlete's 3 March.
    session.add(Activity(source="concept2", external_id="late", type="rower", start=datetime(2026, 3, 4, 4, 30, tzinfo=UTC), duration=1800.0, avg_hr=160))
    session.commit()
    run_matching(session)
    from catch.core.settings_store import get_settings

    s = get_settings(session)
    assert len(scoring.day_strain(session, day, s)["components"]) == 1
    assert scoring.day_strain(session, day + timedelta(days=1), s)["components"] == []


def test_moving_west_removes_a_phantom_future_score_row(session):
    localtime.set_preferences(session, home="Asia/Tokyo", follow=False)
    session.add(DailyWellness(date=date(2026, 1, 1), resting_hr=50))
    session.commit()
    tomorrow_somewhere = localtime.today(session) + timedelta(days=1)
    session.add(DailyScore(date=tomorrow_somewhere, strain_json="{}"))
    session.commit()
    scoring.recompute_scores(session, full=True)
    assert session.get(DailyScore, tenant.pk(tomorrow_somewhere)) is None


# -- Existing data: backfill ---------------------------------------------------------------------------------------------------


def test_existing_rows_without_a_stamp_are_backfilled_once_and_the_timeline_learned(session):
    session.info["catch_no_stamp"] = True  # rows as they were before session 32
    garmin(session, "old1", datetime(2026, 4, 1, 12, 0, tzinfo=UTC), 2)
    garmin(session, "old2", datetime(2026, 4, 20, 12, 0, tzinfo=UTC), 9)
    del session.info["catch_no_stamp"]
    assert localtime.needs_backfill(session)
    assert localtime.ensure_backfilled(session) is True
    rows = session.exec(select(Activity).order_by(Activity.start)).all()
    assert [r.local_tz for r in rows] == ["+02:00", "+09:00"] and all(r.local_date for r in rows)
    assert len(session.exec(select(UserZonePeriod)).all()) >= 1
    assert localtime.ensure_backfilled(session) is False  # idempotent


# -- Scheduler: notifications run on each user's own clock ---------------------------------------------------------------------


def test_quiet_hours_and_the_morning_brief_follow_each_users_own_zone(session):
    from catch.notify import triggers

    now = datetime(2026, 6, 1, 23, 0, tzinfo=UTC)  # 19:00 in New York, 08:00 next day in Tokyo
    settings = {"notifications": {"quiet_hours_start": "22:00", "quiet_hours_end": "06:00", "types": {}}}
    localtime.set_preferences(session, home="America/New_York", follow=False)
    ny_now = localtime.now_local(session, now)
    assert (ny_now.hour, triggers._in_quiet_hours(settings, ny_now)) == (19, False)
    with tenant.use_owner("tokyo-user"), Session(session.get_bind()) as other:
        from catch.core.models import UserProfile

        other.add(UserProfile(id="tokyo-user", timezone="Asia/Tokyo", follow_device_zone=False))
        other.commit()
        tokyo_now = localtime.now_local(other, now)
        assert tokyo_now.hour == 8 and localtime.today(other, now) == date(2026, 6, 2)
        assert not triggers._in_quiet_hours(settings, tokyo_now)
    assert triggers._in_quiet_hours(settings, localtime.now_local(session, datetime(2026, 6, 2, 3, 0, tzinfo=UTC)))  # 23:00 NY


# -- Provider timestamps -----------------------------------------------------------------------------------------------------


def test_concept2_results_with_and_without_zone_information():
    from catch.sync.concept2_client import _result_end_utc

    assert _result_end_utc({"date_utc": "2026-05-12 10:00:00", "date": "2026-05-12 19:00:00"}) == datetime(2026, 5, 12, 10, tzinfo=UTC)
    assert _result_end_utc({"date": "2026-05-12 19:00:00", "timezone": "Asia/Tokyo"}) == datetime(2026, 5, 12, 10, tzinfo=UTC)
    # Neither: read in the zone the athlete was in (here Tokyo), not silently as UTC.
    tokyo = lt.tz_for("Asia/Tokyo")
    assert _result_end_utc({"date": "2026-05-12 19:00:00"}, lambda _: tokyo) == datetime(2026, 5, 12, 10, tzinfo=UTC)
    assert _result_end_utc({"date": "2026-05-12 19:00:00"}) == datetime(2026, 5, 12, 19, tzinfo=UTC)  # no timeline at all: documented UTC


def test_garmin_and_whoop_offsets_are_read_without_double_conversion():
    zone, grade = localtime.activity_provider_zone("garmin", json.dumps({"startTimeGMT": "2026-01-10 12:00:00", "startTimeLocal": "2026-01-10 07:00:00"}))
    assert (zone, grade) == ("-05:00", "garmin")
    assert localtime.activity_provider_zone("whoop", json.dumps({"timezone_offset": "+05:30"})) == ("+05:30", "whoop")
    assert localtime.activity_provider_zone("garmin", json.dumps({"startTimeGMT": "2026-01-10 12:00:00"})) == (None, None)
    assert localtime.activity_provider_zone("concept2", json.dumps({"timezone": None})) == (None, None)


def test_a_phone_workout_keeps_the_offset_written_in_its_start_time():
    from catch.analytics.health_import import validate_workout

    w = validate_workout({"external_id": "x", "start": "2026-05-12T19:00:00+09:00", "end": "2026-05-12T19:45:00+09:00"},
                         now=datetime(2026, 5, 13, tzinfo=UTC))
    assert w["start"] == datetime(2026, 5, 12, 10, 0, tzinfo=UTC) and w["utc_offset_minutes"] == 540
    w = validate_workout({"external_id": "y", "start": "2026-05-12T10:00:00Z", "end": "2026-05-12T10:45:00Z"}, now=datetime(2026, 5, 13, tzinfo=UTC))
    assert w["utc_offset_minutes"] is None


# -- One helper: no server clock anywhere else --------------------------------------------------------------------------------

BANNED = re.compile(r"\bdate_?\.today\(\)|\.astimezone\(\)|\bdatetime\.now\(\)|time\.localtime\(")
ALLOWED = {"catch/core/localtime.py", "catch/analytics/localtime.py"}


def test_no_day_is_bucketed_on_the_servers_own_clock_outside_the_one_helper():
    """L-09/L-49: every local day goes through catch.core.localtime. A bare date.today(), datetime.now() or .astimezone() reads the
    server's zone, which on the public build is nobody's."""
    offenders = []
    for path in (ROOT / "catch").rglob("*.py"):
        rel = str(path.relative_to(ROOT))
        if rel in ALLOWED or "/static/" in rel:
            continue
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if BANNED.search(line.split("#", 1)[0]):
                offenders.append(f"{rel}:{i}")
    assert offenders == []


def test_change_day_moves_one_workout_within_a_day_of_its_recorded_day_and_recomputes_both(client, session):
    assert client.post("/api/login", json={"password": "correct-horse-battery-staple"}).status_code == 200
    localtime.set_preferences(session, home="Europe/Paris", follow=False)
    update_settings(session, {"max_hr": 190})
    for d in (date(2026, 9, 1), date(2026, 9, 2)):
        session.add(DailyWellness(date=d, resting_hr=50))
    session.add(Activity(source="concept2", external_id="late", type="rower", start=datetime(2026, 9, 1, 21, 40, tzinfo=UTC), duration=3000.0, avg_hr=150))
    session.commit()
    run_matching(session)
    scoring.recompute_scores(session, full=True)
    cid = session.exec(select(Activity)).first().canonical_id
    detail = client.get(f"/api/activities/{cid}").json()
    assert detail["local_date"] == detail["recorded_local_date"] == "2026-09-01"
    assert client.patch(f"/api/activities/{cid}", json={"local_date": "2026-09-05"}).status_code == 422
    moved = client.patch(f"/api/activities/{cid}", json={"local_date": "2026-09-02"}).json()
    assert moved["local_date"] == "2026-09-02" and moved["start"].startswith("2026-09-01T21:40")  # the time itself never changes
    session.expire_all()
    from catch.core.settings_store import get_settings

    s = get_settings(session)
    assert scoring.day_strain(session, date(2026, 9, 1), s)["components"] == []
    assert len(scoring.day_strain(session, date(2026, 9, 2), s)["components"]) == 1
    reverted = client.post(f"/api/activities/{cid}/revert", json={"field": "local_date"}).json()
    assert reverted["local_date"] == "2026-09-01"
