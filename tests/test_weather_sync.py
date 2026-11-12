from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlmodel import select

from catch.core.models import Activity, ActivityTrack, ActivityWeather, WeatherCell
from catch.core.settings_store import update_settings
from catch.sync.tracks import ingest_track
from catch.sync.weather import cell_for, enrich_pending, ensure_weather, pending_count, weather_payload
from catch.sync.weather_client import ATTRIBUTION, is_final
from tests.test_fit_parse import FakeDataMessage
from tests.test_fit_track_parse import semi

M_PER_DEG = 111194.93
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


class FakeClient:
    """Stands in for OpenMeteoClient: counts calls, serves 24 hourly stamps per requested day."""

    def __init__(self, complete=True, null_vars=(), fail=False):
        self.calls: list[tuple] = []
        self.complete, self.null_vars, self.fail = complete, set(null_vars), fail

    def fetch_day(self, lat_e1, lon_e1, day):
        self.calls.append((lat_e1, lon_e1, day))
        if self.fail:
            return None
        start = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())
        hourly = {}
        for h in range(24):
            row = {"temperature_2m": 10.0 + h, "relative_humidity_2m": 50.0, "precipitation": 0.5,
                   "weather_code": 3, "wind_speed_10m": 18.0, "wind_direction_10m": 270.0,
                   "wind_gusts_10m": 30.0, "pressure_msl": 1010.0}
            for v in self.null_vars:
                row[v] = None
            hourly[start + h * 3600] = row
        return {"hourly": hourly, "grid_lat": lat_e1 / 10 + 0.04, "grid_lon": lon_e1 / 10 - 0.04,
                "elevation": 2.0, "complete": self.complete}


def row_activity(session, tmp_path, start, *, ext="w1", seconds=500, type_="rowing_v2", family="rowing"):
    """An activity with a real ingested track: due north at 4 m/s from (45.0, -73.0)."""
    fit = tmp_path / f"{ext}.fit"
    fit.write_bytes(b"faked")
    a = Activity(source="garmin", external_id=ext, type=type_, start=start, duration=float(seconds),
                 sport_family=family, fit_path=str(fit), raw_json="{}")
    session.add(a)
    session.commit()
    session.refresh(a)
    step = 4.0 * 5 / M_PER_DEG
    frames = [
        FakeDataMessage("record", {"timestamp": start + timedelta(seconds=5 * i),
                                   "position_lat": semi(45.0 + i * step), "position_long": semi(-73.0)})
        for i in range(seconds // 5 + 1)
    ]
    _patch_fitdecode_for(frames)
    ingest_track(session, a)
    return a


_monkeypatch_holder = {}


def _patch_fitdecode_for(frames):
    import types
    from tests.test_fit_parse import FakeFitReader

    import catch.sync.fit_parse as fp

    fp.fitdecode = types.SimpleNamespace(FitReader=lambda path: FakeFitReader(frames), FitDataMessage=FakeDataMessage)


@pytest.fixture(autouse=True)
def _restore_fitdecode():
    import catch.sync.fit_parse as fp

    real = fp.fitdecode
    yield
    fp.fitdecode = real


START = datetime(2026, 10, 30, 20, 37, 42, tzinfo=timezone.utc)


def test_cell_rounding_is_to_a_tenth_of_a_degree():
    assert cell_for(45.0449, -72.9551) == (450, -730)
    assert cell_for(40.738, -74.043) == (407, -740)


def test_matches_weather_to_the_window_and_stores_attribution(session, tmp_path):
    a = row_activity(session, tmp_path, START)
    client = FakeClient()
    w = ensure_weather(session, a, client, now=NOW)
    assert w.status == "ok" and w.attribution == ATTRIBUTION
    s = json.loads(w.summary_json)
    assert s["window_start"] == "2026-10-30T20:37:42+00:00"
    assert s["window_end"] == "2026-10-30T20:46:02+00:00"
    # temp = 10 + hour: 20:37-20:46 interpolates between the 20:00 (30 C) and 21:00 (31 C) stamps
    # a linear series averages to its midpoint value: 20:41:52 is 2512 s into the 20:00 hour
    assert s["temperature_c"]["avg"] == pytest.approx(30 + 2512 / 3600, abs=1e-6)
    assert s["wind"]["direction_from_label"] == "W" and s["wind"]["speed_kmh"] == pytest.approx(18.0)
    assert s["location_rounded"] == {"lat": 45.0, "lon": -73.0}
    assert s["provisional"] is False
    assert client.calls == [(450, -730, date(2026, 10, 30))]  # the window sits inside one UTC day


def test_the_same_cell_day_is_fetched_once_for_any_number_of_activities(session, tmp_path):
    a1 = row_activity(session, tmp_path, START, ext="w1")
    a2 = row_activity(session, tmp_path, START + timedelta(hours=2), ext="w2")
    client = FakeClient()
    ensure_weather(session, a1, client, now=NOW)
    ensure_weather(session, a2, client, now=NOW)
    ensure_weather(session, a1, client, now=NOW, force=True)  # even a forced recompute reuses the cache
    assert len(client.calls) == 1
    assert len(session.exec(select(WeatherCell)).all()) == 1


def test_a_finished_ok_result_is_not_recomputed_without_force(session, tmp_path):
    a = row_activity(session, tmp_path, START)
    client = FakeClient()
    first = ensure_weather(session, a, client, now=NOW)
    again = ensure_weather(session, a, FakeClient(fail=True), now=NOW)
    assert again.fetched_at == first.fetched_at


def test_window_across_utc_midnight_fetches_both_days(session, tmp_path):
    a = row_activity(session, tmp_path, datetime(2026, 10, 30, 23, 50, tzinfo=timezone.utc), ext="mid")
    client = FakeClient()
    w = ensure_weather(session, a, client, now=NOW)
    assert [c[2] for c in client.calls] == [date(2026, 10, 30), date(2026, 10, 31)]
    assert w.status == "ok"
    assert len(json.loads(w.summary_json)["grid"]) == 2


def test_stored_track_start_round_trips_as_aware_utc(session, tmp_path):
    a = row_activity(session, tmp_path, START)
    session.expire_all()
    track = session.get(ActivityTrack, a.id)
    assert track.start.utcoffset() == timedelta(0)  # the column type rejects naive values
    s = json.loads(ensure_weather(session, a, FakeClient(), now=NOW).summary_json)
    assert s["window_start"] == "2026-10-30T20:37:42+00:00"


def test_missing_observations_stay_missing(session, tmp_path):
    a = row_activity(session, tmp_path, START)
    w = ensure_weather(session, a, FakeClient(null_vars=["temperature_2m", "wind_gusts_10m"]), now=NOW)
    s = json.loads(w.summary_json)
    assert s["temperature_c"]["avg"] is None and s["wind"]["gust_max_kmh"] is None
    assert s["wind"]["speed_kmh"] == pytest.approx(18.0)
    assert w.status == "partial"  # no temperature at all: the weakest core variable decides, not the average


def test_provider_with_nothing_for_the_window_is_unavailable_not_invented(session, tmp_path):
    a = row_activity(session, tmp_path, START)
    nulls = [v for v in ("temperature_2m", "relative_humidity_2m", "precipitation", "weather_code",
                         "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "pressure_msl")]
    w = ensure_weather(session, a, FakeClient(null_vars=nulls, complete=False), now=NOW)
    assert w.status == "unavailable"
    s = json.loads(w.summary_json)
    assert s["temperature_c"]["avg"] is None and s["precipitation_mm"] is None and s["condition"]["code"] is None


def test_unreachable_provider_writes_nothing_so_the_next_pass_retries(session, tmp_path):
    a = row_activity(session, tmp_path, START)
    assert ensure_weather(session, a, FakeClient(fail=True), now=NOW) is None
    assert session.get(ActivityWeather, a.id) is None
    assert session.exec(select(WeatherCell)).all() == []
    assert ensure_weather(session, a, FakeClient(), now=NOW).status == "ok"


def test_provisional_day_is_partial_and_refetched_only_after_the_ttl(session, tmp_path):
    a = row_activity(session, tmp_path, START)
    day_after = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)  # 2 days later: inside the reanalysis delay
    assert is_final(date(2026, 10, 30), day_after.date()) is False
    client = FakeClient(complete=False)
    w = ensure_weather(session, a, client, now=day_after)
    assert w.status == "partial" and json.loads(w.summary_json)["provisional"] is True
    ensure_weather(session, a, client, now=day_after + timedelta(hours=1))
    assert len(client.calls) == 1  # inside the 12 h TTL: cache
    ensure_weather(session, a, client, now=day_after + timedelta(hours=13))
    assert len(client.calls) == 2
    done = FakeClient(complete=True)
    assert ensure_weather(session, a, done, now=NOW).status == "ok"  # a final day replaces it


def test_disabled_setting_makes_no_calls(session, tmp_path):
    a = row_activity(session, tmp_path, START)
    update_settings(session, {"on_water": {"weather_enabled": False}})
    client = FakeClient()
    assert ensure_weather(session, a, client, now=NOW) is None
    assert client.calls == []
    assert enrich_pending(session, client, now=NOW)["disabled"] is True


def test_no_track_or_positionless_track_means_no_weather(session, tmp_path):
    bare = Activity(source="garmin", external_id="x", type="indoor_rowing", start=START, duration=600.0)
    session.add(bare)
    session.commit()
    session.refresh(bare)
    client = FakeClient()
    assert ensure_weather(session, bare, client, now=NOW) is None
    session.add(ActivityTrack(activity_id=bare.id, start=START, n_points=0))
    session.commit()
    assert ensure_weather(session, bare, client, now=NOW) is None
    assert client.calls == []


def test_a_window_in_the_future_is_not_fetched(session, tmp_path):
    a = row_activity(session, tmp_path, START)
    client = FakeClient()
    assert ensure_weather(session, a, client, now=START - timedelta(days=1)) is None
    assert client.calls == []


def test_payload_distinguishes_not_fetched_from_data(session, tmp_path):
    a = row_activity(session, tmp_path, START)
    p = weather_payload(session, a.id)
    assert p["status"] == "not_fetched" and p["weather"] is None and p["attribution"] == ATTRIBUTION
    ensure_weather(session, a, FakeClient(), now=NOW)
    p = weather_payload(session, a.id)
    assert p["status"] == "ok" and p["weather"]["wind"]["speed_kmh"] == pytest.approx(18.0)
    assert "not a measurement" in p["disclaimer"] and "performance correction" in p["disclaimer"]
    assert p["source"] == "provider_reanalysis"


def test_enrich_pending_is_bounded_and_skips_finished_work(session, tmp_path):
    acts = [row_activity(session, tmp_path, START + timedelta(days=i), ext=f"e{i}") for i in range(3)]
    client = FakeClient()
    assert enrich_pending(session, client, limit=2, now=NOW) == {"processed": 2, "ok": 2, "stopped": None}
    assert enrich_pending(session, client, limit=2, now=NOW) == {"processed": 1, "ok": 1, "stopped": None}
    assert enrich_pending(session, client, limit=2, now=NOW) == {"processed": 0, "ok": 0, "stopped": None}
    assert len(acts) == 3


def test_enrich_pending_leaves_a_fresh_partial_alone_until_its_ttl(session, tmp_path):
    row_activity(session, tmp_path, START)
    client = FakeClient(complete=False)
    soon = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    assert enrich_pending(session, client, now=soon)["processed"] == 1
    assert enrich_pending(session, client, now=soon + timedelta(hours=1))["processed"] == 0
    assert enrich_pending(session, client, now=soon + timedelta(hours=13))["processed"] == 1


# ---- a backfill must always terminate (the CLI loops until a pass writes nothing) ---------------

def drive_like_the_cli(session, client, now, max_passes=50):
    """The CLI's loop, minus the sleep: repeat while a pass wrote something."""
    passes, written = 0, 0
    while passes < max_passes:
        passes += 1
        r = enrich_pending(session, client, limit=20, now=now)
        if r["processed"] == 0:
            return passes, written, r
        written += r["processed"]
    raise AssertionError("never terminated")


def test_an_unreachable_provider_ends_the_pass_at_once_and_reports_nothing_written(session, tmp_path):
    for i in range(4):
        row_activity(session, tmp_path, START + timedelta(days=i), ext=f"d{i}")
    client = FakeClient(fail=True)
    passes, written, last = drive_like_the_cli(session, client, NOW)
    assert (passes, written) == (1, 0)
    assert last == {"processed": 0, "ok": 0, "stopped": "provider_unavailable"}
    assert len(client.calls) == 1  # stopped at the first failure instead of burning the budget on the rest
    assert pending_count(session, NOW) == 4


def test_a_provisional_row_the_provider_cannot_refresh_is_not_progress(session, tmp_path):
    a = row_activity(session, tmp_path, START)
    soon = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    assert ensure_weather(session, a, FakeClient(complete=False), now=soon).status == "partial"
    later = soon + timedelta(hours=13)  # TTL elapsed, but the provider is down: existing row comes back unchanged
    passes, written, last = drive_like_the_cli(session, FakeClient(fail=True), later)
    assert (passes, written) == (1, 0) and last["stopped"] == "provider_unavailable"


def test_a_track_with_no_usable_summary_is_never_selected(session, tmp_path):
    a = row_activity(session, tmp_path, START)
    stray = Activity(source="garmin", external_id="stray", type="indoor_rowing", start=START, duration=600.0)
    session.add(stray)
    session.commit()
    session.refresh(stray)
    # an erg file that picked up two stray fixes: n_points >= 2 but filtering left no summary
    session.add(ActivityTrack(activity_id=stray.id, start=START, n_points=2, n_records=500, summary_json=None))
    session.commit()
    client = FakeClient()
    assert pending_count(session, NOW) == 1  # only the real track
    assert enrich_pending(session, client, now=NOW) == {"processed": 1, "ok": 1, "stopped": None}
    assert [c[2] for c in client.calls] == [date(2026, 10, 30)]
    assert a.id != stray.id and pending_count(session, NOW) == 0
    # and with the provider down, that stray row can't keep the loop alive
    assert drive_like_the_cli(session, FakeClient(fail=True), NOW)[0] == 1


def test_minute_budget_signal(monkeypatch):
    import catch.sync.weather_client as wc

    monkeypatch.setattr(wc, "_call_times", [])
    assert wc.minute_budget_exhausted() is False
    monkeypatch.setattr(wc, "_MAX_PER_MINUTE", 2)
    import time as _t

    monkeypatch.setattr(wc, "_call_times", [_t.monotonic(), _t.monotonic()])
    assert wc.minute_budget_exhausted() is True
