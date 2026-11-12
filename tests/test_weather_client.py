from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

import catch.sync.weather_client as wc
from catch.sync.weather_client import ATTRIBUTION, HOURLY_VARS, OpenMeteoClient, parse_response

# conftest stubs fetch_day for every test; the client's own tests need the real one back.
REAL_FETCH_DAY = OpenMeteoClient.fetch_day

OLD = date(2026, 10, 30)
BASE = int(datetime(2026, 10, 30, tzinfo=timezone.utc).timestamp())


def body(day=OLD, n=24, null_var=None):
    start = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())
    hourly = {"time": [start + h * 3600 for h in range(n)]}
    for v in HOURLY_VARS:
        hourly[v] = [None if v == null_var else float(h) for h in range(n)]
    return {"latitude": 40.738, "longitude": -74.043, "elevation": 0.0, "hourly": hourly}


@pytest.fixture(autouse=True)
def _fresh_budget(monkeypatch):
    monkeypatch.setattr(wc, "_call_times", [])
    monkeypatch.setattr(wc, "_day_counter", {})
    monkeypatch.setattr(OpenMeteoClient, "fetch_day", REAL_FETCH_DAY)


def client_for(handler):
    return OpenMeteoClient(httpx.Client(base_url=wc.BASE_URL, transport=httpx.MockTransport(handler)))


def test_request_sends_rounded_coordinates_utc_and_one_day():
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        return httpx.Response(200, json=body())

    out = client_for(handler).fetch_day(407, -740, OLD)
    q = seen[0].url.params
    assert (q["latitude"], q["longitude"]) == ("40.7", "-74.0")  # rounded to 0.1 degree before sending
    assert q["timezone"] == "GMT" and q["timeformat"] == "unixtime" and q["wind_speed_unit"] == "kmh"
    assert q["start_date"] == q["end_date"] == "2026-10-30"
    assert set(q["hourly"].split(",")) == set(HOURLY_VARS)
    assert seen[0].url.path == "/v1/archive" and len(seen) == 1
    assert len(out["hourly"]) == 24 and out["hourly"][BASE]["temperature_2m"] == 0.0
    assert out["grid_lat"] == 40.738 and out["elevation"] == 0.0


def test_user_agent_is_generic_and_carries_no_email():
    ua = OpenMeteoClient().http.headers["User-Agent"]
    assert "@" not in ua and ua.startswith("Catch/")


def test_old_complete_day_is_final_but_recent_or_gappy_days_are_not():
    assert parse_response(body(), OLD)["complete"] is True
    today = datetime.now(timezone.utc).date()
    assert parse_response(body(today - timedelta(days=2)), today - timedelta(days=2))["complete"] is False
    assert parse_response(body(null_var="wind_gusts_10m"), OLD)["complete"] is False
    assert parse_response(body(n=23), OLD)["complete"] is False


def test_failures_return_none_and_never_raise():
    assert client_for(lambda r: httpx.Response(500)).fetch_day(407, -740, OLD) is None
    assert client_for(lambda r: httpx.Response(200, content=b"<html>")).fetch_day(407, -740, OLD) is None
    assert client_for(lambda r: httpx.Response(200, json={"error": True, "reason": "x"})).fetch_day(407, -740, OLD) is None
    assert client_for(lambda r: httpx.Response(200, json={"hourly": {}})).fetch_day(407, -740, OLD) is None

    def boom(req):
        raise httpx.ConnectError("down")

    assert client_for(boom).fetch_day(407, -740, OLD) is None


def test_missing_variable_series_become_none_not_zero():
    b = body()
    del b["hourly"]["pressure_msl"]
    out = parse_response(b, OLD)
    assert out["hourly"][BASE]["pressure_msl"] is None


def test_request_budget_stops_calls_without_a_request(monkeypatch):
    monkeypatch.setattr(wc, "_MAX_PER_MINUTE", 2)
    n = []

    def handler(req):
        n.append(1)
        return httpx.Response(200, json=body())

    c = client_for(handler)
    assert c.fetch_day(407, -740, OLD) and c.fetch_day(407, -740, OLD)
    assert c.fetch_day(407, -740, OLD) is None
    assert len(n) == 2


def test_daily_budget(monkeypatch):
    monkeypatch.setattr(wc, "_MAX_PER_DAY", 1)
    c = client_for(lambda r: httpx.Response(200, json=body()))
    assert c.fetch_day(407, -740, OLD) is not None
    assert c.fetch_day(407, -740, OLD) is None


def test_attribution_text_credits_the_provider_and_licence():
    assert "Open-Meteo.com" in ATTRIBUTION and "CC BY 4.0" in ATTRIBUTION
