"""Session 36 follow-up: lining up a PM5 recording with a watch's (catch/analytics|sync/recording_offset.py). A proposal only when the
two recordings clearly agree; the charts link only at an offset the athlete confirmed, keyed to that exact pair of recordings."""

from __future__ import annotations

import json
import math
import random
from datetime import datetime, timedelta, timezone

import pytest

from catch.analytics import recording_offset as ro
from catch.analytics.samples_codec import pack_series
from catch.core.models import Activity, ActivitySamples, CanonicalActivity, Stroke
from conftest import TEST_PASSWORD


def _hr_profile(n: int, seed: int = 3) -> list[float]:
    """A pyramid session's heart rate (1-2-3-4-3-2-1 minute reps, 90 s easy between), warm-up drift and noise. Identical repeats
    would fit at more than one offset — see test_flat_or_ambiguous_signals_propose_nothing."""
    rng = random.Random(seed)
    hard: list[bool] = [False] * 300
    for minutes in (1, 2, 3, 4, 3, 2, 1):
        hard += [True] * (60 * minutes) + [False] * 90
    hard += [False] * max(0, n - len(hard))
    out, hr = [], 95.0
    for t in range(n):
        target = 110 + t * 0.01 if t < 300 else (172.0 if hard[t] else 128.0)
        hr += (target - hr) * 0.04
        out.append(hr + rng.uniform(-1.5, 1.5))
    return out


def test_wall_times_add_rests_and_refuse_unknown_ones():
    strokes = [{"t": 2.0, "interval_index": 0}, {"t": 240.0, "interval_index": 0}, {"t": 3.0, "interval_index": 1}]
    defs = [{"time": 2400, "rest_time": 1200}, {"time": 2400, "rest_time": 1200}]
    assert ro.wall_times(strokes, defs) == [2.0, 240.0, 363.0]
    assert ro.wall_times(strokes, [{"time": 2400}, {"time": 2400}]) is None  # the rest before rep 2 isn't known
    assert ro.wall_times([{"t": 5.0, "interval_index": 0}], []) == [5.0]  # one continuous piece


def test_a_clear_match_is_proposed_at_the_right_offset():
    watch = _hr_profile(2400)
    lag = 137
    erg = watch[lag : lag + 1900]
    got = ro.suggest_offset(watch, erg, centre_s=60, signal="heart_rate")
    assert got["offset_s"] == lag and got["r"] > 0.95 and got["overlap_s"] >= 1800


def test_flat_or_ambiguous_signals_propose_nothing():
    flat = [150.0] * 1500
    assert ro.suggest_offset(flat, flat[:1000], signal="heart_rate")["offset_s"] is None
    periodic = [150 + 10 * math.sin(2 * math.pi * t / 60) for t in range(2400)]  # every 60 s fits equally well
    got = ro.suggest_offset(periodic, periodic[200:1400], centre_s=0, signal="stroke_rate")
    assert got["offset_s"] is None and "More than one" in got["reason"]
    unrelated = ro.suggest_offset(_hr_profile(2000, seed=1), [100 + random.Random(9).uniform(-20, 20) for _ in range(1200)], signal="heart_rate")
    assert unrelated["offset_s"] is None


# --- through the API --------------------------------------------------------------------------------------------------


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def _two_recordings(session, *, lag: int = 137, intervals: bool = False, rest_known: bool = True):
    start = datetime(2026, 5, 4, 7, 0, tzinfo=timezone.utc)
    watch_hr = _hr_profile(2400)
    canonical = CanonicalActivity(sport_family="rowing", start=start)
    session.add(canonical)
    session.flush()
    watch = Activity(source="garmin", external_id="w1", type="indoor_rowing", start=start, duration=2400.0, avg_hr=150, canonical_id=canonical.id)
    erg = Activity(source="concept2", external_id="c1", type="rower", start=start + timedelta(seconds=lag + 40), duration=1900.0, canonical_id=canonical.id)
    if intervals:
        erg.intervals_json = json.dumps({"intervals": [{"time": 9500, **({"rest_time": 0} if rest_known else {})}, {"time": 9500}]})
    session.add_all([watch, erg])
    session.flush()
    session.add(ActivitySamples(activity_id=watch.id, start=start, n_samples=2400, hr_blob=pack_series(watch_hr), power_blob=pack_series([None] * 2400),
                                cadence_blob=pack_series([None] * 2400)))
    for k in range(0, 1900, 2):
        idx = 1 if (intervals and k >= 950) else 0
        t = float(k - 950 if idx else k) or 0.5
        session.add(Stroke(activity_id=erg.id, seq=k, interval_index=idx, t=t, hr=round(watch_hr[k + lag]), stroke_rate=24.0, pace_500m=120.0))
    session.commit()
    return canonical, watch, erg


def test_alignment_is_proposed_confirmed_and_retired_when_the_pair_changes(client, session):
    _login(client)
    canonical, watch, erg = _two_recordings(session)
    url = f"/api/activities/{canonical.id}/erg-alignment"
    state = client.get(url).json()
    assert state["state"] == "not_linked" and state["wall_time_known"] is True and state["offset_s"] is None
    proposal = client.post(f"{url}/suggest").json()
    assert proposal["offset_s"] == pytest.approx(137, abs=1) and proposal["signal"] == "heart_rate"
    assert client.get(url).json()["state"] == "not_linked"  # a proposal links nothing by itself

    confirmed = client.put(url, json={"offset_s": proposal["offset_s"]}).json()
    assert confirmed["state"] == "confirmed" and confirmed["offset_s"] == proposal["offset_s"]
    assert client.put(url, json={"offset_s": 1.5}).status_code == 422
    assert client.put(url, json={"offset_s": 7 * 3600}).status_code == 422

    strokes = client.get(f"/api/erg/{erg.id}/strokes").json()["strokes"]
    assert strokes[0]["t_wall"] == strokes[0]["t"]

    # Another recording becomes the heart-rate chart's: the saved offset was for a different pair and no longer applies.
    other = Activity(source="garmin", external_id="w2", type="indoor_rowing", start=watch.start, duration=2400.0, avg_hr=151,
                     hr_source_type="chest_strap", canonical_id=canonical.id)
    session.add(other)
    session.commit()
    assert client.get(url).json()["state"] == "not_linked"
    assert client.delete(url).json()["state"] == "not_linked"
    assert "erg_alignment" not in json.loads(session.get(CanonicalActivity, canonical.id).overrides_json or "{}")


def test_unknown_rests_block_alignment(client, session):
    _login(client)
    canonical, _, erg = _two_recordings(session, intervals=True, rest_known=False)
    url = f"/api/activities/{canonical.id}/erg-alignment"
    assert client.get(url).json()["wall_time_known"] is False
    assert "rests aren't known" in client.post(f"{url}/suggest").json()["reason"]
    assert client.put(url, json={"offset_s": 100}).status_code == 422
    assert client.get(f"/api/erg/{erg.id}/strokes").json()["strokes"][0]["t_wall"] is None


def test_same_recording_needs_no_offset(client, session):
    _login(client)
    start = datetime(2026, 5, 5, 7, 0, tzinfo=timezone.utc)
    canonical = CanonicalActivity(sport_family="rowing", start=start)
    session.add(canonical)
    session.flush()
    erg = Activity(source="concept2", external_id="c9", type="rower", start=start, duration=600.0, avg_hr=140, canonical_id=canonical.id)
    session.add(erg)
    session.commit()
    url = f"/api/activities/{canonical.id}/erg-alignment"
    assert client.get(url).json()["state"] == "same_recording"
    assert client.put(url, json={"offset_s": 10}).status_code == 422
