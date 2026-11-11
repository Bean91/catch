from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from catch.analytics.weather import (
    circular_mean_deg,
    compass_label,
    status_for,
    summarize_window,
    to_utc_ts,
    utc_dates_needed,
)

T20 = int(datetime(2026, 10, 30, 20, tzinfo=timezone.utc).timestamp())
H = 3600


def row(temp=None, hum=None, wind=None, gust=None, wdir=None, pres=None, precip=None, code=None):
    return {"temperature_2m": temp, "relative_humidity_2m": hum, "wind_speed_10m": wind,
            "wind_gusts_10m": gust, "wind_direction_10m": wdir, "pressure_msl": pres,
            "precipitation": precip, "weather_code": code}


def hours(*rows, first=T20):
    return {first + i * H: r for i, r in enumerate(rows)}


# the worked example: 20:37 -> 21:25 UTC (48 minutes)
START = T20 + 37 * 60
END = T20 + H + 25 * 60


def test_precipitation_is_a_preceding_hour_sum_prorated_by_overlap():
    # stamp 21:00 covers (20:00, 21:00] -> 23 min of the window; stamp 22:00 covers (21:00, 22:00] -> 25 min
    h = hours(row(precip=9.9), row(precip=1.2), row(precip=0.6))  # stamps 20:00, 21:00, 22:00
    s = summarize_window(h, START, END)
    # the 20:00 stamp covers (19:00, 20:00] and must contribute nothing
    assert s["precipitation_mm"] == pytest.approx(1.2 * 23 / 60 + 0.6 * 25 / 60)
    assert s["precipitation_mm"] == pytest.approx(0.71, abs=1e-9)


def test_instantaneous_values_interpolate_linearly_between_stamps():
    h = hours(row(temp=10), row(temp=12), row(temp=14))
    s = summarize_window(h, START, END)
    # a linear series averages to its value at the window midpoint, 21:01 -> 12 + 2/60
    assert s["temperature_c"]["avg"] == pytest.approx(12 + 2 / 60)
    assert s["temperature_c"]["min"] == pytest.approx(10 + 2 * 37 / 60)  # value at 20:37
    assert s["temperature_c"]["max"] == pytest.approx(12 + 2 * 25 / 60)  # value at 21:25


def test_wind_direction_uses_the_shortest_arc():
    h = hours(row(wdir=350), row(wdir=10))
    s = summarize_window(h, T20, T20 + H)  # the whole 350 -> 10 swing, symmetric about north
    d = s["wind"]["direction_from_deg"]
    assert min(d, 360 - d) < 1.0  # ~0/360, never ~180
    assert s["wind"]["direction_from_label"] == "N"


def test_circular_mean_wraps_and_cancels():
    m = circular_mean_deg([350, 10])
    assert min(m, 360 - m) == pytest.approx(0, abs=1e-6)
    assert circular_mean_deg([90, 270]) is None  # opposite winds: no honest mean
    assert circular_mean_deg([]) is None


def test_compass_labels():
    assert [compass_label(d) for d in (0, 90, 180, 270, 315, 359)] == ["N", "E", "S", "W", "NW", "N"]


def test_a_missing_stamp_is_never_interpolated_across():
    h = hours(row(temp=10, wind=20), row(temp=None, wind=20), row(temp=14, wind=20))
    s = summarize_window(h, START, END)
    assert s["temperature_c"]["avg"] is None  # both bounding segments touch the missing 21:00 stamp
    assert s["variable_coverage"]["temperature"] == 0.0
    assert s["wind"]["speed_kmh"] == pytest.approx(20.0)
    assert s["variable_coverage"]["wind_speed"] == 1.0


def test_partial_coverage_reports_the_covered_fraction_only():
    # stamps 20:00 and 21:00 exist, 22:00 missing entirely: the 21:00-21:25 stretch is uncovered
    h = hours(row(temp=10), row(temp=12))
    s = summarize_window(h, START, END)
    assert s["variable_coverage"]["temperature"] == pytest.approx(23 / 48, abs=1e-3)
    # only 20:37-21:00 is covered; a linear series averages to its midpoint value there (20:48:30)
    assert s["temperature_c"]["avg"] == pytest.approx(10 + 2 * 48.5 / 60)


def test_empty_hourly_is_unavailable_not_invented():
    s = summarize_window({}, START, END)
    assert s["coverage"] == 0.0 and s["precipitation_mm"] is None and s["temperature_c"]["avg"] is None
    assert status_for(s, provisional=False) == "unavailable"
    assert s["hours"] == []


def test_status_ladder():
    full = summarize_window(hours(row(temp=10, wind=5, precip=0), row(temp=11, wind=5, precip=0), row(temp=12, wind=5, precip=0)), START, END)
    assert status_for(full, provisional=False) == "ok"
    assert status_for(full, provisional=True) == "partial"
    thin = summarize_window(hours(row(temp=10, wind=5, precip=0), row(temp=11, wind=5, precip=0)), START, END)
    assert status_for(thin, provisional=False) == "partial"


def test_condition_headline_is_nearest_the_midpoint():
    h = hours(row(code=61), row(code=3), row(code=0))  # midpoint 21:01 -> the 21:00 stamp
    s = summarize_window(h, START, END)
    assert s["condition"]["code"] == 3 and s["condition"]["text"] == "Overcast"
    assert [c["code"] for c in s["condition"]["codes_in_window"]] == [0, 3, 61]


# ---- time zones: only UTC instants matter -------------------------------------------------

def test_the_same_instant_in_any_zone_matches_the_same_hours():
    utc = datetime(2026, 10, 30, 20, 37, tzinfo=timezone.utc)
    ny = utc.astimezone(ZoneInfo("America/New_York"))  # 16:37 EDT
    syd = utc.astimezone(ZoneInfo("Australia/Sydney"))  # 07:37 next day AEDT
    assert to_utc_ts(ny) == to_utc_ts(syd) == to_utc_ts(utc)
    assert to_utc_ts(utc.replace(tzinfo=None)) == to_utc_ts(utc)  # SQLite hands back naive UTC


def test_sydney_morning_belongs_to_the_previous_utc_day():
    local = datetime(2026, 11, 1, 8, 0, tzinfo=ZoneInfo("Australia/Sydney"))  # 21:00 UTC Oct 31
    start = to_utc_ts(local)
    assert utc_dates_needed(start, start + 3000) == [date(2026, 10, 31)]


def test_window_across_utc_midnight_needs_two_days_and_the_next_days_zero_stamp():
    start = datetime(2026, 10, 30, 23, 40, tzinfo=timezone.utc).timestamp()
    end = start + 40 * 60  # 00:20 next day
    assert utc_dates_needed(start, end) == [date(2026, 10, 30), date(2026, 10, 31)]
    # ends at 23:50 the same day: still needs 00:00 next day for the 23:00-24:00 precipitation hour
    assert utc_dates_needed(start, start + 600) == [date(2026, 10, 30), date(2026, 10, 31)]


def test_dst_change_day_uses_real_utc_elapsed_time():
    # US clocks fall back 2026-11-01 02:00 EDT -> 01:00 EST. 01:30 EDT and 01:30 EST are an hour apart in UTC.
    first = datetime(2026, 11, 1, 1, 30, tzinfo=ZoneInfo("America/New_York"), fold=0)
    second = datetime(2026, 11, 1, 1, 30, tzinfo=ZoneInfo("America/New_York"), fold=1)
    assert to_utc_ts(second) - to_utc_ts(first) == 3600


def test_nonpositive_window_is_rejected():
    with pytest.raises(ValueError):
        summarize_window({}, 100.0, 100.0)
