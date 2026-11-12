from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import HTTPException

from catch.coach import tools
from catch.coach.chat import _tool_label
from catch.sync.weather import ensure_weather
from tests.test_api_gps import make_activity, canon, L, _restore_fitdecode  # noqa: F401
from tests.test_weather_sync import FakeClient
from datetime import datetime, timezone

NEW = ("get_route", "get_route_history", "get_on_water_metrics", "get_workout_weather")


def test_new_tools_are_registered_read_only_with_required_ids():
    for name in NEW:
        spec = tools.TOOLS[name]
        assert spec["write"] is False
        assert spec["input_schema"]["additionalProperties"] is False
    assert tools.TOOLS["get_route"]["input_schema"]["required"] == ["activity_id"]
    assert tools.TOOLS["get_route_history"]["input_schema"]["required"] == ["route_id"]
    assert "split_m" in tools.TOOLS["get_on_water_metrics"]["input_schema"]["properties"]
    assert len(tools.TOOLS) == 40


def test_descriptions_state_the_observed_vs_inferred_rules():
    assert "no coordinates" in tools.TOOLS["get_route"]["description"].lower()
    w = tools.TOOLS["get_workout_weather"]["description"]
    assert "never a performance correction" in w and "inference" in w
    assert "NOT wind-" in tools.TOOLS["get_route_history"]["description"]


def test_get_route_returns_an_area_and_no_track(session, tmp_path):
    a = make_activity(session, tmp_path, "a", L, 0, raw={"distance": 2686.0})
    cid = canon(session, a)
    out = tools.call_tool(session, "get_route", {"activity_id": cid})
    assert out["has_track"] is True and out["area"]["place_name"] == "Westport"
    flat = json.dumps(out)
    for banned in ('"points"', '"signature"', '"reference"', '"polyline"', '"bounds"'):
        assert banned not in flat


def test_get_on_water_metrics_and_split_arg(session, tmp_path):
    a = make_activity(session, tmp_path, "a", L, 0)
    cid = canon(session, a)
    out = tools.call_tool(session, "get_on_water_metrics", {"activity_id": cid, "split_m": 1000})
    assert out["splits"]["split_m"] == 1000
    assert out["metrics"]["distance_m"]["source"] == "gps_derived"
    assert out["environment_corrected"] is False


def test_no_gps_is_reported_not_guessed(session):
    from catch.core.models import Activity

    erg = Activity(source="garmin", external_id="e", type="indoor_rowing", start=datetime.now(timezone.utc), duration=600.0)
    session.add(erg)
    session.commit()
    cid = canon(session, erg)
    assert tools.call_tool(session, "get_route", {"activity_id": cid})["has_track"] is False
    assert tools.call_tool(session, "get_on_water_metrics", {"activity_id": cid})["has_track"] is False
    w = tools.call_tool(session, "get_workout_weather", {"activity_id": cid})
    assert w["status"] == "no_gps" and w["weather"] is None


def test_weather_tool_distinguishes_missing_from_observed(session, tmp_path):
    a = make_activity(session, tmp_path, "a", L, 0)
    cid = canon(session, a)
    first = tools.call_tool(session, "get_workout_weather", {"activity_id": cid})
    assert first["status"] == "not_fetched" and first["weather"] is None
    ensure_weather(session, a, FakeClient(), now=datetime(2026, 11, 11, tzinfo=timezone.utc))
    second = tools.call_tool(session, "get_workout_weather", {"activity_id": cid})
    assert second["status"] == "ok" and second["source"] == "provider_reanalysis"
    assert "Open-Meteo" in second["attribution"] and second["weather"]["wind"]["direction_from_label"] == "W"


def test_route_history_tool_and_unknown_ids(session, tmp_path):
    a = make_activity(session, tmp_path, "a", L, 0)
    make_activity(session, tmp_path, "b", L, 3, speed=3.0)
    canon(session, a)
    from catch.core.models import ActivityTrack

    route_id = session.get(ActivityTrack, a.id).route_id
    out = tools.call_tool(session, "get_route_history", {"route_id": route_id})
    assert out["stats"]["n_sessions"] == 2 and out["stats"]["source"] == "gps_derived"
    assert any("corrected" in c for c in out["stats"]["caveats"])
    with pytest.raises(HTTPException):
        tools.call_tool(session, "get_route_history", {"route_id": 999})
    with pytest.raises(HTTPException):
        tools.call_tool(session, "get_route", {"activity_id": 999})


def test_chip_labels():
    assert _tool_label("get_route", {"activity_id": 7}) == "Read the GPS route of workout #7"
    assert _tool_label("get_workout_weather", {"activity_id": 7}) == "Read weather for workout #7"


def test_system_prompt_separates_observed_from_inferred():
    from pathlib import Path

    text = (Path(tools.__file__).parent / "system_prompt.md").read_text()
    assert "## On-water, routes & weather" in text
    assert "is your inference" in text and "wind-, current- or water-corrected" in text


def test_mcp_exposes_the_same_names():
    from catch.mcp_server.server import build_server

    class Backend:
        async def call_tool(self, name, args):
            return {}

    names = {t.name for t in asyncio.run(build_server(Backend()).list_tools())}
    assert names == set(tools.TOOLS) and set(NEW) <= names


def test_split_m_bounds_hold_on_the_tool_path_too(session, tmp_path):
    a = make_activity(session, tmp_path, "a", L, 0)
    cid = canon(session, a)
    for bad in (1, 49, 10001):
        with pytest.raises(ValueError, match="between 50 and 10000"):
            tools.call_tool(session, "get_on_water_metrics", {"activity_id": cid, "split_m": bad})
    assert tools.call_tool(session, "get_on_water_metrics", {"activity_id": cid, "split_m": 50})["splits"]["split_m"] == 50
    assert tools.TOOLS["get_on_water_metrics"]["input_schema"]["properties"]["split_m"]["minimum"] == 50


def test_a_split_that_would_make_thousands_of_rows_is_refused(session, tmp_path, monkeypatch):
    from catch.api import routes_gps

    a = make_activity(session, tmp_path, "a", L, 0)
    cid = canon(session, a)
    monkeypatch.setattr(routes_gps, "SPLIT_ROWS_MAX", 10)  # the 2.7 km course at 100 m would be 27 rows
    with pytest.raises(ValueError, match="more than"):
        tools.call_tool(session, "get_on_water_metrics", {"activity_id": cid, "split_m": 100})
