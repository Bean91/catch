from __future__ import annotations

import pytest

from catch.analytics.technique import fade, rate_power_slope, split_consistency, watts_per_stroke


def test_split_consistency_perfectly_even_piece():
    strokes = [
        {"t": 0, "distance": 0},
        {"t": 52.5, "distance": 250},
        {"t": 105, "distance": 500},
        {"t": 157.5, "distance": 750},
        {"t": 210, "distance": 1000},
    ]
    result = split_consistency(strokes)
    assert result["value"] == pytest.approx(0.0, abs=1e-6)
    assert result["band"] == "consistent"


def test_split_consistency_needs_two_full_splits():
    result = split_consistency([{"t": 0, "distance": 0}, {"t": 50, "distance": 200}])
    assert result["value"] is None
    assert result["band"] == "insufficient_data"


def test_watts_per_stroke():
    strokes = [{"watts": 300, "stroke_rate": 30}, {"watts": 320, "stroke_rate": 32}]
    result = watts_per_stroke(strokes)
    assert result["value"] == pytest.approx(600.0)


def test_rate_power_slope_exact_linear_fit():
    strokes = [
        {"stroke_rate": 28, "watts": 280},
        {"stroke_rate": 30, "watts": 300},
        {"stroke_rate": 32, "watts": 320},
        {"stroke_rate": 34, "watts": 340},
    ]
    result = rate_power_slope(strokes)
    assert result["value"] == pytest.approx(10.0)
    assert result["band"] == "efficient"


def test_fade_detects_slowdown_in_last_quarter():
    paces = [100, 100, 105, 105, 108, 108, 112, 112]
    strokes = [{"t": i * 10.0, "pace_500m": p} for i, p in enumerate(paces)]
    result = fade(strokes)
    assert result["value"] == pytest.approx(12.0)
    assert result["band"] == "faded"


def test_fade_needs_at_least_eight_strokes():
    result = fade([{"t": 0, "pace_500m": 100}] * 4)
    assert result["value"] is None
    assert result["band"] == "insufficient_data"
