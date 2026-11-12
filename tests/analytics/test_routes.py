import math

import pytest

from catch.analytics.defaults import DEFAULT_SETTINGS
from catch.analytics.gps import RawTrack, filter_track
from catch.analytics.routes import eligible, match, path_length_m, signature

S = DEFAULT_SETTINGS["on_water"]
M_PER_DEG = 111194.93


def course(points, dt=5.0, speed=4.0, jitter=0.0):
    """Walk a polyline of (lat, lon) waypoints at constant speed, emitting a fix every dt s."""
    lats, lons, ts = [], [], []
    t = 0.0
    for (la, lo), (lb, lb_) in zip(points, points[1:]):
        seg = math.hypot((lb - la) * M_PER_DEG, (lb_ - lo) * M_PER_DEG * math.cos(math.radians(la)))
        steps = max(1, int(seg / (speed * dt)))
        for i in range(steps):
            f = i / steps
            lats.append(la + (lb - la) * f + jitter * ((-1) ** i))
            lons.append(lo + (lb_ - lo) * f)
            ts.append(t)
            t += dt
    lats.append(points[-1][0])
    lons.append(points[-1][1])
    ts.append(t)
    return filter_track(RawTrack(t=ts, lat=lats, lon=lons), 10.0, S)


# a 2 km out-and-back "L" on the water
L = [(45.0, -73.0), (45.0, -72.98), (45.01, -72.98)]


def test_signature_has_fixed_size_and_hits_the_endpoints():
    sig = signature(course(L))
    assert len(sig) == 64
    assert sig[0] == pytest.approx([45.0, -73.0], abs=1e-4)
    assert sig[-1] == pytest.approx([45.01, -72.98], abs=1e-4)
    assert path_length_m(sig) == pytest.approx(1574 + 1112, rel=0.03)


def test_same_course_different_pace_and_rate_aligns():
    a = signature(course(L, dt=5.0, speed=4.0))
    b = signature(course(L, dt=3.0, speed=3.0, jitter=0.00001))  # ~1 m GPS wobble, slower
    m = match(a, b, S)
    assert m["aligned"] is True and m["direction"] == "same"
    assert m["coverage"] >= 0.9


def test_reversed_direction_is_not_silently_merged():
    a = signature(course(L))
    b = signature(course(L[::-1]))
    m = match(a, b, S)
    assert m["direction"] == "reversed"
    assert m["aligned"] is False


def test_partial_course_is_not_aligned():
    a = signature(course(L))
    b = signature(course(L[:2]))  # only the first leg
    m = match(a, b, S)
    assert m["aligned"] is False


def test_different_course_far_away_is_not_aligned():
    a = signature(course(L))
    b = signature(course([(45.2, -73.0), (45.2, -72.98), (45.21, -72.98)]))
    assert match(a, b, S)["aligned"] is False


def test_offset_start_beyond_tolerance_is_not_aligned():
    a = signature(course(L))
    shifted = [(45.0 + 0.003, -73.0), (45.0 + 0.003, -72.98), (45.01 + 0.003, -72.98)]  # ~330 m north
    assert match(a, signature(course(shifted)), S)["aligned"] is False


def test_empty_or_mismatched_signatures_never_align():
    assert match([], [], S)["aligned"] is False
    assert match([[1.0, 1.0]] * 3, [[1.0, 1.0]] * 4, S)["aligned"] is False


def test_gap_eligibility():
    assert eligible(0.1, S) is True
    assert eligible(0.4, S) is False
    assert eligible(None, S) is False


# ---- history ----------------------------------------------------------------------------------

from catch.analytics.routes import history_stats  # noqa: E402


def sess(d, speed, hr=None, weather=None, cid=1):
    return {"date": d, "canonical_id": cid, "avg_speed_mps": speed, "moving_s": 3000, "elapsed_s": 3200,
            "distance_m": speed * 3000, "avg_hr": hr, "weather": weather}


def test_history_ranks_by_moving_speed_and_reports_typical_and_recent():
    h = history_stats([sess("2026-10-01", 3.0, 140), sess("2026-10-08", 3.4, 150, cid=2),
                       sess("2026-10-15", 3.2, 145, cid=3), sess("2026-10-22", 3.1, None, cid=4)])
    assert h["best"]["canonical_id"] == 2
    assert h["typical_avg_speed_mps"] == pytest.approx(3.15)  # median of 3.0, 3.1, 3.2, 3.4
    assert h["recent"]["canonical_id"] == 4
    assert h["recent_vs_typical_pct"] == pytest.approx((3.1 - 3.15) / 3.15 * 100)
    assert h["hr"] == {"n": 3, "mean": 145.0, "min": 140, "max": 150}
    assert h["source"] == "gps_derived" and len(h["caveats"]) == 2
    assert "wind" in h["caveats"][0] and "corrected" in h["caveats"][0]


def test_speed_distribution_quartiles_and_histogram_counts_add_up():
    h = history_stats([sess(f"2026-10-{i:02d}", v, cid=i) for i, v in enumerate([3.0, 3.1, 3.2, 3.3, 3.4], 1)])
    d = h["speed_distribution"]
    assert (d["min"], d["median"], d["max"]) == (3.0, 3.2, 3.4)
    assert d["p25"] == pytest.approx(3.1) and d["p75"] == pytest.approx(3.3)
    assert sum(b["count"] for b in d["histogram"]) == 5 and len(d["histogram"]) == 5


def test_single_session_has_nothing_to_compare_and_no_hr_claim_without_hr():
    h = history_stats([sess("2026-10-01", 3.0)])
    assert h["n_sessions"] == 1 and h["recent_vs_typical_pct"] is None and h["hr"] is None
    assert h["speed_distribution"]["histogram"][0]["count"] == 1


def test_empty_history_is_visibly_empty():
    h = history_stats([])
    assert h["n_sessions"] == 0 and h["best"] is None and h["speed_distribution"] is None


def test_weather_differences_are_observations_never_corrections():
    calm = {"temperature_avg_c": 18.0, "wind_speed_kmh": 8.0, "precipitation_mm": 0.0}
    windy = {"temperature_avg_c": 12.0, "wind_speed_kmh": 24.0, "precipitation_mm": 1.0}
    h = history_stats([sess("2026-10-01", 3.0, weather=windy), sess("2026-10-08", 3.4, weather=calm, cid=2),
                       sess("2026-10-15", 3.2, weather=windy, cid=3)])
    wind = next(d for d in h["weather_differences"] if d["metric"] == "wind speed (km/h)")
    assert wind["best_session"] == 8.0 and wind["other_sessions_median"] == 24.0 and wind["difference"] == -16.0
    assert wind["kind"] == "observed_difference" and "not a correction" in wind["note"]
    # the ranking itself is untouched by weather
    assert h["best"]["canonical_id"] == 2


def test_no_weather_comparison_when_the_best_session_has_no_weather():
    h = history_stats([sess("2026-10-01", 3.0, weather={"wind_speed_kmh": 5.0}), sess("2026-10-08", 3.4, cid=2)])
    assert h["weather_differences"] == []
