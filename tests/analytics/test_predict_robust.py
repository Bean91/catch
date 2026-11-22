"""The 2k estimate on bad data and on interval work (2026-11-22, docs/analytics.md §2). A confirmed 3,046 m piece timed over a
whole 44-minute interval session once gave a range of -2:10 to 16:18."""

from __future__ import annotations

import math
from datetime import date, timedelta

from catch.analytics.predict import MAX_HALF_FRACTION, interval_point, predict_2k

AS_OF = date(2026, 11, 22)


def _p(distance, duration, days_ago, effort="declared", label="Piece", **kw):
    return {"distance_m": distance, "duration_s": duration, "date": AS_OF - timedelta(days=days_ago), "effort": effort, "label": label, **kw}


def test_the_reported_case_gives_a_sane_range_and_says_what_it_left_out():
    pts = [_p(2000, 434.5, 3, label="Piece: 2000m"), _p(3046, 2640.0, 12, label="Piece: custom"), _p(2000, 430.8, 16, label="Piece: 2000m")]
    r = predict_2k(pts, AS_OF)
    lo, hi = r["range_s"]
    assert r["predicted_time_s"] == 434.5
    assert 428 < lo < 434.5 < hi < 441  # about 7:11-7:17, from two 2ks 3.7 s apart
    assert [e["label"] for e in r["excluded"]] == ["Piece: custom"]
    assert "interval session saved as one piece" in r["excluded"][0]["reason"]
    assert "Left out: Piece: custom" in r["explanation"]
    assert len(r["components"]) == 2


def test_the_range_is_never_negative_and_never_wider_than_the_cap():
    pts = [_p(500, 92.0, 2, effort="hr_verified"), _p(10_000, 2350.0, 5, effort="effort_unknown"), _p(2000, 410.0, 40), _p(6000, 1390.0, 80)]
    r = predict_2k(pts, AS_OF)
    lo, hi = r["range_s"]
    assert lo > 0 and (hi - lo) / 2 <= MAX_HALF_FRACTION * r["predicted_time_s"] + 1e-9


def test_a_real_slower_2k_still_counts_but_a_mis_entered_one_does_not():
    kept = predict_2k([_p(2000, 420.0, 60), _p(2000, 445.0, 3)], AS_OF)  # 6 % slower: fitness dropped, still evidence
    assert len(kept["components"]) == 2 and not kept["excluded"]
    dropped = predict_2k([_p(2000, 420.0, 60), _p(2000, 500.0, 3)], AS_OF)  # 19 % slower: not a full effort
    assert len(dropped["components"]) == 1 and dropped["excluded"][0]["date"] == (AS_OF - timedelta(days=3)).isoformat()


def test_impossible_paces_are_dropped_either_way():
    r = predict_2k([_p(2000, 120.0, 1), _p(2000, 431.0, 2)], AS_OF)  # 0:30/500 m
    assert len(r["components"]) == 1 and r["components"][0]["duration_s"] == 431.0


def test_interval_point_sits_between_one_rep_and_the_whole_set():
    no_rest = interval_point([(500, 105, 0)] * 4)
    assert math.isclose(no_rest["paul_distance_m"], 2000)
    long_rest = interval_point([(500, 105, 600)] * 4)
    assert 500 < long_rest["paul_distance_m"] < 700
    mid = interval_point([(500, 105, 60)] * 4)
    assert long_rest["paul_distance_m"] < mid["paul_distance_m"] < no_rest["paul_distance_m"]
    assert mid["rest_s"] == 180  # the rest after the last rep doesn't count
    assert interval_point([(500, 105, 60)]) is None  # one rep isn't a set
    assert interval_point([(50, 10, 60)] * 4) is None  # strides aren't evidence


def test_intervals_count_but_never_set_the_yardstick_and_never_earn_high_confidence_alone():
    fast_set = {**interval_point([(500, 98.0, 60)] * 6), "date": AS_OF - timedelta(days=2), "effort": "declared", "label": "Intervals"}
    with_test = predict_2k([_p(2000, 440.0, 5), fast_set], AS_OF)
    assert {c["kind"] for c in with_test["components"]} == {"continuous", "intervals"}  # the slower real 2k isn't thrown out
    alone = predict_2k([fast_set, {**fast_set, "date": AS_OF - timedelta(days=9)}], AS_OF)
    assert alone["predicted_time_s"] is not None and alone["confidence"] != "high"
    assert "interval work only" in alone["explanation"]
