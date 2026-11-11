import math

import pytest

from catch.analytics.defaults import DEFAULT_SETTINGS
from catch.analytics.gps import (
    RawTrack,
    build_series,
    compute_metrics,
    compute_splits,
    detect_on_water,
    filter_track,
    haversine_m,
    likely_rowing,
    pace_for,
    speed_ceiling_mps,
)

S = DEFAULT_SETTINGS["on_water"]
# 1 degree of latitude on the IUGG mean sphere: 6371008.8 * pi / 180 = 111,194.93 m
M_PER_DEG = 111194.93


def north_track(n, dt=5.0, speed=4.0, lat0=45.0, lon0=-73.0, t0=0.0):
    """A boat going due north at a constant speed: lat advances speed*dt/M_PER_DEG per fix."""
    step = speed * dt / M_PER_DEG
    return RawTrack(
        t=[t0 + i * dt for i in range(n)],
        lat=[lat0 + i * step for i in range(n)],
        lon=[lon0] * n,
    )


def test_haversine_hand_checked():
    assert haversine_m(45.0, -73.0, 45.001, -73.0) == pytest.approx(111.19493, abs=1e-3)
    # a degree of longitude shrinks with cos(latitude): at 60N it's exactly half the equator's
    assert haversine_m(60.0, 10.0, 60.0, 11.0) == pytest.approx(M_PER_DEG * 0.5, rel=2e-4)
    assert haversine_m(10.0, 10.0, 10.0, 10.0) == 0.0


def test_straight_track_distance_speed_and_splits():
    raw = north_track(101)  # 500 s at 4 m/s = 2000 m
    ft = filter_track(raw, 10.0, S)
    m = compute_metrics(ft, None, S)
    assert m["distance_m"]["value"] == pytest.approx(2000.0, abs=0.5)
    assert m["moving_s"]["value"] == pytest.approx(500.0)
    assert m["elapsed_s"]["value"] == pytest.approx(500.0)
    assert m["avg_speed_mps"]["value"] == pytest.approx(4.0, abs=0.005)
    assert m["peak_speed_mps"]["value"] == pytest.approx(4.0, abs=0.005)
    assert m["distance_m"]["source"] == "gps_derived"
    sp = compute_splits(ft, 500.0, S)
    assert len(sp["splits"]) == 4
    for s in sp["splits"]:
        assert s["time_s"] == pytest.approx(125.0, abs=0.1)
        assert s["partial"] is False and s["has_gap"] is False
    assert sp["consistency"]["cv_pct"] == pytest.approx(0.0, abs=0.01)
    assert sp["consistency"]["n_splits"] == 4


def test_split_boundary_is_interpolated_between_fixes():
    # fixes every 20 s at 4 m/s (80 m apart) -> a 500 m boundary falls mid-interval (t=125 s)
    ft = filter_track(north_track(11, dt=20.0), 10.0, S)
    sp = compute_splits(ft, 500.0, S)
    assert sp["splits"][0]["time_s"] == pytest.approx(125.0, abs=0.1)
    assert sp["splits"][1]["partial"] is True
    assert sp["splits"][1]["distance_m"] == pytest.approx(300.0, abs=0.5)  # 800 m total


def test_pace_consistency_needs_four_clean_splits():
    ft = filter_track(north_track(61), 10.0, S)  # 1200 m -> 2 full + partial
    assert compute_splits(ft, 500.0, S)["consistency"] is None


def test_uneven_pacing_has_nonzero_cv():
    a = north_track(51, speed=3.0)  # 250 s, 750 m
    b = north_track(51, speed=5.0, lat0=a.lat[-1], t0=a.t[-1] + 5.0)
    raw = RawTrack(t=a.t + b.t, lat=a.lat + b.lat, lon=a.lon + b.lon)
    ft = filter_track(raw, 10.0, S)
    sp = compute_splits(ft, 250.0, S)
    assert sp["consistency"]["cv_pct"] > 5


def test_missing_duplicate_and_out_of_order_fixes_are_dropped_and_counted():
    raw = north_track(21)
    raw.lat[3] = None
    raw.lon[3] = None
    raw.lat[5], raw.lon[5] = 0.0, 0.0  # null island
    raw.lat[7] = float("nan")
    raw.t[10] = raw.t[9]  # duplicate timestamp
    raw.t[15] = raw.t[14] - 1  # goes backwards
    r = filter_track(raw, 10.0, S).report
    assert r["points_in"] == 21
    assert r["dropped_no_fix"] == 3
    assert r["dropped_duplicate_time"] == 1
    assert r["dropped_out_of_order"] == 1


def test_single_spike_is_rejected_and_does_not_inflate_distance():
    raw = north_track(41)
    raw.lat[20] += 5000 / M_PER_DEG  # 5 km out for one fix
    ft = filter_track(raw, 10.0, S)
    assert ft.report["dropped_jump"] == 1
    assert ft.report["reanchored"] == 0
    assert compute_metrics(ft, None, S)["distance_m"]["value"] == pytest.approx(800.0, abs=1.0)


def test_consistent_relocation_reanchors_without_counting_the_jump():
    a = north_track(21)  # 400 m
    b = north_track(21, lat0=a.lat[-1] + 0.5, t0=a.t[-1] + 5.0)  # teleports ~55 km, keeps rowing
    raw = RawTrack(t=a.t + b.t, lat=a.lat + b.lat, lon=a.lon + b.lon)
    ft = filter_track(raw, 10.0, S)
    assert ft.report["reanchored"] == 1
    assert len(set(ft.segment)) == 2
    assert compute_metrics(ft, None, S)["distance_m"]["value"] == pytest.approx(800.0, abs=2.0)


def test_gap_is_never_interpolated():
    a = north_track(13)  # 60 s, 240 m
    b = north_track(13, lat0=a.lat[-1] + 0.0003, t0=a.t[-1] + 65.0)  # 65 s silence
    raw = RawTrack(t=a.t + b.t, lat=a.lat + b.lat, lon=a.lon + b.lon)
    ft = filter_track(raw, 10.0, S)
    assert ft.report["gaps"] == 1
    assert ft.report["gap_seconds"] == pytest.approx(65.0)
    m = compute_metrics(ft, None, S)
    assert m["distance_m"]["value"] == pytest.approx(480.0, abs=1.0)  # two 240 m halves only
    assert m["elapsed_s"]["value"] == pytest.approx(185.0)
    assert m["moving_s"]["value"] == pytest.approx(120.0)  # the 65 s gap is nobody's moving time
    sp = compute_splits(ft, 200.0, S)
    assert any(s["has_gap"] for s in sp["splits"])


def test_stationary_jitter_is_not_moving_time_or_moving_distance():
    n = 30
    raw = RawTrack(
        t=[i * 5.0 for i in range(n)],
        lat=[45.0 + (1.0 if i % 2 else 0.0) / M_PER_DEG for i in range(n)],  # 1 m wobble / 5 s = 0.2 m/s
        lon=[-73.0] * n,
    )
    m = compute_metrics(filter_track(raw, 10.0, S), None, S)
    assert m["moving_s"]["value"] == 0.0
    assert m["moving_distance_m"]["value"] == 0.0
    assert m["stopped_s"]["value"] == pytest.approx(145.0)
    assert m["avg_speed_mps"]["value"] is None  # nothing moved, so no speed is claimed
    # total distance deliberately counts every pair (matches Garmin on real data), so the wobble
    # shows up here — and is visibly separate from moving distance
    assert m["distance_m"]["value"] == pytest.approx(29.0, abs=0.1)


def test_slow_drift_counts_toward_distance_but_not_moving_time():
    # 0.3 m/s drift for 100 s: below the 0.5 m/s moving threshold, real movement
    m = compute_metrics(filter_track(north_track(21, speed=0.3), 10.0, S), None, S)
    assert m["distance_m"]["value"] == pytest.approx(30.0, abs=0.2)
    assert m["moving_s"]["value"] == 0.0


def test_elapsed_based_average_matches_garmins_convention():
    ft = filter_track(north_track(101), 10.0, S)
    assert compute_metrics(ft, None, S)["avg_speed_elapsed_mps"]["value"] == pytest.approx(4.0, abs=0.01)
    a = north_track(21)  # 80 s moving, then 20 s parked, then 80 s moving
    park = RawTrack(t=[a.t[-1] + 5 * i for i in range(1, 5)], lat=[a.lat[-1]] * 4, lon=[-73.0] * 4)
    b = north_track(21, lat0=a.lat[-1], t0=park.t[-1] + 5.0)
    raw = RawTrack(t=a.t + park.t + b.t, lat=a.lat + park.lat + b.lat, lon=a.lon + park.lon + b.lon)
    m = compute_metrics(filter_track(raw, 10.0, S), None, S)
    assert m["avg_speed_mps"]["value"] == pytest.approx(4.0, abs=0.02)  # moving basis ignores the stop
    assert m["avg_speed_elapsed_mps"]["value"] < 3.6  # elapsed basis is dragged down by it


def test_peak_speed_bounds_a_gps_error_by_error_over_window():
    raw = north_track(61)
    raw.lat[30] += 6 / M_PER_DEG  # one fix 6 m off the line
    ft = filter_track(raw, 10.0, S)
    assert max(ft.pair_speed) > 5.0  # a naive per-pair peak reads (20+6)/5 = 5.2 m/s
    peak = compute_metrics(ft, None, S)["peak_speed_mps"]["value"]
    assert 4.0 <= peak <= 4.0 + 6 / 10 + 0.01  # chord error is at most error / window = 0.6 m/s


def test_too_few_fixes_returns_none():
    assert filter_track(RawTrack(t=[0.0], lat=[45.0], lon=[-73.0]), 10.0, S) is None
    raw = RawTrack(t=[0.0, 5.0, 10.0], lat=[None, None, 45.0], lon=[None, None, -73.0])
    assert filter_track(raw, 10.0, S) is None


def test_incomplete_track_without_speed_hr_or_altitude_still_measures():
    ft = filter_track(north_track(11), 10.0, S)
    series = build_series(ft, 600, "rowing")
    assert series[0]["hr"] is None and series[0]["elevation_m"] is None
    assert series[0]["provider_speed_mps"] is None
    assert series[-1]["distance_m"] == pytest.approx(200.0, abs=0.5)


def test_provider_values_are_kept_separate_with_delta():
    ft = filter_track(north_track(101), 10.0, S)
    m = compute_metrics(ft, {"distance_m": 2020.0, "max_speed_mps": 5.4, "moving_s": 505.0}, S)
    assert m["provider"]["distance_m"]["source"] == "provider"
    assert m["distance_delta_vs_provider_pct"] == pytest.approx(-0.99, abs=0.05)
    assert m["provider"]["avg_speed_mps"] is None  # not supplied -> visibly missing, not derived


def test_series_downsamples_and_keeps_endpoints():
    ft = filter_track(north_track(2001, dt=1.0), 10.0, S)
    series = build_series(ft, 200, "rowing")
    assert len(series) == 200
    assert series[0]["elapsed_s"] == 0.0 and series[-1]["elapsed_s"] == 2000.0


def test_pace_units_by_sport():
    assert pace_for(4.0, "rowing") == {"unit": "s_per_500m", "value": 125.0}
    assert pace_for(4.0, "running") == {"unit": "s_per_km", "value": 250.0}
    assert pace_for(5.0, "cycling")["value"] == pytest.approx(18.0)
    assert pace_for(0.0, "rowing")["value"] is None


def test_speed_ceiling_by_type_and_family():
    assert speed_ceiling_mps("rowing_v2", "rowing", S) == 10
    assert speed_ceiling_mps("hiking", "other", S) == 6
    assert speed_ceiling_mps("kayaking", "other", S) == 8
    assert speed_ceiling_mps("road_biking", "cycling", S) == 25
    assert speed_ceiling_mps("yoga", "other", S) == 15


def test_detect_on_water():
    assert detect_on_water("garmin", "rowing_v2", True) == {"kind": "on_water", "basis": "garmin_type"}
    assert detect_on_water("garmin", "indoor_rowing", False)["kind"] == "erg"
    assert detect_on_water("concept2", "water", False) == {"kind": "on_water", "basis": "concept2_type"}
    assert detect_on_water("concept2", "rower", False)["kind"] == "erg"
    assert detect_on_water("garmin", "other", True) == {"kind": "unknown", "basis": "gps_track"}


def test_likely_rowing_is_a_narrow_inference():
    assert likely_rowing(24, 3.5) is True
    assert likely_rowing(90, 3.5) is False  # running/cycling cadence
    assert likely_rowing(None, 3.5) is False


def test_cum_dist_at_interpolates_clamps_and_freezes_in_gaps():
    from catch.analytics.gps import cum_dist_at

    ft = filter_track(north_track(11), 10.0, S)  # 0..50 s, 4 m/s
    assert cum_dist_at(ft, -5) == 0.0
    assert cum_dist_at(ft, 12.5) == pytest.approx(50.0, abs=0.1)
    assert cum_dist_at(ft, 999) == pytest.approx(200.0, abs=0.5)
    a = north_track(13)
    b = north_track(13, lat0=a.lat[-1] + 0.0003, t0=a.t[-1] + 65.0)
    gapped = filter_track(RawTrack(t=a.t + b.t, lat=a.lat + b.lat, lon=a.lon + b.lon), 10.0, S)
    assert cum_dist_at(gapped, 90.0) == pytest.approx(cum_dist_at(gapped, 61.0))  # flat across the silence


def test_lap_metrics_split_distance_by_window_and_keep_provider_values_apart():
    from catch.analytics.gps import lap_metrics

    ft = filter_track(north_track(101), 10.0, S)  # 500 s, 2000 m
    laps = [{"offset_s": 0.0, "duration_s": 250.0, "distance_m": 1010.0, "avg_hr": 150.0},
            {"offset_s": 250.0, "duration_s": 250.0}]
    out = lap_metrics(ft, laps)
    assert out[0]["gps_distance_m"] == pytest.approx(1000.0, abs=0.5)
    assert out[1]["gps_avg_speed_mps"] == pytest.approx(4.0, abs=0.01)
    assert out[0]["provider"]["distance_m"] == 1010.0 and out[1]["provider"]["distance_m"] is None
