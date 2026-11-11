from __future__ import annotations

import json
from datetime import timedelta

import pytest

from catch.core.models import Activity, ActivityTrack, Route
from catch.core.settings_store import update_settings
from catch.sync.matching import run_matching
from catch.sync.samples import store_samples
from catch.sync.weather_client import ATTRIBUTION, OpenMeteoClient
from conftest import TEST_PASSWORD
from tests.test_fit_parse import FakeDataMessage
from tests.test_routes_sync import D0, L, activity as make_activity, rid  # noqa: F401
from tests.test_routes_sync import _restore_fitdecode  # noqa: F401
from tests.test_weather_sync import FakeClient


def login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def canon(session, a):
    run_matching(session)
    session.refresh(a)
    return a.canonical_id


def test_every_endpoint_requires_auth(client):
    for path in ("/api/activities/1/track", "/api/activities/1/on-water", "/api/activities/1/weather",
                 "/api/routes", "/api/routes/1", "/api/routes/1/history"):
        assert client.get(path).status_code == 401, path


def test_track_payload_for_an_on_water_row(client, session, tmp_path):
    a = make_activity(session, tmp_path, "a", L, 0, raw={"distance": 2000.0})
    cid = canon(session, a)
    login(client)
    body = client.get(f"/api/activities/{cid}/track", params={"points": 100}).json()
    assert body["has_track"] is True and body["sport_family"] == "rowing"
    assert body["pace_unit"] == "s_per_500m"
    assert 3 <= body["returned_count"] <= 100 and body["accepted_count"] > 100
    p = body["points"][0]
    assert {"elapsed_s", "lat", "lon", "distance_m", "speed_mps", "pace", "hr", "elevation_m"} <= set(p)
    assert p["hr"] == 140.0 and p["elevation_m"] is None  # absent altitude stays None, never 0
    assert body["bounds"]["min_lat"] <= body["start"]["lat"] <= body["bounds"]["max_lat"]
    assert body["filter_report"]["records_without_fix"] == 0
    assert body["filter_report"]["accuracy_reported"] is False
    assert body["provenance"]["speed_pace_distance"] == "gps_derived"
    assert client.get(f"/api/activities/{cid}").json()["has_track"] is True


def test_on_water_metrics_label_every_source_and_never_claim_a_correction(client, session, tmp_path):
    raw = {"distance": 2010.0, "movingDuration": 700.0, "maxSpeed": 4.4, "averageSpeed": 2.9}
    a = make_activity(session, tmp_path, "a", L, 0, raw=raw)
    cid = canon(session, a)
    login(client)
    body = client.get(f"/api/activities/{cid}/on-water").json()
    assert body["detection"] == {"kind": "on_water", "basis": "garmin_type", "category": "on_water"}
    m = body["metrics"]
    assert m["distance_m"]["source"] == "gps_derived" and m["avg_speed_mps"]["source"] == "gps_derived"
    assert m["provider"]["distance_m"] == {"value": 2010.0, "source": "provider", "method": "garmin"}
    assert m["provider"]["moving_s"]["value"] == 700.0
    expected = (m["distance_m"]["value"] - 2010.0) / 2010.0 * 100
    assert m["distance_delta_vs_provider_pct"] == pytest.approx(expected)
    assert m["distance_m"]["value"] == pytest.approx(2686, rel=0.03)  # the L course: 1574 m east + 1112 m north
    assert body["pace"]["unit"] == "s_per_500m" and body["pace"]["source"] == "gps_derived"
    assert body["splits"]["split_m"] == 500 and body["splits"]["splits"][0]["pace"]["unit"] == "s_per_500m"
    assert all(s["source"] == "gps_derived" for s in body["splits"]["splits"])
    assert body["environment_corrected"] is False and "not corrected" in body["environment_note"]
    assert body["laps"] == {"usable": False, "count": 0, "rows": [],
                            "note": "Only one lap recorded — no lap or interval breakdown to show."}
    assert body["weather"] is None and body["route"] is None


def test_split_distance_is_configurable_and_validated(client, session, tmp_path):
    a = make_activity(session, tmp_path, "a", L, 0)
    cid = canon(session, a)
    login(client)
    s250 = client.get(f"/api/activities/{cid}/on-water", params={"split_m": 250}).json()["splits"]
    s1000 = client.get(f"/api/activities/{cid}/on-water", params={"split_m": 1000}).json()["splits"]
    assert s250["split_m"] == 250 and len(s250["splits"]) > len(s1000["splits"])
    assert client.get(f"/api/activities/{cid}/on-water", params={"split_m": 5}).status_code == 422


def test_laps_are_listed_only_when_there_are_at_least_two(client, session, tmp_path):
    from tests.test_fit_track_parse import T0  # noqa: F401

    start = D0
    laps = [FakeDataMessage("lap", {"start_time": start, "total_elapsed_time": 300.0, "total_distance": 1100.0}),
            FakeDataMessage("lap", {"start_time": start + timedelta(seconds=300), "total_elapsed_time": 300.0,
                                    "total_distance": 400.0})]
    a = make_activity(session, tmp_path, "a", L, 0, extra_frames=laps)
    cid = canon(session, a)
    login(client)
    body = client.get(f"/api/activities/{cid}/on-water").json()["laps"]
    assert body["usable"] is True and body["count"] == 2 and len(body["rows"]) == 2
    assert body["rows"][0]["provider"]["distance_m"] == 1100.0  # the lap's own number, kept separate
    assert body["rows"][0]["gps_distance_m"] != body["rows"][0]["provider"]["distance_m"]


def test_gps_running_activity_gets_a_map_and_metrics_but_no_route(client, session, tmp_path):
    a = make_activity(session, tmp_path, "r", L, 0, family="running", type_="running", speed=3.0)
    cid = canon(session, a)
    login(client)
    t = client.get(f"/api/activities/{cid}/track").json()
    assert t["has_track"] is True and t["pace_unit"] == "s_per_km"
    ow = client.get(f"/api/activities/{cid}/on-water").json()
    assert ow["route"] is None and ow["detection"]["kind"] == "unknown"
    assert ow["likely_rowing"]["kind"] == "inference"
    assert client.put(f"/api/activities/{cid}/route", json={"new_route": True}).status_code == 409


def test_indoor_and_unprocessed_activities_say_why_there_is_no_track(client, session, tmp_path):
    erg = Activity(source="garmin", external_id="erg", type="indoor_rowing", start=D0, duration=600.0)
    raw_only = Activity(source="garmin", external_id="nofit", type="rowing_v2", start=D0 + timedelta(days=1), duration=600.0)
    session.add_all([erg, raw_only])
    session.commit()
    session.add(ActivityTrack(activity_id=erg.id, start=D0, n_points=0, n_records=500))
    session.commit()
    c1, c2 = canon(session, erg), canon(session, raw_only)
    login(client)
    t1 = client.get(f"/api/activities/{c1}/track").json()
    assert t1 == {"has_track": False, "reason": "no_gps_recorded", "message": "No GPS track was recorded for this activity."}
    assert client.get(f"/api/activities/{c2}/track").json()["reason"] == "not_processed"
    assert client.get(f"/api/activities/{c1}/on-water").json()["detection"]["kind"] == "erg"
    assert client.get(f"/api/activities/{c1}").json()["has_track"] is False
    assert client.get("/api/activities/9999/track").status_code == 404


def test_existing_samples_endpoint_is_untouched_by_a_track(client, session, tmp_path):
    a = make_activity(session, tmp_path, "a", L, 0)
    store_samples(session, a.id, start=a.start, hr=[130.0 + i % 9 for i in range(900)],
                  power=[None] * 900, cadence=[22.0] * 900)
    cid = canon(session, a)
    login(client)
    body = client.get(f"/api/activities/{cid}/samples", params={"points": 100}).json()
    assert body["has_data"] is True and body["returned_count"] <= 100
    assert set(body["points"][0]) == {"elapsed_s", "hr", "power", "cadence"}


def test_weather_states_and_attribution(client, session, tmp_path, monkeypatch):
    a = make_activity(session, tmp_path, "a", L, 0)
    cid = canon(session, a)
    login(client)
    w = client.get(f"/api/activities/{cid}/weather").json()
    assert w["status"] == "not_fetched" and w["weather"] is None and w["attribution"] == ATTRIBUTION
    # provider unreachable (conftest stub returns None): an honest 503, nothing stored
    assert client.post(f"/api/activities/{cid}/weather/refresh").status_code == 503
    assert client.get(f"/api/activities/{cid}/weather").json()["status"] == "not_fetched"

    fake = FakeClient()
    monkeypatch.setattr(OpenMeteoClient, "fetch_day", lambda self, la, lo, d: fake.fetch_day(la, lo, d))
    ok = client.post(f"/api/activities/{cid}/weather/refresh").json()
    assert ok["status"] == "ok" and ok["attribution"] == ATTRIBUTION and ok["attribution_url"].startswith("https://open-meteo.com")
    assert ok["weather"]["wind"]["speed_kmh"] == pytest.approx(18.0)
    assert "performance correction" in ok["disclaimer"]
    # the brief rides along on the on-water payload
    assert client.get(f"/api/activities/{cid}/on-water").json()["weather"]["wind_speed_kmh"] == pytest.approx(18.0)

    update_settings(session, {"on_water": {"weather_enabled": False}})
    assert client.post(f"/api/activities/{cid}/weather/refresh").status_code == 409


def test_weather_for_an_activity_without_gps_is_explicit(client, session):
    erg = Activity(source="garmin", external_id="e", type="indoor_rowing", start=D0, duration=600.0)
    session.add(erg)
    session.commit()
    cid = canon(session, erg)
    login(client)
    w = client.get(f"/api/activities/{cid}/weather").json()
    assert w["status"] == "no_gps" and w["weather"] is None and w["attribution"] == ATTRIBUTION


def test_routes_list_detail_edit_and_history(client, session, tmp_path):
    a = make_activity(session, tmp_path, "a", L, 0, speed=3.0)
    b = make_activity(session, tmp_path, "b", L, 7, speed=4.0)
    cid_a, cid_b = canon(session, a), canon(session, b)
    login(client)
    routes = client.get("/api/routes").json()["routes"]
    assert len(routes) == 1 and routes[0]["n_sessions"] == 2
    route_id = routes[0]["id"]
    detail = client.get(f"/api/routes/{route_id}").json()
    assert len(detail["reference"]) == 64 and detail["name_is_manual"] is False

    patched = client.patch(f"/api/routes/{route_id}", json={"name": "Home course", "tags": ["steady", "lake"]}).json()
    assert patched["display_name"] == "Home course" and patched["tags"] == ["steady", "lake"]
    assert client.patch(f"/api/routes/{route_id}", json={"tags": ["x"]}).json()["name"] == "Home course"  # name untouched
    assert client.patch(f"/api/routes/{route_id}", json={"name": None}).json()["name"] is None  # explicit clear

    h = client.get(f"/api/routes/{route_id}/history").json()
    assert h["stats"]["best"]["canonical_id"] == cid_b and h["stats"]["n_sessions"] == 2
    assert h["stats"]["source"] == "gps_derived" and h["sessions"][0]["canonical_id"] == cid_b
    on_water = client.get(f"/api/activities/{cid_a}/on-water").json()
    assert on_water["route"]["id"] == route_id
    assert client.get("/api/routes/999").status_code == 404
    assert client.get("/api/routes/999/history").status_code == 404
    assert client.patch("/api/routes/999", json={"name": "x"}).status_code == 404


def test_assigning_creating_and_unpinning_a_route_by_hand(client, session, tmp_path):
    a = make_activity(session, tmp_path, "a", L, 0)
    b = make_activity(session, tmp_path, "b", L, 1)
    cid_a, cid_b = canon(session, a), canon(session, b)
    login(client)
    route_id = rid(session, a)
    assert client.put(f"/api/activities/{cid_b}/route", json={"route_id": None}).json()["route"] is None
    assert session.get(ActivityTrack, b.id).route_pinned is True
    back = client.put(f"/api/activities/{cid_b}/route", json={"unpin": True}).json()["route"]
    assert back["id"] == route_id
    assert client.put(f"/api/activities/{cid_a}/route", json={"route_id": 999}).status_code == 404
    made = client.put(f"/api/activities/{cid_a}/route", json={"new_route": True, "name": "Solo"}).json()["route"]
    assert made["display_name"] == "Solo" and made["id"] != route_id


def test_coach_route_summary_carries_no_track_coordinates(session, tmp_path):
    from catch.api.routes_gps import build_route_summary

    a = make_activity(session, tmp_path, "a", L, 0, raw={"distance": 2010.0})
    cid = canon(session, a)
    out = build_route_summary(session, cid)
    text = json.dumps(out)
    assert out["has_track"] is True and out["area"]["place_name"] == "Westport"
    for banned in ("points", "polyline", "signature", "reference", "bounds", "start", "end"):
        assert banned not in out and f'"{banned}"' not in text
    c = out["area"]["approx_center"]
    assert round(c["lat"], 1) == c["lat"] and round(c["lon"], 1) == c["lon"]
    assert out["gps_distance_m"]["source"] == "gps_derived" and out["provider_distance_m"]["source"] == "provider"


def test_too_many_splits_is_a_422_not_a_500(client, session, tmp_path, monkeypatch):
    from catch.api import routes_gps

    a = make_activity(session, tmp_path, "a", L, 0)
    cid = canon(session, a)
    monkeypatch.setattr(routes_gps, "SPLIT_ROWS_MAX", 10)
    login(client)
    r = client.get(f"/api/activities/{cid}/on-water", params={"split_m": 100})
    assert r.status_code == 422 and "larger split" in r.json()["detail"]
