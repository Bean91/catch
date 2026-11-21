"""Session 32: the pure time-zone rules (catch/analytics/localtime.py), with New York, Paris and Tokyo."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from catch.analytics import localtime as lt

NY, PARIS, TOKYO = ZoneInfo("America/New_York"), ZoneInfo("Europe/Paris"), ZoneInfo("Asia/Tokyo")
UTC = timezone.utc


def test_utc_to_local_day_in_three_zones():
    instant = datetime(2026, 6, 1, 23, 30, tzinfo=UTC)
    assert lt.local_date(instant, NY) == date(2026, 6, 1)  # 19:30 EDT
    assert lt.local_date(instant, PARIS) == date(2026, 6, 2)  # 01:30 CEST
    assert lt.local_date(instant, TOKYO) == date(2026, 6, 2)  # 08:30 JST


def test_a_late_evening_new_york_session_stays_on_its_local_day_although_utc_has_rolled_over():
    # 23:30 in New York on 3 March is 04:30 UTC on 4 March.
    instant = datetime(2026, 3, 4, 4, 30, tzinfo=UTC)
    assert lt.local_date(instant, NY) == date(2026, 3, 3)


def test_naive_instants_are_read_as_utc_never_as_local():
    assert lt.local_date(datetime(2026, 1, 1, 2, 0), NY) == date(2025, 12, 31)


def test_spring_forward_day_is_23_hours_and_fall_back_is_25():
    lo, hi = lt.day_utc_range(date(2026, 3, 8), NY)
    assert hi - lo == timedelta(hours=23)
    lo, hi = lt.day_utc_range(date(2026, 11, 1), NY)
    assert hi - lo == timedelta(hours=25)
    lo, hi = lt.day_utc_range(date(2026, 3, 29), PARIS)
    assert hi - lo == timedelta(hours=23)
    assert lt.day_utc_range(date(2026, 3, 8), TOKYO)[1] - lt.day_utc_range(date(2026, 3, 8), TOKYO)[0] == timedelta(hours=24)


def test_a_spring_forward_missing_local_time_maps_forward_and_a_repeated_one_takes_the_first():
    # 02:30 doesn't exist in New York on 8 March 2026 (clocks jump 02:00 -> 03:00): it lands at 03:30 EDT = 07:30 UTC.
    assert lt.local_wall_to_utc(date(2026, 3, 8), 2, 30, NY) == datetime(2026, 3, 8, 7, 30, tzinfo=UTC)
    # 01:30 happens twice on 1 November 2026; the first (EDT, UTC-4) is used.
    assert lt.local_wall_to_utc(date(2026, 11, 1), 1, 30, NY) == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)


def test_copying_a_meal_keeps_its_wall_clock_time_across_a_dst_change():
    breakfast = datetime(2026, 3, 7, 13, 0, tzinfo=UTC)  # 08:00 EST
    copied = lt.shift_local_days(breakfast, 1, NY)
    assert copied.astimezone(NY).hour == 8 and copied == datetime(2026, 3, 8, 12, 0, tzinfo=UTC)  # 08:00 EDT


def test_offsets_and_names():
    assert lt.parse_offset_minutes("-05:00") == -300
    assert lt.parse_offset_minutes("+0530") == 330
    assert lt.parse_offset_minutes("+09") == 540
    assert lt.parse_offset_minutes(-18000) == -300  # seconds, as some payloads send
    assert lt.parse_offset_minutes("bogus") is None and lt.parse_offset_minutes("+23:00") is None
    assert lt.offset_name(-300) == "-05:00" and lt.offset_name(345) == "+05:45"
    assert lt.tz_for("+09:00").utcoffset(None) == timedelta(hours=9)
    assert lt.tz_for("Not/AZone") is None and lt.tz_for("localtime") is None
    assert lt.is_valid_iana("America/New_York") and not lt.is_valid_iana("EST5EDT ") and not lt.is_valid_iana(None)


# -- The timeline: records keep the day they happened on ----------------------------------------------------------------------


def trip() -> lt.Timeline:
    """Home in New York; flew to Tokyo on 10 May (period from 01:00 UTC), back on 20 May."""
    return lt.Timeline(fallback_name="America/New_York", periods=[
        (datetime(2026, 5, 10, 1, 0, tzinfo=UTC), "Asia/Tokyo"),
        (datetime(2026, 5, 20, 3, 0, tzinfo=UTC), "America/New_York"),
    ])


def test_a_session_abroad_lands_on_the_local_day_where_it_happened():
    tl = trip()
    # 19:00 in Tokyo on 12 May = 10:00 UTC: Tokyo's 12 May, which New York would have called 12 May 06:00 — and 23:30 Tokyo time
    # is still New York's same morning, but the session belongs to Tokyo's day.
    assert tl.local_date(datetime(2026, 5, 12, 14, 30, tzinfo=UTC)) == (date(2026, 5, 12), "Asia/Tokyo")
    assert tl.local_date(datetime(2026, 5, 12, 15, 30, tzinfo=UTC)) == (date(2026, 5, 13), "Asia/Tokyo")


def test_history_does_not_move_when_the_athlete_comes_home():
    tl = trip()
    tokyo_evening = datetime(2026, 5, 15, 13, 0, tzinfo=UTC)  # 22:00 JST on 15 May; 09:00 EDT the same 15 May
    before, _ = tl.local_date(tokyo_evening)
    after_return = lt.Timeline(fallback_name="America/New_York", periods=trip().periods + [(datetime(2026, 6, 1, tzinfo=UTC), "America/New_York")])
    assert after_return.local_date(tokyo_evening)[0] == before == date(2026, 5, 15)


def test_a_record_s_own_watch_offset_beats_the_timeline_and_an_account_zone_does_not():
    tl = trip()
    at = datetime(2026, 5, 12, 23, 0, tzinfo=UTC)  # in Tokyo per the timeline
    # The watch says UTC+2 (the athlete was actually somewhere else that evening): the watch wins.
    assert tl.record_zone(at, "+02:00", "garmin") == "+02:00"
    # Concept2's zone is the logbook account's setting, often "home": the timeline wins.
    assert tl.record_zone(at, "America/New_York", "concept2") == "Asia/Tokyo"
    # Before any period is known, the account zone is still better than nothing.
    assert tl.record_zone(datetime(2026, 4, 1, tzinfo=UTC), "Europe/Paris", "concept2") == "Europe/Paris"


def test_a_watch_offset_matching_the_timeline_reads_as_the_named_zone():
    tl = trip()
    assert tl.record_zone(datetime(2026, 5, 12, 23, 0, tzinfo=UTC), "+09:00", "whoop") == "Asia/Tokyo"
    # New York in summer is -04:00.
    assert tl.record_zone(datetime(2026, 7, 1, 12, 0, tzinfo=UTC), "-04:00", "garmin") == "America/New_York"


def test_follow_off_reads_everything_in_the_home_zone():
    tl = lt.Timeline(fallback_name="Europe/Paris", periods=trip().periods, follow=False)
    assert tl.record_zone(datetime(2026, 5, 12, 23, 0, tzinfo=UTC), "+09:00", "garmin") == "Europe/Paris"


def test_a_session_crossing_local_midnight_belongs_to_the_day_it_started():
    tl = lt.Timeline(fallback_name="Europe/Paris")
    start = datetime(2026, 9, 1, 21, 40, tzinfo=UTC)  # 23:40 CEST on 1 Sept, a 50-minute row ending 00:30 on 2 Sept
    assert tl.local_date(start)[0] == date(2026, 9, 1)


def test_crossing_the_date_line_can_skip_or_repeat_a_date_without_losing_records():
    # Tokyo -> Honolulu: leave 20:00 JST 1 June (11:00 UTC), land the "same" morning 1 June HST.
    tl = lt.Timeline(fallback_name="Asia/Tokyo", periods=[(datetime(2026, 6, 1, 11, 0, tzinfo=UTC), "Pacific/Honolulu")])
    days = [tl.local_date(datetime(2026, 6, 1, 10, 0, tzinfo=UTC))[0], tl.local_date(datetime(2026, 6, 1, 20, 0, tzinfo=UTC))[0]]
    assert days == [date(2026, 6, 1), date(2026, 6, 1)]  # two records, one repeated calendar day, nothing dropped


def test_observation_changes_zone_compares_offsets_at_that_instant():
    tl = lt.Timeline(fallback_name="America/New_York")
    assert lt.observation_changes_zone(tl, datetime(2026, 7, 1, tzinfo=UTC), "+09:00")
    assert not lt.observation_changes_zone(tl, datetime(2026, 7, 1, tzinfo=UTC), "-04:00")
    assert not lt.observation_changes_zone(tl, datetime(2026, 1, 15, tzinfo=UTC), "America/New_York")


@pytest.mark.parametrize("day", [date(2026, 3, 8), date(2026, 11, 1), date(2026, 6, 1)])
def test_zone_for_day_reads_noon_utc_inside_the_day(day):
    tl = trip()
    lo, hi = tl.day_range(day)
    assert lo < datetime(day.year, day.month, day.day, 12, tzinfo=UTC) < hi
