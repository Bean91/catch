"""Session 36 follow-up: the per-recording stroke summary (catch/analytics/stroke_summary.py, catch/sync/stroke_summary.py) — the
best-power curve's rules, the cached split-by-rate bands agreeing with a direct per-stroke count, and the cache's fill/invalidation."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import func
from sqlmodel import select

from catch.analytics import performance_lab as lab
from catch.analytics import stroke_summary as ss
from catch.core import localtime
from catch.core.models import Activity, Stroke
from catch.sync import stroke_summary
from catch.sync.matching import run_matching
from catch.sync.upsert import upsert_strokes
from conftest import TEST_PASSWORD


def _strokes(spec: list[tuple[float, float]], *, dt: float = 2.0, interval: int = 0, t0: float = 0.0) -> list[dict]:
    """`spec`: (seconds, watts) steps; one stroke every `dt` seconds."""
    out, t = [], t0
    for seconds, watts in spec:
        for _ in range(int(seconds / dt)):
            t += dt
            out.append({"t": t, "watts": watts, "interval_index": interval, "pace_500m": 120.0, "stroke_rate": 20.0})
    return out


# --- the curve -----------------------------------------------------------------------------------------------------


def test_constant_power_and_durations_only_when_covered():
    curve = ss.power_curve(_strokes([(700, 200.0)]))
    assert curve["10"] == curve["600"] == 200.0
    assert "1200" not in curve  # no continuous run of 20 minutes


def test_step_function_is_time_weighted():
    curve = ss.power_curve(_strokes([(60, 100.0), (60, 400.0)]))
    assert curve["60"] == pytest.approx(400.0)
    assert "120" not in curve  # the strokes span 2 s to 120 s: 118 s, just short of two minutes
    curve = ss.power_curve(_strokes([(60, 100.0), (64, 400.0)]))
    assert curve["120"] == pytest.approx((56 * 100 + 64 * 400) / 120, abs=0.2)


def test_a_window_never_spans_intervals_or_a_pause():
    two = _strokes([(300, 300.0)], interval=0) + _strokes([(300, 300.0)], interval=1)  # t restarts per interval
    curve = ss.power_curve(two)
    assert curve["120"] == 300.0 and "600" not in curve
    paused = _strokes([(200, 250.0)]) + _strokes([(200, 250.0)], t0=230.0)  # a 32 s pause
    assert "300" not in ss.power_curve(paused)


def test_missing_watts_break_the_run_and_bike_has_no_curve():
    strokes = _strokes([(100, 200.0)]) + [{"t": 102.0, "watts": None, "interval_index": 0, "pace_500m": None, "stroke_rate": 20.0}]
    strokes += _strokes([(100, 200.0)], t0=102.0)
    assert "120" not in ss.power_curve(strokes)
    assert ss.power_curve([{**s, "watts": None} for s in _strokes([(600, 200.0)])]) == {}


def test_rate_bands_round_half_up_and_filter():
    rows = [
        {"stroke_rate": 21.5, "pace_500m": 120.0},  # rounds to 22 -> band 22
        {"stroke_rate": 21.4, "pace_500m": 110.0},  # 21 -> band 20
        {"stroke_rate": 55.0, "pace_500m": 100.0},  # out of range
        {"stroke_rate": 20.0, "pace_500m": 400.0},  # a split slower than 5:00: out
    ]
    assert ss.rate_bands(rows) == {"22": [1, 120.0], "20": [1, 110.0]}


def test_best_curve_picks_the_source_and_halves():
    entries = [
        {"curve": {"60": 300.0, "600": 250.0}, "date": date(2026, 1, 5), "ref": "/workouts/1"},
        {"curve": {"60": 320.0}, "date": date(2026, 6, 5), "ref": "/workouts/2"},
    ]
    rows = {r["duration_s"]: r for r in ss.curve_halves(entries, date(2026, 4, 1))}
    assert rows[60]["best"]["ref"] == "/workouts/2" and rows[60]["earlier"]["watts"] == 300.0
    assert rows[600]["recent"] is None and rows[600]["best"]["watts"] == 250.0
    assert rows[3600]["best"] is None


# --- the cache -----------------------------------------------------------------------------------------------------


def _rower(session, ext: str, day: date) -> Activity:
    a = Activity(source="concept2", external_id=ext, type="rower", workout_type="JustRow",
                 start=datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=9), distance=6000, duration=1500.0)
    session.add(a)
    session.commit()
    run_matching(session)
    session.refresh(a)
    return a


def _c2_strokes(n: int, rate: float, pace: float) -> list[dict]:
    return [{"seq": k, "t": 2.0 * (k + 1), "distance": 10.0 * k, "interval_index": 0, "pace_500m": pace, "stroke_rate": rate,
             "watts": 2.8 / (pace / 500) ** 3, "hr": None} for k in range(n)]


def test_upsert_strokes_stores_the_summary_and_replaces_it(session):
    a = _rower(session, "x1", date(2026, 3, 1))
    upsert_strokes(session, a.id, _c2_strokes(400, 20.2, 120.0))
    session.refresh(a)
    first = json.loads(a.stroke_summary_json)
    assert first["v"] == ss.SUMMARY_VERSION and first["n"] == 400 and first["rate_bands"] == {"20": [400, 48000.0]}
    upsert_strokes(session, a.id, _c2_strokes(300, 24.0, 110.0))  # a re-sync replaces strokes and the summary together
    session.refresh(a)
    again = json.loads(a.stroke_summary_json)
    assert again["n"] == 300 and set(again["rate_bands"]) == {"24"}


def test_cached_bands_match_a_direct_per_stroke_count(session):
    a = _rower(session, "x2", date(2026, 3, 2))
    strokes = [{"seq": k, "t": 2.0 * (k + 1), "interval_index": 0, "pace_500m": 100.0 + (k % 70), "stroke_rate": 16 + (k % 31) * 0.97, "watts": 200.0}
               for k in range(900)]
    for s in strokes:
        session.add(Stroke(activity_id=a.id, **s))
    session.commit()
    cached = stroke_summary.summaries_for(session, [a.id])[a.id]["rate_bands"]
    rate = func.round(Stroke.stroke_rate)
    direct: dict[int, list[float]] = {}
    q = select(rate, func.count(), func.sum(Stroke.pace_500m)).where(
        Stroke.activity_id == a.id, Stroke.stroke_rate >= lab.RATE_RANGE[0], Stroke.stroke_rate <= lab.RATE_RANGE[1],
        Stroke.pace_500m >= 60, Stroke.pace_500m <= 300,
    ).group_by(rate)
    for r, n, total in session.exec(q).all():
        cell = direct.setdefault(lab.rate_band(float(r)), [0, 0.0])
        cell[0] += n
        cell[1] += total
    assert {int(k): [v[0], pytest.approx(v[1])] for k, v in cached.items()} == {k: [v[0], pytest.approx(v[1])] for k, v in direct.items()}


def test_lazy_fill_old_version_rebuild_and_no_recompute_mark(session):
    a = _rower(session, "x3", date(2026, 3, 3))
    for s in _c2_strokes(200, 22.0, 115.0):
        session.add(Stroke(activity_id=a.id, **s))
    session.commit()
    assert session.get(Activity, a.id).stroke_summary_json is None  # synced before the cache existed
    localtime.pending_recompute_from(session)
    stroke_summary.summaries_for(session, [a.id])
    session.expire_all()
    assert json.loads(session.get(Activity, a.id).stroke_summary_json)["n"] == 200
    assert localtime.pending_recompute_from(session) is None  # a cache write marks no day for a recompute
    stale = json.loads(session.get(Activity, a.id).stroke_summary_json)
    stale["v"] = 0
    stale["n"] = -1
    session.get(Activity, a.id).stroke_summary_json = json.dumps(stale)
    session.commit()
    assert stroke_summary.summaries_for(session, [a.id])[a.id]["n"] == 200


def test_power_curve_route(client, session):
    today = date.today()
    a = _rower(session, "x4", today - timedelta(days=20))
    upsert_strokes(session, a.id, _c2_strokes(400, 20.0, 110.0))
    client.post("/api/login", json={"password": TEST_PASSWORD})
    body = client.get("/api/lab/power-curve").json()
    assert body["watts_basis"] == "derived_from_pace" and body["recordings"] == 1
    sixty = next(d for d in body["durations"] if d["duration_s"] == 60)
    assert sixty["best"]["ref"] == f"/workouts/{a.canonical_id}" and sixty["best"]["watts"] == pytest.approx(2.8 / (110 / 500) ** 3, abs=0.1)
    assert sixty["earlier"] is None and sixty["recent"]["watts"] == sixty["best"]["watts"]
    assert next(d for d in body["durations"] if d["duration_s"] == 3600)["best"] is None


def test_maintenance_backfill_fills_old_recordings_in_batches(session):
    ids = []
    for i in range(3):
        a = _rower(session, f"bf{i}", date(2026, 2, 1 + i))
        for st in _c2_strokes(50, 20.0, 120.0):
            session.add(Stroke(activity_id=a.id, **st))
        ids.append(a.id)
    session.commit()
    assert stroke_summary.backfill(session, limit=2) == 2
    assert stroke_summary.backfill(session, limit=2) == 1
    assert stroke_summary.backfill(session, limit=2) == 0
    session.expire_all()
    assert all(json.loads(session.get(Activity, i).stroke_summary_json)["n"] == 50 for i in ids)
