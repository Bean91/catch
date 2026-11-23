"""Session 36: personal records (catch/sync/records.py) and the Performance Lab (catch/analytics|sync/performance_lab.py)."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from catch.analytics import performance_lab as lab
from catch.core.models import Activity, CanonicalActivity, Piece, Stroke
from catch.sync import records as rec
from catch.sync.matching import run_matching
from conftest import TEST_PASSWORD


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def _c2(session, ext, day: date, distance, duration, *, type_="rower", wt="JustRow", watts=None, hr=None, verified=None, tags=None, exclude=False):
    a = Activity(source="concept2", external_id=ext, type=type_, workout_type=wt, start=datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=9),
                 distance=distance, duration=duration, avg_power=watts, avg_hr=hr, c2_verified=verified)
    session.add(a)
    session.commit()
    run_matching(session)
    session.refresh(a)
    if tags or exclude:
        c = session.get(CanonicalActivity, a.canonical_id)
        ov = {}
        if tags:
            ov["tags"] = tags
        if exclude:
            ov["exclude_from_totals"] = True
        c.overrides_json = json.dumps(ov)
        session.add(c)
        session.commit()
    return a


D0 = date(2026, 3, 1)


def test_records_label_dedupe_history_and_exclusions(session):
    _c2(session, "a", D0, 2000, 430.0, watts=280, tags=["test"], verified=True)
    _c2(session, "b", D0 + timedelta(days=30), 2005, 425.0, watts=290)  # within tolerance, faster: a new best
    _c2(session, "c", D0 + timedelta(days=40), 2000, 410.0, watts=320, exclude=True)  # excluded: never a record
    _c2(session, "d", D0 + timedelta(days=50), 10000, 2400.0, watts=210)
    _c2(session, "e", D0 + timedelta(days=60), 4000, 1000.0, wt="FixedDistanceInterval", watts=300)  # interval: never
    r = rec.records(session, "rowing_erg")
    two = next(x for x in r["distance"] if x["key"] == "2000m")
    assert two["best"]["duration_s"] == 425.0 and two["best"]["label"] == "training"
    assert [h["duration_s"] for h in two["history"]] == [430.0, 425.0]
    assert two["history"][0]["label"] == "test" and two["history"][0]["verified"] is True
    assert two["count"] == 2
    ten = next(x for x in r["distance"] if x["key"] == "10000m")
    assert ten["best"]["ref"].startswith("/workouts/")
    power20 = next(x for x in r["power"] if x["key"] == "20min_power")
    assert power20["best"]["avg_watts"] == 210  # the only effort of 20 min or more
    power1 = next(x for x in r["power"] if x["key"] == "1min_power")
    assert power1["best"]["avg_watts"] == 290 and power1["best"]["watts_basis"] == "measured"


def test_bike_records_are_their_own_and_per_1000m(session):
    _c2(session, "bk", D0, 10000, 1200.0, type_="bike", watts=230)
    _c2(session, "rw", D0, 2000, 430.0, watts=280)
    bike = rec.records(session, "bike")
    ten = next(x for x in bike["distance"] if x["key"] == "10000m")
    assert ten["best"]["pace_s"] == pytest.approx(120.0) and ten["best"]["split_m"] == 1000.0
    assert all(x["best"] is None for x in bike["distance"] if x["key"] == "2000m")  # a rowing 2k never lands on a bike board
    rowing_10k = next(x for x in rec.records(session)["distance"] if x["key"] == "10000m")
    assert rowing_10k["best"] is None


def test_pieces_are_labelled_and_their_rowing_watts_marked_derived(session):
    host = _c2(session, "host", D0, 8000, 2100.0, wt="JustRow")
    p = Piece(canonical_id=host.canonical_id, piece_type="2000m", distance_m=2000.0, duration_s=420.0, avg_watts=302.3, splits_json="[]", modality="rowing_erg")
    session.add(p)
    session.commit()
    best = next(x for x in rec.records(session)["distance"] if x["key"] == "2000m")["best"]
    assert best["label"] == "piece" and best["watts_basis"] == "derived" and best["ref"] == f"/tests/piece/{p.id}"


def test_records_window(session):
    _c2(session, "old", D0, 2000, 400.0)
    _c2(session, "new", D0 + timedelta(days=200), 2000, 420.0)
    r = rec.records(session, "rowing_erg", start=D0 + timedelta(days=100))
    assert next(x for x in r["distance"] if x["key"] == "2000m")["best"]["duration_s"] == 420.0


def test_api_records_and_pbs_shape(client, session):
    _c2(session, "x", D0, 2000, 430.0)
    _login(client)
    body = client.get("/api/records").json()
    assert {x["key"] for x in body["distance"]} >= {"10000m", "2000m"}
    pbs = client.get("/api/pbs").json()
    assert pbs["2000m"]["duration_s"] == 430.0 and "10000m" in pbs
    assert client.get("/api/records", params={"modality": "ski"}).status_code == 422


# --- Lab: pure rules ---------------------------------------------------------------------------------------------


def test_hr_at_workload_needs_two_sessions_each_side():
    split = date(2026, 6, 1)
    s = [
        {"date": date(2026, 5, 1), "avg_watts": 205, "avg_hr": 150, "ref": "/workouts/1"},
        {"date": date(2026, 5, 8), "avg_watts": 210, "avg_hr": 152, "ref": "/workouts/2"},
        {"date": date(2026, 6, 8), "avg_watts": 212, "avg_hr": 145, "ref": "/workouts/3"},
        {"date": date(2026, 6, 15), "avg_watts": 208, "avg_hr": 147, "ref": "/workouts/4"},
        {"date": date(2026, 6, 15), "avg_watts": 250, "avg_hr": 165, "ref": "/workouts/5"},
    ]
    out = lab.hr_at_workload(s, split)
    b200 = next(b for b in out if b["band_w"] == [200, 220])
    assert b200["earlier"]["median_hr"] == 151 and b200["recent"]["median_hr"] == 146 and b200["hr_change_bpm"] == -5
    b240 = next(b for b in out if b["band_w"] == [240, 260])
    assert b240["recent"]["median_hr"] is None and b240["hr_change_bpm"] is None  # one session: no figure


def test_split_by_rate_is_stroke_weighted_and_thresholded():
    split = date(2026, 6, 1)
    rows = [
        {"session": 1, "date": date(2026, 5, 1), "band": 20, "strokes": 40, "pace_sum": 40 * 120.0},
        {"session": 2, "date": date(2026, 5, 2), "band": 20, "strokes": 40, "pace_sum": 40 * 118.0},
        {"session": 3, "date": date(2026, 6, 2), "band": 20, "strokes": 100, "pace_sum": 100 * 116.0},
        {"session": 4, "date": date(2026, 6, 3), "band": 20, "strokes": 20, "pace_sum": 20 * 110.0},
        {"session": 5, "date": date(2026, 6, 3), "band": 30, "strokes": 500, "pace_sum": 500 * 100.0},
    ]
    out = {tuple(b["band_spm"]): b for b in lab.split_by_rate(rows, split)}
    assert out[(20, 22)]["earlier"]["split_s"] == pytest.approx(119.0)
    assert out[(20, 22)]["recent"]["split_s"] == pytest.approx((100 * 116 + 20 * 110) / 120)
    assert out[(30, 32)]["recent"]["split_s"] is None  # one session only


# --- Lab: through the API, with real strokes --------------------------------------------------------------------


def test_lab_routes_with_real_data(client, session):
    today = date.today()
    for i, (days_ago, hr) in enumerate([(300, 152), (290, 150), (40, 145), (30, 143)]):
        a = _c2(session, f"s{i}", today - timedelta(days=days_ago), 6000, 1500.0, watts=205, hr=hr)
        for k in range(80):
            session.add(Stroke(activity_id=a.id, seq=k, t=k * 2.0, distance=k * 10.0, pace_500m=118.0 - (2 if days_ago < 100 else 0), stroke_rate=20.4, watts=205, hr=hr))
    session.commit()
    _login(client)
    hr = client.get("/api/lab/hr-at-workload").json()
    band = next(b for b in hr["bands"] if b["band_w"] == [200, 220])
    assert band["earlier"]["sessions"] == 2 and band["recent"]["sessions"] == 2 and band["hr_change_bpm"] == pytest.approx(-7)
    sr = client.get("/api/lab/split-by-rate").json()
    b20 = next(b for b in sr["bands"] if b["band_spm"] == [20, 22])
    assert b20["split_change_s"] == pytest.approx(-2.0)
    prog = client.get("/api/lab/progression").json()
    six = next(s for s in prog["series"] if s["key"] == "6000m")
    assert len(six["points"]) == 4 and six["points"][0]["new_best"] is True
