from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from catch.core.models import Activity, ActivitySamples, ActivityTrack, ActivityWeather, Route
from catch.sync.routes import (
    assign_all_routes, assign_route, create_route_from_activity, list_routes, route_for_activity,
    route_history, set_route, unpin_route, update_route,
)
from catch.sync.tracks import ingest_track
from tests.test_fit_parse import FakeDataMessage
from tests.test_fit_track_parse import semi
from tests.test_weather_sync import _patch_fitdecode_for, _restore_fitdecode  # noqa: F401

M = 111194.93
L = [(45.0, -73.0), (45.0, -72.98), (45.01, -72.98)]
ELSEWHERE = [(45.3, -73.0), (45.3, -72.98), (45.31, -72.98)]
D0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


def frames_for(waypoints, start, speed=4.0, dt=5.0):
    pts = []
    for (la, lo), (lb, lc) in zip(waypoints, waypoints[1:]):
        seg = math.hypot((lb - la) * M, (lc - lo) * M * math.cos(math.radians(la)))
        n = max(1, int(seg / (speed * dt)))
        pts += [(la + (lb - la) * i / n, lo + (lc - lo) * i / n) for i in range(n)]
    pts.append(waypoints[-1])
    return [FakeDataMessage("record", {"timestamp": start + timedelta(seconds=dt * i),
                                       "position_lat": semi(la), "position_long": semi(lo), "heart_rate": 140})
            for i, (la, lo) in enumerate(pts)]


def activity(session, tmp_path, ext, waypoints, day, *, family="rowing", type_="rowing_v2", speed=4.0, place="Westport", raw=None, extra_frames=(), canonical_id=None):
    start = D0 + timedelta(days=day)
    fit = tmp_path / f"{ext}.fit"
    fit.write_bytes(b"x")
    a = Activity(source="garmin", external_id=ext, type=type_, start=start, duration=900.0,
                 sport_family=family, fit_path=str(fit), canonical_id=canonical_id, raw_json=json.dumps({"locationName": place, **(raw or {})}))
    session.add(a)
    session.commit()
    session.refresh(a)
    _patch_fitdecode_for(frames_for(waypoints, start, speed=speed) + list(extra_frames))
    ingest_track(session, a)
    return a


def rid(session, a):
    return session.get(ActivityTrack, a.id).route_id


def test_a_single_session_is_never_a_route(session, tmp_path):
    a = activity(session, tmp_path, "a", L, 0)
    assert rid(session, a) is None
    assert session.exec(select(Route)).all() == []


def test_second_aligned_session_forms_a_route_and_a_third_joins_it(session, tmp_path):
    a = activity(session, tmp_path, "a", L, 0)
    b = activity(session, tmp_path, "b", L, 3, speed=3.5)
    assert rid(session, a) == rid(session, b) is not None
    routes = session.exec(select(Route)).all()
    assert len(routes) == 1 and routes[0].name is None
    assert routes[0].auto_label.startswith("Westport · ") and "km" in routes[0].auto_label
    c = activity(session, tmp_path, "c", L, 6, speed=4.2)
    assert rid(session, c) == routes[0].id and len(session.exec(select(Route)).all()) == 1


def test_a_different_course_stays_unassigned(session, tmp_path):
    activity(session, tmp_path, "a", L, 0)
    activity(session, tmp_path, "b", L, 1)
    far = activity(session, tmp_path, "far", ELSEWHERE, 2)
    assert rid(session, far) is None


def test_non_rowing_never_gets_routes(session, tmp_path):
    a = activity(session, tmp_path, "r1", L, 0, family="running", type_="running", speed=3.0)
    b = activity(session, tmp_path, "r2", L, 1, family="running", type_="running", speed=3.0)
    assert rid(session, a) is None and rid(session, b) is None
    assert session.exec(select(Route)).all() == []
    assert "signature" not in json.loads(session.get(ActivityTrack, a.id).summary_json)


def test_pinning_overrides_auto_matching_and_unpin_restores_it(session, tmp_path):
    a = activity(session, tmp_path, "a", L, 0)
    b = activity(session, tmp_path, "b", L, 1)
    route_id = rid(session, a)
    set_route(session, b, None)  # athlete says: not this route
    row = session.get(ActivityTrack, b.id)
    assert row.route_id is None and row.route_pinned is True
    assign_route(session, b)
    assert rid(session, b) is None  # auto leaves a pinned track alone
    assert unpin_route(session, b) == route_id
    assert session.get(ActivityTrack, b.id).route_pinned is False


def test_set_route_validates(session, tmp_path):
    a = activity(session, tmp_path, "a", L, 0)
    with pytest.raises(KeyError):
        set_route(session, a, 999)
    bare = Activity(source="garmin", external_id="bare", type="rowing_v2", start=D0)
    session.add(bare)
    session.commit()
    session.refresh(bare)
    with pytest.raises(KeyError):
        set_route(session, bare, None)


def test_create_a_named_route_from_one_session(session, tmp_path):
    a = activity(session, tmp_path, "a", L, 0)
    r = create_route_from_activity(session, a, "  Sunday loop ")
    assert r.name == "Sunday loop" and rid(session, a) == r.id
    assert route_for_activity(session, a)["display_name"] == "Sunday loop"
    assert route_for_activity(session, a)["name_is_manual"] is True


def test_rename_and_tag_a_route_dedupes_and_can_clear_the_name(session, tmp_path):
    a = activity(session, tmp_path, "a", L, 0)
    activity(session, tmp_path, "b", L, 1)
    route = session.get(Route, rid(session, a))
    update_route(session, route, name="Home course", set_name=True, tags=["Steady", "steady", " ", "Lake"])
    assert route.name == "Home course" and json.loads(route.tags_json) == ["Steady", "steady", "Lake"]
    update_route(session, route, name="", set_name=True)
    assert route.name is None
    assert route_for_activity(session, a)["display_name"].startswith("Westport")  # auto label, flagged not manual
    assert route_for_activity(session, a)["name_is_manual"] is False


def test_assign_all_is_idempotent(session, tmp_path):
    for i, ext in enumerate("abc"):
        activity(session, tmp_path, ext, L, i)
    first = assign_all_routes(session)
    assert first["routes"] == 1
    assert assign_all_routes(session) == {"routes": 1, "new": 0}


def test_history_lists_sessions_best_and_context(session, tmp_path):
    a = activity(session, tmp_path, "a", L, 0, speed=3.0)
    b = activity(session, tmp_path, "b", L, 7, speed=4.0)
    c = activity(session, tmp_path, "c", L, 14, speed=3.5)
    session.add(ActivityWeather(activity_id=b.id, status="ok", provider="open-meteo", attribution="x",
                                summary_json=json.dumps({"temperature_c": {"avg": 15.0},
                                                         "wind": {"speed_kmh": 9.0, "direction_from_label": "NW"},
                                                         "precipitation_mm": 0.0, "condition": {"text": "Clear sky"}})))
    session.commit()
    route = session.get(Route, rid(session, a))
    h = route_history(session, route)
    assert [s["activity_id"] for s in h["sessions"]] == [c.id, b.id, a.id]  # newest first
    assert h["stats"]["best"]["activity_id"] == b.id
    assert h["stats"]["n_sessions"] == 3
    assert h["stats"]["source"] == "gps_derived"
    assert next(s for s in h["sessions"] if s["activity_id"] == b.id)["weather"]["wind_speed_kmh"] == 9.0
    assert next(s for s in h["sessions"] if s["activity_id"] == a.id)["weather"] is None  # missing stays missing
    assert h["confidence"] == "insufficient_data"  # no wellness history in a test DB: the ladder says so
    assert "aligned" in h["comparison"]
    assert any("corrected" in c for c in h["stats"]["caveats"])


def test_list_routes_counts_sessions(session, tmp_path):
    activity(session, tmp_path, "a", L, 0)
    activity(session, tmp_path, "b", L, 1)
    rows = list_routes(session)
    assert len(rows) == 1 and rows[0]["n_sessions"] == 2 and rows[0]["length_source"] == "gps_derived"


def test_rows_with_a_null_sport_family_still_get_routes_and_the_rowing_ceiling(session, tmp_path):
    """Activities that predate the sport_family column have it NULL; it must be derived from
    source+type (found by running the backfill on a copy of the real, older database)."""
    from catch.sync.tracks import filtered_for

    a = activity(session, tmp_path, "old1", L, 0, family=None)
    b = activity(session, tmp_path, "old2", L, 1, family=None)
    assert a.sport_family is None
    assert rid(session, a) == rid(session, b) is not None
    assert filtered_for(session, a, session.get(ActivityTrack, a.id)).report["ceiling_mps"] == 10.0


def test_two_devices_recording_one_outing_are_not_a_repeat(session, tmp_path):
    """Routes form at ingest, before matching merges the two recordings into one canonical, so the
    guard has to work from time overlap alone (both rows start at the same moment here)."""
    a = activity(session, tmp_path, "dev1", L, 0)
    b = activity(session, tmp_path, "dev2", L, 0)
    assert a.canonical_id is None and b.canonical_id is None
    assert session.exec(select(Route)).all() == []
    from catch.sync.routes import assign_all_routes

    assert assign_all_routes(session)["routes"] == 0
    c = activity(session, tmp_path, "later", L, 5)  # a genuine second outing on another day still pairs up
    assert rid(session, c) is not None and len(session.exec(select(Route)).all()) == 1


def test_already_merged_rows_never_pair_even_if_their_times_differ(session, tmp_path):
    a = activity(session, tmp_path, "m1", L, 0, canonical_id=5)
    b = activity(session, tmp_path, "m2", L, 3, canonical_id=5)
    assert rid(session, a) is None and rid(session, b) is None


def test_history_counts_a_merged_outing_once(session, tmp_path):
    a = activity(session, tmp_path, "a", L, 0)
    b = activity(session, tmp_path, "b", L, 7)
    c = activity(session, tmp_path, "c", L, 7)  # second device, same outing as b
    route = session.get(Route, rid(session, a))
    for x, cid in ((a, 1), (b, 2), (c, 2)):
        x.canonical_id = cid
        session.add(x)
    cr = session.get(ActivityTrack, c.id)
    cr.route_id = route.id
    session.add(cr)
    session.commit()
    h = route_history(session, route)
    assert h["stats"]["n_sessions"] == 2 and len(h["sessions"]) == 2


def test_a_late_duplicate_recording_does_not_join_the_route_its_twin_is_on(session, tmp_path):
    a = activity(session, tmp_path, "a", L, 0)
    b = activity(session, tmp_path, "b", L, 4)
    route_id = rid(session, a)
    assert route_id is not None and rid(session, b) == route_id
    twin = activity(session, tmp_path, "b-watch2", L, 4)  # same moment as b, second device
    assert rid(session, twin) is None
    assert len(session.exec(select(Route)).all()) == 1
